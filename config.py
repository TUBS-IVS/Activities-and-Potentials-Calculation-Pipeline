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

# Throwaway layers written to be looked at in QGIS and then deleted or
# rewritten. Never an input to anything, and gitignored.
EXPERIMENTAL_DIR = ROOT / "data" / "experimental_extract"

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
#     healthcare  1,216 features
#     club          193 features
#     craft         644 features
#
# ~1,500 offices - lawyers, insurance, company and government premises - are
# occupied buildings, and for a capacity pipeline missing them is a larger
# error than any amount of street furniture wrongly kept.
#
# A key must appear in BOTH this dict and POI_EXTRA_ATTRIBUTES to work properly,
# and the two do different jobs:
#
#     this dict              SELECTS which features are extracted
#     POI_EXTRA_ATTRIBUTES   PROMOTES a tag to a real column
#
# `healthcare` and `club` were in the attributes only, which produced the column
# and almost none of the features. Verified against osmium on the clipped PBF:
#
#                    in PBF   extracted   missing
#     healthcare      1,216         938      -278
#     club              193          29      -164
#
# All 441 missing features carry NO other filter key - `healthcare` or `club` is
# the only tag describing them - so nothing else could pull them in. They are
# real premises: 123 physiotherapists, 36 alternative practitioners, 23
# podiatrists, 15 speech therapists, 6 midwives; 81 sports clubhouses, 6
# gardening clubs, 5 scout huts. Named examples: "Kieferchirurgie am Ring",
# "Hebammenpraxis Lehre", "Heidberger Tennis-Club e.V.", "Schuetzenhaus
# Sauingen". All 441 also pass the section 5 semantic filter, so all 441 reach
# the POI layer.
#
# `craft` is a filter key for the same reason: it was returning 54 rows as an
# incidental column and returns 644 as a key.
POI_EXTRACT_FILTER = {
    # the original six
    "amenity": True,
    "shop": True,
    "tourism": True,
    "office": True,
    "craft": True,
    "leisure": True,
    # recovered after the osmium audit found them extracted-as-columns-only
    "healthcare": True,
    "club": True,
    # added after sweeping every OSM key that can be the ONLY tag on a real
    # premises. Counts are what each one contributes to the final POI layer:
    "sport": True,              # 3,926  climbing walls, shooting ranges, pools
    "historic": True,           # 2,409  mostly memorials; also ruins, historic buildings
    "religion": True,           # 1,116  churches not tagged place_of_worship
    "social_facility": True,    #   369  was already a kept COLUMN but never a selector
    "government": True,         #    89
    "industrial": True,         #    82
    "university": True,         #    70  campus buildings
    "military": True,           #    57  barracks are workplaces
    "education": True,          #    31
    "company": True,            #    19
    "trade": True,              #    19
    "school": True,             #     9
}
# Promotes a tag to a real column. `healthcare` and `club` are not in pyrosm's
# tag configuration, so without this pyrosm falls back to `_basic_tags` for them
# and the column never appears - which is why they must be listed in BOTH places
# rather than in either one alone.
POI_EXTRA_ATTRIBUTES = [
    "healthcare", "club", "sport", "historic", "religion", "social_facility",
    "government", "industrial", "university", "military", "education",
    "company", "trade", "school",
]

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
# EVERY RULE IS A BLOCK-LIST. That is a deliberate change from an earlier
# version which used allow-lists for `tourism`, `information` and `leisure`:
#
#     a block-list drops what you have judged
#     an allow-list drops everything nobody thought to name
#
# The second is a hard drop by omission, and it was doing real damage. Measured
# on this region: the `tourism` allow-list had 8 permitted values, so `zoo`,
# `attraction`, `camp_site` and `caravan_site` were deleted for not being on it -
# 86 % of that rule's drops were wrong. `leisure` deleted water parks, marinas,
# golf courses and riding stables the same way. Downstream classification is done
# by an LLM, which handles an odd tag far better than this filter handles an
# unlisted one, so the bar here is "definitely not a visitable interior" rather
# than "recognised venue".
#
# Reviewed value by value against this region. `grave_yard` is KEPT - 78 of 153
# contain a real building (chapels, halls). `bus_station` is DROPPED - the 15
# here are paved forecourts, 571-4,136 m2, and the only one tagged building=yes
# is 13.3 m2, a shelter.
POI_EXCLUDE_VALUES = {
    # ── amenity: the big one, 43,448 drops, all reviewed ──────────────────
    "amenity": [
        "parking", "bench", "parking_space", "waste_basket",
        "bicycle_parking", "hunting_stand", "recycling", "shelter",
        "post_box", "vending_machine", "charging_station", "grit_bin",
        "parking_entrance", "parcel_locker", "fountain", "waste_disposal",
        "toilets", "drinking_water", "bicycle_rental", "taxi",
        "clock", "car_sharing", "trolley_bay", "motorcycle_parking",
        "marketplace", "atm", "lounger", "telephone",
        "bicycle_repair_station", "kneipp_water_cure", "bus_station",
        "loading_dock", "compressed_air", "letter_box", "nest_box",
        "vacuum_cleaner", "sanitary_dump_station", "water_point", "binoculars",
        "animal_training", "feeding_place", "weighbridge", "ticket_validator",
        "stables", "smoking_area", "information", "water", "table",
        "traffic_park", "boat_rental", "scooter_parking", "kick-scooter_rental",
        "wildlife_feeding", "snow_removal_station", "public_bath",
        "small_electric_vehicle_parking", "deer_feeding", "public_viewing",
        "bicycle_wash", "locker", "baby_hatch", "weight_station", "bbq",
    ],
    # ── building: NOT a rule any more ─────────────────────────────────────
    # A `building` block-list can never fire here. Every extracted feature
    # carries one of the selector keys; if that value is informative the escape
    # hatch keeps the row, and if it is not, the lifecycle rule drops it anyway.
    # It was dead code in the last run (0 drops) and the dead-rule guard in the
    # notebook would now flag it. Non-enterable building VALUES live in
    # POI_NON_ENTERABLE_BUILDINGS below, where they stop a shed from counting
    # as interior evidence for the veto.
    # ── tourism: only things with no interior at all ──────────────────────
    # Was an 8-value allow-list. `information` is NOT blocked here - a
    # `tourism=information` feature is judged by the `information` rule below,
    # which is where the board-versus-office distinction actually lives.
    "tourism": ["viewpoint", "artwork", "picnic_site"],
    # ── information: boards and signposts, not tourist offices ────────────
    # This rule dropped 0 rows until POI_ESCAPE_HATCH_POINTER_VALUES existed:
    # every guidepost is also `tourism=information`, and that tag counted as
    # "another use", so 6,489 guideposts, boards, maps and route markers - 19 %
    # of the layer - reached the output. `office` and `visitor_centre` are the
    # values with an interior; POI_MUST_SURVIVE guards them.
    "information": [
        "board", "map", "guidepost", "route_marker", "terminal",
        "tactile_map", "tactile_model", "audioguide", "qr_code",
        "hikingmap", "citymap", "departure_board", "depature_board",
    ],
    # ── leisure: open-air by nature ───────────────────────────────────────
    # Was a 16-value allow-list, which deleted water_park, horse_riding, marina
    # and golf_course. `swimming_pool` is deliberately NOT blocked even though
    # ~711 here are private garden pools: a public pool carries the same tag, so
    # the LLM gets to judge rather than this file. (448 of them do carry
    # `access=private` inside `tags`, should that judgement ever be revisited.)
    #
    # `pitch` was on this list and still let 2,753 pitches through, because
    # `sport=soccer` counted as another use. `sport` is in
    # POI_ESCAPE_HATCH_IGNORES now - see there.
    "leisure": [
        "pitch", "playground", "park", "garden", "nature_reserve", "track",
        "dog_park", "common", "firepit", "picnic_table", "outdoor_seating",
        "bleachers", "slipway", "fitness_station", "bird_hide", "wildlife_hide",
        "swimming_area", "beach_resort", "fishing",
    ],
    # ── historic: things with no interior by definition ───────────────────
    # `historic` is a selector because castles, manors, mills and historic
    # buildings are real premises. It also selects 1,243 memorials, 306 boundary
    # stones, 63 milestones and a few dozen wayside crosses, stones and tombs,
    # none of which can be entered. `yes` is NOT blocked: the 119 `historic=yes`
    # rows are mostly old buildings (66 carry a building tag, 84 are named).
    # `ruins`, `castle`, `monument` and `archaeological_site` stay for the LLM.
    "historic": [
        "memorial", "boundary_stone", "milestone", "wayside_cross",
        "wayside_shrine", "stone", "tomb", "cannon", "highwater_mark",
        "rune_stone", "boundary_marker", "marker", "pillory", "gallows",
    ],
}

