"""
config.py — Central configuration for the generic Capacity Calculation Pipeline.

To adapt this pipeline to a new region, only edit the values in this file.
All notebooks import their settings from here.
"""

from pathlib import Path

# ──────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────

ROOT = Path(__file__).parent

INPUT_DIR     = ROOT / "data" / "input"
OUTPUT_DIR    = ROOT / "data" / "output"
REFERENCE_DIR = ROOT / "data" / "reference"

# --- User-supplied input files ---

# (1) ALKIS-like 3D building data
#     Columns expected: gml_id, measHeight (m), function (ALKIS code),
#     optionally: Stadt, Strasse, HausNr, Name
BUILDINGS_FILE         = INPUT_DIR / "buildings.gpkg"

# (2) OSM building footprints — used to fill gaps where ALKIS is missing
#     (new construction, unlicensed buildings, etc.)
#     If you already have this file pre-downloaded/exported, place it here.
#     If left as None, notebook 02 will extract it automatically from the PBF.
OSM_BUILDINGS_INPUT_FILE = INPUT_DIR / "osm_buildings.gpkg"   # set to None to auto-extract

OSM_PBF_FILE           = INPUT_DIR / "region.pbf"           # full Geofabrik download
STUDY_BOUNDARY_FILE    = INPUT_DIR / "study_boundary.gpkg"
ZONE_TARGETS_FILE      = INPUT_DIR / "zone_targets.gpkg"
ZONE_LAYER             = "regionbsstructuredata_zone"

# Column mapping: how to derive the 7 pipeline activity columns from the zone file.
# Each entry is either a single source column name or a list of columns to sum.
# Set to None to use the column name directly (if your zone file already has friendly names).
ZONE_COLUMN_MAP = {
    "Workers":         "SG_3_BE~17",
    "School":          ["SG_4_BS", "SG_4_GSCH", "SG_4_WFSCH"],
    "University":      "SG_4_HS",
    "Kindergarten":    "SG_4_KITA",
    "Retail_Daily":    "SG_5_EK_TB",
    "Retail_Non-Daily":"SG_5_EK~19",
    "Leisure":         "SG_6_FR~23",
}

LANDUSE_FILES = {
    "residential": INPUT_DIR / "landuse_residential.gpkg",
    "commercial":  INPUT_DIR / "landuse_commercial.gpkg",
    "industrial":  INPUT_DIR / "landuse_industrial.gpkg",
    "public":      INPUT_DIR / "landuse_public.gpkg",
    "sports":      INPUT_DIR / "landuse_sports.gpkg",
}

# --- Reference files (shipped with the repo) ---
BUILDING_FUNCTION_CODELIST = REFERENCE_DIR / "building_function_codelist.csv"
ALKIS_ACTIVITY_MAP         = REFERENCE_DIR / "alkis_building_activity_map.xlsx"

# --- Intermediate / output files (written by the pipeline) ---
CLIPPED_PBF_FILE          = OUTPUT_DIR / "area_of_study_clipped.pbf"
ALL_POIS_FILE             = OUTPUT_DIR / "01_all_pois.gpkg"
ALL_BUILDINGS_OSM_FILE    = OUTPUT_DIR / "01_all_buildings_osm.gpkg"
VOLUMES_FILTERED_FILE     = OUTPUT_DIR / "01_building_volumes_filtered.gpkg"
OSM_POIS_MODIFIED_FILE    = OUTPUT_DIR / "03_osm_pois_modified.gpkg"
ENRICHED_BUILDINGS_FILE   = OUTPUT_DIR / "04_enriched_building_volume_data.gpkg"
CONDENSED_BUILDINGS_FILE  = OUTPUT_DIR / "05_condensed_buildings_with_pois.gpkg"
CLASSIFIED_BUILDINGS_FILE = OUTPUT_DIR / "06_classified_buildings.gpkg"

# --- Buildings the validation sample was drawn from (notebook 10) ---
# The condensed dataset whose rows the annotated workbook indexes into.
#
# Needed because notebook 05 derives `gml_id` from the positional row index, which is
# NOT reproducible across runs: a fresh run of identical code produced 567,961
# buildings against this file's 578,080, and of the validation ids that still resolved,
# NONE had a matching volume. Scoring against a regenerated dataset therefore compares
# different buildings while every join looks healthy.
#
# The workbook stores those positional ids, so this file is the only input that can be
# scored against it. Notebook 10 verifies the correspondence via volume_m3 before
# scoring, and refuses to score if it fails.
VALIDATION_BUILDINGS_FILE = (
    ROOT.parent / "Capacity_Calculation-pipeline-original" / "Areas-of-interest-POIs"
    / "condensed_buildings_with_pois.gpkg"
)
REDISTRIBUTION_FILE       = OUTPUT_DIR / "07_building_level_redistributed.gpkg"
REDISTRIBUTION_VALIDATION = OUTPUT_DIR / "07_redistribution_validation.csv"
REDISTRIBUTION_LOG        = OUTPUT_DIR / "07_redistribution_allocation_log.csv"
FINAL_RESULTS_FILE        = OUTPUT_DIR / "08_final_results.gpkg"

