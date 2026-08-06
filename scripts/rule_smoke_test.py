"""
rule_smoke_test.py — Check what the rule-based classifier (rule_utils.py)
predicts for a given set of tags, without touching real data. Use this to
sanity-check the rule tables before running the pipeline.

Usage (from project root):

    # One-shot: pass tags as flags, see the prediction and which layer fired
    python scripts/rule_smoke_test.py --amenity restaurant
    python scripts/rule_smoke_test.py --shop bakery --shop kiosk
    python scripts/rule_smoke_test.py --function 31001_2000
    python scripts/rule_smoke_test.py --function 31001_2000 --osm_landuse_class industrial
    python scripts/rule_smoke_test.py --building church --additional_information "religion: christian"

    # Inspect the ALKIS code table directly: every code, or one code, with its
    # German label and the answer it produces
    python scripts/rule_smoke_test.py --alkis
    python scripts/rule_smoke_test.py --alkis 31001_3031

    # Interactive REPL: type "field=value" lines, blank line to classify,
    # "reset" to clear, "quit" to exit
    python scripts/rule_smoke_test.py

    # Pull N real rows from data/output/05_condensed_buildings_with_pois.gpkg
    # and show their tags next to what the rules predict
    python scripts/rule_smoke_test.py --real 15
    python scripts/rule_smoke_test.py --real 15 --seed 7
"""

import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from rule_utils import (
    classify_building, classify_from_tags, classify_from_alkis,
    classify_from_osm_fallback, as_list, parse_additional_information,
    ALKIS_RULES, GENERIC_COMMERCIAL_CODES, refine_by_landuse,
)

# Fields any rule can read.
FIELDS = [
    "amenity", "shop", "tourism", "building", "information",
    "function", "osm_building_type", "osm_landuse_class",
    "additional_information",
]

# Shown for context when inspecting real rows, but NO rule reads these.
# `label_en` is deliberately excluded from the rules: 31001_3031 is "Schloss"
# and ships as "Lock", so the code is the only safe key. `osm_names` is
# excluded by design — see the module docstring in rule_utils.py.
CONTEXT_FIELDS = ["label_en", "osm_names", "volume_m3", "alkis_address"]


def _german_labels():
    """code -> German label, read from the shipped codelist. Display only."""
    try:
        import pandas as pd
        from config import BUILDING_FUNCTION_CODELIST
        cl = pd.read_csv(BUILDING_FUNCTION_CODELIST, encoding="utf-8",
                         encoding_errors="replace")
        return dict(zip(cl["function"], cl["label_de"]))
    except Exception:
        return {}


def explain(row):
    """Show which layer fired and why, then the final result — more detail than
    classify_building() alone gives you."""
    print("-" * 74)
    print("INPUT (read by rules):")
    shown = False
    for f in FIELDS:
        if row.get(f) not in (None, ""):
            print(f"  {f:22} = {row[f]!r}")
            shown = True
    if not shown:
        print("  (no tags set)")

    ctx = [(f, row[f]) for f in CONTEXT_FIELDS if row.get(f) not in (None, "")]
    if ctx:
        print("CONTEXT (not read by any rule):")
        for f, v in ctx:
            print(f"  {f:22} = {v!r}")

    tags_result = classify_from_tags(row)
    print(f"\nLayer 1  POI tags     -> {tags_result}")
    if tags_result is None:
        alkis_result = classify_from_alkis(row)
        print(f"Layer 2  ALKIS code   -> {alkis_result}")
        code = str(row.get("function") or "").strip()
        if code in GENERIC_COMMERCIAL_CODES:
            base = ALKIS_RULES[code][1]
            refined = refine_by_landuse(base, row.get("osm_landuse_class"))
            note = "no match, kept" if refined == base else f"refined from {base!r}"
            print(f"         land-use     -> {refined!r}  ({note})")
        if alkis_result is None:
            print(f"Layer 3  OSM fallback -> {classify_from_osm_fallback(row)}")

    result = classify_building(row)
    print("\nFINAL:")
    print(f"  source          = {result['interpreted_type']}")
    print(f"  mid_labels      = {result['mid_labels']}")
    print(f"  bosserhof_class = {result['bosserhof_class']}")

    extra = parse_additional_information(row.get("additional_information"))
    if extra:
        print(f"  (parsed additional_information -> {extra})")
    print("-" * 74)