# A block-list judges its key ONLY when that key is the only thing describing
# the feature. `amenity=fuel` + `building=roof` is a petrol station, not a roof.
# The `leisure` rule already worked this way; extending it to every rule is what
# took the old `building` rule from 58 wrong drops to 0.
#
# Two KEYS never count as evidence, because on their own they describe nothing:
#
#   building  says there is a structure, not what happens in it. Counting it
#             readmitted 58 outdoor features - pitches, stadiums, playgrounds -
#             on the strength of a bare `building=yes`.
#   sport     qualifies a `leisure` feature. `sport=soccer` on a pitch does not
#             put the pitch indoors, yet counting it let 2,753 pitches, 167
#             running tracks and 54 fitness stations through the `leisure`
#             rule. Features carrying ONLY `sport` - 305 climbing walls,
#             shooting ranges, pools - still survive: the lifecycle rule needs
#             one informative key and `sport` counts there.
POI_ESCAPE_HATCH_IGNORES = ("building", "sport")

# One VALUE never counts as evidence either. `tourism=information` is a pointer
# to the `information` key, not a use of its own: the office-versus-board
# distinction lives in `information=office` against `information=guidepost`.
# Until this was written down every guidepost was rescued from the `information`
# rule by the very tag that sent it there; the rule dropped 0 rows and 6,489
# signposts and boards reached the output. Value-level rather than key-level
# because `tourism=museum` must keep vouching for a `historic=memorial`.
POI_ESCAPE_HATCH_POINTER_VALUES = {"tourism": ("information",)}

