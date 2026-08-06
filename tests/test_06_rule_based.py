"""
test_06_rule_based.py — Tests for the deterministic rule-based classifier.

Two kinds of test here:

  * Real-sample tests, driven by `tests/data/sample_condensed_buildings.parquet`
    — 24 rows sampled from the real condensed buildings file across 8 signal
    buckets (school, kindergarten, restaurant, supermarket, hospital, office,
    named_only, sparse). Regenerate with:
        python tests/create_classifier_test_sample.py

  * Table tests, which call `classify_building` with a hand-built row. These
    pin decisions that were made deliberately and would otherwise be easy to
    undo by accident — the ALKIS code table, the land-use refinement, the
    `work` invariant, and the exclusions.

`rule_utils.classify_building` is fully deterministic, so no mocking is needed
anywhere: the assertions are exact, not approximate.
"""

import pytest
import pandas as pd

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import TARGET_MID_LABELS, BOSSERHOF_WEIGHTS
from rule_utils import (
    classify_building, validate_rule_tables, as_list,
    ALKIS_RULES, GENERIC_COMMERCIAL_CODES,
)

DATA_DIR = Path(__file__).parent / "data"
SAMPLE_FILE = DATA_DIR / "sample_condensed_buildings.parquet"

BOSSERHOF_WEIGHTS_LOWER = {k.lower() for k in BOSSERHOF_WEIGHTS}
VALID_SOURCES = {"poi_tags", "alkis_code", "osm_fallback", "no_signal"}


def classify(**row):
    """Classify a hand-built row. gml_id is supplied so failures are readable."""
    row.setdefault("gml_id", 0)
    return classify_building(row)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def sample_df():
    if not SAMPLE_FILE.exists():
        pytest.skip(
            f"Sample fixture not found: {SAMPLE_FILE}. "
            "Run tests/create_classifier_test_sample.py first."
        )
    return pd.read_parquet(SAMPLE_FILE)


@pytest.fixture(scope="module")
def all_predictions(sample_df):
    results = []
    for _, row in sample_df.iterrows():
        result = classify_building(row.to_dict())
        result["_bucket"] = row["_bucket"]
        results.append(result)
    return results


# ── Rule tables are internally valid ──────────────────────────────────────────

class TestRuleTableValidation:
    def test_validate_rule_tables_passes(self):
        assert validate_rule_tables() is True

    def test_every_alkis_row_is_a_two_tuple(self):
        for code, value in ALKIS_RULES.items():
            assert isinstance(value, tuple) and len(value) == 2, \
                f"ALKIS_RULES[{code!r}] is malformed: {value!r}"

    def test_alkis_codes_look_like_alkis_codes(self):
        """Guards against a label being pasted in where a code belongs — the
        exact mistake the code-keyed table exists to prevent."""
        for code in ALKIS_RULES:
            assert "_" in code and code.replace("_", "").isdigit(), \
                f"ALKIS_RULES key {code!r} is not an ALKIS function code"


# ── classify_building on real sampled rows ────────────────────────────────────

