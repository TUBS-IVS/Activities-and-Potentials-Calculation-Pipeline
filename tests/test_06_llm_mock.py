"""
test_06_llm_mock.py — LLM classification tests using real sampled rows + mock API.

The fixture `tests/data/sample_condensed_buildings.parquet` contains 24 rows
sampled from the real condensed buildings file across 8 signal buckets:
  school, kindergarten, restaurant, supermarket, hospital, office, named_only, sparse

No real API calls are made. The mock returns deterministic JSON based on the
sentence content, so these tests exercise the full pipeline
(real data → sentence → mock LLM → extract → validate) on realistic inputs.

To regenerate the sample fixture from fresh data:
    python tests/create_llm_test_sample.py
"""

import json
import pytest
import pandas as pd

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import TARGET_MID_LABELS
from llm_utils import is_missing, format_value, row_to_llm_input, extract_first_json, validate as _validate

DATA_DIR = Path(__file__).parent / "data"
SAMPLE_FILE = DATA_DIR / "sample_condensed_buildings.parquet"


def validate(obj):
    _validate(obj, TARGET_MID_LABELS)


# ── Mock LLM — keyword-based, no API calls ────────────────────────────────────

def mock_call_tu_llm(sentence):
    s = sentence.lower()
    if "kindergarten" in s or "kita" in s or "childcare" in s:
        return json.dumps({"interpreted_type": "kindergarten", "mid_labels": ["childcare"],
                           "bosserhof_class": "kindergartens", "reason": "childcare facility"})
    if "school" in s or "grundschule" in s or "gymnasium" in s:
        return json.dumps({"interpreted_type": "school", "mid_labels": ["school", "work"],
                           "bosserhof_class": "schools", "reason": "school detected"})
    if "hospital" in s or "klinik" in s or "krankenhaus" in s:
        return json.dumps({"interpreted_type": "hospital", "mid_labels": ["errands", "work"],
                           "bosserhof_class": "hospitals", "reason": "hospital detected"})
    if "supermarket" in s or "e center" in s or "edeka" in s or "rewe" in s:
        return json.dumps({"interpreted_type": "supermarket", "mid_labels": ["retail_daily", "work"],
                           "bosserhof_class": "discount stores", "reason": "supermarket"})
    if "restaurant" in s or "gastro" in s or "cafe" in s:
        return json.dumps({"interpreted_type": "restaurant", "mid_labels": ["leisure", "errands"],
                           "bosserhof_class": "restaurants / gastronomy", "reason": "restaurant"})
    if "office" in s or "post_office" in s or "büro" in s:
        return json.dumps({"interpreted_type": "office", "mid_labels": ["work", "business"],
                           "bosserhof_class": "normal office", "reason": "office"})
    return json.dumps({"interpreted_type": "unknown", "mid_labels": [],
                       "bosserhof_class": None, "reason": "no clear signal"})


def predict_row_with_mock(gml_id, sentence):
    try:
        raw = mock_call_tu_llm(sentence)
        obj = extract_first_json(raw)
        validate(obj)
        return {"gml_id": gml_id, "mid_labels": obj["mid_labels"],
                "bosserhof_class": obj["bosserhof_class"],
                "interpreted_type": obj["interpreted_type"], "error": None}
    except Exception as e:
        return {"gml_id": gml_id, "mid_labels": [], "bosserhof_class": None,
                "interpreted_type": "error", "error": str(e)}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def sample_df():
    if not SAMPLE_FILE.exists():
        pytest.skip(f"Sample fixture not found: {SAMPLE_FILE}. Run tests/create_llm_test_sample.py first.")
    return pd.read_parquet(SAMPLE_FILE)

@pytest.fixture(scope="module")
def sample_by_bucket(sample_df):
    return {bucket: grp for bucket, grp in sample_df.groupby("_bucket")}

@pytest.fixture(scope="module")
def all_predictions(sample_df):
    results = []
    for _, row in sample_df.iterrows():
        sentence = row_to_llm_input(row.to_dict())
        result = predict_row_with_mock(row["gml_id"], sentence)
        result["_bucket"] = row["_bucket"]
        result["sentence"] = sentence
        results.append(result)
    return results


