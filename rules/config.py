"""
config.py — Configuration of the rule-based classifier (rules/).

The rule tables themselves live in rule_utils.py; this file holds the label vocabulary and worker densities they
are checked against, and where the classification reads its input and writes its result. It is separate from the
pipeline's config.py in the repository root, which this folder never imports.
"""

import os
from pathlib import Path

# ──────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────

ROOT      = Path(__file__).parent          # rules/
REPO_ROOT = ROOT.parent

# ALKIS building-function codelist: code -> German / English label (rule_smoke_test.py)
BUILDING_FUNCTION_CODELIST = ROOT / "reference" / "building_function_codelist.csv"

# ──────────────────────────────────────────────
# ACTIVITY LABEL TAXONOMY
# ──────────────────────────────────────────────

# Valid MiD activity labels a building may be assigned (see rule_utils.py)
TARGET_MID_LABELS = {
    "work", "university", "school", "childcare",
    "retail_daily", "retail_non_daily", "leisure",
    "sports", "errands", "meetup", "lessons", "business",
}

# MiD labels -> the 7 zone activity columns used for redistribution
MID_LABEL_TO_ACTIVITY = {
    "work":           "Workers",
    "business":       "Workers",
    "retail_daily":   "Retail_Daily",
    "errands":        "Retail_Daily",
    "retail_non_daily": "Retail_Non-Daily",
    "leisure":        "Leisure",
    "sports":         "Leisure",
    "meetup":         "Leisure",
    "lessons":        "Leisure",
    "school":         "School",
    "university":     "University",
    "childcare":      "Kindergarten",
}

# ──────────────────────────────────────────────
# BOSSERHOF WORKER WEIGHTS
# Workers per 100 m³ of building volume for each Bosserhof class.
# All keys must be lowercase (normalization is applied before lookup).
# Every class must be listed: a missing one gives NaN and the building is silently dropped.
# ──────────────────────────────────────────────

BOSSERHOF_WEIGHTS = {
    "transport":                        0.5,
    "yards depots storage areas construction yards": 0.85,
    "highly productive industries machine material or space intensive": 0.85,
    "others industrial":                1.85,
    "craft businesses":                 1.9,
    "craft courtyards":                 1.85,
    "normal office":                    2.9,
    "open plan office":                 4.15,
    "business oriented services":       3.5,
    "customer oriented services":       3.0,
    "hotels":                           1.5,
    "hotels with conference areas":     0.8,
    "restaurants gastronomy":           1.9,
    "suppliers for car dealerships":    1.7,
    "vehicle electrical repair":        2.0,
    "customer service":                 3.3,
    "car dealerships":                  0.7,
    "wholesale":                        2.45,
    "retail small scale":               3.75,
    "discount stores":                  0.9,
    "diy stores":                       0.75,
    "furniture stores":                 0.55,
    "hypermarkets superstores":         1.2,
    "shopping centers":                 3.1,
    "self service department stores":   1.1,
    "department stores":                1.55,
    "factory outlet centers":           2.15,
    "retail wholesale":                 2.1,    # missing → NaN → silent drop
    "schools":                          1.0,
    "universities":                     0.75,
    "research institutes":              1.25,
    "kindergartens":                    2.3,
    "hospitals":                        1.25,
    "nursing homes":                    0.62,
    "entertainment culture":            1.67,
    "large cinemas":                    0.83,
    "musical theatres":                 1.43,
    "large discos fun leisure pools":   0.8,
    "arenas large events":              1.43,
    "theme parks":                      1.67,
    "fitness wellness":                 0.8,
    "industrial operations production": 1.35,
    "crafts and trades":                1.88,
    "services":                         2.31,
    "retail":                           1.75,
    "public facilities":                1.2,
    "facilities for culture leisure and sports": 1.23,
}

# ──────────────────────────────────────────────
# INPUT: THE PREPROCESSED BUILDINGS AND POIs
# Written by steps 01 and 04 of the pipeline (pipeline/01_osm_extraction.ipynb,
# pipeline/04_semantic_enrichment.ipynb). Only read, never written. Set the
# environment variable RULES_INPUT_DIR to read them from another folder.
# ──────────────────────────────────────────────

INPUT_DIR = Path(os.getenv("RULES_INPUT_DIR", REPO_ROOT / "data" / "output"))

ENRICHED_BUILDINGS_FILE = INPUT_DIR / "04_buildings_enriched.gpkg"  # layers buildings, building_pois
ALL_POIS_FILE           = INPUT_DIR / "01_all_pois.gpkg"            # layer pois: every OSM tag of a POI

# Which building-POI pairs feed the engine's POI-tag columns. Own pairs are POIs placed
# on the building (inside it or snapped to it within 50 m, as a point, a footprint or a
# unit of a mall); site pairs are the campus, plant or estate polygons that contain it.
# Main run: own + site. Second run: own POIs only, as a sensitivity check.
POI_RUNS = {
    "sites": ("point", "footprint", "unit", "site"),
    "own":   ("point", "footprint", "unit"),
}

# ──────────────────────────────────────────────
# OUTPUT
# ──────────────────────────────────────────────

# One row per building: building_id, then per run the Bosserhof class, the MiD labels and the deciding layer
RULES_OUTPUT_FILE = REPO_ROOT / "data" / "output" / "rules_classification.parquet"