# ── the veto: interior evidence beats the block-list ──────────────────────
# For these rules a block-listed row is kept when its full tag set - promoted
# columns plus the folded `tags` JSON - shows an enterable structure. NOT applied
# to `amenity` or `tourism`: there it would readmit 2,148 rows, mostly cash
# machines with `opening_hours=24/7`, car parks and recycling containers.
POI_VETO_RULES = ("information", "leisure", "historic")

# What counts as interior evidence, per rule; "*" applies to every veto rule.
#   building          counts unless its value is in POI_NON_ENTERABLE_BUILDINGS
#   building:levels   only buildings have floors
#   indoor            counts only as indoor=yes
#   opening_hours     counts unless it is 24/7, which is what cash machines,
#                     playgrounds and fitness stations carry. Information rule
#                     only: a signpost has no hours, a staffed info point does.
#                     Not for leisure, where municipal playgrounds carry hours.
#   addr:housenumber  information rule only, for the same reason.
# Names are deliberately NOT evidence: of 5,006 named rows these rules drop,
# only 70 have a kept POI of the same name within 100 m, and the business-like
# names are boards ABOUT a museum or a former pharmacy, not the venue itself.
# Measured: about 40 rows rescued in this region - a shooting range mapped as a
# pitch with building=yes, a "Kalthalle" pitch that is a building=sports_hall,
# an info terminal with a house number and opening hours. After the veto no row
# dropped by these rules carries a building tag.
POI_INTERIOR_EVIDENCE = {
    "*":           ("building", "building:levels", "indoor"),
    "information": ("opening_hours", "addr:housenumber"),
}
# Building values that are structures but not interiors anyone visits.
POI_NON_ENTERABLE_BUILDINGS = frozenset({
    "roof", "shed", "hut", "container", "no", "carport", "canopy",
    "garage", "garages", "wall", "ruins", "tent", "shelter", "bunker",
})

# ── qualifier exceptions ──────────────────────────────────────────────────
# A block-listed value that a second tag turns back into a staffed site.
# `amenity=recycling` covers 1,855 container stations and 41 recycling centres
# (Wertstoffhoefe; 30 named, 16 with opening hours), and `recycling_type=centre`
# is the only tag that separates them.
#   key:   (rule key, blocked value)
#   value: {qualifier tag: values that rescue the row}
POI_BLOCK_EXCEPTIONS = {
    ("amenity", "recycling"): {"recycling_type": ("centre",)},
}