def run_alkis_table(only_code=None):
    """Print the ALKIS code table with German labels and resulting answers."""
    de = _german_labels()
    codes = [only_code] if only_code else list(ALKIS_RULES)
    if only_code and only_code not in ALKIS_RULES:
        print(f"Code {only_code!r} is not in ALKIS_RULES ({len(ALKIS_RULES)} codes). "
              "Buildings with it fall through to the OSM layer.")
        return
    print(f"{'code':<12} {'german label':<44} {'mid_labels':<40} bosserhof_class")
    print("-" * 74)
    for code in codes:
        r = classify_building({"gml_id": 0, "function": code})
        labels = ",".join(r["mid_labels"]) or "—"
        cls = r["bosserhof_class"] or "—"
        mark = " *" if code in GENERIC_COMMERCIAL_CODES else ""
        print(f"{code:<12} {str(de.get(code, ''))[:44]:<44} {labels[:40]:<40} {cls}{mark}")
    if not only_code:
        print("-" * 74)
        n_excl = sum(1 for l, c in ALKIS_RULES.values() if not (l or c))
        print(f"{len(ALKIS_RULES)} codes: {n_excl} excluded, {len(ALKIS_RULES)-n_excl} active.")
        print("* = Bosserhof class is refined by osm_landuse_class; see LANDUSE_BOSSERHOF_REFINEMENT.")


def run_one_shot(args):
    row = {"gml_id": 0}
    for f in FIELDS:
        val = getattr(args, f, None)
        if val:
            row[f] = val if isinstance(val, str) else str(val)
    explain(row)


def run_interactive():
    print("Rule smoke test — interactive mode.")
    print(f"Fields: {', '.join(FIELDS)}")
    print("Type 'field=value' (repeat for multiple tags, e.g. amenity=doctors then amenity=pharmacy).")
    print("Blank line = classify. 'reset' = clear current row. 'quit' = exit.\n")

    row = {"gml_id": 0}
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line.lower() in ("quit", "exit"):
            break
        if line.lower() == "reset":
            row = {"gml_id": 0}
            print("(cleared)")
            continue
        if line == "":
            explain(row)
            row = {"gml_id": 0}
            continue
        if "=" not in line:
            print(f"Unrecognized input: {line!r}. Use field=value, or blank line to classify.")
            continue
        field, _, value = line.partition("=")
        field = field.strip()
        if field not in FIELDS:
            print(f"Unknown field {field!r}. Valid fields: {', '.join(FIELDS)}")
            continue
        if field in row and row[field]:
            # accumulate multi-valued tags the way the real data stores them
            row[field] = str(as_list(row[field]) + [value.strip()])
        else:
            row[field] = value.strip()
        print(f"  set {field} = {row[field]!r}")


def run_real_samples(n, seed):
    import geopandas as gpd
    from config import CONDENSED_BUILDINGS_FILE

    if not CONDENSED_BUILDINGS_FILE.exists():
        print(f"ERROR: {CONDENSED_BUILDINGS_FILE} not found. Run notebooks 01-05 first.")
        sys.exit(1)

    print(f"Loading {CONDENSED_BUILDINGS_FILE.name}...")
    gdf = gpd.read_file(CONDENSED_BUILDINGS_FILE).drop(columns=["geometry"])
    if "function" not in gdf.columns:
        print("WARNING: no 'function' column — re-run notebook 05, which now "
              "carries the raw ALKIS code through. Layer 2 will not fire.")
    for _, row in gdf.sample(n, random_state=seed).iterrows():
        explain(row.to_dict())


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for f in FIELDS:
        parser.add_argument(f"--{f}")
    parser.add_argument("--alkis", nargs="?", const="__all__", metavar="CODE",
                        help="Print the ALKIS code table, or one code's entry")
    parser.add_argument("--real", type=int, metavar="N",
                        help="Classify N real rows sampled from the condensed buildings file")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for --real sampling")
    args = parser.parse_args()

    if args.alkis:
        run_alkis_table(None if args.alkis == "__all__" else args.alkis)
    elif args.real:
        run_real_samples(args.real, args.seed)
    elif any(getattr(args, f) for f in FIELDS):
        run_one_shot(args)
    else:
        run_interactive()


if __name__ == "__main__":
    main()