# --- Manual validation (notebooks 09 & 10) ---
VALIDATION_DIR            = ROOT / "data" / "validation"
# Hand-annotated workbook: an earlier classification run's predictions with the
# validator's verdict encoded as a cell fill colour. See notebook 09.
VALIDATION_SOURCE_FILE    = VALIDATION_DIR / "sample_version_1_balanced.xlsx"
VALIDATION_GROUND_TRUTH   = VALIDATION_DIR / "09_ground_truth.parquet"
VALIDATION_SCORE_DETAIL   = VALIDATION_DIR / "10_score_detail.csv"
VALIDATION_SCORE_SUMMARY  = VALIDATION_DIR / "10_score_summary.csv"

# Fill colours used by the validator, as ARGB hex (openpyxl reports them this
# way). These are Excel's standard green/red/yellow conditional-format fills.
VALIDATION_COLOURS = {
    "FFC6EFCE": "correct",     # green  — prediction accepted as-is
    "FFFFC7CE": "error",       # red    — wrong; corrected value typed in the cell
    "FFFFEB9C": "uncertain",   # yellow — validator could not decide; excluded
}

# Free-text values the validator used to mean "this building hosts no activity"
# (i.e. it is residential). These are a real, scoreable ground truth of "empty",
# distinct from an empty cell, which means "flagged wrong but never corrected".
VALIDATION_NO_ACTIVITY_TERMS = {"living", "residential", "seems residential", "none", "no"}

# Misspelled activity names OBSERVED in this workbook's hand-typed corrections.
# Without an entry the name matches nothing and the label is SILENTLY DROPPED from
# the ground truth, which then penalises any classifier that predicted it correctly.
# Exactly two such typos exist in sample_version_1_balanced.xlsx:
#   gml_id 229408  row 584   "['Kindergarden', 'Leisure', 'Workers']"  -> lost Kindergarten
#   gml_id 478921  row 1051  "['Workers', 'Leisue']"                   -> lost Leisure
#
# DO NOT pre-populate this with plausible-looking typos that do not occur. Notebook 09
# asserts that no unrecognised token resembles an activity name, and that assertion is
# the real safety mechanism. A speculative entry would silently absorb a future typo
# before the assertion could report it — so guessing here makes the ground truth less
# trustworthy, not more. Add an entry only after the notebook has failed and named it.
VALIDATION_ACTIVITY_TYPO_FIXES = {
    "kindergarden": "Kindergarten",
    "leisue": "Leisure",
}

# ──────────────────────────────────────────────
# COORDINATE REFERENCE SYSTEM
# ──────────────────────────────────────────────

TARGET_CRS = "EPSG:25832"   # UTM Zone 32N — change for other regions

# ──────────────────────────────────────────────
# VOLUME THRESHOLDS
# ──────────────────────────────────────────────

MIN_BUILDING_VOLUME_M3  = 1    # filter in notebook 01 (geometry cleaning)
MIN_CONDENSED_VOLUME_M3 = 30   # filter in notebook 05 (before classification)

# ──────────────────────────────────────────────
# OSM POI EXTRACTION
# ──────────────────────────────────────────────

EXCLUDE_AMENITIES = [
    "parking", "bench", "parking_space", "waste_basket", "bicycle_parking",
    "hunting_stand", "recycling", "shelter", "post_box", "vending_machine",
    "charging_station", "grit_bin", "parking_entrance", "parcel_locker",
    "fountain", "grave_yard", "waste_disposal", "toilets", "drinking_water",
    "bicycle_rental", "taxi", "clock", "car_sharing", "trolley_bay",
    "motorcycle_parking", "marketplace", "atm", "lounger", "telephone",
    "bicycle_repair_station", "kneipp_water_cure", "bus_station",
    "loading_dock", "compressed_air", "letter_box", "nest_box",
    "vacuum_cleaner", "sanitary_dump_station", "water_point", "binoculars",
    "animal_training", "feeding_place", "weighbridge", "ticket_validator",
    "stables", "smoking_area", "information", "water", "table",
    "traffic_park", "boat_rental", "scooter_parking", "kick-scooter_rental",
    "wildlife_feeding", "snow_removal_station", "public_bath",
    "small_electric_vehicle_parking", "deer_feeding", "public_viewing",
    "bicycle_wash", "locker", "baby_hatch", "weight_station", "bbq",
]

EXCLUDE_BUILDING_TYPES = ["roof", "shed", "hut", "container", "no"]