class TestClassifyOnRealSamples:
    def test_no_errors_on_any_row(self, sample_df):
        for _, row in sample_df.iterrows():
            classify_building(row.to_dict())  # must not raise

    def test_all_mid_labels_are_valid(self, all_predictions):
        for r in all_predictions:
            for label in r["mid_labels"]:
                assert label in TARGET_MID_LABELS, \
                    f"Invalid label '{label}' for gml_id={r['gml_id']} [{r['_bucket']}]"

    def test_mid_labels_are_unique_and_sorted(self, all_predictions):
        for r in all_predictions:
            labels = r["mid_labels"]
            assert labels == sorted(set(labels)), \
                f"gml_id={r['gml_id']} labels not deduplicated/sorted: {labels}"

    def test_bosserhof_class_is_always_a_known_class_or_none(self, all_predictions):
        for r in all_predictions:
            cls = r["bosserhof_class"]
            assert cls is None or cls.lower() in BOSSERHOF_WEIGHTS_LOWER, \
                f"Unknown bosserhof_class {cls!r} for gml_id={r['gml_id']} [{r['_bucket']}]"

    def test_all_rows_have_a_known_interpreted_type(self, all_predictions):
        for r in all_predictions:
            assert r["interpreted_type"] in VALID_SOURCES, \
                f"gml_id={r['gml_id']} has unexpected source {r['interpreted_type']!r}"

    def test_school_rows_get_school_or_lessons_label(self, all_predictions):
        for r in [x for x in all_predictions if x["_bucket"] == "school"]:
            assert "school" in r["mid_labels"] or "lessons" in r["mid_labels"], \
                f"School row gml_id={r['gml_id']} got {r['mid_labels']}"

    def test_kindergarten_rows_get_childcare_label(self, all_predictions):
        for r in [x for x in all_predictions if x["_bucket"] == "kindergarten"]:
            assert "childcare" in r["mid_labels"], \
                f"Kindergarten row gml_id={r['gml_id']} got {r['mid_labels']}"

    def test_supermarket_rows_get_retail_daily(self, all_predictions):
        for r in [x for x in all_predictions if x["_bucket"] == "supermarket"]:
            assert "retail_daily" in r["mid_labels"], \
                f"Supermarket row gml_id={r['gml_id']} got {r['mid_labels']}"

    def test_restaurant_rows_get_leisure_not_errands(self, all_predictions):
        """Eating out is discretionary (MiD 'Freizeit'), not a functional task."""
        for r in [x for x in all_predictions if x["_bucket"] == "restaurant"]:
            assert "leisure" in r["mid_labels"], \
                f"Restaurant row gml_id={r['gml_id']} got {r['mid_labels']}"
            assert "errands" not in r["mid_labels"], \
                f"Restaurant row gml_id={r['gml_id']} incorrectly got 'errands'"

    def test_sparse_and_named_only_rows_do_not_crash(self, all_predictions):
        rows = [x for x in all_predictions if x["_bucket"] in ("sparse", "named_only")]
        assert len(rows) > 0
        for r in rows:
            assert isinstance(r["mid_labels"], list)


# ── The `work` invariant ──────────────────────────────────────────────────────

class TestWorkInvariant:
    """A Bosserhof class IS a worker-density rating, so `work` is added
    centrally to anything carrying one. The rule tables therefore describe only
    the visitor-facing purpose — this is what puts the staff side back."""

    def test_work_present_whenever_bosserhof_class_is_set(self, all_predictions):
        for r in all_predictions:
            if r["bosserhof_class"]:
                assert "work" in r["mid_labels"], \
                    f"gml_id={r['gml_id']} has {r['bosserhof_class']!r} but no 'work'"

    @pytest.mark.parametrize("tag,value", [
        ("amenity", "restaurant"), ("amenity", "school"), ("amenity", "kindergarten"),
        ("shop", "bakery"), ("tourism", "hotel"), ("building", "office"),
    ])
    def test_visitor_facing_pois_still_get_work(self, tag, value):
        r = classify(**{tag: value})
        assert "work" in r["mid_labels"], f"{tag}={value} got {r['mid_labels']}"

    def test_no_work_without_a_bosserhof_class(self):
        r = classify(function="31001_1000")   # Wohngebäude
        assert r["mid_labels"] == []
        assert r["bosserhof_class"] is None


# ── The ALKIS code table ──────────────────────────────────────────────────────

