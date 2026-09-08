"""config.py — central configuration for the final capacity-calculation pipeline.

To adapt the pipeline to a new region, only edit this file.

Constants are added here as each step is built, so a constant's presence means
some step actually reads it. Nothing is carried over speculatively.
"""

import os
from pathlib import Path

# ──────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────

ROOT = Path(__file__).parent

# INPUT_DIR can be overridden so the multi-GB source files may live outside the
# repo (they are gitignored either way):
#     set CAPACITY_INPUT_DIR=D:\somewhere\else
INPUT_DIR     = Path(os.getenv("CAPACITY_INPUT_DIR", ROOT / "data" / "input"))
OUTPUT_DIR    = ROOT / "data" / "output"
REFERENCE_DIR = ROOT / "data" / "reference"

# Every layer the pipeline writes is in this CRS. Change for other regions.
TARGET_CRS = "EPSG:25832"   # UTM zone 32N

# ──────────────────────────────────────────────
# STEP 01 — OSM extraction
# ──────────────────────────────────────────────

# Inputs (user-supplied, placed in data/input/)
STUDY_BOUNDARY_FILE = INPUT_DIR / "regionalverband_area.gpkg"   # clip polygon: 8 districts + VW-Werk (contained)
OSM_PBF_FILE        = INPUT_DIR / "niedersachsen-260113.osm.pbf"  # Geofabrik extract

# Outputs
CLIPPED_PBF_FILE       = OUTPUT_DIR / "01_study_area_clipped.pbf"
ALL_POIS_FILE          = OUTPUT_DIR / "01_all_pois.gpkg"
ALL_BUILDINGS_OSM_FILE = OUTPUT_DIR / "01_all_buildings_osm.gpkg"

# ──────────────────────────────────────────────
# STEP 01 — POI extraction filter
# ──────────────────────────────────────────────
# Which OSM keys `pyrosm.get_pois()` is allowed to return.
#
# This MUST be passed explicitly. pyrosm's default is
# {"amenity": True, "shop": True, "tourism": True} and nothing else, which
# silently loses every workplace that OSM describes with another key. Counted
# with `osmium tags-filter -R` on this region's clipped PBF:
#
#     office      1,525 features, only    27 also carry amenity/shop/tourism
#     healthcare  1,210 features, only   900 also carry one of those
#     club          193 features, only    19 also carry one of those
#
# ~1,500 offices - lawyers, insurance, company and government premises - are
# occupied buildings, and for a capacity pipeline missing them is a larger
# error than any amount of street furniture wrongly kept.
#
# `craft` is included as a filter key, not just a column: it was returning 54
# rows as an incidental column and returns 644 as a key.
POI_EXTRACT_FILTER = {
    "amenity": True,
    "shop": True,
    "tourism": True,
    "office": True,
    "craft": True,
    "leisure": True,
}
# `healthcare` and `club` are not in pyrosm's tag configuration, so naming them
# in POI_EXTRACT_FILTER alone would filter on them without promoting them to
# columns (pyrosm falls back to `_basic_tags` for an unknown key). Listing them
# here makes them real columns.
POI_EXTRA_ATTRIBUTES = ["healthcare", "club"]

# ──────────────────────────────────────────────
# STEP 01 — POI role classification
# ──────────────────────────────────────────────

# An area POI's role is decided by how many *real* buildings it contains. These
# two filters keep ancillary structures from inflating that count: a school with
# one classroom block and three garages is a single-footprint POI, not a
# four-building site.
POI_ANCILLARY_BUILDING_TAGS = frozenset({
    "garage", "garages", "carport", "shed", "hut", "roof", "canopy",
    "service", "transformer_tower", "bunker", "ruins", "greenhouse",
    "barn", "stable", "sty", "container", "kiosk", "toilets",
})
POI_MIN_BUILDING_AREA_M2 = 50.0

# Columns kept as real fields on the slimmed POI layer. Every other OSM tag is
# folded into the `tags` JSON string, so nothing is lost - see step 01.
POI_KEEP_TAG_COLS = [
    "amenity", "shop", "tourism", "office", "landuse",
    "building", "building:levels", "religion", "social_facility",
    "craft", "healthcare", "club", "leisure",
]
POI_KEEP_DESC_COLS = ["name", "operator", "opening_hours"]
POI_KEEP_ADDR_COLS = [
    "addr:street", "addr:housenumber", "addr:postcode", "addr:city",
]
# OSM edit metadata - dropped outright rather than folded into `tags`.
POI_DROP_META_COLS = ["lat", "lon", "changeset", "visible", "version"]