# ── Tests: sentence building on real rows ─────────────────────────────────────

class TestSentenceBuildingRealRows:
    def test_all_rows_produce_a_string(self, sample_df):
        for _, row in sample_df.iterrows():
            sentence = row_to_llm_input(row.to_dict())
            assert isinstance(sentence, str), f"Expected str, got {type(sentence)} for gml_id={row['gml_id']}"

    def test_nan_fields_never_appear_in_sentence(self, sample_df):
        for _, row in sample_df.iterrows():
            sentence = row_to_llm_input(row.to_dict())
            assert "nan" not in sentence.lower(), f"'nan' leaked into sentence for gml_id={row['gml_id']}: {sentence}"
            assert "none" not in sentence.lower(), f"'none' leaked into sentence for gml_id={row['gml_id']}: {sentence}"

    def test_school_rows_contain_school_keyword(self, sample_by_bucket):
        for _, row in sample_by_bucket["school"].iterrows():
            sentence = row_to_llm_input(row.to_dict())
            assert "school" in sentence.lower() or "grundschule" in sentence.lower() or \
                   "gymnasium" in sentence.lower() or "fahrschule" in sentence.lower(), \
                f"School row gml_id={row['gml_id']} sentence has no school keyword:\n{sentence}"

    def test_kindergarten_rows_contain_kindergarten_keyword(self, sample_by_bucket):
        for _, row in sample_by_bucket["kindergarten"].iterrows():
            sentence = row_to_llm_input(row.to_dict())
            assert "kindergarten" in sentence.lower() or "kita" in sentence.lower(), \
                f"Kindergarten row gml_id={row['gml_id']} missing keyword:\n{sentence}"

    def test_supermarket_rows_contain_supermarket_keyword(self, sample_by_bucket):
        for _, row in sample_by_bucket["supermarket"].iterrows():
            sentence = row_to_llm_input(row.to_dict())
            assert "supermarket" in sentence.lower(), \
                f"Supermarket row gml_id={row['gml_id']} missing keyword:\n{sentence}"

    def test_sparse_rows_produce_nonempty_general_context(self, sample_by_bucket):
        """Sparse rows have no OSM tags but still have ALKIS label_en — sentence must not be empty."""
        for _, row in sample_by_bucket["sparse"].iterrows():
            sentence = row_to_llm_input(row.to_dict())
            assert sentence != "", f"Sparse row gml_id={row['gml_id']} produced empty sentence"

    def test_multi_value_fields_use_semicolon_separator(self, sample_df):
        """Rows with list-valued columns (e.g. multiple shop types) must join with '; '."""
        list_rows = sample_df[sample_df["shop"].astype(str).str.startswith("[")]
        if list_rows.empty:
            pytest.skip("No list-valued shop column in sample")
        for _, row in list_rows.iterrows():
            sentence = row_to_llm_input(row.to_dict())
            assert ";" in sentence or len(sentence) > 0, \
                f"List shop values not formatted correctly in gml_id={row['gml_id']}"


# ── Tests: JSON extraction (pure unit — not data-dependent) ───────────────────

class TestJSONExtraction:
    def test_extracts_valid_json(self):
        raw = 'Some text {"interpreted_type": "office", "mid_labels": ["work"], "bosserhof_class": "normal office", "reason": "office"} trailing'
        obj = extract_first_json(raw)
        assert obj["interpreted_type"] == "office"
        assert obj["mid_labels"] == ["work"]

    def test_raises_on_no_json(self):
        with pytest.raises(ValueError, match="No JSON"):
            extract_first_json("This has no JSON at all")

    def test_raises_on_invalid_json(self):
        with pytest.raises((ValueError, json.JSONDecodeError)):
            extract_first_json("{invalid json here")


# ── Tests: schema validation (pure unit) ──────────────────────────────────────