class TestAlkisCodeTable:
    @pytest.mark.parametrize("code,why", [
        ("31001_1000", "Wohngebäude — a dwelling"),
        ("31001_1210", "Land-/forstw. Wohngebäude — a farm dwelling"),
        ("31001_1223", "Forsthaus — a dwelling"),
        ("31001_2500", "Gebäude zur Versorgung — unmanned utility"),
        ("31001_2461", "Parkhaus"),
        ("31001_2462", "Parkdeck"),
        ("31001_2513", "Wasserbehälter"),
        ("31001_3081", "Trauerhalle"),
        ("31001_3281", "Schutzhütte"),
        ("31001_2073", "Hütte mit Übernachtung"),
        ("51001_1002", "Kirchturm — a tower, not a church"),
        ("51001_1005", "Kühlturm"),
        ("51001_1012", "Palast-, Schlossturm — a tower, not the palace"),
        ("51006_1431", "Zuschauertribüne, überdacht — open-air"),
        ("51006_1432", "Zuschauertribüne, nicht überdacht — open-air"),
        ("51007_1400", "Befestigung (Burgruine) — a ruin"),
        ("51009_1750", "Denkmal"),
    ])
    def test_excluded_codes_carry_no_activity(self, code, why):
        r = classify(function=code)
        assert r["mid_labels"] == [], f"{code} ({why}) should carry no activity"
        assert r["bosserhof_class"] is None
        assert r["interpreted_type"] == "alkis_code"

    def test_schloss_is_culture_not_a_canal_lock(self):
        """31001_3031 is 'Schloss' (a palace) but ships with the English label
        "Lock". Excluding it as a waterway structure was wrong — this is why
        the table is keyed on the code and not on the translated text."""
        r = classify(function="31001_3031")
        assert r["bosserhof_class"] == "entertainment culture"
        assert "leisure" in r["mid_labels"]

    @pytest.mark.parametrize("code", ["31001_3041", "31001_3043", "31001_3045"])
    def test_all_religious_codes_agree(self, code):
        """Kirche / Kapelle / Gotteshaus are one building type and must get one
        answer. They previously diverged because a regex matched two of three."""
        r = classify(function=code)
        assert set(r["mid_labels"]) == {"meetup", "leisure", "work"}
        assert r["bosserhof_class"] == "public facilities"

    @pytest.mark.parametrize("code", [
        "31001_3000", "31001_3100", "31001_3012", "31001_3071",
        "31001_3015", "31001_3017", "31001_3019", "31001_3011",
    ])
    def test_public_family_is_consistent(self, code):
        """The generic public code must agree with its specific siblings."""
        r = classify(function=code)
        assert set(r["mid_labels"]) == {"errands", "work"}
        assert r["bosserhof_class"] == "public facilities"

    @pytest.mark.parametrize("code", ["31001_3072", "31001_3075"])
    def test_staff_only_public_codes(self, code):
        """Feuerwehr and Justizvollzugsanstalt generate staff trips only."""
        r = classify(function=code)
        assert r["mid_labels"] == ["work"]
        assert r["bosserhof_class"] == "public facilities"

    @pytest.mark.parametrize("code", ["31001_2100", "31001_1130", "31001_2320"])
    def test_specific_industrial_codes_are_not_services(self, code):
        r = classify(function=code)
        assert r["bosserhof_class"] == "industrial operations production"

    def test_unknown_code_falls_through(self):
        """A code absent from the table must not be silently classified."""
        r = classify(function="31001_9999")
        assert r["interpreted_type"] == "no_signal"
        assert r["mid_labels"] == []

    def test_missing_code_falls_through(self):
        r = classify(function=None)
        assert r["interpreted_type"] == "no_signal"


class TestGenericAlkisEmitsNoRetail:
    """The generic 'Handel und Dienstleistungen' codes must not claim retail.
    They previously supplied 84% of all retail_non_daily buildings (9,777 of
    11,622), swamping the 1,832 buildings actually tagged as shops."""

    @pytest.mark.parametrize("code", [
        "31001_2000", "31001_2010", "31001_1120", "31001_2310",
        "31001_2100", "31001_1130", "31001_2320",
    ])
    def test_no_retail_label(self, code):
        r = classify(function=code)
        assert "retail_daily" not in r["mid_labels"]
        assert "retail_non_daily" not in r["mid_labels"]
        assert "errands" not in r["mid_labels"]
        assert set(r["mid_labels"]) == {"work", "business"}


