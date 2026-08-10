"""
make_blind_sample.py — Build a BLIND annotation workbook.

Why this exists
---------------
`sample_version_1_balanced.xlsx` arrived pre-filled with an earlier LLM run's
answers and the reviewer's job was to tick or correct them. That makes the
resulting ground truth a function of what the reviewer was SHOWN, not a property
of the buildings. Measured on that workbook, for Bosserhof:

    green rows (n=719): the new LLM run repeats the earlier answer 68.4% of the
                        time, and scores correct 68.4% of the time. Identical,
                        because on a green row the truth IS the earlier answer.
                        Repeat it -> 100% correct. Deviate -> 0% correct.
    red rows (n=155):   the human overrode the earlier answer, so repeating it is
                        automatically wrong. The new run repeats it 52.9% of the
                        time. It scores 5.2%.

498 of the LLM's 500 correct Bosserhof answers come from the green subset. Its
independently-verified score is 8 of 155. Neither subset ranks classifiers: one
rewards agreeing with the seed, the other punishes it.

The only fix is a sample labelled from the raw evidence with NO classifier output
visible. That is what this script produces.

Outputs
-------
data/validation/blind_sample_v1.xlsx      -> give this to the annotator
    Sheet "annotate"  : evidence + empty answer columns, randomised row order,
                        opaque blind_id (no gml_id, so the old workbook cannot
                        be looked up)
    Sheet "vocabulary": the 7 activities and 47 Bosserhof classes, verbatim
    Sheet "how_to"    : instructions, including how to say "no activity"

data/validation/blind_sample_v1_key.parquet -> DO NOT OPEN BEFORE ANNOTATING
    blind_id -> gml_id, plus both classifiers' predictions, held back for scoring.

Reproducible: fixed seed, stratified by evidence tier so the sample is not
dominated by easy POI-tagged buildings.

Usage:
    python scripts/make_blind_sample.py [--n 200] [--seed 20260810]
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import pyogrio

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config import (                                          # noqa: E402
    VALIDATION_BUILDINGS_FILE, VALIDATION_GROUND_TRUTH, VALIDATION_DIR,
    BUILDING_FUNCTION_CODELIST, GENERIC_COMMERCIAL, ZONE_ACTIVITY_COLUMNS,
    BOSSERHOF_WEIGHTS, llm_validation_checkpoint,
)
from rule_utils import classify_building                       # noqa: E402
from validation_utils import resolve_prediction_bosserhof      # noqa: E402
from llm_utils import normalise_mid_labels                     # noqa: E402

OUT_XLSX = VALIDATION_DIR / "blind_sample_v1.xlsx"
OUT_KEY = VALIDATION_DIR / "blind_sample_v1_key.parquet"

# Shown to the annotator. This is deliberately EVERYTHING known about the
# building, including names: blindness here means "no classifier output", not
# "less evidence". The truth is what is actually there, not what any one
# classifier is permitted to see.
EVIDENCE_COLUMNS = [
    "osm_names", "amenity", "shop", "building", "tourism", "information",
    "label_en", "osm_building_type", "osm_landuse_class", "osm_landuse_name",
    "gfk_class", "ALKIS_Landuse_info", "tags_search", "additional_information",
    "volume_m3",
]

POI_COLS = ["amenity", "shop", "tourism", "building", "information",
            "additional_information"]


def evidence_tier(row):
    """Same tiering notebook 10 uses — classifier-independent, from the row."""
    if any(pd.notna(row.get(c)) and str(row.get(c)).strip() not in ("", "None")
           for c in POI_COLS):
        return "1 POI tag"
    fn = str(row.get("function") or "")
    if fn in GENERIC_COMMERCIAL:
        return "2 generic commercial code"
    if fn:
        return "3 specific code"
    if pd.notna(row.get("osm_building_type")) or pd.notna(row.get("osm_landuse_class")):
        return "4 OSM footprint only"
    return "5 no signal"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200, help="buildings to sample")
    ap.add_argument("--seed", type=int, default=20260810)
    args = ap.parse_args()

    if not VALIDATION_BUILDINGS_FILE.exists():
        raise SystemExit(f"missing: {VALIDATION_BUILDINGS_FILE}")

    # ── Sample frame: the 885 buildings BOTH arms already have predictions for.
    # Reusing them costs no API calls and, because these are also the rows the
    # biased workbook covers, it lets us measure the acceptance bias directly:
    # blind truth vs workbook truth on the very same buildings.
    truth = pd.read_parquet(VALIDATION_GROUND_TRUTH)
    truth["gml_id"] = truth["gml_id"].astype(str)
    frame_ids = set(truth.loc[truth.activities_scoreable | truth.bosserhof_scoreable,
                              "gml_id"])

    fields = set(pyogrio.read_info(VALIDATION_BUILDINGS_FILE)["fields"])
    need = ["gml_id"] + [c for c in EVIDENCE_COLUMNS if c in fields]
    src = pyogrio.read_dataframe(VALIDATION_BUILDINGS_FILE,
                                 columns=[c for c in need if c in fields],
                                 read_geometry=False)
    src["gml_id"] = src["gml_id"].astype(str)
    src = src[src["gml_id"].isin(frame_ids)].copy()

    codelist = pd.read_csv(BUILDING_FUNCTION_CODELIST, encoding="utf-8",
                           encoding_errors="replace")
    src["function"] = src["label_en"].map(dict(zip(codelist["label_en"],
                                                   codelist["function"])))
    src["tier"] = src.apply(evidence_tier, axis=1)

    # ── Stratified sample, proportional to the tier mix of the frame, so the
    # sheet is not dominated by easy POI-tagged buildings.
    shares = src["tier"].value_counts(normalize=True)
    picks = []
    for tier, share in shares.items():
        k = max(1, round(args.n * share))
        grp = src[src["tier"] == tier]
        picks.append(grp.sample(min(k, len(grp)), random_state=args.seed))
    sample = pd.concat(picks).drop_duplicates("gml_id")
    if len(sample) > args.n:
        sample = sample.sample(args.n, random_state=args.seed)

    # ── Randomise row order and assign an OPAQUE id. gml_id is withheld so the
    # annotator cannot look a building up in the old workbook.
    sample = sample.sample(frac=1.0, random_state=args.seed).reset_index(drop=True)
    sample.insert(0, "blind_id", [f"B{i:04d}" for i in range(1, len(sample) + 1)])

    # ── The key: withheld until annotation is finished.
    rule = pd.DataFrame([classify_building(r) for r in sample.to_dict("records")])
    rule["gml_id"] = rule["gml_id"].astype(str)
    key = sample[["blind_id", "gml_id", "tier"]].merge(
        rule[["gml_id", "mid_labels", "bosserhof_class"]].rename(
            columns={"mid_labels": "rule_mid_labels",
                     "bosserhof_class": "rule_bosserhof"}),
        on="gml_id", how="left")

    ck = llm_validation_checkpoint("blind", 1)
    if ck.exists():
        llm = pd.read_parquet(ck)
        llm["gml_id"] = llm["gml_id"].astype(str)
        llm["llm_mid_labels"] = llm["mid_labels"].map(normalise_mid_labels)
        llm["llm_bosserhof"] = llm["bosserhof_class"].map(resolve_prediction_bosserhof)
        key = key.merge(llm[["gml_id", "llm_mid_labels", "llm_bosserhof"]],
                        on="gml_id", how="left")

    # The old workbook's verdict, so the acceptance bias can be quantified later.
    key = key.merge(truth[["gml_id", "activities_truth", "bosserhof_truth",
                           "activities_scoreable_reason", "bosserhof_scoreable_reason"]]
                    .rename(columns={"activities_truth": "workbook_activities",
                                     "bosserhof_truth": "workbook_bosserhof"}),
                    on="gml_id", how="left")
    key.to_parquet(OUT_KEY, index=False)

    # ── The annotation sheet: evidence + EMPTY answer columns, nothing else.
    sheet = sample[["blind_id"] + [c for c in EVIDENCE_COLUMNS if c in sample.columns]].copy()
    sheet["activities"] = ""
    sheet["bosserhof_class"] = ""
    sheet["uncertain"] = ""
    sheet["notes"] = ""

    # ── LEAK GUARD ────────────────────────────────────────────────────────────
    # The whole instrument is void if a prediction reaches the sheet. The right
    # invariant is PROVENANCE, not string matching: every column must either come
    # from the frozen source file, be the opaque id, or be an empty answer field.
    #
    # A string test would be both too weak and too noisy. Too noisy because
    # 'retail' is simultaneously an OSM landuse value and a Bosserhof headline
    # class, so evidence the annotator must see trips it. Too weak because a
    # leaked prediction under an innocuous column name would pass.
    ANSWER_COLS = {"activities", "bosserhof_class", "uncertain", "notes"}
    allowed = set(fields) | {"blind_id"} | ANSWER_COLS
    foreign = [c for c in sheet.columns if c not in allowed]
    assert not foreign, (
        f"columns not present in {VALIDATION_BUILDINGS_FILE.name} reached the "
        f"annotation sheet: {foreign}. Everything shown must be raw evidence.")

    # Identity must not be recoverable: no gml_id, no tier, no workbook row.
    for banned in ("gml_id", "tier", "row_in_workbook"):
        assert banned not in sheet.columns, f"{banned} must not be in the sheet"

    assert (sheet["activities"] == "").all(), "activities column must ship empty"
    assert (sheet["bosserhof_class"] == "").all(), "bosserhof column must ship empty"
    assert sheet["blind_id"].is_unique, "blind_id must be unique"
    assert set(sheet["blind_id"]) == set(key["blind_id"]), "sheet and key disagree"

    vocab = pd.DataFrame({
        "activities (choose zero or more)":
            sorted(ZONE_ACTIVITY_COLUMNS) + [""] * (len(BOSSERHOF_WEIGHTS) - len(ZONE_ACTIVITY_COLUMNS)),
        "bosserhof_class (choose exactly one, or leave blank)":
            sorted(BOSSERHOF_WEIGHTS),
    })

    how_to = pd.DataFrame({"instructions": [
        "Label each building from the evidence columns ONLY.",
        "",
        "No classifier output is shown anywhere in this workbook, and that is",
        "deliberate. A previous round asked a reviewer to tick or correct an",
        "LLM's answers, and the resulting 'truth' turned out to measure agreement",
        "with that LLM rather than what is actually in the buildings. Please do",
        "not consult the earlier spreadsheet, and do not try to recall it.",
        "",
        "ACTIVITIES — column 'activities'",
        "  Semicolon-separated, from the vocabulary sheet. Example:",
        "     Workers;Retail_Daily",
        "  A building can host several. If nothing happens in it (purely",
        "  residential), write exactly:  none",
        "  Leave BLANK only if you cannot decide.",
        "",
        "BOSSERHOF — column 'bosserhof_class'",
        "  Exactly ONE value from the vocabulary sheet. Prefer the specific",
        "  subcategory; use a headline category only if you genuinely cannot be",
        "  more precise. If the building should carry no class at all, write:  none",
        "  Leave BLANK only if you cannot decide.",
        "",
        "UNCERTAIN — column 'uncertain'",
        "  Put an x here if you are guessing. These rows are excluded from",
        "  scoring rather than counted against anyone.",
        "",
        "NOTES — free text, optional. Useful when the vocabulary has no good fit.",
        "",
        "Please do not add, delete, reorder or rename columns or rows —",
        "blind_id is how answers are matched back to buildings.",
    ]})

    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as xl:
        sheet.to_excel(xl, sheet_name="annotate", index=False)
        vocab.to_excel(xl, sheet_name="vocabulary", index=False)
        how_to.to_excel(xl, sheet_name="how_to", index=False)

    print(f"sample      : {len(sheet)} buildings (seed {args.seed})")
    print("tier mix    :")
    for t, n in sample["tier"].value_counts().sort_index().items():
        print(f"    {t:28s} {n:>4}  ({n/len(sample):.0%})")
    print(f"\nannotate -> {OUT_XLSX}")
    print(f"KEY      -> {OUT_KEY}   (do not open before annotating)")
    print(f"\nkey columns: {list(key.columns)}")


if __name__ == "__main__":
    main()
