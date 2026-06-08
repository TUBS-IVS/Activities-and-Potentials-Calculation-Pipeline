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
BUILDING_FUNCTION_XML      = REFERENCE_DIR / "BuildingFunctionTypeAdV.xml"

# --- Intermediate / output files (written by the pipeline) ---
CLIPPED_PBF_FILE          = OUTPUT_DIR / "area_of_study_clipped.pbf"
ESSENTIAL_POIS_FILE       = OUTPUT_DIR / "01_essential_pois.gpkg"
ALL_POIS_FILE             = OUTPUT_DIR / "01_all_pois.gpkg"
ALL_BUILDINGS_OSM_FILE    = OUTPUT_DIR / "01_all_buildings_osm.gpkg"
VOLUMES_FILTERED_FILE     = OUTPUT_DIR / "01_building_volumes_filtered.gpkg"
OSM_POIS_MODIFIED_FILE    = OUTPUT_DIR / "03_osm_pois_modified.gpkg"
OSM_POIS_CLEANED_FILE     = OUTPUT_DIR / "03_osm_pois_cleaned.gpkg"
ENRICHED_BUILDINGS_FILE   = OUTPUT_DIR / "04_enriched_building_volume_data.gpkg"
CONDENSED_BUILDINGS_FILE  = OUTPUT_DIR / "05_condensed_buildings_with_pois.gpkg"
LLM_PREDICTIONS_DIR       = OUTPUT_DIR / "llm_predictions"
LLM_CHECKPOINT_FILE       = LLM_PREDICTIONS_DIR / "predictions_checkpoint.parquet"
LLM_ERRORS_FILE           = LLM_PREDICTIONS_DIR / "prediction_errors.parquet"
LLM_MERGED_FILE           = OUTPUT_DIR / "09_llm_predictions_merged.gpkg"
POTENTIALS_FILE           = OUTPUT_DIR / "10_final_potentials.gpkg"
REDISTRIBUTION_FILE       = OUTPUT_DIR / "10_building_level_redistributed.gpkg"
REDISTRIBUTION_VALIDATION = OUTPUT_DIR / "10_redistribution_validation.csv"
REDISTRIBUTION_LOG        = OUTPUT_DIR / "10_redistribution_allocation_log.csv"
FINAL_RESULTS_FILE        = OUTPUT_DIR / "11_final_results.gpkg"

# ──────────────────────────────────────────────
# COORDINATE REFERENCE SYSTEM
# ──────────────────────────────────────────────

TARGET_CRS = "EPSG:25832"   # UTM Zone 32N — change for other regions

# ──────────────────────────────────────────────
# VOLUME THRESHOLDS
# ──────────────────────────────────────────────

MIN_BUILDING_VOLUME_M3  = 1    # filter in notebook 01 (geometry cleaning)
MIN_CONDENSED_VOLUME_M3 = 30   # filter in notebook 05 (before LLM input)

# ──────────────────────────────────────────────
# OSM POI EXTRACTION
# ──────────────────────────────────────────────

ESSENTIAL_SHOP_CATEGORIES = [
    "bakery", "supermarket", "kiosk", "butcher", "convenience",
    "beverages", "chemist", "laundry", "stationery", "greengrocer", "general",
]

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
# Non-enterable / infrastructure building types to remove from ALKIS data
# ──────────────────────────────────────────────

LABELS_TO_REMOVE = [
    "canopy",
    "Agricultural and forestry business building",
    "Buildings for supplying energy",
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
# LLM API SETTINGS
# ──────────────────────────────────────────────

LLM_API_URL        = "https://ki-toolbox.tu-braunschweig.de/api/v1/chat/send"
LLM_MODEL          = "gpt-oss-120b"
LLM_REASONING      = "high"       # "low", "medium", or "high"
LLM_MAX_RETRIES    = 3
LLM_BACKOFF_SEC    = 2.0
LLM_TIMEOUT_SEC    = 120
LLM_MAX_WORKERS    = 4            # ThreadPoolExecutor parallelism
LLM_CHUNK_SIZE     = 50           # rows per checkpoint flush

# Valid MiD activity labels the LLM may assign
TARGET_MID_LABELS = {
    "work", "university", "school", "childcare",
    "retail_daily", "retail_non_daily", "leisure",
    "sports", "errands", "meetup", "lessons", "business",
}

# ──────────────────────────────────────────────
# BOSSERHOF CLASS NORMALIZATION
# Maps non-standard LLM outputs → canonical class names
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