# ── regression guard ──────────────────────────────────────────────────────
# Every row carrying one of these values before the filter must still be there
# after it. Tourist offices are the canary for the `information` rule: they
# share `tourism=information` with 6,500 signposts and must not go with them.
POI_MUST_SURVIVE = {"information": ("office", "visitor_centre")}

# Lifecycle prefixes and placeholders, matched against the tag VALUE.
# OSM normally carries these as a key (`disused:amenity=restaurant`), but the
# mis-tagged value form occurs too. Whatever used to happen here, it does not
# happen now, so the row is not an activity.
EXCLUDE_LIFECYCLE_PREFIXES = (
    "disused:", "abandoned:", "was:", "razed:",
    "demolished:", "removed:", "construction:", "proposed:",
)
EXCLUDE_PLACEHOLDER_USES = frozenset({"construction", "proposed", "fixme", "unknown", "*"})

# Where the dropped POIs are written, so the filter can be audited by eye in
# QGIS rather than trusted from a percentage. Carries a `dropped_by` column
# naming the rule that removed each row.
DROPPED_POIS_FILE = EXPERIMENTAL_DIR / "01_dropped_pois.gpkg"

# ──────────────────────────────────────────────
# STEP 01 — poi_use
# ──────────────────────────────────────────────
# `poi_use` is a CONVENIENCE, not a source of truth. It collapses the
# use-bearing columns into one string so the layer can be styled and eyeballed
# in QGIS.
#
# It is deliberately NOT what downstream classification reads. Every tag a POI
# carries survives in the layer - verified against osmium on 31 POIs, 606 of 606
# tags reachable either as a real column or inside the `tags` JSON - so the LLM
# gets the full picture and `poi_use` throwing information away costs nothing.
#
# THE ORDER OF THIS LIST NO LONGER CARRIES MEANING. It used to be a priority
# ranking for picking one winner, which invited unanswerable arguments about
# whether `sport` outranks `leisure`. The filter above only needs the SET - "is
# any use-bearing tag informative?" - and `poi_use` needs only *a* readable
# answer, not the *best* one. First informative value still wins, but which that
# is is now an implementation detail rather than a decision.
POI_USE_SOURCES = [
    "amenity", "shop", "office", "craft", "healthcare", "social_facility",
    "education", "university", "school", "government", "company", "trade",
    "industrial", "military", "tourism", "club", "sport", "religion",
    "historic", "leisure", "building",
]

# ─────────────────────────────
# STEP 01 — POI nesting  (DESIGNED, NOT IMPLEMENTED)
# ─────────────────────────────
# 4,711 POIs sit inside another POI's footprint (1,625 parents) - a mall and its
# tenants, a campus and its institutes. Redistribution needs to split the
# building volume between them by floor area rather than evenly, which means
# step 01 has to emit `poi_parent_id`, `poi_role = 'unit'` and `split_area_m2`.
#
# The rule, the measurements behind it and the traps are written up in
#     docs/nested-poi-area-split.md
#
# No constants are defined here yet on purpose: in this file a constant's
# presence means some step actually reads it, and nothing reads these yet.
# The one gotcha worth repeating here, because it is easy to trip over while
# writing that code: POINTS CARRY `area_m2 = 0.0`, NOT NULL. A null check will
# not find the children that need an imputed area - test the geometry type.