ALLOWED_TOURISM_TYPES = [
    "chalet", "hotel", "museum", "apartment", "guest_house",
    "hostel", "theme_park", "gallery",
]

ALLOWED_INFORMATION_TYPES = ["office"]

# ──────────────────────────────────────────────
# BUILDING LABEL EXCLUSIONS
# Non-enterable / infrastructure building types to remove from ALKIS data.
#
# NOTE: this list matches on the English `label_en` text, unlike
# rule_utils.ALKIS_RULES which is keyed on the raw code. An entry that does not
# exactly match a real codelist label is a SILENT no-op — it filters nothing and
# raises nothing. Validate entries against the CODELIST, not against your data:
# a label absent from the codelist is a typo (a bug), whereas a valid label with
# zero buildings is simply inactive in this region (fine).
#     python -c "import pandas as pd, config as c; \
#       cl=pd.read_csv(c.BUILDING_FUNCTION_CODELIST, encoding='utf-8', encoding_errors='replace'); \
#       print('typos:', [l for l in c.LABELS_TO_REMOVE if l not in set(cl['label_en'])])"
# ──────────────────────────────────────────────

LABELS_TO_REMOVE = [
    "canopy",
    "Agricultural and forestry business building",
    # Was "Buildings for supplying energy", which matches no codelist label and
    # was therefore a no-op. The real label for 31001_2501 is below. It happens
    # to be unused in Lower Saxony (0 buildings — like every other specific
    # supply subtype: 2510 water, 2520 electricity, 2570 gas, 2590 utility,
    # 2591 pumping station), so fixing it changes nothing here, but it would
    # have failed silently in a region that does populate the code.
    "Energy supply buildings",
    "silo",
    "mast",
    "Solar cells",
    "Wind turbine",
    "Operational building for road traffic",
    "tank",
    "Radio mast",
    "chimney",
    "barracks",
    "Transmission and radio tower",
    "Creation",
    "Observation tower",
    "Water tower",
    "Windmill",
    "ski jump (inrun)",
]

# ──────────────────────────────────────────────
# ACTIVITY LABEL TAXONOMY
# ──────────────────────────────────────────────

# Valid MiD activity labels a building may be assigned (see rule_utils.py)
TARGET_MID_LABELS = {
    "work", "university", "school", "childcare",
    "retail_daily", "retail_non_daily", "leisure",
    "sports", "errands", "meetup", "lessons", "business",
}

# ──────────────────────────────────────────────
# BOSSERHOF CLASS NORMALIZATION
# Maps non-standard classifier outputs → canonical class names
# ──────────────────────────────────────────────

BOSSERHOF_NORMALIZATION_MAP = {
    "others":                           "others industrial",
    "industrial operations production others":
        "industrial operations production",
    "highly productive industries":
        "highly productive industries machine material or space intensive",
    "services normal office":           "normal office",
    "industrial operations others":     "industrial operations production",
    "industrial operations production highly productive industries machine material or space intensive":
        "highly productive industries machine material or space intensive",
    "yards depots storage areas":
        "yards depots storage areas construction yards",
    "services customer oriented services": "customer oriented services",
    "facilities for culture leisure and sports fitness wellness": "fitness wellness",
    "fun leisure pools":                "large discos fun leisure pools",
}

# ──────────────────────────────────────────────
# BOSSERHOF WORKER WEIGHTS
# Workers per 100 m³ of building volume for each Bosserhof class.
# All keys must be lowercase (normalization is applied before lookup).
# Bug fix: added "retail wholesale" (was missing → silent NaN drop)
# Bug fix: fixed casing on "normal office", "hotels", "customer service", etc.
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
    "retail wholesale":                 2.1,    # was missing → NaN → silent drop
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

# Bosserhof classes where worker volume is capped at 75th percentile
STRICT_CAP_CLASSES = {
    "restaurants gastronomy",
    "retail small scale",
    "discount stores",
    "diy stores",
    "wholesale",
    "retail",
}

# Bosserhof classes where volume is capped at 95th percentile
LARGE_FORMAT_CAP_CLASSES = {
    "shopping centers",
    "hypermarkets superstores",
    "self service department stores",
    "department stores",
    "factory outlet centers",
}

# ──────────────────────────────────────────────
# ACTIVITY REDISTRIBUTION MAPPING
# Maps MiD labels → zone activity column names
# ──────────────────────────────────────────────

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

# Zone activity columns expected in ZONE_TARGETS_FILE
ZONE_ACTIVITY_COLUMNS = [
    "Workers", "School", "University", "Kindergarten",
    "Retail_Daily", "Retail_Non-Daily", "Leisure",
]

# OSM buildings: assumed floor height in meters when no height tag exists
DEFAULT_FLOOR_HEIGHT_M = 2.0
DEFAULT_FLOORS         = 1