# ──────────────────────────────────────────────
# STEP 01 — OSM building layer
# ──────────────────────────────────────────────
# This layer is a REFERENCE, not a deliverable: step 03 uses it to fill gaps
# where ALKIS has no record and to lend OSM attributes to ALKIS buildings. So it
# is not filtered by use the way the POIs are - an unlabelled `building=yes` is
# still a real building. Only non-polygon geometry and OSM edit metadata go.
#
# `building:levels` and `height` are kept because they are the only OSM inputs
# to a volume, and volume is what capacity is derived from.
BUILDING_KEEP_COLS = [
    "building", "building:levels", "building:min_level", "building:flats",
    "building:use", "building:material", "height",
    "name", "amenity", "shop", "office", "craft", "landuse", "operator",
    "addr:street", "addr:housenumber", "addr:postcode", "addr:city",
]
BUILDING_DROP_META_COLS = [
    "visible", "version", "changeset", "timestamp", "source",
    "website", "phone", "email", "url", "wikipedia", "internet_access",
    "opening_hours", "ref", "start_date", "addr:country", "addr:place",
    "addr:housename", "levels",
]

# ──────────────────────────────────────────────
# STEP 01 — POI semantic filter
# ──────────────────────────────────────────────
# A POI is only useful downstream if it names an activity happening INSIDE a
# building. Street furniture, open-air infrastructure and parking do not, and
# would otherwise be assigned to whichever building they happen to sit in.
#
# Reviewed value by value against this region. Two changes from the list used in
# the previous pipeline:
#   grave_yard  KEPT  - 78 of 153 contain a real building (chapels, halls).
#   bus_station DROPPED - the 15 here are paved forecourts, 571-4,136 m2; the
#                         only one tagged building=yes is 13.3 m2, a shelter.
EXCLUDE_AMENITIES = [
    "parking", "bench", "parking_space", "waste_basket",
    "bicycle_parking", "hunting_stand", "recycling", "shelter",
    "post_box", "vending_machine", "charging_station", "grit_bin",
    "parking_entrance", "parcel_locker", "fountain", "waste_disposal",
    "toilets", "drinking_water", "bicycle_rental", "taxi",
    "clock", "car_sharing", "trolley_bay", "motorcycle_parking",
    "marketplace", "atm", "lounger", "telephone",
    "bicycle_repair_station", "kneipp_water_cure", "bus_station", "loading_dock",
    "compressed_air", "letter_box", "nest_box", "vacuum_cleaner",
    "sanitary_dump_station", "water_point", "binoculars", "animal_training",
    "feeding_place", "weighbridge", "ticket_validator", "stables",
    "smoking_area", "information", "water", "table",
    "traffic_park", "boat_rental", "scooter_parking", "kick-scooter_rental",
    "wildlife_feeding", "snow_removal_station", "public_bath", "small_electric_vehicle_parking",
    "deer_feeding", "public_viewing", "bicycle_wash", "locker",
    "baby_hatch", "weight_station", "bbq",
]

# building=* values that are not enterable structures.
EXCLUDE_BUILDING_TYPES = ["roof", "shed", "hut", "container", "no"]

# tourism and information use a keep-list instead: nearly every other value is
# an outdoor feature (viewpoint, artwork, picnic_site, information board), so
# exclusion would be the longer and leakier list.
ALLOWED_TOURISM_TYPES = [
    "chalet", "hotel", "museum",
    "apartment", "guest_house", "hostel",
    "theme_park", "gallery",
]
ALLOWED_INFORMATION_TYPES = ["office"]

# `leisure` is newly extracted and is mostly outdoor: of 9,291 features here,
# 2,878 are pitches, 1,955 playgrounds, 711 private garden swimming pools and
# 670 parks. A keep-list of the enterable venues admits ~1,000 of them.
#
# `stadium` (50) and `water_park` (59) are deliberately absent: the occupancy
# they describe is not inside a building, which is what this layer is for.
ALLOWED_LEISURE_TYPES = [
    "sports_centre", "sports_hall", "fitness_centre", "dance",
    "sauna", "spa", "bowling_alley", "escape_game",
    "hackerspace", "indoor_play", "trampoline_park", "ice_rink",
    "adult_gaming_centre", "amusement_arcade", "tanning_salon", "resort",
]

# Lifecycle prefixes and placeholders, matched against the tag VALUE.
# OSM normally carries these as a key (`disused:amenity=restaurant`), but the
# mis-tagged value form occurs too and reaches this layer as
# `poi_use='disused:restaurant'`. Whatever used to happen here, it does not
# happen now, so the row is not an activity.
EXCLUDE_LIFECYCLE_PREFIXES = (
    "disused:", "abandoned:", "was:", "razed:",
    "demolished:", "removed:", "construction:", "proposed:",
)
EXCLUDE_PLACEHOLDER_USES = frozenset({"construction", "proposed", "fixme", "unknown", "*"})