# ──────────────────────────────────────────────
# STEP 02 — ALKIS / LoD2 extraction
# ──────────────────────────────────────────────
# Recreates ALKIS_LOD2-data_extraction.ipynb from the original pipeline: select
# the region's LoD2 tiles, download them, merge them into one layer.
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
# measured at 3.53 rows per building - so this file is ~3.5x larger than the
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
# maximum. Z also makes an exact volume possible; see notebook 03, section 6.
LOD2_MERGE_GEOM_TYPE = "MULTIPOLYGONZ"
LOD2_MERGE_FLATTEN_Z = False
# The two must agree: `-dim XY` together with a Z geometry type asks GDAL to
# flatten and keep Z in the same call.
assert LOD2_MERGE_FLATTEN_Z == (not LOD2_MERGE_GEOM_TYPE.endswith("Z")), (
    "LOD2_MERGE_FLATTEN_Z and LOD2_MERGE_GEOM_TYPE contradict each other"
)

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
# EXPERIMENTAL_DIR is defined in the PATHS block at the top of this file.

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
# `elev_*_m`. measHeight really is a height above ground, so it becomes
# `height_top_m` - and it is the ridge, not the eaves.
# The naming convention, so every column reads on its own:
#   height_*  metres ABOVE THE GROUND at this building
#   elev_*    metres ABOVE SEA LEVEL
#   top       the ridge - the highest line of the roof
#   eaves     the MEAN eaves height. LGLN's attribute table (3D-Kundentag
#             2019, Wichmann, slide 22: "Firsthoehe / Mittlere Traufhoehe /
#             Bodenhoehe in m - Absoluter Wert") makes it a mean, so for a
#             lean-to roof it sits ABOVE the low roof edge - by about 0.8 m on
#             median across the region's 65,030 lean-to parts, 1.25 m in the
#             120 anomalous parts inspected - and `area x height_eaves` is NOT
#             a lower bound on the volume. It was called `wall` here until that
#             was measured.
#
# "ridge" and "eaves" are roofing jargon and the AdV names hide the more
# dangerous distinction: Firsthoehe/Traufhoehe/AbsHoehe are ABSOLUTE ELEVATIONS,
# not heights, and this region spans 45-970 m of terrain, so confusing the two
# is not a rounding error. measHeight really is a height above ground - and it
# is measured to the RIDGE, which is the whole reason volume_old_m3 runs high.
ALKIS_RENAME = {
    "measHeight":  "height_top_m",       # ground -> highest point of the roof
    "Firsthoehe":  "elev_top_m",         # highest point, above sea level
    "Traufhoehe":  "elev_eaves_m",       # MEAN eaves height, above sea level
    "AbsHoehe":    "elev_ground_m",      # the ground, above sea level
    "DachFlaech":  "roof_area_m2",
    # NOT renamed and worth knowing: DachNeig is measured FROM THE VERTICAL, so
    # a flat roof reads 90.0 rather than 0. Renaming would not stop that
    # surprising someone, so it is documented instead.
    "DachNeig":    "roof_pitch_deg",
    "DachOri":     "roof_azimuth_deg",
    # TWO classifications, not code + label: roofType is the AdV 15-code list
    # (1000 Flachdach ... 5000 Mischform, 9999 Sonstiges), DachName is LGLN's
    # finer 24-name list. 5000 maps to four names, 3500 to two, 9999 to nine
    # (six of them with more than a handful of rows).
    "roofType":    "roof_code",
    "DachName":    "roof_shape",
    # DatenquelleDachhoehe, per the LGLN Produkt- und Formatbeschreibung LoD2:
    # 1000 LASERSCAN, 2000 STOCKWERK, 3000 STANDARD, 4000/5000 PHOTOGRAMMETRIE,
    # 6000 MANUELL. 6000 is the MANUALLY POST-PROCESSED subset: per LGLN's 2019
    # 3D-Kundentag slides ~1 % landmarks plus ~5 % "ortspraegende Gebaeude und
    # grobe Fehler" statewide (5.8 % of the buildings here) - i.e. the
    # better-checked roofs, not "estimated" ones as an earlier comment said.
    # Measured per building: 88 % of fire stations, 85 % of recreation
    # buildings and 86 % of chapels have a manually processed part, against
    # 3.8 % of residential buildings (per PART: 44 / 43 / 40 % vs 1.9 %).
    "DqDach":      "roof_source",
    "creationDa":  "created_on",
    "GrundrissA":  "plan_acquired_on",
    "Name":        "name",
    "AGS":         "ags",
    "Stadt":       "city",
    "Strasse":     "street",
    "HausNr":      "house_number",
}

# Final column order: identity, then the measures, then the source attributes.
# ──────────────────────────────────────────────
# STEP 03 — sliver parts
# ──────────────────────────────────────────────
# 54,093 parts (3.90 %) have a footprint under 1 m2. They are CORRECTLY
# classified ground surfaces - flat, and sitting at AbsHoehe - they are simply
# not structures. Measured shape: bounding rectangle median 1.48 m x 0.25 m,
# aspect ratio 4.81, and 31 % are thinner than 1:10. That is a wall-thickness
# leftover, the gap where two adjoining outlines fail to meet, or a small jog in
# a facade that was given its own part. The 22 % that are compact (~0.5 x 0.5 m,
# 3.5 m tall) look like chimneys, vents and stair heads modelled separately.
#
# Dropping them is close to free and removes half of all bracket defects:
#     rows removed          53,236    3.84 % of parts (857 of the 54,093 kept
#                                     as the only part of their building)
#     volume lost          118,103 m3 0.0174 % of the region
#     bracket defects gone  33,722 of 66,563
# 98.4 % are one part of a multi-part building, holding a median 0.28 % of their
# building's footprint, so the parent keeps essentially everything.
ALKIS_MIN_PART_AREA_M2 = 1.0