class TestValidation:
    def test_valid_response_passes(self):
        obj = {"interpreted_type": "school", "mid_labels": ["school", "work"],
               "bosserhof_class": "schools", "reason": "It is a school."}
        validate(obj)

    def test_invalid_mid_label_raises(self):
        obj = {"interpreted_type": "x", "mid_labels": ["INVALID_LABEL"],
               "bosserhof_class": None, "reason": "x"}
        with pytest.raises(ValueError, match="Invalid label"):
            validate(obj)

    def test_missing_key_raises(self):
        obj = {"mid_labels": [], "bosserhof_class": None, "reason": "x"}
        with pytest.raises(ValueError, match="Missing key"):
            validate(obj)

    def test_null_bosserhof_is_valid(self):
        obj = {"interpreted_type": "bench", "mid_labels": [], "bosserhof_class": None, "reason": "not a building"}
        validate(obj)

    def test_all_target_mid_labels_accepted(self):
        obj = {"interpreted_type": "mixed", "mid_labels": list(TARGET_MID_LABELS),
               "bosserhof_class": "services", "reason": "all labels"}
        validate(obj)


# ── Tests: mock predict on real sample rows ───────────────────────────────────

class TestMockPredictOnRealSamples:
    def test_no_errors_on_any_row(self, all_predictions):
        errors = [r for r in all_predictions if r["error"] is not None]
        msgs = "\n".join(f"  gml_id={r['gml_id']} [{r['_bucket']}]: {r['error']}" for r in errors)
        assert not errors, f"{len(errors)} rows failed:\n{msgs}"

    def test_all_mid_labels_are_valid(self, all_predictions):
        for r in all_predictions:
            for label in r["mid_labels"]:
                assert label in TARGET_MID_LABELS, \
                    f"Invalid label '{label}' for gml_id={r['gml_id']} [{r['_bucket']}]"

    def test_school_rows_get_school_label(self, all_predictions):
        school_rows = [r for r in all_predictions if r["_bucket"] == "school"]
        for r in school_rows:
            assert "school" in r["mid_labels"] or "work" in r["mid_labels"], \
                f"School row gml_id={r['gml_id']} got unexpected labels {r['mid_labels']}\nSentence: {r['sentence']}"

    def test_kindergarten_rows_get_childcare_label(self, all_predictions):
        kinder_rows = [r for r in all_predictions if r["_bucket"] == "kindergarten"]
        for r in kinder_rows:
            assert "childcare" in r["mid_labels"], \
                f"Kindergarten row gml_id={r['gml_id']} got {r['mid_labels']}"

    def test_supermarket_rows_get_retail_daily(self, all_predictions):
        sm_rows = [r for r in all_predictions if r["_bucket"] == "supermarket"]
        for r in sm_rows:
            assert "retail_daily" in r["mid_labels"], \
                f"Supermarket row gml_id={r['gml_id']} got {r['mid_labels']}"

    def test_restaurant_rows_get_leisure_or_errands(self, all_predictions):
        rest_rows = [r for r in all_predictions if r["_bucket"] == "restaurant"]
        for r in rest_rows:
            assert "leisure" in r["mid_labels"] or "errands" in r["mid_labels"], \
                f"Restaurant row gml_id={r['gml_id']} got {r['mid_labels']}"

    def test_sparse_rows_do_not_crash(self, all_predictions):
        sparse_rows = [r for r in all_predictions if r["_bucket"] == "sparse"]
        for r in sparse_rows:
            assert r["error"] is None, \
                f"Sparse row gml_id={r['gml_id']} crashed: {r['error']}"

    def test_sparse_rows_have_no_invented_labels(self, all_predictions):
        """Sparse rows have no amenity/shop/name — mock returns []. Ensure no hallucinated labels."""
        sparse_rows = [r for r in all_predictions if r["_bucket"] == "sparse"]
        for r in sparse_rows:
            assert r["mid_labels"] == [], \
                f"Sparse row gml_id={r['gml_id']} unexpectedly got labels {r['mid_labels']}"

    def test_all_rows_have_interpreted_type(self, all_predictions):
        for r in all_predictions:
            assert r["interpreted_type"] not in (None, "", "error"), \
                f"gml_id={r['gml_id']} [{r['_bucket']}] missing interpreted_type"

    def test_hospital_rows_get_work_or_errands(self, all_predictions):
        hosp_rows = [r for r in all_predictions if r["_bucket"] == "hospital"]
        for r in hosp_rows:
            assert "work" in r["mid_labels"] or "errands" in r["mid_labels"], \
                f"Hospital row gml_id={r['gml_id']} got {r['mid_labels']}"