class TestLanduseRefinement:
    """The only refinement in the pipeline, and it applies to the generic
    commercial code alone. Uses an OSM tag, never volume."""

    def test_generic_commercial_code_is_the_only_one_refined(self):
        assert GENERIC_COMMERCIAL_CODES == {"31001_2000"}

    @pytest.mark.parametrize("landuse,expected", [
        ("industrial",           "industrial operations production"),
        ("retail",               "retail"),
        ("commercial",           "services"),
        ("residential",          "services"),
        (None,                   "services"),
        ("residential;retail",   "retail"),
        ("commercial;residential", "services"),
    ])
    def test_refinement(self, landuse, expected):
        r = classify(function="31001_2000", osm_landuse_class=landuse)
        assert r["bosserhof_class"] == expected

    def test_refinement_does_not_touch_specific_codes(self):
        r = classify(function="31001_2100", osm_landuse_class="retail")
        assert r["bosserhof_class"] == "industrial operations production"

    def test_refinement_never_changes_the_mid_labels(self):
        for lu in ("industrial", "retail", "commercial", "residential", None):
            r = classify(function="31001_2000", osm_landuse_class=lu)
            assert set(r["mid_labels"]) == {"work", "business"}


# ── Tag-value normalisation ───────────────────────────────────────────────────

class TestCompositeTagValues:
    """OSM uses ';' as its multi-value separator. 84 osm_building_type values
    in this dataset are composites; splitting them in as_list() lets the
    existing single-value rules answer, instead of one row per combination."""

    @pytest.mark.parametrize("raw,expected", [
        ("church;yes",   ["church", "yes"]),
        ("school;yes",   ["school", "yes"]),
        ("a;b;c",        ["a", "b", "c"]),
        ("plain",        ["plain"]),
        ("['x','y']",    ["x", "y"]),
        ("['a;b']",      ["a", "b"]),
        (None,           []),
        ("",             []),
    ])
    def test_as_list_splits_on_semicolon(self, raw, expected):
        assert as_list(raw) == expected

    @pytest.mark.parametrize("value,label,cls", [
        ("church;yes", "meetup", "public facilities"),
        ("school;yes", "school", "schools"),
        ("retail;yes", "retail_daily", "retail"),
        ("industrial;yes", "work", "industrial operations production"),
    ])
    def test_composites_resolve_through_existing_rules(self, value, label, cls):
        r = classify(osm_building_type=value)
        assert label in r["mid_labels"]
        assert r["bosserhof_class"] == cls

    def test_kv_pairs_still_parse_after_the_split_change(self):
        r = classify(additional_information="office: lawyer; craft: bakery")
        assert "business" in r["mid_labels"]
        assert r["bosserhof_class"] is not None


# ── Exclusions on the OSM side ────────────────────────────────────────────────

class TestVehicleStorageExcluded:
    @pytest.mark.parametrize("value", ["garage", "garages", "carport", "parking"])
    def test_carries_no_activity(self, value):
        for col in ("building", "osm_building_type"):
            r = classify(**{col: value})
            assert r["mid_labels"] == [], f"{col}={value} should carry no activity"
            assert r["bosserhof_class"] is None


class TestFarmBuildings:
    """ALKIS already drops 'Land- und forstwirtschaftliches Betriebsgebäude'
    via config.LABELS_TO_REMOVE, so the OSM side matches: livestock and farm
    structures carry no destination activity. Greenhouses are the documented
    exception, mirroring ALKIS keeping 31001_2740."""

    @pytest.mark.parametrize("value", [
        "barn", "stable", "cowshed", "sty", "farm", "farm_auxiliary",
        "allotment_house", "slurry_tank", "digester", "silo",
    ])
    def test_farm_structures_carry_no_activity(self, value):
        r = classify(osm_building_type=value)
        assert r["mid_labels"] == [], f"{value} should carry no activity"
        assert r["bosserhof_class"] is None

    def test_greenhouse_is_still_a_workplace(self):
        r = classify(osm_building_type="greenhouse")
        assert r["mid_labels"] == ["work"]
        assert r["bosserhof_class"] == "others industrial"

    def test_alkis_greenhouse_agrees_with_osm_greenhouse(self):
        assert (classify(function="31001_2740")["bosserhof_class"]
                == classify(osm_building_type="greenhouse")["bosserhof_class"])

    def test_riding_hall_is_a_sports_venue(self):
        r = classify(osm_building_type="riding_hall")
        assert "sports" in r["mid_labels"]
        assert r["bosserhof_class"] == "fitness wellness"