# Priority order for resolving `poi_use`: the first column holding an
# informative value wins. `amenity` is OSM's primary use descriptor, so
# `amenity=shelter` beats `building=yes` on the same feature; `building` is last
# because it describes the structure, not the activity inside it.
# `club` outranks `leisure`: a sports club carrying `club=sport` +
# `leisure=pitch` is a clubhouse, and `sport` describes it better than `pitch`.
POI_USE_SOURCES = [
    "amenity", "shop", "office", "craft",
    "healthcare", "tourism", "club", "leisure", "building",
]

# ──────────────────────────────────────────────
# STEP 02 — ALKIS / LoD2 extraction
# ──────────────────────────────────────────────
# Recreates ALKIS_LOD2-data_extraction.ipynb from the original pipeline: select
# the region's LoD2 tiles, download them, unzip them, merge them into one layer.
# Extraction only - no volume, no dedupe, no labels, no merging of polygons.
#
# Inputs (user-supplied, placed in data/input/)
#   The tile index is LGLN's statewide catalogue of LoD2 tiles - 37,928 polygons,
#   each carrying `shp` (a zipped shapefile URL), `xml` (the CityGML twin) and
#   `tile_id`. It is EPSG:4326 regardless of what the tiles themselves use.
LOD2_TILE_INDEX_FILE = INPUT_DIR / "lgln-opengeodata-lod2.geojson"

# Download cache. Lives under INPUT_DIR because it is bulk source data, is
# gitignored with the rest of data/input, and can be deleted freely - both
# stages skip whatever is already on disk.
LOD2_CACHE_DIR = INPUT_DIR / "lod2_cache"
LOD2_ZIP_DIR   = LOD2_CACHE_DIR / "zip"   # one .zip per tile, as downloaded
# There is no unzip directory: the merge reads each shapefile straight out of
# its archive through GDAL's /vsizip/ virtual filesystem. Extracting all 3,620
# tiles would cost ~30 GB and produces a byte-identical merge.

# Outputs
LOD2_REGION_TILES_FILE = OUTPUT_DIR / "02_lod2_region_tiles.gpkg"
ALKIS_RAW_FILE         = OUTPUT_DIR / "02_alkis_lod2_raw.gpkg"

# Download behaviour. 3,620 tiles for this region; the source is an IBM Cloud
# object store and handles parallel requests fine, but be a good citizen.
LOD2_DOWNLOAD_WORKERS = 8
LOD2_DOWNLOAD_TIMEOUT_S = 60
LOD2_DOWNLOAD_RETRIES = 3

# The merged layer is RAW: one row per LoD2 surface, not per building. A tile
# holds ground, wall and roof surfaces as separate rows sharing one `gml_id` -
# measured at 3.58 rows per building - so this file is ~3.6x larger than the
# building count and `gml_id` is deliberately NOT unique in it. Reducing it to
# one row per building is a later step's decision, not this one's.
#
# `-nlt MULTIPOLYGONZ` is needed for the merge to work at all: LoD2 shapefiles
# are MultiPatch (3D surfaces), which shapely cannot parse - `geopandas.read_file`
# on a raw tile dies with `ParseException: Unknown WKB type 16` - so GDAL has to
# convert it, and appending 3,620 tiles into one layer needs a single declared
# geometry type.
#
# THE Z ORDINATE IS KEPT. An earlier version passed `-dim XY` to save disk
# (5.09 -> 4.26 GB), on the reasoning that heights are already in the attributes.
# That was wrong: Z does not carry heights, it carries the SURFACE SEMANTICS, and
# it is the only thing that distinguishes a ground surface from a roof surface.
# No attribute column does - every row of a building repeats identical values.
#
# Measured on a 60-tile sweep: classifying by Z gives exactly one GROUND surface
# for 13,833 of 13,833 parts (100.00 %), holding across 46.8-824.9 m terrain,
# both DqDach groups and every surface count. Without Z the fallback is the
# original pipeline's "largest area per gml_id", which is wrong for 1.15 % of
# parts - median +32 %, worst +255 % footprint - because a roof overhang wins the
# maximum. Z also makes an exact volume possible; see ALKIS_VOLUME_METHOD below.
LOD2_MERGE_GEOM_TYPE = "MULTIPOLYGONZ"
LOD2_MERGE_FLATTEN_Z = False