# 853 of the slivers ARE the whole building - their alkis_id has no other part.
# Dropping those would delete 857 ALKIS objects from the region. With this on,
# a building whose every part is below the threshold keeps its largest one, so
# the filter removes geometry noise without ever removing a building.
ALKIS_KEEP_LARGEST_PART_PER_BUILDING = True

ALKIS_OUTPUT_COLS = [
    "gml_id", "alkis_id",
    "area_m2", "volume_3d_m3", "volume_old_m3", "volume_ratio",
    "height_top_m", "height_eaves_m",
    "elev_ground_m", "elev_eaves_m", "elev_top_m",
    "function",
    "roof_shape", "roof_code", "roof_is_fallback", "roof_area_m2", "roof_pitch_deg",
    "roof_azimuth_deg",
    "name", "ags", "city", "street", "house_number",
    "n_surfaces", "n_roof_faces", "n_roof_clipped", "roof_source",
    "created_on", "plan_acquired_on",
    "geometry",
]

# --- Step 03 volume: roof faces are clipped to their part's footprint ---------
# LGLN attaches a hip-type roof face to ONE part of a multi-part building while
# the face spans the whole roof. Summing prisms per part then counts the volume
# under that face over the NEIGHBOURING parts too - twice for the building. It
# showed as `volume_3d_m3 > area x ridge height`, which no roof can produce, on
# 17,469 parts of the unclipped run, almost all HipAndGableRoof and HipRoof in
# multi-part buildings.
# Measured on this region by recomputing the unclipped volume of every part the
# clip touched: 19,020 parts (1.4 %) in 16,704 buildings carried spilling faces,
# their volume was overstated by 53 %, and the clip removed 4.47 M m3 = 0.66 %
# of the region. Per building, relative to the corrected volume, the error was
# a median 13 % (90th percentile 22 %): 11,151 buildings above +10 %, 2,701
# above +20 %, 57 above +50 %, 12 more than doubled. Those buildings hold 6.1 %
# of the region's volume, so the error moved demand between houses rather than
# changing the regional total.
#
# Clipping every face's projection to its own ground polygon removes it. Checked
# against a 0.25 m grid integral over the dissolved footprint of 1,984 sample
# buildings: the clipped sum is within 0.05 % overall, no multi-part building
# differs by more than 5 %, and the only four buildings above 5 % (max 6 %) are
# single-part flat roofs under 10 m2 where the grid itself is coarse.
#
# WHEN a face counts as spilling. LoD2 coordinates sit on a 1 mm grid, so a face
# that shares an edge with the footprint can stick out by a millimetre-wide
# sliver - 0.01-0.02 m2 along a 10-20 m edge. An area tolerance of 1e-3 m2
# treated those as spills and flagged 2.8x too many parts (236 of the sample's
# parts instead of the 85 with a real spill). The test is therefore on WIDTH:
# the spill is shaved by half this value on every side and only what survives
# is a spill. Millimetre slivers vanish; a real spill is at least 15 cm wide
# here (1st percentile 0.57 m). On the sample this recovers exactly the 85 real
# parts and none of the others. The integral is the same for a planar face
# either way, so this only decides what `n_roof_clipped` reports.
ALKIS_ROOF_SPILL_MIN_WIDTH_M = 0.02

# A flat roof carrying the AdV code 9999 ("Sonstiges") is LGLN's LoD1 fallback:
# "LoD2-Gebaeude, die automatisiert aus einem LoD1-Objekt mit einem Flachdach
# modelliert werden, haben als Attribut fuer die Dachform die Kennung 9999"
# (AdV Datenformatbeschreibung LoD2-DE). The roof recognition failed and the
# building is a flat box at laser height, so its volume carries the same
# overstatement volume_old_m3 has. 54,060 parts here (4.1 %). LGLN puts the
# automatic recognition at ~70 % correct overall.
ALKIS_ROOF_FALLBACK = {"roof_code": 9999, "roof_shape": "PolyFlatRoof"}