class TestKnownUnknowns:
    def test_shop_yes_is_generic_retail(self):
        """shop=yes states that it IS retail, just not which kind."""
        r = classify(shop="yes")
        assert r["bosserhof_class"] == "retail"
        assert set(r["mid_labels"]) == {"retail_daily", "retail_non_daily", "work"}

    @pytest.mark.parametrize("value", ["hall", "service", "yes", "construction", "ruins"])
    def test_uninformative_building_values_carry_no_activity(self, value):
        r = classify(osm_building_type=value)
        assert r["mid_labels"] == [], f"osm_building_type={value} should carry no activity"


# ── Layer precedence ──────────────────────────────────────────────────────────

class TestLayerPrecedence:
    def test_poi_wins_over_alkis(self):
        """A specific POI must not be overridden by the generic ALKIS code —
        and the ALKIS class (services, 2.31) must not leak in and outrank it."""
        r = classify(shop="bakery", function="31001_2000")
        assert r["interpreted_type"] == "poi_tags"
        assert r["bosserhof_class"] == "retail small scale"
        assert "business" not in r["mid_labels"]

    def test_kindergarten_is_not_overridden_by_services(self):
        """kindergartens is 2.30 and services is 2.31, so a union-then-max-weight
        design would silently turn every kindergarten into 'services'."""
        r = classify(amenity="kindergarten", function="31001_2000")
        assert r["bosserhof_class"] == "kindergartens"

    def test_alkis_wins_over_osm_footprint(self):
        r = classify(function="31001_3021", osm_building_type="commercial")
        assert r["interpreted_type"] == "alkis_code"
        assert r["bosserhof_class"] == "schools"

    def test_alkis_exclusion_halts_and_does_not_fall_through(self):
        """An explicit 'no activity' is an answer, not a gap. Measured: letting
        exclusions fall through would reclassify 492 of 252,470 buildings."""
        r = classify(function="31001_1000", osm_building_type="commercial")
        assert r["interpreted_type"] == "alkis_code"
        assert r["mid_labels"] == []
        assert r["bosserhof_class"] is None

    def test_osm_footprint_used_when_no_alkis_code(self):
        r = classify(osm_building_type="commercial")
        assert r["interpreted_type"] == "osm_fallback"
        assert r["bosserhof_class"] == "services"

    def test_osm_landuse_is_the_last_resort(self):
        r = classify(osm_landuse_class="industrial")
        assert r["interpreted_type"] == "osm_fallback"
        assert r["bosserhof_class"] == "industrial operations production"


# ── Multi-POI reconciliation ──────────────────────────────────────────────────

class TestMultiPoiReconciliation:
    def test_labels_are_unioned(self):
        r = classify(shop="['bakery','clothes']")
        assert "retail_daily" in r["mid_labels"]
        assert "retail_non_daily" in r["mid_labels"]

    def test_highest_weight_class_wins(self):
        """retail small scale (3.75) beats discount stores (0.9)."""
        r = classify(shop="['supermarket','bakery']")
        assert r["bosserhof_class"] == "retail small scale"

    def test_explicit_null_entries_do_not_win(self):
        """shop=vacant is (set(), None) and must not suppress a real hit."""
        r = classify(shop="['vacant','bakery']")
        assert r["bosserhof_class"] == "retail small scale"

    def test_across_different_tag_columns(self):
        r = classify(amenity="restaurant", shop="bakery")
        assert "leisure" in r["mid_labels"]
        assert "retail_daily" in r["mid_labels"]
        assert r["bosserhof_class"] == "retail small scale"  # 3.75 > 1.9