# ──────────────────────────────────────────────
# STEP 03 — ALKIS refinement
# ──────────────────────────────────────────────
# Reads 02_alkis_lod2_raw.gpkg and refines it: drop columns that carry nothing,
# then (later steps) reduce surfaces to buildings and compute volume. Semantics -
# the function codelist, the activity map, the OSM POI join - are step 04's job.

# --- Step 03.1: columns that hold ONE value for every row ---------------------
# Measured on the 4,891,343-row raw layer: each of these has exactly 1 distinct
# value, so it cannot distinguish any building from any other. `Eigentum` and
# `Lizenz` are also ~200 bytes each on every row, which is most of the file's
# bulk rather than most of its information.
#
# This list is asserted against the data, not trusted: step 03 recomputes which
# columns are constant and fails if the sets disagree, because a differing set
# means the source data changed and the reasoning below needs revisiting.
ALKIS_DROP_CONSTANT_COLS = {
    "Lizenz":     "CC-BY-4.0 licence text, identical on every row",
    "Eigentum":   "'Landesamt fuer Geoinformation ...' - the publisher, not the building",
    "Land":       "'Germany' - the whole extract is one country",
    "LetzteAend": "2024-09-30 - one statewide edit date for the release",
    "DqLage":     "1000 - positional quality flag, never varies",
    "DqBoden":    "1300 - ground-surface quality flag, never varies",
    "Geom2DRef":  "3000 - 2D geometry reference code, never varies",
}

# --- Step 03.x (EXPERIMENTAL): ALKIS object outlines --------------------------
# A scratch area for layers made to be looked at in QGIS and then thrown away.
# Not an input to anything, and not a deliverable - hence its own folder rather
# than data/output, so nothing downstream can start depending on it by accident.
EXPERIMENTAL_DIR = ROOT / "data" / "experimental_extract"

# One polygon per ALKIS object (`externRef` tail), built by dissolving every
# surface that belongs to it. Written as a shapefile because that is what was
# asked for; note a shapefile caps each component file at 2 GB and truncates
# field names to 10 characters, so the attributes below are kept short.
ALKIS_OUTLINES_SHP = EXPERIMENTAL_DIR / "alkis_outlines.shp"

# --- Step 03 output: the refined 2D building layer ----------------------------
# One row per LoD2 PART (gml_id), not per ALKIS object. Chosen because every
# height and roof attribute is a property of the part: measHeight, roofType,
# DachName, Firsthoehe and Traufhoehe all differ between the parts of one
# building, so dissolving to alkis_id would force an arbitrary winner and lose
# the rest irreversibly. `alkis_id` is carried on every row, so aggregating up
# to real buildings is a one-line groupby whenever a later step wants it.
#
# This is the hand-off from 3D to 2D: the geometry is the flat GROUND polygon,
# and the 3D information survives as numbers (volume_3d_m3, the height columns).
ALKIS_BUILDINGS_FILE = OUTPUT_DIR / "03_alkis_buildings.gpkg"

# Source name -> output name. Renamed so the columns read as what they are
# rather than as AdV shorthand, and so the two volumes are impossible to mix up.
#
# Note the z/height distinction: Firsthoehe, Traufhoehe and AbsHoehe are ABSOLUTE
# ELEVATIONS above sea level, not heights above the ground, so they become
# `*_z_m`. measHeight really is a height above ground, so it becomes
# `height_ridge_m` - and it is the ridge, not the eaves.
ALKIS_RENAME = {
    "measHeight":  "height_ridge_m",
    "Firsthoehe":  "ridge_z_m",
    "Traufhoehe":  "eaves_z_m",
    "AbsHoehe":    "ground_z_m",
    "DachFlaech":  "roof_area_m2",
    "DachNeig":    "roof_pitch_deg",
    "DachOri":     "roof_azimuth_deg",
    "roofType":    "roof_type",
    "DachName":    "roof_shape",
    "DqDach":      "dq_roof",
    "creationDa":  "created_on",
    "GrundrissA":  "plan_acquired_on",
    "Name":        "name",
    "AGS":         "ags",
    "Stadt":       "city",
    "Strasse":     "street",
    "HausNr":      "house_number",
}

# Final column order: identity, then the measures, then the source attributes.
ALKIS_OUTPUT_COLS = [
    "gml_id", "alkis_id",
    "area_m2", "volume_3d_m3", "volume_old_m3", "volume_ratio",
    "height_ridge_m", "height_eaves_m",
    "ground_z_m", "eaves_z_m", "ridge_z_m",
    "function",
    "roof_shape", "roof_type", "roof_area_m2", "roof_pitch_deg", "roof_azimuth_deg",
    "name", "ags", "city", "street", "house_number",
    "n_surfaces", "n_roof_faces", "dq_roof", "created_on", "plan_acquired_on",
    "geometry",
]