# --- Step 03 second output: aggregated to real ALKIS buildings ----------------
# The part-level layer above is the lossless one. This is the same data collapsed
# to one row per ALKIS object (869,316 of them), because "a building" is what a
# person means and what the POI join in step 04 mostly wants to reason about.
#
# Both are kept. Going part -> building is a groupby; going back is impossible,
# which is why the part layer stays authoritative.
#
# How the collapse is done, and where it loses information:
#   summed      volume_3d_m3, volume_old_m3, roof_area_m2, n_surfaces,
#               n_roof_faces, n_roof_clipped - additive quantities, safe
#   dissolved   geometry, and area_m2 recomputed FROM the dissolved shape rather
#               than summed, so overlapping parts are not double counted
#   largest     function, roof_shape, roof_code, address - taken from the part
#               with the biggest ground area. Arbitrary when parts disagree,
#               hence n_functions and functions_all below
#   extremes    height_top_max_m, height_eaves_max_m, elev_ground_min_m,
#               elev_top_max_m        - the building envelope
#   any         roof_manual_any   - some part was manually post-processed (6000)
#               roof_fallback_any - some part is a LoD1 flat-box fallback; its
#                                   volume is a box, treat like volume_old_m3
#
# `n_functions` and `functions_all` exist so a mixed-use building is visible as
# such instead of silently becoming whatever its largest part happens to be -
# which matters directly for classification in step 04.
ALKIS_BY_BUILDING_FILE = OUTPUT_DIR / "03_alkis_by_building.gpkg"

ALKIS_BUILDING_COLS = [
    "alkis_id",
    "area_m2", "volume_3d_m3", "volume_old_m3", "volume_ratio",
    "n_parts", "n_uuid", "is_multipart",
    "function", "n_functions", "functions_all",
    "roof_shape", "roof_code", "roof_area_m2",
    "height_top_max_m", "height_top_avg_m", "height_eaves_max_m",
    "elev_ground_min_m", "elev_top_max_m",
    "name", "ags", "city", "street", "house_number",
    "n_surfaces", "n_roof_faces", "n_roof_clipped",
    "roof_manual_any", "roof_fallback_any",
    "created_on", "plan_acquired_on",
    "geometry",
]

# `functions_all` is expected to be entirely NULL in this region and that is not
# a fault: `function` is an attribute of the ALKIS OBJECT, so every LoD2 part of
# a building inherits the same value and the parts can never disagree (measured:
# 0 of 869,316). AdV also exports only the FIRST of several Bauwerksfunktionen
# (Datenformatbeschreibung LoD2-DE, `function`), so a second function is lost
# at the source, not here. The column is kept as a cross-region guard - somewhere with
# per-part functions would fill it - so it is exempted from the empty-column
# check rather than dropped.
ALKIS_ALLOW_EMPTY_COLS = ["functions_all"]

# ──────────────────────────────────────────────
# STEP 04 — semantic enrichment
# ──────────────────────────────────────────────
# Reads 03_alkis_by_building.gpkg (one row per ALKIS object) and attaches what
# each building is FOR: the AdV function labels, the MiD activity map, and the
# OSM POI layer from step 01. Step 03 was structural; this step is semantic.

# --- Step 04.1: slim the layer down to what enrichment and classification need
# 31 attribute columns in, 18 out (plus geometry). `function` is the parameter everything downstream turns
# on, so it and the identity/measure columns stay; step-03 provenance and source
# metadata go.
#
# `ags` is kept as the administrative KEY and `city` only as its label: measured
# 145 distinct ags against 144 distinct city, because `Helmstedt, Stadt` carries
# two AGS keys (03154010, 03154028). Grouping by name would silently merge them.
#
# Dropped and why:
#   street, house_number   folded into a single `address`
#   n_functions,           always 1 and always NULL respectively - `function` is
#   functions_all          an attribute of the ALKIS object, so a building's
#                          parts can never disagree (0 of 869,316)
#   n_uuid                 id-minting provenance, nothing reads it
#   roof_code              the coarser AdV 15-code class; roof_shape is LGLN's
#                          finer 24-name class and is the one kept
#   roof_area_m2           a step-03 QA column
#   elev_ground_min_m,     sea-level elevations. Heights above ground are what
#   elev_top_max_m         capacity depends on; the elevations were only ever
#                          intermediates. NOTE this drops the only topography
#                          signal in the layer - restore elev_ground_min_m if a
#                          later step wants terrain.
#   n_surfaces,            step-03 provenance: how many LoD2 surfaces and roof
#   n_roof_faces,          faces became this row, and how many faces had to be
#   n_roof_clipped         clipped to their footprint
#   created_on,            source metadata dates, constant within a building
#   plan_acquired_on
ALKIS_SLIM_COLS = [
    "alkis_id",
    "function",
    "name", "address", "city", "ags",
    "area_m2",
    "volume_3d_m3", "volume_old_m3", "volume_ratio",
    "height_top_max_m", "height_top_avg_m", "height_eaves_max_m",
    "roof_shape", "roof_manual_any", "roof_fallback_any",
    "n_parts", "is_multipart",
    "geometry",
]

# `address` is built as "<street> <house_number>", falling back to the street
# alone when the number is missing and to NULL when neither exists. Expect it
# empty on about two thirds of the layer: street and house_number are filled on
# 34.9 % of buildings (49 % of parts, 54 % of raw surfaces - addresses sit on
# multi-part buildings), so anything downstream that wants address matching
# reaches only a third of the stock.
ALKIS_ADDRESS_PARTS = ("street", "house_number")

# --- Step 04.2: the two reference tables --------------------------------------
# Both key on the `function` value in its full `31001_1000` form, so both are
# plain left joins with no string surgery. Measured coverage of the 88 codes
# occurring in this region: 88/88 in both. Nothing falls out of either join.
#
# The codelist says what a code MEANS; the activity map says what HAPPENS there,
# and the activity map is the one the redistribution ultimately weights.
BUILDING_FUNCTION_CODELIST_FILE = REFERENCE_DIR / "building_function_codelist_de_en.csv"

# Converted once from alkis_building_activity_map.xlsx, which is kept beside it.
# CSV rather than xlsx so the pipeline needs no `openpyxl`, and so the table is
# greppable and diffable - it is 280 rows of static reference data that wants
# reviewing by eye, not a spreadsheet to be recomputed.
ALKIS_ACTIVITY_MAP_FILE = REFERENCE_DIR / "alkis_building_activity_map.csv"

# The 14 atomic activities the map uses, split on ";". `unspecified` and `other`
# are real values in the source, not placeholders, and one row has no activities
# at all - so a building can legitimately end up with nothing useful.
ALKIS_ACTIVITY_SEP = ";"

# Outputs of 04.2. The review CSV is the decision table for "is this building
# type worth keeping?": one row per function code with its labels, activities,
# building count, volume share and physical profile. The inspection layer is the
# same information on the geometry, for looking at in QGIS.
FUNCTION_REVIEW_CSV = OUTPUT_DIR / "04_function_activity_review.csv"
LABELLED_INSPECT_FILE = EXPERIMENTAL_DIR / "04_buildings_labelled.gpkg"

# --- Step 04.3: drop the places that are only somewhere to live --------------
# A building whose activity set is a SUBSET of this describes a home and nothing
# else, so it hosts none of the demand a capacity model places. Expressed as a
# rule over `activities` rather than as a hand-kept code list, so a building that
# also hosts trade, work or errands is retained automatically - the flat with a
# shop on the ground floor stays, which is the case that matters.
ALKIS_HOME_ONLY_ACTIVITIES = frozenset({"home", "meetup"})

# The rule's expected result on this region, asserted against the data. If the
# computed set differs, the activity map or the source release has changed and
# the reasoning below needs revisiting rather than the list being edited.
ALKIS_EXPECTED_HOME_ONLY = {
    "31001_1000": "residential buildings (home;meetup) - 327,264 buildings, 299.9M m3",
    "31001_1210": "agricultural and forestry residential (home) - 4,197 buildings, 6.2M m3",
}

# THE COST, decided deliberately: `meetup` IS a redistribution target - the
# original pipeline maps MiD `meetup` -> Leisure - and dropping 31001_1000
# removes 299.9M m3 of it. So visiting-friends trips have nowhere to land and
# Leisure demand falls entirely on pubs, sports halls and cinemas. Accepted:
# home visits are out of scope for a capacity model. Revisit here if the Leisure
# totals later look too concentrated on venues.
