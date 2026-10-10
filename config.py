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
# Geofabrik snapshot, https://download.geofabrik.de/europe/germany/niedersachsen.html
# (daily latest, monthly archive). This is the only raw input that moves: between
# 260113 and 260910 the region gained 4 % POI-tagged objects and 1.4 % footprints.
# ALKIS Landnutzung is cut once a year (260101 is current) and the LoD2 tiles
# date from mid-2024 with no fixed update cycle. Refresh: download the dated
# file, change the name here, rerun steps 01 and 04.
OSM_PBF_FILE        = INPUT_DIR / "niedersachsen-260910.osm.pbf"  # data up to 2026-09-10T20:21Z

# Outputs
CLIPPED_PBF_FILE       = OUTPUT_DIR / "01_study_area_clipped.pbf"
ALL_POIS_FILE          = OUTPUT_DIR / "01_all_pois.gpkg"
LANDUSE_OSM_FILE       = OUTPUT_DIR / "01_landuse_osm.gpkg"     # every OSM landuse=* polygon, for the land-use check in step 04
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
# --- ALKIS Landnutzung (land use), open data ----------------------------------------
# The statewide ALKIS land-use layer from LGLN's STAC catalogue
# (https://alkis.stac.lgln.niedersachsen.de/collections/alkis-landnutzung), cut
# 2026-01-01, CC-BY-4.0, 3.4 GB. Seamless: 22 layers (ln_wohnnutzung,
# ln_landwirtschaft, ln_gewerblichedienstleistungen, ...), every parcel in
# exactly one, 468,146 polygons over the region. Step 04 clips it to the region
# on the fly (~15 s) and writes the class under every building's centre as
# `alkis_landuse`. Replaces the five themed 2023 extracts used before, which had
# no agricultural class and put farm halls under residential.
#
# ALKIS records the DOMINANT use of a parcel, so a shop with flats above stands
# on wohnnutzung. That is why the land only decides for buildings nothing else
# describes - anything with a POI, a site or a named/use-tagged OSM twin has
# been kept by stronger evidence already. OSM landuse (01_landuse_osm.gpkg) is
# carried as `osm_landuse` for information only: it draws one residential
# polygon around a whole village and covers 488 of the 564 halls that ALKIS
# puts on commercial land. Where they disagree, ALKIS looked at the parcel.
ALKIS_LANDUSE_FILE = INPUT_DIR / "FS_LN_03_NI_260101.gpkg"

# The 22 layers of that file, by their German layer name, and the English label
# that step 04 writes into `alkis_landuse`. Only English reaches the layer and
# the LLM, as with the building classes. A layer missing here stops the run -
# a new release with a new layer must be looked at, not silently carried as a
# German name.
ALKIS_LANDUSE_LABELS_EN = {
    "ln_wohnnutzung":                      "residential",
    "ln_landwirtschaft":                   "agriculture",
    "ln_forstwirtschaft":                  "forestry",
    "ln_aquakulturundfischereiwirtschaft": "aquaculture and fisheries",
    "ln_industrieundverarbeitendesgewerbe": "industry and manufacturing",
    "ln_gewerblichedienstleistungen":      "commercial services",
    "ln_lagerung":                         "storage",
    "ln_abbau":                            "mining and extraction",
    "ln_oeffentlicheeinrichtungen":        "public facilities",
    "ln_kulturundunterhaltung":            "culture and entertainment",
    "ln_bestattung":                       "cemetery",
    "ln_versorgungundentsorgung":          "utilities and waste",
    "ln_wasserwirtschaft":                 "water management",
    "ln_schutzanlage":                     "protective structure",
    "ln_sportanlage":                      "sports facility",
    "ln_freizeitanlage":                   "leisure facility",
    "ln_freiluftundnaherholung":           "open-air recreation",
    "ln_strassenundwegeverkehr":           "road traffic",
    "ln_bahnverkehr":                      "rail traffic",
    "ln_schiffsverkehr":                   "shipping",
    "ln_flugverkehr":                      "air traffic",
    "ln_ohnenutzung":                      "unused",
}

# The land-use rule (decided 2026-09-11) for a building whose ALKIS class can
# carry noise in numbers and that nothing else describes. Two kinds of class:
#   generic non-residential  the code says only "some business / public use /
#                            recreation happens here" and names no use:
#                            2000, 2100, 2010, 3000, 3200
#   residential-first mixed  a dwelling with some trade in it: 1110, 1120, 1130.
#                            On a residential parcel with nothing in OSM
#                            confirming the trade, that is a house.
# Codes that name a specific use (3072 fire station, 3021 school, 3041 church)
# and the business-first mixed codes with housing (2310, 2320, 3100) are NOT in
# the rule: there the code itself is the information, and together they held
# 127 such buildings across 20 classes. "Nothing describes" means: no
# POI, no site, no OSM twin name, no ALKIS name (since 2026-09-14), and the twin
# footprint (if any) is mute - a
# bare 'yes', a residential or farm tag from OSM_DROP_UNLESS_POI (house,
# apartments, barn, stable, ...) or a structure tag from OSM_TWIN_STRUCTURE_TAGS.
# For class 2000 the rule starts at ALKIS_SIZE_FLOOR_EVIDENCE_M2, below which the
# floor and the evidence band already decide; the other classes have no floor,
# so the rule applies at every size. Then the ALKIS land-use parcel under the centre
# decides:
#   ALKIS_LANDUSE_DROP   the land says living or farming: the building goes
#   everything else      commercial services, industry, public, storage,
#                        utilities, transport, recreation, or unknown: it stays
#                        as a generic workplace
# Measured first pass (bare/no twin, class 2000 only) on 7,156 halls: 3,050 on
# wohnnutzung (median 268 m2, 9 m tall - houses coded business), 2,728 on
# landwirtschaft (barns and machinery halls), 1,183 on business land. Second
# pass (mute twins, class 2100 added) measured on 20,842 buildings: 7,409 go -
# 7,119 class-2000 halls (house, barn and garages twins now included) and 470
# class-2100 workshops (median 89 m2, 5 m tall, 350 on wohnnutzung); 13,253
# stay on business land. Third pass, the six further codes: 2,198 kept buildings
# still showed the pattern, 84 % of them in two classes - 1,238 of 5,788 class
# 1120 (median 152 m2, 10.6 m: two-storey houses) and 606 of 8,542 class 2010
# (median 68 m2) - the rest 89 class 1130, 89 class 3000, 28 class 3200,
# 21 class 1110. With all eight: 36,827 undescribed buildings, 9,554 go
# (20.2M m3), 26,964 stay on business, public or infrastructure land; the
# layer ends at 48,966 buildings.
ALKIS_LANDUSE_RULE_CLASSES = frozenset({
    "31001_2000", "31001_2100", "31001_2010", "31001_3000", "31001_3200",   # generic non-residential
    "31001_1110", "31001_1120", "31001_1130",                               # residential-first mixed
})
ALKIS_LANDUSE_DROP = frozenset({"residential", "agriculture"})   # English labels from ALKIS_LANDUSE_LABELS_EN

# The parcel's CODED kind, one level below the layer, decoded to English as
# `alkis_landuse_detail` (added 2026-09-14: "more information is better than
# skipping information"). Public-facility parcels carry `funktion` (1110
# government and administration, 1120 education and science, 1140 religious,
# 1150 health, 1160 social services, 1170 public safety), utility, industry
# and recreation parcels carry `art`. The labels come from the AdV codelists
# in the GDI-DE registry (https://registry.gdi-de.org/codelist/de.adv-online.gid/
# AX_Funktion_FlaecheBesondererFunktionalerPraegung, AX_Funktion_IndustrieUnd-
# Gewerbeflaeche, AX_Funktion_SportFreizeitUndErholungsflaeche), fetched
# 2026-09-14 and matched against the codes actually present in the region.
# Layers whose codes do NOT match a registry list are left undecoded on
# purpose - transport (51xx/52xx), culture (1210/1220), storage (8xxx),
# extraction, forest and water - a wrong label being worse than none. A code
# present in the data but missing here is reported by step 04, not invented:
# 2026-09-14 that was 4370 (125 leisure parcels) and 1550/1600 (205
# commercial-services parcels), which no current registry list carries.
# Layer -> (attribute, {code: English label}).
ALKIS_LANDUSE_DETAIL_EN = {
    "ln_oeffentlicheeinrichtungen": ("funktion", {
    "1100": "public purposes", "1110": "government and administration", "1120": "education and science",
    "1130": "culture", "1140": "religious institution", "1150": "health and spa", "1160": "social services",
    "1170": "public safety and order", "1180": "media and communication", "1200": "parking",
    "1300": "historic site", "1310": "castle or fortress", "1320": "palace grounds",
    }),
    "ln_versorgungundentsorgung": ("art", {
    "2500": "utility plant", "2501": "utility plant", "2502": "utility plant", "2520": "waterworks",
    "2521": "waterworks", "2522": "waterworks", "2530": "power plant", "2531": "power plant",
    "2532": "power plant", "2540": "transformer station", "2550": "refinery", "2551": "refinery",
    "2552": "refinery", "2560": "gasworks", "2561": "gasworks", "2562": "gasworks", "2570": "heating plant",
    "2571": "heating plant", "2572": "heating plant", "2580": "radio and telecommunications facility",
    "2581": "radio and telecommunications facility", "2582": "radio and telecommunications facility",
    "2600": "waste disposal", "2601": "waste disposal", "2602": "waste disposal",
    "2610": "sewage treatment plant", "2611": "sewage treatment plant", "2612": "sewage treatment plant",
    "2620": "waste treatment plant", "2621": "waste treatment plant", "2622": "waste treatment plant",
    "2623": "waste treatment plant", "2630": "landfill", "2640": "underground landfill",
    "2700": "extraction facility", "2701": "extraction facility",
    }),
    "ln_industrieundverarbeitendesgewerbe": ("art", {
    "1400": "trade and services", "1410": "professional services", "1420": "banking", "1430": "insurance",
    "1440": "trade", "1450": "exhibition and fairs", "1460": "accommodation", "1470": "restaurants",
    "1480": "entertainment", "1490": "horticulture", "1510": "crafts", "1520": "petrol station",
    "1530": "logistics and transport", "1540": "research and development", "1700": "industry and commerce",
    "1701": "industry and commerce", "1710": "production", "1740": "storage area", "1770": "raw materials",
    "1780": "company social facility", "1790": "shipyard", "1801": "food and feed production",
    "1802": "textiles and clothing", "1803": "wood and packaging products",
    "1804": "print, audio and video products", "1805": "mineral oil processing and coking",
    "1806": "chemicals, pharma and plastics", "1807": "mineral building materials",
    "1808": "metal production and processing", "1809": "technology, electrics and electronics",
    "1810": "mechanical engineering", "1811": "vehicle construction", "1812": "furniture and consumer goods",
    }),
    "ln_gewerblichedienstleistungen": ("art", {
    "1400": "trade and services", "1410": "professional services", "1420": "banking", "1430": "insurance",
    "1440": "trade", "1450": "exhibition and fairs", "1460": "accommodation", "1470": "restaurants",
    "1480": "entertainment", "1490": "horticulture", "1510": "crafts", "1520": "petrol station",
    "1530": "logistics and transport", "1540": "research and development", "1700": "industry and commerce",
    "1701": "industry and commerce", "1710": "production", "1740": "storage area", "1770": "raw materials",
    "1780": "company social facility", "1790": "shipyard", "1801": "food and feed production",
    "1802": "textiles and clothing", "1803": "wood and packaging products",
    "1804": "print, audio and video products", "1805": "mineral oil processing and coking",
    "1806": "chemicals, pharma and plastics", "1807": "mineral building materials",
    "1808": "metal production and processing", "1809": "technology, electrics and electronics",
    "1810": "mechanical engineering", "1811": "vehicle construction", "1812": "furniture and consumer goods",
    }),
    "ln_freizeitanlage": ("art", {
    "4100": "sports facility", "4101": "sports facility", "4110": "golf", "4120": "sports ground",
    "4130": "racetrack", "4140": "equestrian sports", "4150": "shooting range", "4160": "ice or roller rink",
    "4170": "tennis", "4200": "leisure facility", "4210": "zoo", "4211": "zoo", "4220": "wildlife park",
    "4230": "amusement park", "4235": "climbing facility", "4240": "open-air stage",
    "4250": "open-air museum", "4260": "drive-in cinema", "4270": "driving practice or test ground",
    "4275": "go-kart track", "4280": "dog training ground", "4290": "model aircraft field",
    "4295": "air sports field", "4300": "recreation area", "4301": "recreation area",
    "4310": "weekend and holiday home area", "4320": "swimming", "4321": "swimming", "4330": "campsite",
    "4331": "campsite", "4400": "green space", "4410": "settlement green space", "4420": "park",
    "4430": "botanical garden", "4431": "botanical garden", "4440": "allotment gardens",
    "4450": "weekend site", "4460": "garden", "4470": "playground or kick-about field",
    }),
    "ln_freiluftundnaherholung": ("art", {
    "4100": "sports facility", "4101": "sports facility", "4110": "golf", "4120": "sports ground",
    "4130": "racetrack", "4140": "equestrian sports", "4150": "shooting range", "4160": "ice or roller rink",
    "4170": "tennis", "4200": "leisure facility", "4210": "zoo", "4211": "zoo", "4220": "wildlife park",
    "4230": "amusement park", "4235": "climbing facility", "4240": "open-air stage",
    "4250": "open-air museum", "4260": "drive-in cinema", "4270": "driving practice or test ground",
    "4275": "go-kart track", "4280": "dog training ground", "4290": "model aircraft field",
    "4295": "air sports field", "4300": "recreation area", "4301": "recreation area",
    "4310": "weekend and holiday home area", "4320": "swimming", "4321": "swimming", "4330": "campsite",
    "4331": "campsite", "4400": "green space", "4410": "settlement green space", "4420": "park",
    "4430": "botanical garden", "4431": "botanical garden", "4440": "allotment gardens",
    "4450": "weekend site", "4460": "garden", "4470": "playground or kick-about field",
    }),
}

# ──────────────────────────────────────────────
# STEP 01 — what is a POI candidate, and what is not
# ──────────────────────────────────────────────
# The extractor needs a POSITIVE list of keys - "everything except outdoor
# things" is not expressible, because "everything" is the whole map. So the
# principle "drop only what is clearly not a visitable interior" is applied in
# two places: the keys below decide what enters the candidate set, and the
# block-lists further down decide what leaves it. Audited 2026-09-11 against
# every NAMED point or polygon in the region: 93,942 named features, 28,864 of
# them (points/polygons) carrying none of the original 20 keys. Of those the
# activity places were named buildings with a use tag (about 1,300), man_made
# plants (189), industrial/commercial/retail land-use areas (402 named, many
# more unnamed), stations (51) and power plants (37) - all added below. The
# rest were bus stops (9,165), hydrants, field and place names, boundaries,
# street names: POI_NOT_EXTRACTED records them so the decision is visible.
#
# Mappers use three schemes for the same business, and all three are read:
#   1. a use tag (amenity/shop/office/...) on a node or on the building  -> POI_EXTRACT_FILTER
#   2. a NAMED building with only building=<use>  (the Goslar scheme)     -> POI_EXTRACT_BY_VALUE + POI_BUILDING_ACTIVITY_TAGS
#   3. an area drawn around the site (landuse=industrial, amenity=school) -> POI_EXTRACT_BY_VALUE, becomes a `site`
# and whatever is named but fits none of them still reaches the ALKIS building
# as `osm_twin_name` in step 04, as information for the LLM.
# Lines (LineString, MultiLineString) are dropped at extraction, no exceptions.

# Pass 1: keys that make a feature a candidate with ANY value.
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

# Pass 2: keys that make a feature a candidate only with these VALUES. Added
# 2026-09-11 after the audit. `building` is further restricted to NAMED
# features by POI_BUILDING_ACTIVITY_TAGS below; the others count named or not -
# an unnamed industrial estate still tells every building inside it where it
# stands, and an unnamed sewage works is still a workplace.
POI_EXTRACT_BY_VALUE = {
    "building": [
        "industrial", "commercial", "warehouse", "retail", "office", "manufacture",
        "supermarket", "kiosk", "hotel", "school", "kindergarten", "university",
        "college", "hospital", "fire_station", "government", "public", "civic",
        "hall", "sports_centre", "sports_hall", "church", "community_centre",
        "museum", "restaurant",
    ],
    "man_made": ["works", "wastewater_plant", "water_works"],   # plants and plant units: 189
    "landuse": ["industrial", "commercial", "retail"],          # business parks, depots, estates - as sites
    "railway": ["station", "halt"],                              # 51 station points, snap to the station building
    "power": ["plant"],                                           # 37 power stations
    "aeroway": ["terminal"],                                      # airport terminals
}

# A feature whose ONLY accepted key is `building` counts only when it is NAMED
# and the value is one of these (the same list as above). An unnamed
# building=industrial is just a hall - its use reaches the ALKIS building through
# `osm_twin_tag` in step 04 anyway - and a named building=yes mixes data centres
# with hunting huts (1,970 in the region), so it is information, not a POI.
POI_BUILDING_ACTIVITY_TAGS = frozenset(POI_EXTRACT_BY_VALUE["building"])

# Keys deliberately NOT extracted, with the reason and the region's count of
# named point/polygon features carrying only them. Recorded so the choice can
# be validated and revisited; the notebook asserts none of them is in a filter.
POI_NOT_EXTRACTED = {
    "public_transport": "bus and tram stops, platforms, stop positions - 9,165 named",
    "emergency":        "hydrants, assembly points - 2,025 named",
    "natural":          "landscape - 1,845 named",
    "waterway":         "rivers, streams",
    "place":            "settlement and locality names - 1,352 named",
    "highway":          "street names, crossings, bus bays - 1,128 named",
    "boundary":         "administrative areas - 789 named",
    "barrier":          "gates, bollards, fences - 151 named",
    "playground":       "equipment on playgrounds",
    "advertising":      "billboards",
    "telecom":          "street cabinets, exchanges",
    "pipeline":         "infrastructure",
    # keys that ARE extracted, but only with the values in POI_EXTRACT_BY_VALUE:
    #   building  yes 1,970 / house 121 / apartments 73 / service 62 / hut 37 named: homes, huts, cabins, or nothing said
    #   landuse   farmland 1,098 / forest / meadow / allotments / cemetery / residential / farmyard: no indoor activity;
    #             farmyard stays out so barns are not rescued by the yard around them
    #   man_made  monitoring_station 422 / adit / mineshaft / survey_point / bridge / tower / water_well: unstaffed
    #   power     substation 167 / generator 83 (wind turbines) / pole: unstaffed
    #   railway   tram_stop / stop / platform / signal_box / switch: outdoor
    #   aeroway   runway / taxiway / hangar: not destinations
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
    "historic", "leisure",
    "man_made", "landuse", "railway", "power", "aeroway",   # pass-2 keys, 2026-09-11
    "building",
]

# ─────────────────────────────
# STEP 01 — POI nesting
# ─────────────────────────────
# 3,144 POIs (13.6 %) sit inside another POI's polygon: a mall and its 128 shop
# units, a campus and its institutes. Downstream a building's volume is split
# between its units by floor area rather than evenly, and a campus hands its
# label to every building inside it - see docs/nested-poi-area-split.md. Step 01
# therefore emits, per POI:
#   poi_parent_id    the smallest non-unit POI polygon containing the POI's
#                    representative point, other than itself (a shop in a mall on
#                    a campus points at the mall; the mall points at the campus),
#                    else null. 1,423 parents in this region.
#   poi_role='unit'  when that parent carries a building=* tag - it IS one
#                    building - and the child is a point or footprint. Children
#                    of an area parent (campus, outlet village, zoo, holiday
#                    park) keep their role; a site child stays a site. The tag
#                    decides, not the parent's poi_role: Schloss-Arkaden is a
#                    'site' by building count yet one building=retail.
#   split_area_m2    units only. Own area for polygons; the median area of the
#                    polygon siblings for points; the fallback below when no
#                    sibling has an area, which makes the split even. Only ever
#                    a SHARE within the parent - unit outlines span floors and
#                    sum to 154 % of the Schloss-Arkaden footprint.
#
# Indoor units are recognised by one of these tag KEYS with no building tag, and
# they can never be parents: room outlines on different floors overlap in plan,
# and without this a first-floor shop becomes the parent of the ground-floor
# shop below it (549 wrong parents when measured). It must be the KEY - the
# mall polygon itself carries surveillance=indoor as a value.
POI_UNIT_TAG_KEYS = ("indoor", "level", "level:ref")
# Points carry area_m2 = 0.0, not null, so the imputation tests geom_kind.
POI_SPLIT_AREA_FALLBACK_M2 = 1.0

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
#
# THE FILTER LADDER (section 7 of the notebook), in the order the reasons are
# assigned - a building gets the FIRST reason that applies, `drop_reason` on
# the labelled extract, NULL when kept. State on 2026-09-14 (OSM 260910):
# 869,316 ALKIS + 50,011 OSM gap-fill = 919,327 polygons in, 39,786 out.
#
#   list1                     ALKIS_DROP_ALWAYS / OSM_DROP_ALWAYS: canopies, masts,
#                             garages, sheds, roofs, towers ... no POI can save them
#   floor_structure           any class under SIZE_FLOOR_M2 whose OSM twin is in
#                             OSM_TWIN_STRUCTURE_TAGS: goes with list 1
#   list2_no_poi              ALKIS_DROP_UNLESS_POI / OSM_DROP_UNLESS_POI (residential,
#                             farm, bare 'yes' ...) with no POI or site on them
#   floor_no_evidence         any class under SIZE_FLOOR_M2 with no POI, site,
#                             activity tag, OSM name or ALKIS name
#   band_no_evidence          class 2000 between the floor and
#                             ALKIS_SIZE_FLOOR_EVIDENCE_M2 with none of those
#   land_residential_or_farm  ALKIS_LANDUSE_RULE_CLASSES with a mute twin, no POI,
#                             site or name, on ALKIS_LANDUSE_DROP land
#   twin_structure_no_poi     every OSM footprint on it in OSM_TWIN_STRUCTURE_TAGS,
#                             nothing on it - any class, any size
#
# What saves a building (`rescued_by`): poi (inside), snap (a building-bound
# POI within POI_SNAP_MAX_DISTANCE_M, see POI_BUILDING_BOUND_MIN_INSIDE_SHARE),
# site (inside a site polygon of POI_SITE_RESCUE_MIN_AREA_M2 or more), osm_tag
# (an OSM_TWIN_ACTIVITY_TAGS twin), osm_name (a named twin), alkis_name (the
# cadastre named it). Kept buildings
# then receive their POIs with shares (04.5) and are written to
# ENRICHED_BUILDINGS_FILE; OSM gap-fill rows carry an estimated volume
# (OSM_GAP_FLOOR_HEIGHT_M). The three QGIS extracts are LABELLED_INSPECT_FILE
# (everything, with the flags), KEPT_INSPECT_FILE and POI_ASSIGNMENTS_FILE.

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

# Output of 04.2: every building with its label and activities on the geometry,
# plus a `kept` flag, for class-by-class review in QGIS. The per-code summary
# table is only printed in the notebook, not written.
LABELLED_INSPECT_FILE = EXPERIMENTAL_DIR / "04_buildings_labelled.gpkg"
# Output of 04.4: the same layer filtered down to what survives the two drop
# lists - the file to open when the question is "what is left?".
KEPT_INSPECT_FILE = EXPERIMENTAL_DIR / "04_buildings_kept.gpkg"

# --- Step 04.3: fill the gaps in ALKIS with OSM footprints --------------------
# ALKIS/LoD2 is the authoritative building stock, but it is not complete: OSM
# has footprints where ALKIS has no record (new buildings since the LoD2
# release, sheds and huts the cadastre never took up, and 829 buildings that lie
# outside the LoD2 tile set entirely). Those footprints are appended to the
# layer from 01_all_buildings_osm.gpkg so the map and the redistribution see a
# building there rather than a hole.
#
# "No ALKIS record" is decided by FOOTPRINT COVERAGE, not by a touch test: the
# share of an OSM footprint's area that ALKIS buildings cover. A touch test
# would call an OSM building "present" because a neighbour's wall clips its
# corner. Measured on this region (509,792 OSM footprints against 869,316 ALKIS
# buildings) the coverage is sharply bimodal:
#
#     coverage      OSM footprints
#     exactly 0            43,531      no ALKIS building touches it
#     0    - 0.05           2,287
#     0.05 - 0.10           1,447      <- the valley floor
#     0.10 - 0.20           2,339
#     0.20 - 0.50          17,047      rising: offset digitising, one OSM
#     0.50 - 1.00         443,141      polygon over several ALKIS parts, ...
#
# The threshold sits on the valley floor. Below it, 47,264 footprints (9.27 %,
# 5.0 km2, median 33 m2) are treated as absent from ALKIS. Moving it to 0.05
# changes the answer by 1,447 buildings; to 0.20 by 2,339 - the choice is not
# sensitive. The 0.10-0.50 band is NOT filled: an OSM polygon 30 % covered by
# ALKIS almost always is the same building drawn differently, and filling it
# would put a second footprint on top of the first.
OSM_GAP_MAX_ALKIS_COVERAGE = 0.10

# `building=no` is OSM's way of saying "this area is explicitly not a building"
# (3 in this region). Everything else stays, including `construction` (100) and
# `roof` (444) - the layer's principle is not to lose a real feature, and a
# `roof` is the OSM counterpart of ALKIS's 94,571 canopies.
OSM_GAP_EXCLUDE_BUILDING_TAGS = frozenset({"no"})

# What the filled rows carry in `function` and `label_en`. A single synthetic
# class rather than one per OSM `building=*` value, so QGIS shows the whole fill
# as one legend entry that can be ticked on and off; the OSM tag itself is kept
# in `osm_building` for anyone who wants to split it further. It is not an AdV
# code, does not start with 31001/51xxx, and is absent from both reference
# tables on purpose - the joins run BEFORE the fill so nothing tries to look it
# up.
OSM_GAP_FUNCTION_CODE = "OSM"
OSM_GAP_LABEL_EN = "Building mapped in OSM, no ALKIS record"

# Height and volume of the filled rows (decided 2026-09-11). There is no LoD2
# model to measure, so the estimate of the previous pipeline is used, unchanged:
#   height = OSM `height` tag if present,
#            else `building:levels` x OSM_GAP_FLOOR_HEIGHT_M,
#            else OSM_GAP_DEFAULT_FLOORS x OSM_GAP_FLOOR_HEIGHT_M;
#   volume = footprint area x height, written to BOTH volume_3d_m3 and
#            volume_old_m3 (volume_ratio 1.0), height to height_top_max_m and
#            height_top_avg_m.
# So every polygon in the layer carries geometry, and the volume-weighted
# redistribution no longer gives these rows zero weight. `source == 'osm'`
# marks the estimate. Of the 1,609 filled rows kept on 2026-09-11, 217 had
# levels and 43 a height; the other 84 % get the default. For comparison the
# kept ALKIS buildings have a median roof height of 7.3 m and 6.1 m3 per m2 of
# footprint, so 2 m per floor is a deliberately conservative floor, not a
# typical building.
OSM_GAP_FLOOR_HEIGHT_M = 2.0   # previous pipeline: DEFAULT_FLOOR_HEIGHT_M
OSM_GAP_DEFAULT_FLOORS = 1     # previous pipeline: DEFAULT_FLOORS

# The filled rows take `ags` and `city` from the NEAREST ALKIS building rather
# than from OSM's `addr:city`, so the administrative key stays in ALKIS's own
# vocabulary ("Braunschweig, Stadt" / 03101000) and grouping by it keeps
# working. Measured: median distance 7 m, 99 % within 420 m; 97 of 47,264 have
# no ALKIS building within this cap and keep a NULL key.
OSM_GAP_AGS_MAX_DISTANCE_M = 1000

# The fill's expected size on this region, as a sanity band rather than an
# assertion. Outside it, the most likely causes are a CRS mismatch between the
# two layers (coverage collapses to 0 and EVERYTHING is a gap) or a re-run of
# step 01 on a different PBF.
OSM_GAP_EXPECTED_SHARE_PCT = (5.0, 15.0)

# What the filled rows do NOT have, and what that means downstream:
#   volume_3d_m3 and the heights are NULL. OSM has `building:levels` on 5.4 %
#   and `height` on 1.3 % of the gap rows (kept as `osm_levels`, `osm_height_m`),
#   nowhere near enough to estimate a volume for the rest. Until a later step
#   decides how to weight a building without a volume, these rows carry ZERO
#   weight in a volume-proportional redistribution - they are on the map, not
#   yet in the model.
#   activities is NULL and function is 'OSM', so the ALKIS lists in 04.4 never
#   touch them; they are judged by their OSM building=* tag instead
#   (OSM_DROP_ALWAYS / OSM_DROP_UNLESS_POI below). 3,088 are tagged `house` and 531 `apartments`; an OSM
#   `building=*` -> activity map is the obvious next reference table.

# --- Step 04.4: drop what is not a place of activity ---------------------------
# Two lists of ALKIS function codes, applied in this order. Decided class by
# class with the user on 2026-09-10/11 from the per-code profile: count, volume,
# physical shape, and how many step-01 POIs sit on each class.
#
#   1. ALKIS_DROP_ALWAYS      list 1 - dropped, no exceptions. The POLYGONS go;
#                             the POIs on them do not: they are placed on the
#                             actual building next door (POI_SNAP_MAX_DISTANCE_M)
#   2. ALKIS_DROP_UNLESS_POI  list 2 - dropped unless a POI or a site is on the
#                             building. Residential buildings are in here BY CODE.
#
# "A POI is on the building" = the POI's representative point falls within the
# footprint of an actual building (one list 1 does not remove), OR the POI is of
# a building-bound use and this is the nearest actual building within
# POI_SNAP_MAX_DISTANCE_M, OR the building is at least POI_SITE_RESCUE_MIN_AREA_M2
# and lies inside a site polygon. Presence only; the POI join itself is 04.5 and
# must use the same placement. OSM gap-fill rows (function 'OSM') are in neither
# list and pass through untouched.
#
# Both lists are keyed on the full '31001_2000' form. Every code listed must
# exist in the codelist - the notebook asserts it - because a typo here is
# otherwise a silent no-op, which is exactly the bug the optimized pipeline
# shipped with ("Buildings for supplying energy" matched no label and removed
# nothing). Counts in the reasons are this region's, for orientation; a listed
# code with 0 buildings elsewhere is fine. The activity map plays NO part in the
# drop; see ALKIS_HOME_ONLY_ACTIVITIES for its one remaining, advisory role.

# List 1. Structures with no usable inside, three technical shells, and the mills.
ALKIS_DROP_ALWAYS = {
    # -- roofs, containers, installations ----------------------------------------
    "51009_1610": "Ueberdachung, canopy - 94,571 forecourt roofs, carports, bus shelters; median 10 m2. 145 POIs sit under them (fuel stations, pharmacies, banks); the canopy goes, the POI moves to the building next to it",
    "51009_1750": "Denkmal, monument - 11",
    "51003_1201": "Silo - 1,784",
    "51003_1205": "Tank - 204",
    "51002_1250": "Mast - 1,772",
    "51002_1230": "Solarzellen, ground-mounted PV arrays - 1,177",
    "51002_1220": "Windrad, wind turbine - 423",
    "51002_1260": "Funkmast, radio mast - 178",
    "51002_1290": "Schornstein, chimney - 119",
    # -- towers, visited or not: structures, not buildings ------------------------
    "51001_1008": "Sende-/Funkturm, transmission tower - 88",
    "51001_1002": "Kirchturm, church tower - 54; the church itself is a separate 31001_3041 polygon",
    "51001_1005": "Kuehlturm, cooling tower - 52",
    "51001_1010": "Foerderturm, mine headframe - 8",
    "51001_1004": "Kontrollturm, control tower - 4",
    "51001_1007": "Feuerwachturm, fire lookout tower - 1",
    "51001_1001": "Wasserturm, water tower - 16; 5 historic markers",
    "51001_1003": "Aussichtsturm, observation tower - 20; viewpoints, decided as tourism structure 2026-09-11",
    "51001_1009": "Stadt-/Torturm, city gate tower - 6",
    "51001_1012": "Schloss-/Burgturm, castle tower - 5",
    # -- sport and heritage structures -------------------------------------------
    "51006_1431": "Zuschauertribuene ueberdacht, covered stand - 23; the sports site carries the activity",
    "51006_1432": "Zuschauertribuene nicht ueberdacht, open stand - 10",
    "51006_1440": "Stadion - 13; these are the pitch polygons, median 12,600 m2 and 0.4 m tall",
    "51006_1470": "Sprungschanze, ski jump inrun - 4",
    "51007_1400": "Befestigung (Burgruine), castle ruins - 17",
    "31001_2211": "Windmuehle, windmill - 12; moved from list 2 on 2026-09-11: the 1 survivor was kept by an attraction POI only",
    "31001_2212": "Wassermuehle, water mill - 5; moved from list 2 on 2026-09-11 with the windmills",
    # -- technical shells coded as buildings ---------------------------------------
    "31001_2513": "Wasserbehaelter, water container - 82",
    "31001_2213": "Schoepfwerk, drainage pumping station - 30",
    "31001_3281": "Schutzhuette, hiking shelter - 77; median 25 m2, the one 'restaurant' POI inside is misplaced",
}

# List 2. Real buildings that are mostly not destinations, but sometimes are -
# and OSM knows which. Dropped unless a POI or a site is on them.
ALKIS_DROP_UNLESS_POI = {
    # -- residential: the case that matters --------------------------------------
    "31001_1000": "Wohngebaeude, residential buildings - 327,264, 44 % of the region's volume. ALKIS codes a block by its dominant use, so the corner restaurant, the hairdresser, the doctor's practice, the care home and the student hall are coded residential too; ~4,600 of them carry a POI or sit in a site and stay",
    "31001_1210": "Land-/forstwirtschaftliches Wohngebaeude, farm and forestry residential - 4,197; manors, riding centres and farm cafes among them",
    "31001_1223": "Forsthaus, forester's house - 37; a home with an office attached",
    # -- agriculture -------------------------------------------------------------
    "31001_2720": "Land- und forstwirtschaftliches Betriebsgebaeude, farm buildings - 18,850; 95 hold a riding stable, a farm shop or a cafe, the rest are barns and stables",
    "31001_2740": "Treibhaus/Gewaechshaus, greenhouse - 602; garden centres and florists among them",
    # -- parking -------------------------------------------------------------------
    "31001_2461": "Parkhaus, parking garage - 65; an Aldi, a KiK, a bakery and two gyms occupy the ground floor of a few",
    "31001_2462": "Parkdeck, parking deck - 80",
    # -- utilities -----------------------------------------------------------------
    "31001_2500": "Gebaeude zur Versorgung, supply - 7,806; median 14 m2 transformer boxes, but Stadtwerke offices, a Telekom site and a water museum among the large ones",
    "31001_2600": "Gebaeude zur Entsorgung, disposal - 770; recycling yards have staff",
    # -- transport operations ------------------------------------------------------
    "31001_2410": "Betriebsgebaeude fuer Strassenverkehr, road - 363; depots",
    "31001_2420": "Betriebsgebaeude fuer Schienenverkehr, rail - 100; station kiosks, cafes, newsagents",
    "31001_2430": "Betriebsgebaeude fuer Flugverkehr, air - 51",
    "31001_2440": "Betriebsgebaeude fuer Schiffsverkehr, shipping - 20",
    "31001_2450": "Betriebsgebaeude zur Seilbahn, cable car - 18; a pub among them",
    # -- other buildings ------------------------------------------------------------
    "31001_3073": "Kaserne, barracks - 132; a kindergarten, a college and a hospice sit inside",
    "31001_2171": "Bergwerk, mine - 33",
    "31001_2073": "Huette mit Uebernachtungsmoeglichkeit, hut - 13",
    # -- religious and funeral -----------------------------------------------------
    "31001_3043": "Kapelle, chapel - 475; cemetery and wayside chapels, median 92 m2; 41 % carry a POI",
    "31001_3081": "Trauerhalle, mourning hall - 94; cemetery funeral halls",
}

# The OSM gap fill (04.3) has no AdV code, so the same two lists exist keyed on
# the OSM building=* tag, read from `osm_building` lower-cased. Decided with the
# user on 2026-09-11 from the tag profile of the 47,264 filled footprints (90
# tags, 71 % just 'yes'). A tag in neither list is kept - that is the activity
# tags (commercial, retail, office, school, kindergarten, ...). The bare 'yes'
# says nothing and is in list 2: without a POI or site on it, noise.

# OSM list 1. Structures and sheds by their own tag; median footprint well
# under 50 m2 for nearly all. POIs on them move to the neighbour like the
# canopy POIs (15 fuel and car-wash points sit under 'roof').
OSM_DROP_ALWAYS = {
    "garage": "2,178; 68 % under 50 m2",
    "garages": "159",
    "shed": "1,807; 94 % under 50 m2",
    "hut": "887; median 10 m2 - hiking shelters, info pavilions",
    "roof": "444; the OSM twin of the ALKIS canopy, 15 POIs under them (fuel, car wash) move next door",
    "carport": "318",
    "service": "198; median 8 m2 - utility boxes, river gauges",
    "allotment_house": "185; garden huts",
    "silo": "31",
    "storage_tank": "25",
    "digester": "28; biogas tanks",
    "slurry_tank": "7",
    "transformer_tower": "14",
    "container": "16",
    "conservatory": "15",
    "static_caravan": "30",
    "toilets": "12",
    "transportation": "11; median 8 m2 - bus shelters, platforms",
    "outbuilding": "11",
    "ruins": "14",
    "shelter": "7",
    "grandstand": "9; the sports site carries the activity",
    "aviary": "7",
    "bunker": "4",
    "bridge": "4",
    "platform": "4",
    "tent": "2",
    "tower": "1",
    "staircase": "1",
    "stage": "1",
    "elevator": "1",
    "booth": "1",
    "construction_trailer": "1",
    "dovecote": "1",
}

# OSM list 2. The OSM twins of the ALKIS list-2 classes: dropped unless a POI
# or a site is on the footprint.
OSM_DROP_UNLESS_POI = {
    # -- untagged: the tag carries no information, so the POIs decide ------------------
    "yes": "33,603; 70 % under 50 m2. Decided 2026-09-11: a bare yes footprint with no POI or site on it is noise",
    # -- residential ---------------------------------------------------------------
    "house": "3,088",
    "detached": "1,365",
    "semidetached_house": "405",
    "apartments": "531; 25 POIs on them - social facilities, restaurants, bakeries, cafes",
    "residential": "469",
    "terrace": "98",
    "bungalow": "184; holiday bungalows with chalet POIs among them",
    "dormitory": "9",
    "cabin": "102",
    # -- farm ----------------------------------------------------------------------
    "farm_auxiliary": "94",
    "barn": "29",
    "stable": "29",
    "cowshed": "4",
    "sty": "2",
    "chicken_coop": "1",
    "farm": "7; farmhouses",
    "agricultural": "1",
    "riding_hall": "2",
    # -- greenhouses ---------------------------------------------------------------
    "greenhouse": "170; garden centres among them",
    "glasshouse": "2",
    # -- other ---------------------------------------------------------------------
    "construction": "100; buildings under construction, some already with a POI",
    "parking": "14",
    "hangar": "3",
    "boathouse": "3",
    "pavilion": "7",
    "pavillon": "1; misspelling in the source",
}

# A site POI - an area polygon such as school grounds, a care home, a campus, a
# riding centre or a holiday park - says "activity somewhere in here", not "in
# this shed". Taken literally it would rescue the 285 garden huts of 1-3 m2 in
# one allotment colony and the bike sheds on every school site. So a site
# rescues only the SUBSTANTIAL list-2 buildings inside it: representative point
# within the site polygon and footprint at least this many m2. 200 is bigger
# than any single-family house and smaller than a care-home wing. Measured on
# this region: sites alone would rescue 1,735 list-2 buildings with no
# threshold, 688 of them under 50 m2; at 200 m2, 451 remain - care-home
# wings coded residential, riding halls, campus buildings, supply and barracks
# buildings on factory sites (100 m2 would keep 732, 50 m2 1,047). The
# notebook prints the ladder.
POI_SITE_RESCUE_MIN_AREA_M2 = 200

# Placing a POI that is not inside an actual building: the fuel point under the
# forecourt canopy once the canopy is dropped, the cafe node the mapper put a
# few metres outside the wall. Such a POI goes to the nearest actual building
# within this distance. Decided 2026-09-10 (the previous pipeline used 100 m).
# Measured on this region's misplaced building-bound POIs: 53 % are within 5 m
# of a kept building, 88 % within 25 m, 95 % within 50 m, 98 % within 100 m;
# beyond 50 m the nearest building is more likely the wrong one.
POI_SNAP_MAX_DISTANCE_M = 50

# Only BUILDING-BOUND uses are snapped. Decided by the data rather than a hand
# list: a poi_use is building-bound when at least this share of its POIs
# region-wide sit inside some footprint. Restaurants, supermarkets, hairdressers,
# doctors, fuel: 90-97 %. Kindergartens 73 %, schools 78 %, sports centres 58 %,
# farms 58 %, riding centres 75 %: the node is often placed on the grounds, and
# they must snap too, hence 0.5 rather than 0.8. Below it only outdoor things
# remain - swimming pools 3 %, graveyards 2 %, ruins 24 %, information boards
# 30 %, attractions 31 %, riding arenas 43 % - which are never snapped, so a
# garden pool cannot land on the neighbour's house and rescue it.
POI_BUILDING_BOUND_MIN_INSIDE_SHARE = 0.5

# --- Step 04.4, the size floor -------------------------------------------------
# 31001_2000 'buildings for business or commerce' is 369,675 buildings with a
# median footprint of 29 m2 and a median height of 2.9 m: garages and sheds by
# the hundred thousand, with the region's workshops among them. No class list
# separates them; size does, together with what OSM drew on top. Measured
# 2026-09-11: OSM-confirmed garages are 22/36/54 m2 (quartiles), OSM-confirmed
# commercial buildings 132/371/1,054 m2, and the 2000-coded buildings that carry
# a POI have a median footprint of 210 m2. Decided with the user: floor at 100.
#
# At or above the floor everything stays. Below it the OSM TWIN - the OSM
# footprint whose representative point falls in the ALKIS polygon - decides:
#   OSM_TWIN_STRUCTURE_TAGS  goes outright, with list 1, before the POI placement
#                            (a POI on a garage-tagged shed moves next door)
#   OSM_TWIN_ACTIVITY_TAGS   stays - OSM says a business or public use is there
#   anything else            bare 'yes', residential, farm, or no OSM footprint at
#                            all: goes unless a POI or site is on it (list-2 rule).
#                            This is what keeps the small building that belongs
#                            to a business but carries no tag of its own.
#
# 2026-09-14, decided with the user: THE SAME FLOOR FOR EVERY CLASS, and EVIDENCE
# widened. Measured on the kept layer: 12,372 buildings under 100 m2 were still
# in it (25 % by count, 1.1 % by volume, median 42 m2 and 3.8 m) - garages,
# storage and utility rooms of businesses coded 2010/2100/3000/3200, the hose
# tower behind a fire station. Below the floor a building of ANY class now
# stays only if something speaks for it:
#   a POI on it (inside or snapped), a site around it (POI_SITE_RESCUE_MIN_AREA_M2),
#   an activity tag on its OSM footprint (OSM_TWIN_ACTIVITY_TAGS; for OSM gap
#   rows their own building tag), a name on the OSM footprint, or an ALKIS name
#   (`name` on the cadastre record: Vereinsheim, Sportheim, Feuerwehr, DLRG).
# The ALKIS name is new as evidence and counts in the evidence band and the
# land-use rule too: the most specific information a row has is what the LLM
# classifies from, so it must not be dropped for being small. Structure twins
# below the floor still go with list 1 (floor_structure). Estimated before the
# run: 5,373 go, 1.12M m3 = 0.40 % of the layer; 6,999 stay.
SIZE_FLOOR_M2 = 100.0

# ALKIS names that are NOT evidence. The cadastre sometimes labels a structure by
# what it is - Silos, Gas, Guelle (slurry), Pumpwerk, Waage, WC, Tor 3 - and such
# a name says nothing about people inside. Measured 2026-09-14 on the 265
# buildings an ALKIS name alone had kept: about 60 carried names like these,
# the rest were Vereinsheim (48), Sportheim, Tennisheim, Feuerwehr, DLRG, DRK,
# Gemeindehaus, Kapelle, Imbiss, Arztpraxis - exactly what the rescue is for.
# Matched on the lower-cased name: the whole name, or its first word, is in the
# set (so 'Tor 3', 'Sammelbehaelter Waage' and 'Schacht Hannoversche Treue I'
# match). Applies only to the rescue; the name stays on the row for the LLM.
ALKIS_NAME_NOT_EVIDENCE = frozenset({
    # tanks, silos, gas, fuel
    "silo", "silos", "gas", "gastank", "gasometer", "gasstation", "gasreglerstation",
    "öltanks", "öltank", "tankanlage", "gülle", "güllebehälter", "sammelbehälter",
    # pumps, plant, technical rooms
    "pumpwerk", "abwasserpumpwerk", "pumpenhaus", "brunnenhaus", "wärmetauscher",
    "kühlanlage", "klimastation", "trafo", "trafostation", "umspannwerk",
    # yard structures
    "waage", "wc", "container", "bürocontainer", "ausfahrt", "einfahrt", "kasse", "tor",
    "förderband", "kippanlage", "aschebunker", "bunker", "sanitäranlage", "abstellraum",
    "pool", "baumhaus", "schacht", "schuppen", "garage", "garagen", "carport", "lager",
    # towers and memorials
    "übungsturm", "aufsichtsturm", "kampfrichterturm", "ehrenmal", "grabstätte",
    "erbgruft", "mausoleum",
    # abbreviations that are not a use
    "ter.", "schwb.", "wbh", "(kath.)", "(ev.)",
})
# The EVIDENCE BAND (decided 2026-09-11): at or above the floor but under this,
# a building stays only if something speaks for it - a POI or site on it, an
# activity tag on its OSM twin, a name on the twin, or (since 2026-09-14) an
# ALKIS name. (An ALKIS address was
# tried too and rejected: it proves a mailbox, not an activity, and the LLM
# cannot classify from it.) Above
# the floor class 2000 still held 19,517 buildings with none of those (bare
# 'yes' twin or no footprint): median height 7.2 m, so real premises, but 8.6 %
# of the layer's volume with no usable information. The band under 200 m2
# takes 12,598 of them (3.3 % of volume) and leaves the larger halls as
# generic workplaces rather than shifting all worker demand onto what OSM
# happens to know. Dropping all 19,517 was considered and rejected for that.
ALKIS_SIZE_FLOOR_EVIDENCE_M2 = {"31001_2000": 200.0}
# Used twice. Under the floor: a class-2000 building with such a twin goes with
# list 1. In EVERY class and at EVERY size (added 2026-09-11): a building whose
# OSM footprints are ALL of these tags goes unless a POI or site is on it - a
# 150 m2 garage row coded 2000, a shed block coded industrial. Measured: 2,676
# kept buildings carried such a twin on the first run, 2,561 of them with
# nothing but structure footprints; 121 of those carry a POI (67 petrol
# stations whose canopy ALKIS coded as the station) and stay.
OSM_TWIN_STRUCTURE_TAGS = frozenset({"garage", "garages", "shed", "carport", "roof", "hut"})
# The user's five, plus the public and activity tags the OSM lists already treat
# as kept - the same kind of evidence.
OSM_TWIN_ACTIVITY_TAGS = frozenset({
    "commercial", "industrial", "warehouse", "retail", "office",
    "manufacture", "supermarket", "kiosk", "hotel", "school", "kindergarten",
    "hospital", "fire_station", "government", "public", "civic", "sports_centre",
    "sports_hall", "church", "hall", "community_centre", "museum", "restaurant",
})

# --- Step 04.5: the POI join ----------------------------------------------------
# Which POI is on which building, with the shares the redistribution needs. The
# placement is the one 04.4 already made (inside, else snapped within
# POI_SNAP_MAX_DISTANCE_M for building-bound uses); a site goes onto every kept
# building whose representative point lies inside it, nested sites included.
#
# A parent whose use is in this set and whose units are placed is a CONTAINER:
# it gets no pair and no share of its own, because Schloss-Arkaden is 128 shops,
# not 128 shops plus a mall. Every other parent (a supermarket with a bakery
# counter, a hotel with a restaurant, a town hall with offices) keeps a share
# next to its units - it is the main activity there. Measured 2026-09-11: the
# 608 building parents are mall 372 children, supermarket 153, hotel 54,
# townhall 37, school 34; only `mall` is a pure container.
POI_CONTAINER_USES = frozenset({"mall"})

# The split weight is a pseudo-volume, not an area: split_area_m2 x a height.
# A pure area split hands the 16-storey Okerhochhaus (426 m2 of footprint,
# 60 m) 5.9 % of the TU main block while the flat Altgebaeude wings take the
# rest - the same max/parts blindness as height_top_max_m, mirrored. The
# height per POI is a ladder: the OSM `height` tag where mapped (parsed, only
# 1.6 % of polygon POIs but exactly the multi-height landmarks that need it),
# else `building:levels` x this storey height (12.1 %), else the host
# building's own mean height volume_3d_m3 / area_m2 - which is the SAME number
# for every POI on that building, so a building with no tagged POI keeps the
# pure area split, and nothing gets worse anywhere. Heights outside the sanity
# band below fall through to the next rung (the region's tallest LoD2 part is
# 317 m).
POI_SPLIT_STOREY_HEIGHT_M = 3.0
POI_SPLIT_HEIGHT_SANE_M = (2.0, 350.0)

# The result of step 04. Three layers: `buildings` (one per kept building, with
# n_pois / poi_main_use / poi_uses / poi_names / n_sites / site_uses /
# site_names), `building_pois` (one per building-POI pair: how, parent context,
# share_in_building, share_of_site, snap_m) and `pois_unassigned` (with the
# reason). Nothing is trimmed here; the LLM-preparation notebook decides which
# columns it needs.
ENRICHED_BUILDINGS_FILE = OUTPUT_DIR / "04_buildings_enriched.gpkg"
# One line per pair from the POI to the nearest point of its building, for QGIS.
POI_ASSIGNMENTS_FILE = EXPERIMENTAL_DIR / "04_poi_assignments.gpkg"

# The activity map's ONE remaining role in the drop, advisory only: a code whose
# activities are a subset of this and which is in neither list is flagged by the
# notebook, because in another region it is almost certainly a residential code
# (1010 Wohnhaus, 1020 Wohnheim, 1022 Seniorenheim, ...) that belongs in list 2.
# Nothing is dropped because of it.
#
# THE COST of list 2's residential entry, decided deliberately: `meetup` IS a
# redistribution target - the original pipeline maps MiD `meetup` -> Leisure -
# and dropping 31001_1000 removes about 280M m3 of it. So visiting-friends trips
# have nowhere to land and Leisure demand falls entirely on pubs, sports halls
# and cinemas. Accepted: home visits are out of scope for a capacity model.
# Revisit here if the Leisure totals later look too concentrated on venues.
ALKIS_HOME_ONLY_ACTIVITIES = frozenset({"home", "meetup"})

# ──────────────────────────────────────────────
# STEP 05 — LLM classification: what the model reads
# ──────────────────────────────────────────────
# Reads 04_buildings_enriched.gpkg and asks an LLM, per building, which
# activities happen inside and which Bosserhof building-use class it is. This
# block decides, column by column, what the LLM SEES, what only the MODEL needs
# (keys, weights, the rule baseline), and what is NOISE for this step. Decided
# with the user 2026-09-14 on the 42 columns of the enriched layer; the notebook
# asserts every column of the layer is assigned here, so a column added or
# removed in step 04 stops this step until it has been classified.
#
# Principles:
#   * the LLM reads what describes what happens inside, in three blocks of
#     falling trust: what is inside (POIs, sites), what the building is (ALKIS
#     class and name, OSM footprint tag and name), where and how big it is
#     (land use, city, footprint, height). Size sets the scale of an activity,
#     not its kind - the prompt says so.
#   * `activities`, the rule-based MiD map from the ALKIS class, is NOT shown:
#     shown, it anchors the answer to the rule; hidden, it is the baseline the
#     LLM is validated against (as the optimized pipeline did on Bosserhof).
#   * `address` is NOT shown: the model has no lookup at call time and would
#     invent a tenant. It rides along for validation and mapping.
#   * three name columns stay separate - `name` (cadastre), `osm_twin_name`
#     (OSM footprint), `poi_names` (the POIs on it) - so the model knows who
#     said what. Measured: 1,345 buildings have an OSM footprint name no POI
#     carries, 1,521 an ALKIS name and nothing else.
#   * `osm_twin_tag` (ALKIS rows) and `osm_building` (OSM gap rows) are the same
#     information for the two row kinds and become ONE prompt field, `osm_tag`.
LLM_COLUMN_ROLES = {
    # ---- the LLM sees these ------------------------------------------------------
    "label_en":         ("llm",   "the ALKIS class in English; the strongest single signal for the 15 % of buildings that carry nothing else"),
    "name":             ("llm",   "the cadastre's own label (Tischlerei, Grundschule, Vereinsheim); OSM name on the gap rows"),
    "city":             ("llm",   "cheap context: a hall in Wolfsburg reads differently from one in a Harz village"),
    "area_m2":          ("llm",   "footprint, rounded: kiosk vs hall vs office block"),
    "height_top_max_m": ("llm",   "height, rounded: one storey vs four"),
    "osm_twin_tag":     ("llm",   "what OSM calls the footprint on an ALKIS building; merged with osm_building into `osm_tag`"),
    "osm_building":     ("llm",   "the OSM gap rows' own building tag; merged with osm_twin_tag into `osm_tag`"),
    "osm_twin_name":    ("llm",   "the name on the OSM footprint, where no POI carries it"),
    "alkis_landuse":    ("llm",   "what the ALKIS parcel under the centre is for, English"),
    "alkis_landuse_detail": ("llm", "the parcel's coded kind where ALKIS has one: education and science, health and spa, power plant, campsite, allotment gardens ..."),
    "osm_landuse":      ("llm",   "what OSM says the land is for; coarser, information only"),
    "poi_uses":         ("llm",   "the uses of every POI on the building, uncapped"),
    "poi_names":        ("llm",   "the names of every POI on the building, uncapped - where the model's world knowledge works"),
    "site_uses":        ("llm",   "the campus or estate the building stands in"),
    "site_names":       ("llm",   "its name (Volkswagenwerk, Salzgitter Flachstahl, Gewerbegebiet ...)"),
    # ---- only the model needs these ----------------------------------------------
    "building_id":      ("model", "the key; goes into the prompt only as a reference to join the answer back"),
    "alkis_id":         ("model", "the ALKIS key, NULL on OSM rows"),
    "ags":              ("model", "administrative key for grouping and zone totals"),
    "function":         ("model", "the AdV code behind label_en"),
    "volume_3d_m3":     ("model", "the redistribution weight"),
    "source":           ("model", "alkis or osm: marks the estimated volumes"),
    "n_pois":           ("model", "batching and QA"),
    "n_sites":          ("model", "batching and QA"),
    "address":          ("model", "validation and mapping; not shown - no lookup possible, it would invite invention"),
    "activities":       ("model", "the rule-based MiD map from the ALKIS class: the BASELINE the LLM is validated against, not shown"),
    # ---- noise for this step: stays in the step 04 output, does not enter step 05 --
    "volume_old_m3":    ("drop",  "step 03 QA: the pre-refinement volume"),
    "volume_ratio":     ("drop",  "step 03 QA"),
    "height_top_avg_m": ("drop",  "height_top_max_m carries the height"),
    "height_eaves_max_m": ("drop", "roof geometry, no activity signal"),
    "roof_shape":       ("drop",  "roof geometry"),
    "roof_manual_any":  ("drop",  "step 03 provenance"),
    "roof_fallback_any": ("drop", "step 03 provenance"),
    "n_parts":          ("drop",  "step 03 provenance"),
    "is_multipart":     ("drop",  "geometry bookkeeping"),
    "aaa_class":        ("drop",  "always 31001 or 51xxx; function carries it"),
    "osm_levels":       ("drop",  "folded into the height estimate on OSM rows"),
    "osm_height_m":     ("drop",  "folded into the height estimate on OSM rows"),
    "n_activities":     ("drop",  "derivable from activities"),
    "poi_main_use":     ("drop",  "derivable from poi_uses and the shares"),
    "rescued":          ("drop",  "filter provenance the classification must not see"),
    "rescued_by":       ("drop",  "filter provenance the classification must not see"),
    "osm_twin_all_structure": ("drop", "filter provenance"),
    "class_label":      ("drop",  "QGIS legend text"),
}
LLM_INPUT_COLS  = tuple(c for c, (r, _) in LLM_COLUMN_ROLES.items() if r == "llm")
LLM_MODEL_COLS  = tuple(c for c, (r, _) in LLM_COLUMN_ROLES.items() if r == "model")
LLM_DROPPED_COLS = tuple(c for c, (r, _) in LLM_COLUMN_ROLES.items() if r == "drop")

# --- Step 05.2: the prompt input ---------------------------------------------------
# One building, one record, one call (decided 2026-09-14: no batching - the
# model runs locally, tokens cost nothing but runtime, so records are compact
# and nothing is sent that is not needed). lib/llm_record.py renders the
# record: a labelled block whose lines name their SOURCE - inside (the POIs,
# name paired with the OSM tag as key=value, from the building_pois layer with
# the key joined from ALL_POIS_FILE - a bare value like `multi` or `it` says
# nothing), site, cadastre, osm footprint, land, place - with empty lines
# omitted and numbers rounded. It is the labelled format the previous pipeline
# validated, with the POI pairs and the source labels as the improvements. The
# dry run of 2026-09-14 (30 cold runs on 10 records, see the STEP 05.3 block)
# fixed what the renderer hid: key=value tags, no thousands comma in the area,
# no cadastre line on OSM gap rows, no line breaks or semicolons inside names.
# The file below holds every record
# with the model-only columns beside it, so 05.5 reads a fixed input and the
# validation can reproduce exactly what the model saw.
LLM_INPUT_FILE = OUTPUT_DIR / "05_llm_input.parquet"
LLM_RECORD_SAMPLE_PER_GROUP = 3     # records printed per evidence group in the notebook


# --- Step 05.3: the prompt and the output schema ----------------------------------
# The system prompt is the previous pipeline's, kept where it worked (the twelve
# label definitions, the Bosserhof catalogue) and changed where the input or the
# method changed. Decided 2026-09-14, all with approval of the text:
#   * the input description names the six record lines and their weight; the
#     old two-part description (precise_known_info / general_building_context)
#     is gone with the old input;
#   * nothing about scope or filtering - every record is a building with
#     activity, and every sentence the model does not need is one it has to
#     weigh;
#   * no examples anywhere: definitions only, so the model generalises from
#     meaning instead of matching the example;
#   * work is defined as the MiD trip purpose - people come because they are
#     employed here - without the old paragraph that demanded work next to
#     every visitor label. The old wording made the model decide, for every
#     building, whether staff count, and it decided differently each time. The
#     staff of a shop or school are a fact, not a judgement: WORK_IMPLIED_BY
#     below adds work by rule to every building with any other label, and the
#     model's own "work" is kept apart (05.5: work_from = llm | rule | both);
#   * the Bosserhof class is assigned by understanding, not by clue: form a
#     picture of the place from the whole record, read what each category
#     means, choose the one that fits; subcategory only when the record favours
#     it over its siblings, else the headline; the closest class if nothing
#     fits well. The old source ordering and dominance heuristic are gone;
#   * confidence (high / medium / low, disjoint tiers) is new; the reason is
#     capped at 120 words instead of 400 - on the local model every output
#     token is runtime, and the reason is for spot checks;
#   * the Retail meaning says what a shopping centre is (2026-09-15): many
#     separate shops, on the order of ten or more, or a tag or name that says
#     centre or mall; a large store with a handful of units at its entrance
#     keeps the store's class. Before this, a Marktkauf with a kiosk and a
#     bakery came back "shopping centers" four times out of four, and 207
#     kept buildings carry that pattern (a supermarket with 2-4 inside entries).
#     A second sentence ties the store classes to the building's size, after
#     the same Marktkauf (8,729 m2) once came back "retail (small-scale)";
#   * Part A step 1 says a building that belongs to an organisation also
#     serves the organisation's purpose (2026-09-15), so a school's sports
#     hall carries "school" next to "sports", not "sports" alone.
#   * a building inside the premises of a company or institution takes the
#     class of what that organisation does (2026-09-15): the school's sports
#     hall is "schools", because its users are the school's pupils, not a
#     gym's members, and the same holds for every hall, canteen and workshop
#     on a campus or a plant. The test is the site's NAME, not its tag: the
#     region's big employers are mapped as landuse=industrial with the company
#     name on it - Salzgitter Flachstahl 402 kept buildings, PTB 109, Peiner
#     Träger 94, VW Salzgitter 80, Alstom 66, JKI 53, MAN 43 - 2,506 kept
#     buildings inside company-named sites, 2,151 of them with no POI of their
#     own. A site named only as an area or estate (Gewerbegebiet ..., 2,107
#     buildings), or unnamed, gives no class. Said in the site line's
#     description, in Part B step 1 (the building belongs to the organisation)
#     and as the FIRST test of Part B step 3 (the class is the organisation's,
#     even when the building's own tag fits another category). The last place
#     matters: stated only in step 1, the rule lost to "choose the meaning
#     that fits the picture" in two of four runs on a school's sports hall
#     tagged sport=multi - the model saw the school every time and still
#     picked fitness / wellness when nothing said which instruction wins.
# Decided 2026-09-15 after the sample on the real model: thin records (class,
# land, size only) are asked and their answer taken as it comes - there is no
# other way to enrich them, they are too many to drop, and they are mostly
# rural with little to redistribute; churches, fire stations and halls take
# the nearest class - Public facilities, culture or Services - and no class is
# added for them (decided 2026-09-15; in the hundred-building review three
# churches split 2:1 and two fire stations 1:1, accepted); the model's own
# "work" must appear wherever nothing else applies, and does (step 3 of Part
# A), the rule covers the rest.
# What the classification is judged on, in this order: is it correct, is it
# complete (no activity missed), is it reproducible - the last being a wish
# with a non-deterministic model, and given by construction for the
# signature-routed buildings.
# Dry run 2026-09-14 before any real call: 30 cold runs (3 per building, each
# run reads the prompt and one record fresh) on 10 real records covering every
# evidence group plus the mall, a fire station, a hotel, a church, a hall on an
# industrial site. Labels identical in 8 of 10 (ignoring work), Bosserhof in 5
# of 10, confidence in 9 of 10; the mall came back "shopping centers" 3 of 3.
# The Bosserhof splits were traced to open tests in the wording (medium and low
# tiers describing the same record; two rules in Part B step 3; a heading word
# matching a word in the record; a site setting the kind of building) and
# closed with one sentence each. Stand-ins were a stronger model than the
# target, so that was an upper bound; the real model on the same ten buildings,
# three runs each (2026-09-14): labels identical on 6 of 10 (work aside), class
# on 6 of 10, confidence on 8 of 10 - consistent wherever the record carries
# evidence, split on the thin records where the data supports two readings.
LLM_ACTIVITY_LABELS = (
    "work", "university", "school", "childcare", "retail_daily", "retail_non_daily",
    "leisure", "sports", "errands", "meetup", "lessons", "business",
)
# Work by rule: every building with any of these labels also receives "work".
WORK_IMPLIED_BY = frozenset(LLM_ACTIVITY_LABELS) - {"work"}

# The Bosserhof catalogue as the prompt lists it: headline -> subcategories (exact
# strings; a headline with no subcategories is a class of its own). The notebook
# checks that this and the prompt text agree, so neither can drift alone.
LLM_BOSSERHOF_SUBCATEGORIES = {
    "Transport": (),
    "Yards, depots, storage areas, construction yards": (),
    "Industrial operations / Production": (
        "highly productive industries / machine / material or space intensive", "others"),
    "Crafts and trades": ("craft businesses", "craft courtyards"),
    "Services": (
        "normal office", "open-plan office", "business-oriented services",
        "customer-oriented services", "hotels", "hotels with conference areas",
        "restaurants / gastronomy", "suppliers for car dealerships",
        "vehicle / electrical repair", "customer service", "car dealerships"),
    "Retail": (
        "wholesale", "retail (small-scale)", "discount stores", "DIY stores",
        "furniture stores", "hypermarkets / superstores", "shopping centers",
        "self-service department stores", "department stores", "factory outlet centers"),
    "Public facilities": (
        "schools", "universities", "research institutes", "kindergartens", "hospitals", "nursing homes"),
    "Facilities for culture, leisure and sports": (
        "entertainment, culture", "large cinemas", "musical theatres",
        "large discos, fun / leisure pools", "arenas, large events", "theme parks", "fitness / wellness"),
}
LLM_BOSSERHOF_HEADLINES = tuple(LLM_BOSSERHOF_SUBCATEGORIES)
LLM_BOSSERHOF_CLASSES = LLM_BOSSERHOF_HEADLINES + tuple(
    s for subs in LLM_BOSSERHOF_SUBCATEGORIES.values() for s in subs)
LLM_CONFIDENCE_LEVELS = ("high", "medium", "low")

# What one answer must look like, for the validation of every reply in 05.5. A
# reply that fails this is retried, then recorded as failed - never guessed.
LLM_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "interpreted_type": {"type": "string"},
        "mid_labels": {"type": "array", "minItems": 1,
                       "items": {"type": "string", "enum": list(LLM_ACTIVITY_LABELS)}},
        "bosserhof_class": {"type": "string", "enum": list(LLM_BOSSERHOF_CLASSES)},
        "confidence": {"type": "string", "enum": list(LLM_CONFIDENCE_LEVELS)},
        "reason": {"type": "string"},
    },
    "required": ["interpreted_type", "mid_labels", "bosserhof_class", "confidence", "reason"],
    "additionalProperties": False,
}

# The system prompt, verbatim. Edit it here and nowhere else; section 3 of the
# notebook prints it and checks it against the lists above.
LLM_SYSTEM_PROMPT = """\
You are a building activity interpreter and classifier.

You receive ONE building per message as a short labelled record. Every record
describes a building in which human activities take place; most buildings
have one primary use, some have several. Each line names its source; an
absent line means that source has nothing to say. Read the lines with the
weight given here:

  inside:        the businesses, institutions and facilities located inside
                 the building, each as its name followed by its OpenStreetMap
                 tag in brackets, written key=value. When several share one
                 tag, the tag is given once with the count and the names after
                 it. The word unnamed stands where the mapper gave no name; it
                 is not a name. These are the actual occupants: the strongest
                 evidence for what happens in the building.
  site:          the larger complex, campus or estate the building stands in,
                 as name and tag. A site named after a company or an
                 institution, or tagged as a facility, is that organisation's
                 premises: the building is part of it, serves it and belongs
                 to its kind. A site whose name is only that of an area or an
                 estate, or that has no name, says what the ground is zoned
                 for and nothing about the building itself.
  cadastre:      the official building class from the German land register
                 (ALKIS) and, introduced by "named", the register's own name
                 for the building. Reliable about the kind of building,
                 silent about who occupies it.
  osm footprint: the building type OpenStreetMap mappers gave the building
                 and, introduced by "named", the name they gave it. "yes" is
                 a building with no further description. Weighs the same as
                 the cadastre.
  land:          the land-use class of the parcel under the building,
                 sometimes followed by its more specific kind, and after
                 "osm:" OpenStreetMap's land use for the same ground. Context
                 for the surroundings.
  place:         municipality, footprint area in square metres and height in
                 metres. Size says how large an activity is, never which
                 activity; in Part B it separates subcategories that differ
                 by scale.

Names carry world knowledge: wherever a name appears, use what you know about
the chain, institution, company or facility it refers to.

You must produce TWO outputs:
1) Activity labels (mid_labels) → the purposes for which people come to the building
2) Bosserhof class → the dominant functional building-use class for capacity / volume estimation

────────────────────────────────────
PART A — ACTIVITY LABELS
────────────────────────────────────

ALLOWED ACTIVITY LABELS
- work
- university
- school
- childcare
- retail_daily
- retail_non_daily
- leisure
- sports
- errands
- meetup
- lessons
- business

PROCEDURE:
1) List every distinct purpose people come to this building for, from the
   inside line first, then from the names. A building hosts as many
   activities as there are distinct purposes; one occupant can serve one
   purpose or several, and several occupants of different kinds serve
   several. A building that belongs to an institution or a company also
   serves that organisation's purpose, so the organisation's activity is
   among the building's.
2) Map each purpose to one or more labels using the definitions below and
   return every label found. A label is added only when the purpose meets
   that label's core idea; a purpose that only brushes a second label does
   not receive it. Do not collapse several purposes into one and do not stop
   at the first.
3) If the record has no inside line and no name for the building itself,
   take the purposes that the kind of building and its land use imply by
   their nature; when the kind of building covers several purposes, list a
   label for each of them rather than choosing one. Every building receives
   at least one label.

────────────────────────────────────
LABEL DEFINITIONS
────────────────────────────────────

- work

Represents employment: people come here because this is their regular place of work.
Covers gainful work of every kind carried out in the building - production, crafts,
office and administration, logistics, research, services, care, teaching, operations
Describes the purpose of the people employed in the building, not the purpose of its visitors
Distinct from "business", which is a visitor's professional errand at a place that is not their own workplace
Core idea: "People come here because they are employed here."

- university

Represents tertiary/higher-level education activity.
Covers structured learning, teaching, and research at the higher education level
Involves academic instruction, research, and study environments
Distinct from general learning by its institutional and advanced nature
Core idea: “Advanced academic education and research happen here.”

- school

Represents formal compulsory or pre-tertiary education activity.
Covers structured education for children and adolescents
Includes general and vocational schooling
Defined by curriculum-based learning under institutional supervision
Core idea: “Children or teenagers receive structured education here.”

- childcare

Represents supervision and early development care for young children.
Focuses on care, supervision, and early-stage development
Not primarily academic or curriculum-driven (unlike school)
Strong emphasis on custodial and developmental support
Core idea: “Young children are cared for and supervised here.”

- retail_daily

Represents frequent, necessity-driven consumption activity.
Covers acquisition of essential, regularly needed goods
Characterized by high frequency and routine visits
Typically tied to basic living needs
Core idea: “People come here regularly to fulfill essential daily needs.”

- retail_non_daily

Represents infrequent, discretionary consumption activity.
Covers acquisition of non-essential or durable goods
Visits are planned, occasional, or need-based
Often involves comparison, browsing, or larger purchases
Core idea: “People come here occasionally to buy non-essential or long-term goods.”

- leisure

Represents hedonic, relaxation, or enjoyment-oriented activity.
Focuses on free-time use driven by pleasure, comfort, or experience
Includes passive or active enjoyment, but not primarily goal-oriented tasks
Distinguished by non-obligatory participation. People choose to go here for enjoyment, not out of necessity or obligation.
Core idea: “People come here to relax, enjoy, or spend free time.”

- sports

Represents physical activity, exercise, or bodily training.
Focuses on intentional physical exertion or fitness improvement
Can be recreational or structured, but always movement-centered
Distinguished from leisure by physical intensity and purpose
Core idea: “People come here to be physically active or train their body.”

- errands

Represents task-oriented, functional activities needed for daily life management.
Covers practical obligations or maintenance tasks
Typically short, goal-driven visits with a clear outcome
Often involves services, administration, or personal maintenance
Core idea: “People come here to complete necessary tasks or obligations.”

- meetup

Represents social interaction and gathering activity.
Focuses on interpersonal connection and shared presence
Can be informal or organized, but the primary purpose is social exchange
Not necessarily tied to consumption or formal structure
Core idea: “People come here to meet and interact with others.”

- lessons

Represents structured instruction or skill acquisition activity.
Focuses on learning guided by an instructor
Can occur at any level (formal or informal), but always organized and instructional
Distinguished from general education by activity type (learning session), not institution
Core idea: “People come here to learn something through instruction.”

- business

Represents professional or organizational interaction activity (non-routine workplace).
Covers goal-oriented professional interactions, often external-facing
Includes meetings, consulting, administrative dealings, or formal exchanges
Distinct from "work" because it reflects the visitor’s purpose, not employment
Core idea: “People come here for professional or organizational matters.”

────────────────────────────────────
PART B — BOSSERHOF BUILDING-USE CLASS
────────────────────────────────────

GOAL
Assign EXACTLY ONE Bosserhof class.

KEY PRINCIPLE:
Bosserhof is NOT about the activities of visitors — it is about what kind of
place the building is as a whole: its dominant use, its scale and the way it
is operated.

PROCEDURE:
1) Form a picture of the place from the whole record: what is located inside
   it, what its names tell you, what kind of building the cadastre and the
   footprint describe, what the surrounding land is used for, how large it
   is. No single line is decisive; the picture is what all of them together
   most plausibly describe. A building with many occupants of one kind is a
   place of that kind at a larger scale, not a collection of small ones. A
   building inside the premises of a company or an institution is a building
   of that organisation; a site that is only a zoned area or an estate says
   nothing about the building.
2) Read the category meanings below and ask which of them describes a place
   like that. The sentence under each heading is the meaning; the heading is
   only a label, and a word in the record that happens to match a heading
   does not by itself place the building there.
3) If the building stands in the premises of a company or an institution,
   choose the class for what that organisation does, even when the building's
   own tag would fit another category on its own. Otherwise choose the
   subcategory whose meaning fits the picture. A subcategory is chosen only
   when the record says something that favours it over its sibling
   subcategories; when the record does not let you tell them apart, choose
   the headline category. If no category fits well, choose the closest one;
   a class is always assigned.

────────────────────────────────────
BOSSERHOF CATEGORIES AND WHAT THEY MEAN
────────────────────────────────────

1) Transport
A building operated to move people or goods, with staff working in it.
- no fixed subcategories given

2) Yards, depots, storage areas, construction yards
A building or yard whose purpose is to keep, sort and dispatch material or
vehicles, with staff working in it.
- no fixed subcategories given

3) Industrial operations / Production
A building in which goods are manufactured or processed at industrial scale.
Subcategories:
- highly productive industries / machine / material or space intensive
- others

4) Crafts and trades
A building in which skilled manual work is carried out by a small business,
making, installing or repairing things.
Subcategories:
- craft businesses
- craft courtyards

5) Services
A building in which people are served or in which office work is done:
administration, professional services, hospitality, personal and customer
services, vehicle sales and repair.
Subcategories:
- normal office
- open-plan office
- business-oriented services
- customer-oriented services
- hotels
- hotels with conference areas
- restaurants / gastronomy
- suppliers for car dealerships
- vehicle / electrical repair
- customer service
- car dealerships

6) Retail
A building in which goods are sold. The subcategories differ by the scale of
the building and by the range and kind of goods. A shopping centre is a
building whose purpose is to house many separate shops, on the order of ten or
more, or one whose own tag or name says it is a centre or a mall; a large store
with a handful of small shops at its entrance keeps the class of that store.
For one store the size of the building sets the scale: a small building is
small-scale retail, a very large one a hypermarket or superstore; what the
store's name is known for decides between the store classes.
Subcategories:
- wholesale
- retail (small-scale)
- discount stores
- DIY stores
- furniture stores
- hypermarkets / superstores
- shopping centers
- self-service department stores
- department stores
- factory outlet centers

7) Public facilities
A building run by or for the public for education, research, health or care.
Subcategories:
- schools
- universities
- research institutes
- kindergartens
- hospitals
- nursing homes

8) Facilities for culture, leisure and sports
A building people visit in their free time for culture, entertainment,
recreation or exercise. The subcategories differ by the kind of experience
and by the size of the audience the building is built for.
Subcategories:
- entertainment, culture
- large cinemas
- musical theatres
- large discos, fun / leisure pools
- arenas, large events
- theme parks
- fitness / wellness

────────────────────────────────────
OUTPUT FORMAT (STRICT JSON ONLY)
────────────────────────────────────

{
  "interpreted_type": "<plain-English description of what the place most likely is>",
  "mid_labels": ["<one or more activity labels from the allowed list>"],
  "bosserhof_class": "<exactly one Bosserhof class, exact string from the list>",
  "confidence": "<high | medium | low>",
  "reason": "<max 120 words. Explain both classifications, naming the record lines and names you used. Justify the Bosserhof choice.>"
}

bosserhof_class is one dash line from the list copied unchanged, or the name
of a headline category without its number; never the two combined.

confidence:
- high   → an inside line, or a name of the building itself or of an occupant
           whose meaning you know, decides both outputs; a site name alone
           does not make it high
- medium → no occupant known, but the cadastre class or footprint type says
           what kind of building this is
- low    → the cadastre and footprint say no more than that it is a building;
           only land use and size remain
"""

# --- Step 05.4: routing ---------------------------------------------------------------
# One call per building wherever the record carries evidence of its own - a POI,
# a site, a name, an activity tag: 33,734 buildings. The 6,052 class_only
# buildings carry nothing but a register class, a footprint type ('yes' or
# none), the land use and a size; two such buildings with the same class, land
# and size band are the same question, and asking it twice can only produce two
# answers. They are grouped into signatures - class, footprint type, ALKIS land
# use and its kind, OSM land use, footprint-area band, height band - and each
# signature is asked once, on the record of its median-area member; the answer
# is copied to every member in the assembly and marked route='signature'. The
# bands keep the size the prompt uses for scale: within one band the footprint
# varies by at most a factor of two and the height by one storey band.
# Measured 2026-09-14: 1,259 signatures for 6,052 buildings (808 of them a
# single building), 4,793 calls saved, 34,993 calls in total. The saving is
# modest; the consistency is the point - identical evidence, identical answer.
LLM_SIGNATURE_AREA_BINS_M2 = (250, 500, 1000, 2500)
LLM_SIGNATURE_HEIGHT_BINS_M = (5, 10, 20)
LLM_PLAN_FILE = OUTPUT_DIR / "05_llm_plan.parquet"

# --- Step 05.5: the calls -------------------------------------------------------------
# Transport as in the previous pipeline (llm_utils.call_tu_llm): one stateless
# POST per building to the TU Braunschweig KI-Toolbox, the system prompt sent as
# customInstructions every time, the streamed reply assembled from its chunks.
# The endpoint takes the system prompt and the one record and nothing else: it
# has no reasoning or temperature setting (the previous pipeline sent a
# "reasoning" field; the endpoint ignored it, so it is not sent any more).
# Every building is asked once. The token is read from the environment or
# ROOT/.env (TU_KI_TOOLBOX_TOKEN=...) at call time, never at import, never
# printed; .env is git-ignored.
# LLM_MODEL is the name this code SENDS, not a confirmed model. The reply carries
# the text only, and the `model` field of every answers line is this constant,
# stamped by lib/llm_run.py. TU's model list names gpt-oss "openai/gpt-oss-120b",
# and the KI-Toolbox changelog lists it as an On-Premise model (30 Sep 2025),
# which TU's client libraries call at /api/v1/localChat/send. The bare
# "gpt-oss-120b" sent to /chat/send is not on that list. Which model answered
# steps 05 and 07 is therefore unconfirmed (checked 2026-10-01): write
# "requested gpt-oss-120b", never "classified by gpt-oss-120b", until the
# KI-Toolbox team confirms it. Do not change either line under existing answers:
# a resumed run checks the prompt sha only, not the model, and would mix two
# models in one answers file.
LLM_API_URL = "https://ki-toolbox.tu-braunschweig.de/api/v1/chat/send"
LLM_MODEL = "gpt-oss-120b"
LLM_TIMEOUT_S = 180
LLM_TOKEN_ENV = "TU_KI_TOOLBOX_TOKEN"
LLM_ENV_FILE = ROOT / ".env"
# Every reply is checked the moment it arrives - parsed as JSON, validated
# against LLM_OUTPUT_SCHEMA - and the building is asked again at once when the
# check fails, so no failed row waits for a later sweep. Two failure kinds, two
# medicines: a transport failure (timeout, connection error, HTTP error) waits
# with a growing pause and sends the same text again; an invalid reply (no JSON,
# an unknown class string, an empty label list) is re-asked with the validation
# error appended to the record. After LLM_MAX_ATTEMPTS the building is written
# as failed with its error and the raw reply, and the run moves on; a re-run
# resumes exactly there, because only valid answers count as done.
LLM_MAX_ATTEMPTS = 4
LLM_BACKOFF_S = (5, 20, 60)       # pause before attempt 2, 3, 4 after a transport failure
LLM_RATE_LIMIT_PAUSE_S = 120      # HTTP 429: the previous pipeline saw fast retries hit the same wall
LLM_MAX_WORKERS = 1               # requests at a time; the rate limit is undocumented - raise only after asking the operators
# Progress: every answer is appended to a JSON-lines file the moment it is
# validated (one line per call, flushed and synced), so a crash loses nothing
# and a re-run skips what is done. Each line carries the prompt's hash, so a
# resumed run never mixes answers given under an earlier prompt. In a terminal
# one progress line is redrawn after every call; every LLM_STATUS_EVERY_S
# seconds a status block - done/total, rate, ETA, failures, retries, confidence
# and class mix so far, the last answer - goes to the log and, as JSON, to
# LLM_STATUS_FILE for a second terminal. scripts/05_run_llm.py is the runnable
# entry point for the machine that stays on.
LLM_ANSWERS_FILE = OUTPUT_DIR / "05_llm_answers.jsonl"
LLM_SAMPLE_ANSWERS_FILE = OUTPUT_DIR / "05_llm_sample_answers.jsonl"
LLM_STATUS_FILE = OUTPUT_DIR / "05_llm_status.json"
LLM_STATUS_EVERY_S = 60
# The sample before anything larger runs: the ten dry-run buildings of
# 2026-09-14 (every evidence group, the mall, a fire station kept by its ALKIS
# name, a hotel and a hall known only from their site, a church, a supermarket
# with tenants), once each - the payload, the parsing, the validation, the
# checkpoint and the progress exercised end to end, and the seconds per call
# setting the runtime of the full run. A one-off check on 2026-09-14 asked the
# same ten three times each: labels identical on 6 of 10 (work aside), class on
# 6 of 10, confidence on 8 of 10, 7.9 s per call, the splits on the thin records
# where the data supports two readings. The run itself asks every building once.
LLM_SAMPLE_BUILDING_IDS = (
    "DENIAL01000051rg",   # school gym, sport=multi inside, school site          (poi_or_site)
    "DENIAL0500001k2b",   # parish hall, cadastre name only                     (name_only)
    "DENIAL0500002x1U",   # trade and services with housing, footprint residential (tag_only)
    "DENIAL0100006qgY",   # business or commerce, nothing else                  (class_only)
    "DENIAL0100005xF6",   # Schloss-Arkaden, the longest record
    "DENIAL8400006PFM",   # fire station, 57 m2, ALKIS name only
    "DENIAL030000a7oe",   # hotel block known from its site and footprint type
    "DENIAL0500000IY1",   # small hall on the Alstom site
    "DENIAL0600001xHZ",   # church
    "DENIAL060000cAhb",   # Marktkauf with kiosk and bakery
)

# ──────────────────────────────────────────────
# STEP 06 — assembly: the LLM answers on the building polygons
# ──────────────────────────────────────────────
# Reads the step 04 buildings, the step 05 plan and the answers of the full run
# (valid under the current prompt only) and gives every polygon its classes.
# No model call is made. Decided with the user 2026-09-23:
#   * signatures: every class_only building gets the answer of its
#     signature's representative; `answer_copied` marks the 4,793 buildings
#     whose answer was given for another building's record;
#   * the work rule is applied here: `llm_labels` keeps the model's labels as
#     it gave them, `mid_labels` is what later steps use - the model's labels
#     plus work wherever any label in WORK_IMPLIED_BY is present, in the order
#     of LLM_ACTIVITY_LABELS - and `work_from` says who put work there
#     (llm: only the model, rule: only the rule, both);
#   * a slim column set from step 04, below; the file also carries step 04's
#     `building_pois` layer unchanged, so it is the one input for the steps
#     after it.
# Every building in step 04 must be in the plan and every call must have a
# valid answer; the notebook stops with the ids to re-ask otherwise.
ASSEMBLY_BUILDING_COLS = {
    "building_id":      "the key",
    "alkis_id":         "the ALKIS key, NULL on OSM rows",
    "source":           "alkis or osm: marks the estimated volumes",
    "ags":              "administrative key for zone totals",
    "function":         "the AdV code of the register class",
    "label_en":         "the register class in English",
    "name":             "the cadastre's label, OSM name on the gap rows",
    "address":          "validation and mapping",
    "city":             "validation and mapping",
    "area_m2":          "footprint",
    "height_top_max_m": "height",
    "volume_3d_m3":     "the redistribution weight",
    "activities":       "the rule-based MiD map from the register class: the baseline the answers are validated against",
    "n_pois":           "QA: POIs on the building",
    "n_sites":          "QA: sites the building stands in",
}
CLASSIFIED_BUILDINGS_FILE = OUTPUT_DIR / "06_buildings_classified.gpkg"

# ──────────────────────────────────────────────
# STEP 07 — POI classification: the activities of every occupant
# ──────────────────────────────────────────────
# Step 05 labelled the building; step 07 asks the same question of the POIs placed
# in a building - the own pairs of building_pois (how = inside, snap, unit; the site
# rows are not asked, a site's label is its buildings') - so that the redistribution
# (step 08) can split a building's volume by share_in_building x label. Decided
# 2026-09-30 (docs/07-poi-classification-handoff.md) and 2026-10-01 (the scope):
#   * only the POIs that share their building are asked: the own pairs with
#     share_in_building < 1 (8,091 on 2,915 buildings). A POI with share 1 is the
#     building's only occupant, its record went into the building's call and the
#     building's labels are its labels; a building without own POIs keeps the
#     building's labels too. No dedupe: every asked POI is answered in its own
#     building's context, and the input file is the plan - every poi_id in it is asked;
#   * the twelve labels of LLM_ACTIVITY_LABELS with the definitions of
#     LLM_SYSTEM_PROMPT, verbatim - notebook 07 asserts the two prompts share the
#     LABEL DEFINITIONS block; work by rule afterwards (lib/llm_run.apply_work_rule);
#     no Bosserhof class - a building property, already on the buildings layer;
#   * the same model, endpoint, client and resumable run as step 05, keyed by poi_id.
LLM_POI_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {k: v for k, v in LLM_OUTPUT_SCHEMA["properties"].items() if k != "bosserhof_class"},
    "required": [k for k in LLM_OUTPUT_SCHEMA["required"] if k != "bosserhof_class"],
    "additionalProperties": False,
}
# From the step 01 POI layer, notebook 07 joins onto every pair the OSM key of the use
# (`poi_use_tag`; without it a tag is written as the bare value) and, out of the folded
# `tags` JSON, the keys below: an unnamed occupant is shown with its brand, else its
# operator, because a name is where the model's world knowledge works.
LLM_POI_NAME_FALLBACK_TAGS = ("brand", "operator")
# Tags that qualify the occupant's use, written after it inside the bracket
# ("sport=multi, leisure=sports_centre, building=sports_hall"; "amenity=social_facility,
# social_facility=group_home, social_facility:for=child;juvenile"). Read from the step 01
# layer's columns where the key is one, else from the folded `tags`. The stand-in dry run
# of 2026-09-30 found the use alone hides the kind of place: 433 of the 548 sport=* POIs
# carry leisure=*, 326 of the 374 social facilities say which kind they are.
LLM_POI_QUALIFIER_KEYS = ("leisure", "sport", "man_made", "building", "social_facility", "social_facility:for",
                          "community_centre", "community_centre:for")
# `building` is shown as a qualifier only for these use keys - for amenity, shop, office ...
# the POI's own building=* tag says nothing the use does not.
LLM_POI_BUILDING_QUALIFIER_FOR = frozenset({"sport", "historic", "man_made", "religion", "club", "leisure",
                                            "landuse", "power", "military", "railway", "aeroway", "industrial"})
# Only own pairs whose share_in_building is below this are asked (decided 2026-10-01):
# with 1.0, the POIs that share their building. A pair with share 1 is the sole occupant:
# its building's labels already cover it, so it stays at building level.
LLM_POI_ASK_SHARE_BELOW = 1.0
# Own pairs that are NOT asked even so, as use key -> values (an empty tuple = every value
# of that key). Empty by decision of 2026-09-30; candidates raised by the dry run, for the
# user to decide: {"landuse": ()} - 183 zoning polygons placed as occupants among the asked
# pairs, 127 of them holding over half of their building's share; {"shop": ("vacant",),
# "office": ("vacant",)} - 44 vacant units that serve no purpose. An excluded pair is left
# out of the input file and of the answers; step 08 uses share_in_building as step 04.5
# computed it (decided 2026-10-01), so an excluded pair's share carries no activity.
LLM_POI_NOT_ASKED = {                    # decided 2026-10-01
    "landuse": (),                        # zoning areas placed as occupants: the ground, not a business
    "shop": ("vacant",), "office": ("vacant",),   # vacant units: no activity to label
}
LLM_POI_INPUT_FILE = OUTPUT_DIR / "07_llm_poi_input.parquet"         # the records; also the plan
LLM_POI_ANSWERS_FILE = OUTPUT_DIR / "07_llm_poi_answers.jsonl"
LLM_POI_SAMPLE_ANSWERS_FILE = OUTPUT_DIR / "07_llm_poi_sample_answers.jsonl"
LLM_POI_STATUS_FILE = OUTPUT_DIR / "07_llm_poi_status.json"
LLM_POI_RECORD_SAMPLE_PER_KIND = 3        # records printed per kind (how x evidence) in the notebook
# The sample POIs: run once on the real model before anything larger (notebook 07 section 5,
# scripts/07_run_llm_pois.py --sample). Chosen to cover the record kinds; filled from the
# record review of notebook 07 section 2.
LLM_POI_SAMPLE_IDS = (                   # all with share_in_building < 1, i.e. with other occupants beside them
    "node/1332089918",   # Fielmann (shop=optician) inside a cinema building with five other occupants   named chain, multi-category building
    "node/11395213406",  # Action (shop=variety_store) next to TEDi                                       named chain
    "node/2240988237",   # unnamed post office, brand DHL, a quarter of its building                       brand as name
    "way/166887097",     # unnamed shop=yes, brand Tamoil, half of its building                            key=yes, brand as name
    "way/44098490",      # unnamed religion=christian, operator a parish, in the Kreuzkirche                operator, church outline
    "way/106298713",     # unnamed man_made=works, an area snapped 3 m onto a metal works                    generic tag, snapped area
    "node/4807345330",   # unnamed office=company, a unit inside the Hapimag resort (hotel)                 generic tag, unit in a hotel
    "node/13282599023",  # a faculty secretariat (office=yes), a unit inside the faculty building           key=yes, institution rule
    "node/317130576",    # unnamed sport=gymnastics inside a Turnhalle (footprint line)                     unnamed specific, outline parent
    "way/99379655",      # unnamed leisure=sports_centre snapped 25 m onto a kindergarten                   unnamed specific, snapped area
    "node/2931347280",   # Eckert & Ziegler Nuclitec (man_made=works), snapped 10 m, industrial site        named company, workplace only
    "way/763442432",     # an eye doctor's practice (amenity=doctors), an area snapped 37 m                  the far snap
    "node/7798478715",   # Tete a Tee (shop=tea), a unit inside City-Galerie Wolfsburg                       unit in a mall
    "node/3358622020",   # Rewe (shop=supermarket), a unit inside the Forum mall                             unit in a mall
    "node/3931912503",   # Rossmann (shop=chemist), a unit inside a REWE                                     chain unit in a supermarket
    "node/894579605",    # Double You (amenity=restaurant) in the Angercenter (footprint line)               outline parent
    "node/4168516251",   # a historic fountain (historic=yes, man_made=water_well) snapped 12 m             snap point, not building-bound by nature
    "node/1608226158",   # Jana's Schuh- und Schlüsseldienst (craft=locksmith;shoemaker) in a centre        multi-value tag, unit
    "way/1144215960",    # unnamed kindergarten, an area snapped onto an OSM gap building                    no cadastre line, footprint line
    "node/2168543995",   # Bücherei Calberlah (amenity=library) in a Realschule                               institution rule?
    "node/8764916644",   # Stadtteilbibliothek Westhagen (amenity=library) in a Schulzentrum                  institution rule, site
    "node/7279307085",   # Lichtblick (amenity=social_facility) in an office building                       social facility with qualifiers
    "node/329451020",    # unnamed amenity=place_of_worship, a unit inside St. Bernward                      unnamed, unit in a church
    "way/729700428",     # Cecil (shop=clothes), a unit inside Schloss-Arkaden - the longest record         mall unit, ~3,000 chars
    "way/8044561",       # MARKTKAUF (shop=supermarket) with five units inside it                            the parent of units
    "node/60149547",     # Helbing (shop=bakery), a unit inside that MARKTKAUF                               unit in a supermarket
)
# The POI prompt: LLM_SYSTEM_PROMPT rewritten for one occupant. The ALLOWED ACTIVITY
# LABELS list and the LABEL DEFINITIONS block are the building prompt's, byte for byte
# (asserted in notebook 07); Part B and the Bosserhof output are gone; the record lines,
# the procedure and the confidence tiers describe one occupant. Reviewed and confirmed
# by the user before any call; its hash tags every answer, so it is not edited once the
# full run has started.
LLM_POI_SYSTEM_PROMPT = """\
You are an activity interpreter for the occupants of buildings.

You receive ONE occupant of a building per message as a short labelled
record: a point or an area that OpenStreetMap mappers mapped in, or just
beside, the building. Whatever it is, it is the thing to label. The record
says what the occupant is and where it sits, then describes the building
around it. Each line names its source; an absent line means that source has
nothing to say. Read the lines with the weight given here:

  occupant:      the thing to label: its name in quotes, if the mapper gave
                 one, followed by its OpenStreetMap tag in brackets, written
                 key=value. The word unnamed stands where the mapper gave no
                 name; it is not a name. Where the mapper gave no name but a
                 brand or an operator, it follows the word unnamed, marked as
                 brand or operator: a brand is the chain the occupant belongs
                 to and stands for its name; an operator is the body that
                 runs the occupant and says what kind of body stands behind
                 it, not that people come here for that body's other
                 affairs. A tag written key=yes says only that the occupant
                 is of that kind and nothing more; several values of one key
                 are joined by ";" inside the bracket; further tags after a
                 comma qualify the first. This line is the strongest evidence
                 for what people come here for.
  role:          where the occupant sits: "inside the building"; "the
                 building itself" when the tag is the one on the building's
                 own OpenStreetMap outline; "a unit inside" a larger occupant
                 of the same building, given as its name and tag; or "placed
                 on the nearest building" because the mapper put it outside
                 every building outline - a point a few metres outside, or an
                 area mapped around or next to the building - with the
                 distance. The role locates the occupant. The parent of a
                 unit is another occupant: its purposes are its own, and the
                 unit shares them only under the institution rule below.
  building also inside: the other businesses, institutions and facilities
                 mapped in the same building, each written as on the
                 occupant line. When several share one tag, the tag is given
                 once with the count and the names after it, and that list
                 runs to the next entry that has its own bracketed tag. They
                 say what kind of place the building is, which matters when
                 the occupant line is generic (procedure step 3) and for the
                 institution rule. They are not the occupant: their purposes
                 are theirs, not its. When this line is absent, the occupant
                 is the only thing mapped in the building.
  building footprint: the tag OpenStreetMap mappers gave the building's own
                 outline and, introduced by "named", the name they gave it.
                 Says what kind of building this is, as the cadastre does.
  building site: the larger complex, campus or estate the building stands in,
                 as name and tag. A site named after a company or an
                 institution, or tagged as a facility, is that organisation's
                 premises. A site whose name is only that of an area, a street
                 or an estate, or that has no name, says what the ground is
                 zoned for and nothing more.
  building cadastre: the official class of the building from the German land
                 register (ALKIS) and, introduced by "named", the register's
                 own name for the building. Reliable about the kind of
                 building. The register's name describes the building as the
                 register saw it and may be older than the occupant; where it
                 contradicts the occupant line, the occupant line wins.
  building place: municipality, footprint area in square metres and height in
                 metres. Size says how large the building is, never which
                 activity the occupant serves.

Names carry world knowledge: use what you know about the chain, institution,
company or facility a name refers to, to understand the thing that carries
the name - the occupant's name, brand or operator for the occupant; a
parent's or a neighbour's name for what that neighbour is; a site's, the
outline's or the register's name for what the building is. What you know
about a neighbour or about the building never becomes a purpose of the
occupant.

The building lines say where the occupant is and what else is there. They
never add a purpose of their own: the occupant is labelled for what people
come to it for, not for what its neighbours or the building are for. The one
exception is an occupant that is the institution the building or the site
belongs to, or one of its parts - a division, a department, a hall or a
service the institution itself runs, as opposed to a separate business or
body that merely has its premises there. The building or the site belongs to
an institution when the site line, the footprint line, the register's name,
the parent on the role line or an occupant on the also-inside line is that
institution. Such an occupant serves the institution's purpose, and that
purpose is among its labels.

work is the purpose of the people employed at the occupant. Give it where
employment is what the place is for - people come to it in order to work
there - and not to every occupant because it has staff.

Your output is the set of activity labels (mid_labels): the purposes for
which people come to this occupant.

────────────────────────────────────
ACTIVITY LABELS
────────────────────────────────────

ALLOWED ACTIVITY LABELS
- work
- university
- school
- childcare
- retail_daily
- retail_non_daily
- leisure
- sports
- errands
- meetup
- lessons
- business

PROCEDURE:
1) List every distinct purpose people come to this occupant for, from the
   occupant line: its tag says what kind of place it is, its name, brand or
   operator what you know about it. One occupant can serve one purpose or
   several. The role says where it sits and adds a purpose only under the
   institution rule; the other occupants and the building add none.
2) Map each purpose to one or more labels using the definitions below and
   return every label found. A label is added only when the purpose meets
   that label's core idea; a purpose that only brushes a second label does
   not receive it. Do not collapse several purposes into one and do not stop
   at the first.
3) If the occupant line says no more than that it is a company, an office, a
   shop, a commercial or industrial building, an area zoned for industry,
   commerce or retail, or a historic object - a generic tag or key=yes, and
   no name, brand or operator you know - take the purposes such a place
   serves by its nature. The building lines may say what kind of such place
   it is, never what its neighbours are for. When the kind of place covers
   several purposes, list a label for each of them rather than choosing one.
   Every occupant receives at least one label.

────────────────────────────────────
LABEL DEFINITIONS
────────────────────────────────────

- work

Represents employment: people come here because this is their regular place of work.
Covers gainful work of every kind carried out in the building - production, crafts,
office and administration, logistics, research, services, care, teaching, operations
Describes the purpose of the people employed in the building, not the purpose of its visitors
Distinct from "business", which is a visitor's professional errand at a place that is not their own workplace
Core idea: "People come here because they are employed here."

- university

Represents tertiary/higher-level education activity.
Covers structured learning, teaching, and research at the higher education level
Involves academic instruction, research, and study environments
Distinct from general learning by its institutional and advanced nature
Core idea: “Advanced academic education and research happen here.”

- school

Represents formal compulsory or pre-tertiary education activity.
Covers structured education for children and adolescents
Includes general and vocational schooling
Defined by curriculum-based learning under institutional supervision
Core idea: “Children or teenagers receive structured education here.”

- childcare

Represents supervision and early development care for young children.
Focuses on care, supervision, and early-stage development
Not primarily academic or curriculum-driven (unlike school)
Strong emphasis on custodial and developmental support
Core idea: “Young children are cared for and supervised here.”

- retail_daily

Represents frequent, necessity-driven consumption activity.
Covers acquisition of essential, regularly needed goods
Characterized by high frequency and routine visits
Typically tied to basic living needs
Core idea: “People come here regularly to fulfill essential daily needs.”

- retail_non_daily

Represents infrequent, discretionary consumption activity.
Covers acquisition of non-essential or durable goods
Visits are planned, occasional, or need-based
Often involves comparison, browsing, or larger purchases
Core idea: “People come here occasionally to buy non-essential or long-term goods.”

- leisure

Represents hedonic, relaxation, or enjoyment-oriented activity.
Focuses on free-time use driven by pleasure, comfort, or experience
Includes passive or active enjoyment, but not primarily goal-oriented tasks
Distinguished by non-obligatory participation. People choose to go here for enjoyment, not out of necessity or obligation.
Core idea: “People come here to relax, enjoy, or spend free time.”

- sports

Represents physical activity, exercise, or bodily training.
Focuses on intentional physical exertion or fitness improvement
Can be recreational or structured, but always movement-centered
Distinguished from leisure by physical intensity and purpose
Core idea: “People come here to be physically active or train their body.”

- errands

Represents task-oriented, functional activities needed for daily life management.
Covers practical obligations or maintenance tasks
Typically short, goal-driven visits with a clear outcome
Often involves services, administration, or personal maintenance
Core idea: “People come here to complete necessary tasks or obligations.”

- meetup

Represents social interaction and gathering activity.
Focuses on interpersonal connection and shared presence
Can be informal or organized, but the primary purpose is social exchange
Not necessarily tied to consumption or formal structure
Core idea: “People come here to meet and interact with others.”

- lessons

Represents structured instruction or skill acquisition activity.
Focuses on learning guided by an instructor
Can occur at any level (formal or informal), but always organized and instructional
Distinguished from general education by activity type (learning session), not institution
Core idea: “People come here to learn something through instruction.”

- business

Represents professional or organizational interaction activity (non-routine workplace).
Covers goal-oriented professional interactions, often external-facing
Includes meetings, consulting, administrative dealings, or formal exchanges
Distinct from "work" because it reflects the visitor’s purpose, not employment
Core idea: “People come here for professional or organizational matters.”

────────────────────────────────────
OUTPUT FORMAT (STRICT JSON ONLY)
────────────────────────────────────

{
  "interpreted_type": "<plain-English description of what this occupant most likely is>",
  "mid_labels": ["<one or more activity labels from the allowed list>"],
  "confidence": "<high | medium | low>",
  "reason": "<max 80 words. Name the record lines and names you used and say why each label applies.>"
}

confidence:
- high   → the occupant line alone - its tag, or its name, brand or operator
           - tells you what it is and what people come to it for
- medium → the occupant line does not: its tag is generic and no name, brand
           or operator helps, but the building lines say what kind of place
           it is, or the institution rule applies
- low    → neither: the occupant line is generic and the building lines say
           no more than that it is a building of some class and size
"""
# Step 07.6 - the answers onto the POIs (notebook 07 section 6, on Windows only). The
# prompt hash of the full run is pinned, so a later edit of LLM_POI_SYSTEM_PROMPT cannot
# hide the answers: 7,864 valid answers, run finished 2026-10-02 00:53 on the Linux server.
LLM_POI_RUN_PROMPT_SHA = "257a72e709cb"
# Layer building_pois: the 7,864 asked POIs with their labels. Layer buildings: step 06's
# buildings, every column unchanged, plus mid_labels_merged - the building's labels and its
# asked POIs' labels, each once (decided 2026-10-01: a label clash is merged). Step 08 reads it.
POI_CLASSIFIED_FILE = OUTPUT_DIR / "07_building_pois_classified.gpkg"

# ──────────────────────────────────────────────
# STEP 08 — redistribution: the VISUM zone targets onto buildings and POIs
# ──────────────────────────────────────────────
# Each zone's target per category is shared out over the units in that zone that carry
# the category, in proportion to their weight; a building's value is the sum of its units.
# Decided with the user 2026-10-02; the size measure, the labels and the shares revised on
# 2026-10-05:
#   * units: a building without asked POIs is one unit with its step-06 labels (sole
#     occupants, buildings without own POIs). In a building with asked POIs (step 07) every
#     asked POI is a unit under its own labels, Workers included;
#   * every unit weighs the floor area it occupies, O (2026-10-05: the Bosserhof rates are
#     workers per 100 m2 of floor area, BUG-04 of the previous pipeline; volume before):
#     Workers O x BOSSERHOF_WEIGHTS[class], each other zone category O / k_red, k_red the
#     unit's redistributed non-work labels. O follows from the floor area (footprint x
#     storeys) and the rules per class in the block "Step 08 on occupied floor area" below -
#     a shop under flats takes the ground floor, a hall is one storey, a main occupant takes
#     what the tenants leave;
#   * a label the building's step-06 labels carry but none of its asked POIs does stays as a
#     "rest" unit on the floor its POIs leave free (at most the floor its class rule gives a sole
#     occupant; one average occupant's share where the POIs fill it; 2026-10-06), split over the
#     building's labels (REDIST_KEEP_UNCOVERED_BUILDING_CATEGORIES; the user chose to keep all);
#   * the labels of steps 06 and 07 are reconciled by OSM use; a Retail or Leisure rest label whose
#     evident source is an active asked POI that step 07 labelled otherwise goes, and a label taken off
#     a POI does not come back as a rest unit (LABEL_RULES; the user, 2026-10-08);
#   * the remaining items of the audit of run 7 - staff catering, OSM-only storeys, the visitor rates,
#     the sizes of POI units, the Workers-0 rules and factors, the leftovers - at the end of the block
#     "Step 08 on occupied floor area" (the user, 2026-10-09);
#   * round 16 - big low office boxes, the sizes of single tenants by format, the published retail floor
#     of 7 malls, the labels the rules use in the file - after them; staff shops, the meetup of audience
#     venues net of their Leisure share and heritage POIs as keys of STAFF_CATERING_RULES and
#     VISITOR_RULES (round 16, 2026-10-09, on the user's behalf);
#   * round 17 - sport halls and studios one storey where only the height gave more and the places
#     known to be closed after them; the hall evidence of the big low office boxes in FLOOR_OFFICE_BOX
#     (their halls in CLASS_FIX_BUILDINGS); the OSM signs of non-use in the vacancy block below (round
#     17, 2026-10-09, on the user's behalf);
#   * site rows give no unit (share_of_site is an audit column). A landuse pair no longer
#     holds floor: the shares are re-split over the asked POIs (2026-10-05, reversing the
#     2026-10-01/02 rule under which 216 shared buildings kept less than their full volume);
#     a vacant pair keeps its empty slot;
#   * a zone with a target but no carrier widens ring by ring through the zones that touch
#     it until carriers are found; the ring is pooled and listed in notebook 08;
#   * a building's zone is the zone holding its representative point; buildings in no zone
#     (226, mostly outside the study area) get nothing;
#   * vacant places get nothing (REDIST_EXCLUDE_VACANT, below).
ZONE_TARGETS_FILE = INPUT_DIR / "zone_targets.gpkg"
ZONE_LAYER = "regionbsstructuredata_zone"       # VISUM structure data; ZONE_COLUMN_MAP fits this layer only
ZONE_ID_COL = "NO"                              # the VISUM zone number, unique
# The seven target categories: a zone column, or the sum of several (missing values count
# as 0). From the previous pipeline (54629cb), unchanged. Leisure SG_6_FR~23 equals
# SG_6_FR~22 + SG_6_FR~24 in every zone; the six other SG_6_* / SG_7_* columns (BE~20, BE~21,
# GE~25, PR~26, SONST, AN~27: 10,378 in total, meaning not documented) are not used.
ZONE_COLUMN_MAP = {
    "Workers":          "SG_3_BE~17",
    "School":           ["SG_4_BS", "SG_4_GSCH", "SG_4_WFSCH"],
    "University":       "SG_4_HS",
    "Kindergarten":     "SG_4_KITA",
    "Retail_Daily":     "SG_5_EK_TB",
    "Retail_Non-Daily": "SG_5_EK~19",
    "Leisure":          "SG_6_FR~23",
}
# MiD label -> target category. Labels are never merged (the user, 2026-10-05: "dont merge any
# label"): only the seven labels with a VISUM zone total are redistributed. Until then business
# counted as Workers, errands as Retail_Daily and sports / meetup / lessons as Leisure (54629cb).
# Errands no longer feeds Retail_Daily - in run 1, 57 % of Retail_Daily rested on errands alone,
# and pharmacies, banks and post counters labelled only errands lose it too (pharmacies carry it by
# their own use since 2026-10-08, LABEL_RULES); at the time 34 zones lost their only Retail_Daily
# carriers (7,231, 0.8 %; 32 zones and 7,111 in run 14), which go to the ring fallback. Leisure comes only
# from the leisure label (46 % of it sat on units whose only Leisure came from sports, meetup or
# lessons: churches, sports halls, clubs). The VISUM Leisure column stays SG_6_FR~23 (= FR~22 +
# FR~24, whose meaning is unknown; the user, 2026-10-05).
MID_LABEL_TO_ACTIVITY = {
    "work":             "Workers",
    "school":           "School",
    "university":       "University",
    "childcare":        "Kindergarten",
    "retail_daily":     "Retail_Daily",
    "retail_non_daily": "Retail_Non-Daily",
    "leisure":          "Leisure",
}
# The five labels without a zone total (the user, 2026-10-05): never redistributed, they feed no
# category. Each gets an area - the unit's occupied area O / k_all, k_all = ALL the unit's
# non-work labels (redistributed or not), so that no area is counted twice; on a rest unit the
# building's labels - and later an absolute value, area x a visitor rate (VISITOR_RATES), "the
# area x density value from Bosserhof ... so no redistribution in such case".
REDIST_AREA_LABELS = ("business", "errands", "sports", "meetup", "lessons")
# The visitor rates of these labels: VISITOR_RATE_ANCHORS and the lookup tables in the block "Step 08
# on occupied floor area" below (agreed by the user, 2026-10-06).
# Workers factor per Bosserhof class (54629cb, with its added "retail wholesale"): workers per
# 100 m2 of floor area, the midpoint of the range in the previous pipeline's source table
# (Final-data-processing; 54629cb mislabelled it "per 100 m3 of building volume"). Used as a
# relative weight inside a zone - occupied floor area x factor - so only the ratios matter; the
# zone target sets the number. Three rates fixed by the user on 2026-10-05 against their
# sources, with the headline means that contain them:
#   * vehicle / electrical repair 2.0 -> 2.5: 30-60 m2 per employee = 1.67-3.33 per 100 m2;
#   * nursing homes 0.62 -> 1.25: 0.45-0.80 was staff per place, not per 100 m2 (FGSV 1.0-1.5);
#   * retail small scale 3.75 -> 3.5: 20-50 m2 per employee = 2.0-5.0 per 100 m2;
#   * services 2.31 -> 2.36, public facilities 1.2 -> 1.30, retail 1.75 -> 1.725: the means of the
#     same 11, 6 and 10 subclass rows with the fixed values.
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
    "vehicle electrical repair":        2.5,
    "customer service":                 3.3,
    "car dealerships":                  0.7,
    "wholesale":                        2.45,
    "retail small scale":               3.5,
    "discount stores":                  0.9,
    "diy stores":                       0.75,
    "furniture stores":                 0.55,
    "hypermarkets superstores":         1.2,
    "shopping centers":                 3.1,
    "self service department stores":   1.1,
    "department stores":                1.55,
    "factory outlet centers":           2.15,
    "retail wholesale":                 2.1,
    "schools":                          1.0,
    "universities":                     0.75,
    "research institutes":              1.25,
    "kindergartens":                    2.3,
    "hospitals":                        1.25,
    "nursing homes":                    1.25,
    "entertainment culture":            1.67,
    "large cinemas":                    0.83,
    "musical theatres":                 1.43,
    "large discos fun leisure pools":   0.8,
    "arenas large events":              1.43,
    "theme parks":                      1.67,
    "fitness wellness":                 0.8,
    "industrial operations production": 1.35,
    "crafts and trades":                1.88,
    "services":                         2.36,
    "retail":                           1.725,
    "public facilities":                1.30,
    "facilities for culture leisure and sports": 1.23,
}
# The step-05 class names are normalised before the lookup - lower case, every run of
# non-letters to one space - then mapped by this table (54629cb, unchanged; for the step-05
# classes only "others" needs it).
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
REDIST_WORKERS_WEIGHT = "floor_x_bosserhof"     # or "floor": occupied floor area x factor (2026-10-02 on volume, floor area since 2026-10-05)
REDIST_KEEP_UNCOVERED_BUILDING_CATEGORIES = True  # the rest units above (decided 2026-10-02: keep all)
REDIST_MULTI_CATEGORY_SPLIT = "even"            # O / k_red over the redistributed labels ("separate splits", the user, 2026-10-05), or "full": O each
# Vacancy (the user, 2026-10-02; widened 2026-10-05): a place with a clear sign that nobody is
# there gets no part of any target - it gives no unit at all (lib/vacancy.py):
#   * a POI: tagged shop=vacant or office=vacant (whatever else it carries), poi_use in
#     VACANCY_POI_USES (vacant; ruins - the user counts every ruin as vacant), its own tags
#     matching VACANCY_POI_TAG_PATTERN (disused / abandoned / vacant = yes, ruins), named
#     "Leerstand" / "zu vermieten", or its step-07 type (poi_type) says so (the text rule below);
#   * a building: it has own POIs and ALL of them carry such a sign; or an OSM building polygon
#     with a vacancy tag (building=ruins / abandoned / disused / vacant / collapsed / destroyed,
#     disused / abandoned / vacant = yes, ruins, abandoned:building / disused:building = yes - any
#     value until run 16 -,
#     shop / office = vacant) covers at least VACANCY_POLYGON_MIN_COVER of its footprint and no
#     active POI is inside (the user, 2026-10-05: with an active POI inside the building keeps
#     it and is listed for review); or its step-05 type (llm_type) says so;
#   * the text rule: vacant, unoccupied, abandoned, disused, derelict, currently / permanently
#     closed, ruin(s/ed), burnt-out, out of use / service, no longer in use - but not a place
#     "with a few vacant units" (partly vacant).
# A shared building whose other tenants are active keeps them (the user, 2026-10-05): the vacant
# unit's share carries nothing, the active tenants keep theirs. Run 1 with the first rule: 74
# buildings and 1 asked POI, about 7,900 of the placed demand; the building polygons' own tags
# were not read then (63 weighted buildings under such a polygon, 17,265 of the demand).
# The OSM signs of non-use (round 17, 2026-10-09, on the user's behalf; the user: "if there is a
# tag letting you know that it's empty, vacant, unused or anything like that then respect OSM
# tags"; VACANCY_OSM_SIGNS, lib/vacancy.osm_signs), each class checked against the live OSM history
# of all 266 such objects on model buildings and about 30 places on the web:
#   * a building under works or gone - building=construction (where it says what is built,
#     construction=*, or was checked, check_date: a bare outline can be years old), demolished,
#     razed, removed - whatever else the object carries (the Stadthalle Braunschweig, the
#     demolished real store at Wolfsburg-Nordsteimke);
#   * a lifecycle prefix on a use key (disused:shop=*, was:amenity=*, abandoned:office=* ...) only
#     where the object has no active primary tag: with one it records a former use of a place
#     active today (the pub tagged disused:shop=supermarket, 2026-10-05); the gone prefixes on
#     building (demolished:building=* ...) on the same terms; disused / abandoned:building only as
#     =yes (a value naming a former building type - train_station - is no sign);
#   * opening_hours closed / off / no / geschlossen / temporarily closed (the whole value, also after
#     Mo-Su, PH or 24/7: closed now), not on a workshop (no public hours);
#   * an end_date before the day of the check, without an active primary tag;
#   * a name, note, description or fixme saying it for good: 'dauerhaft geschlossen', 'Leerstand',
#     'steht leer', 'closed since' ... - not a weekly closing day, a dated closure, a question, a
#     negation or a part of the building (a flat, a floor); 'ehemals' / 'former' tell a building's
#     history, not its use;
#   * shop=no without another active primary tag, not at a fuel station (there it means no shop).
# A building that only such a sign leaves empty keeps its units where it lies on the named site of
# an active occupant (GONE_BUILDINGS' exception) and is listed for review, like a building with an
# active POI under a tagged polygon. An OSM object whose sign a dated source contradicts gives no
# sign ('stale_ids': Netto Hillerse, open again since 2025-12-09; the Wolfsburg library Nordstadt,
# open on Thursdays). Alone against run 16 (before the stale ids): 113 buildings and 16 asked POIs
# give no unit and one comes back (a ski club under a former station,
# abandoned:building=train_station); Workers 2,579 (0.44 %), Retail_Daily 11,916 (1.31 %),
# Retail_Non-Daily 2,927 and Leisure 891 move.
REDIST_EXCLUDE_VACANT = True
VACANCY_POI_USES = frozenset({"vacant", "ruins"})
VACANCY_NAME_PATTERN = r"\bleerstand\b|\bzu vermieten\b"
VACANCY_POI_TAG_PATTERN = r'"(?:disused|abandoned|vacant)"\s*:\s*"yes"|"ruins"\s*:\s*"(?!no")[^"]+"'
VACANCY_TEXT_PATTERN = (r"\b(?:vacant|unoccupied|abandoned|disused|derelict)\b|\b(?:currently|permanently) closed\b"
                        r"|\bruin(?:s|ed)?\b|\b(?:burnt|burned)[- ]out\b|\bout of (?:use|service)\b|\bno longer in use\b")
VACANCY_PARTIAL_PATTERN = r"\bwith (?:a few|some|several|two|three|four|\d+) vacant\b"
VACANCY_BUILDING_VALUES = frozenset({"ruins", "abandoned", "disused", "vacant", "collapsed", "destroyed"})
VACANCY_BUILDING_TAG_PATTERN = (r'"(?:disused|abandoned|vacant)"\s*:\s*"yes"|"ruins"\s*:\s*"(?!no")[^"]+"'
                                r'|"(?:disused|abandoned):building"\s*:\s*"yes"')   # =yes only (round 17)
VACANCY_POLYGON_MIN_COVER = 0.5                 # share of the building's footprint under the tagged OSM polygon(s)
# the OSM signs of non-use read since round 17 (the comment above; lib/vacancy.osm_signs):
VACANCY_OSM_SIGNS = {
    "lifecycle_prefixes": ["disused", "abandoned", "was", "demolished", "razed", "removed", "destroyed"],   # a lifecycle prefix ...
    # ... on a use key, where the object has no active primary tag
    "lifecycle_keys": ["shop", "amenity", "office", "leisure", "craft", "healthcare", "tourism", "club", "power", "military"],
    "gone_prefixes": ["demolished", "razed", "removed", "destroyed"],   # <prefix>:building=* - the building itself is gone
    "building_yes_prefixes": ["disused", "abandoned"],   # disused / abandoned:building=yes - the building is unused
    # the primary tags (the use keys of the lifecycle prefixes) ...
    "active_keys": ["shop", "amenity", "office", "leisure", "craft", "healthcare", "tourism", "club", "power", "military"],
    "inactive_values": ["vacant", "no", "empty", "closed", "disused", "abandoned", "none"],   # ... and the values that make one no active tag
    "works_values": ["construction", "demolished", "razed", "removed"],   # building=* under works or gone
    "construction_needs_detail": True,              # a bare building=construction outline can be years old
    "opening_hours_pattern": (r"^\s*(?:(?:mo-su|ph\s*,\s*mo-su|mo-su\s*,\s*ph|24/7)\s+)?(?:off|closed|geschlossen|no"
                              r"|temporarily closed)\s*$"),   # the whole value: closed now
    "opening_hours_exempt_keys": ["craft"],         # a workshop: 'off' means no public opening hours
    "end_date_before": "2026-10-09",                # an end_date before this day, without an active primary tag
    "note_keys": ["name", "note", "note:de", "description", "description:de", "fixme", "FIXME"],   # texts saying it for good ...
    "note_pattern": (r"dauerhaft\s+geschlossen|endgültig\s+geschlossen|permanently\s+closed|closed\s+since"
                     r"|closed\s+(?:at\s+the\s+)?end\s+of|seit\s+(?:dem\s+)?\d[\d.]*\s+geschlossen"
                     r"|(?<![a-zäöüß])leerstand(?![a-zäöüß])|(?<![a-zäöüß])leerstehend|steht\s+leer|zurzeit\s+leer|derzeit\s+leer"),
    # ... but not a question, a dated closure, a reopening, a negation or a part of the building (a flat, a floor)
    "note_exclude_pattern": (r"\?|(?<![a-zäöüß])bis(?![a-zäöüß])|wiedereröffn|wieder\s+geöffnet"
                             r"|(?<![a-zäöüß])(?:kein|keine|nicht|not|no)\s+(?:mehr\s+|more\s+|longer\s+)?(?:leerstand|leer|dauerhaft"
                             r"|endgültig|permanently)|(?<![a-zäöüß])wohnung|(?<![a-zäöüß])\d+\.?\s*og(?![a-zäöüß])|(?<![a-zäöüß])etage"
                             r"|teilweise|partly|partially"),
    "note_on_polygons": True,                       # False: a note on a building outline is not read (option A2)
    "shop_no": True,                                # shop=no without an active primary tag, not at a fuel station
    "keep_named_site": True,                        # GONE_BUILDINGS' exception: a building on the named site of an active occupant stays
    # OSM objects whose sign a dated source contradicts (the place is in use): no sign is read from them; drop an entry once
    # step 01 is re-extracted after the object was fixed
    "stale_ids": {
        "way/59551753": ("Netto Hillerse (Schier-Raehmen-Weg): the new store opened on 2025-12-09 "
                         "(https://www.neueroeffnung.info/hillerse/netto-markendiscount_2853, update of 2025-11-25; the Samtgemeinde "
                         "Meinersen: demolition for the new build from 2025-06-16; seen 2026-10-09); OSM still says building=construction, "
                         "opening_hours=temporarily closed"),
        "node/703484396": ("Stadtteilbibliothek Nordstadt, Hansaplatz 17, Wolfsburg: open on Thursdays 10-12:30 and 15-17:30, run by "
                           "volunteers (https://www.bildungshaus-wolfsburg.de/oeffnungszeiten-standorte/, seen 2026-10-09); OSM "
                           "opening_hours=off since 2024-07-06"),
    },
}
# --- Step 08 on occupied floor area: the rules per class (the user, 2026-10-05) -----------------
# Every unit weighs the floor area it occupies, O, instead of the building's volume x share:
# Workers O x factor, a redistributed label O / k_red. O starts from the building's floor area
# FA = footprint A x storeys N and follows the rules below (lib/floor_rules.py): the storeys of
# the building (the 08b height rule with its halls, plus the structure rules), whether it has
# dwellings (the residential context RC), and per occupant a floor family - a shop under flats
# takes the ground floor, an office flat one storey, a main occupant what the others leave.
# Decided with the user on 2026-10-05 from the evidence of seven analysts, a synthesis and a
# stress test, and from the colleague's Stage 5-8 rules (VISUM-quality-analysis, all 13 rule
# counts reproduce on our data).

# Floors that no unit occupies in a building WITHOUT dwellings - the upper floors above a shop
# that keeps one floor, a Kita's third storey, the floors a capped point leaves - become one
# Workers-only "remainder" unit (the unmapped upper-floor tenants) at the normal-office factor
# (the user, 2026-10-05; the building's own factor would count offices above a shop at the
# retail rate). It is formed after the hall and box checks, never from a vacant slot and never
# where an ALL unit takes the floor. With dwellings the free floors are flats and carry nothing.
# The office factor holds in shop and office buildings (REDIST_REMAINDER_OFFICE_CLASSES); in any other
# building - a hospital, a Kita, a school, a museum, a gym - the free floor is the building's own main
# use and carries its own factor (the user, 2026-10-06: a hospital's 52,213 m2 of free floor at 2.9
# instead of 1.25 doubled the Workers weight of about 200 such buildings).
REDIST_REMAINDER_WORKERS_FACTOR = 2.9
REDIST_REMAINDER_OFFICE_CLASSES = frozenset({"retail (small-scale)", "Retail", "restaurants / gastronomy", "customer-oriented services",
                                             "customer service", "Services", "business-oriented services", "normal office",
                                             "open-plan office"})

# The storeys: the decided 08b rule (STEP 08b: eaves height capped at the mean height, 3.5 m,
# halls one storey, OSM building:levels over both) and then these structure rules, in this
# order, where OSM building:levels is not mapped (parking also where it is):
#   * a hall class whose head says residential / mixed use: one storey (the flats carry nothing);
#   * a hall word before the office word ("Workshop and office of X", "Office and warehouse"):
#     one storey; "Office building in an industrial estate", "Factory site office building" and
#     "Administrative villa serving the factory" stay;
#   * the crafts classes: never above one storey;
#   * storeyed company uses on factory sites (high-rise, training centre, R&D, laboratory, social
#     building, occupational health): storeys by height, not a hall (Konstruktionshochhaus 1 ->
#     11); canteen buildings there at most FLOOR_CANTEEN_MAX_STOREYS;
#   * worship buildings, fire and rescue stations (not professional ones or office heads), sports
#     halls / pools / riding halls ("gymnasium" only with a sport word or class, 132 German
#     Gymnasium schools otherwise), hangars, wind tunnels, auditoria and towers (not office,
#     residential, hotel or cooling towers, tower blocks or church towers): one storey;
#   * parking garages and decks (ALKIS 2461/2462, OSM building=parking, a parking head): one
#     storey, over OSM levels too (5 of 11 had levels 4-6);
#   * cinemas at most FLOOR_CINEMA_MAX_STOREYS; 'factory outlet' and small-shop brand words
#     (Jacques' Wein-Depot, Games Workshop) no longer make a hall - a brand word only where the
#     hall word of the type also stands in the building's name or a POI name, so that a
#     "Commercial hall housing a greengrocer and a copy shop" stays a hall; IKEA
#     FLOOR_IKEA_STOREYS;
#   * the multi-level furniture houses (the user, 2026-10-05): storeys by height, at most 4;
#   * single-level boxes outside the hall classes (the user, 2026-10-05): one storey;
#   * one storey where only the height gave more (the user, 2026-10-08; FLOOR_ONE_STOREY_RULES):
#     low shops and restaurants, shops with store evidence, low shop boxes, farm halls filed as
#     shops or restaurants, station shops and fuel-station canopies;
#   * department stores and shopping centres count 4.5 m storeys (the user, 2026-10-05);
#   * malls take their mapped levels, else at most 3 (FLOOR_MALL_*); outlets at most 2.
# Not adopted: a 5 m storey for museums, the deep-plan office test, HALL over OSM levels, and
# the colleague's mean height, h / 3.8, 4-storey cap and >= 10,000 m2 rule.
# The type words, read in the head of the step-05 type (the text before "with", "housing", a
# comma ... - HALL_TYPE_HEAD_SPLIT) unless FLOOR_FULL_TYPE_KEYS names them; from the synthesis,
# with the stress-test fix that a bare "Dom" no longer makes a church ("Centrum am Dom" mall):
FLOOR_TYPE_PATTERNS = {
    "worship":        r"\b(?:church|chapel|cathedral|minster|mosque|synagogue|kingdom hall|temple|mourning hall|funeral hall|kirche|kapelle)",
    "worship_excl":   (r"\b(?:parish (?:office|house|hall|centre|center|home)|community (?:centre|center|hall|house)|offices?|school|nursery"
                       r"|kindergarten|daycare|housing|residential|apartments?|rectory|parsonage|pfarrhaus|gemeindehaus|kita|monastery|convent)\b"),
    "fire":           r"\bfire[- ]?(?:station|brigade|department|service)|\bfeuerwehr|\bfeuerwache|\brescue station|\bambulance station|\brettungswache",
    "fire_prof":      r"\bprofessional fire|berufsfeuerwehr|\bmain fire station|hauptfeuerwache|fire and rescue (?:centre|center)",
    "tower":          r"\btowers?\b|\bturm\b",
    "tower_excl":     r"\b(?:office|residential|apartments?|tower block|high[- ]rise|hotel|church|cooling)\b",
    "parking":        r"\bparking (?:garage|deck|structure|facility|building)|multi[- ]stor(?:e)?y car park|\bcar park\b|\bparkhaus\b|\bparkdeck\b",
    "cinema":         r"\bcinema|multiplex|\bkino\b|filmpalast|movie theat",
    "museum":         r"museum",
    "sports_hall":    (r"\bsports? halls?\b|\bgym(?:nastics)? halls?\b|\bturnhalle|\bsporthalle|\btennis ?halls?\b|tennishalle|\briding (?:hall|arena)"
                       r"|\bindoor (?:riding|arena|tennis|sports)|reithalle|\bice (?:rink|arena|stadium|hall)|eissporthalle|\bclimbing hall"
                       r"|\bbouldering hall|\bshooting hall|\bkart(?:ing)? hall|\bmulti[- ]purpose hall|\bevent hall|\bexhibition hall|\bfestival hall"),
    "gym_word":       r"\bgymnasium\b",
    "gym_sport":      r"sport|school gymnasium|indoor",
    "pool":           r"\bswimming (?:pool|bath|hall)|\bindoor (?:pool|swimming)|\bhallenbad|\bleisure pool|\bwater park|\bthermal bath|\baquatic",
    "hangar":         r"\bhangars?\b|\bwind tunnel",
    "auditorium":     r"\bauditorium|\baudimax",
    "canteen":        r"\bcanteen|\bmensa\b|\bcafeteria|\bstaff restaurant|\bdining hall|\bbetriebsrestaurant",
    "storeyed_co":    (r"\bhigh[- ]rise|\bhochhaus|\btraining (?:centre|center|academy)|\bacademy\b|\bR&D\b|\bresearch (?:and development )?"
                       r"(?:centre|center|building)|\blaborator(?:y|ies)\b|\bsocial (?:building|facilities)|\bworks council|\boccupational health"),
    "office_any":     r"\boffices?\b|\bheadquarters\b|\badministrat\w*",
    "town_hall":      r"\b(?:town|city)\s+halls?\b",
    "res_head":       r"\b(?:residential|apartments?|dwellings?|mixed\W?use)\b",
    "factory_outlet": r"factory[- ]outlet",
    # student dormitories only (2026-10-06): not nurses', staff, boarding-school or Lebenshilfe homes, children's homes,
    # or a coworking office in a student dormitory - the head must name the student dormitory
    "dorm":           (r"^\W*(?:(?:a|an|the)\s+)?(?:university\s+)?(?:students?|studenten|studierenden)(?:\s+(?:accommodation|apartments?))?"
                       r"\s*(?:dormitor\w*|residence|housing|hall|accommodation|apartments?|wohnheim)|^\W*studenten(?:wohnheim|apartments?)"),
    "small_school":   (r"\bdriving school|\bmusic school|\bart school|\btutoring|\badult education|\bvolkshochschule|\blanguage school|\bdance school"
                       r"|\bdancing school|\bnachhilfe|\bmusikschule|\bfahrschule"),
    "small_unit":     (r"\bcommunity (?:centre|center|room|hall)|\bclub ?(?:room|house|home)|\bclubhouse|\byouth (?:centre|center|club)|\bfraternity"
                       r"|\bstudent association|\barcade|\bcasino|\bgaming|\blibrary branch|\bgallery|\bmusic school|\bassociation"),
    "gym_studio":     r"\bgym\b|\bfitness|\bdance|\byoga|\bstudio|\bmartial|\bsauna|\bpilates|\bcrossfit|\bboxing|\bkarate|\bjudo|\bdojo",
    "public_office":  r"\bparish office|\bpfarramt|\bcounsel|\badvice|\bberatung|\boffices?\b|\bagency\b",
    "care":           r"nursing|care home|residential care|senior|assisted[- ]living|altenheim|pflege|refugee|asylum|youth (?:home|welfare)|children.s home",
    "pure_home":      (r"^(?:\W*(?:a|an|the)\s+)?(?:private\s+|small\s+|single[- ]family\s+|two[- ]family\s+|detached\s+|semi[- ]detached\s+)*"
                       r"(?:residential (?:building|house|home)|house|home|dwelling|apartment building|residential apartment building)\b"),
    "pure_home_excl": (r"ground[- ]floor|shop|store|office|practice|restaurant|caf[eé]|business|commercial|trade|services|workshop|mixed|church|club"
                       r"|school|kindergarten|hotel|guest|holiday"),
    "small_attraction": r"trampoline|adventure hall|\btent\b|kiosk",
}
FLOOR_FULL_TYPE_KEYS = ("care", "pure_home_excl")
# ALKIS building functions (31001_xxxx) the structure rules read.
FLOOR_ALKIS_CODES = {
    "worship":     frozenset({3041, 3042, 3043, 3045, 3046, 3047, 3081}),
    "fire":        frozenset({3072}),
    "sports_hall": frozenset({3211, 3221, 2728}),
    "parking":     frozenset({2461, 2462}),
}
# The class lists of the structure rules: crafts never above one storey; storeyed company uses
# and canteens on the sites of these industry classes; "gymnasium" makes a sports hall in these
# sport classes; IKEA in these classes; brand words no longer make a hall in these.
FLOOR_CRAFT_CLASSES = frozenset({"Crafts and trades", "craft businesses"})
FLOOR_INDUSTRY_CLASSES = frozenset({
    "Transport", "Industrial operations / Production", "highly productive industries / machine / material or space intensive",
    "others", "Yards, depots, storage areas, construction yards", "craft courtyards"})
FLOOR_SPORT_CLASSES = frozenset({"fitness / wellness", "Facilities for culture, leisure and sports", "large discos, fun / leisure pools",
                                 "arenas, large events"})
FLOOR_IKEA_CLASSES = frozenset({"hypermarkets / superstores", "furniture stores"})
FLOOR_BRAND_UNHALL_CLASSES = frozenset({"retail (small-scale)", "Retail"})
# "Workshop and office of X": the hall word must come before the first location word, and a
# hall word that only qualifies a site ("factory site", "factory premises") is no hall word;
# "serving" counts as a location word ("Administrative villa serving the H. Butting factory").
FLOOR_LOCATION_SPLIT = r"\s+(?:in|on|at|within|of|for|serving)\s+"
FLOOR_HALL_SITE_PATTERN = r"\b(?:halls?|warehouses?|factory|factories|workshops?|depots?)\s+(?:site|premises|grounds|campus|compound)\b"
FLOOR_CANTEEN_MAX_STOREYS = 2
FLOOR_CINEMA_MAX_STOREYS = 2                    # CinemaxX 6 -> 2
# IKEA (in the name, a POI name or the type; a hypermarket or furniture class, no logistics,
# warehouse or distribution type): IKEA Braunschweig has two sales levels.
FLOOR_IKEA_PATTERN = r"\bIKEA\b"
FLOOR_IKEA_EXCLUDE_PATTERN = r"logistic|warehouse|distribution"
FLOOR_IKEA_STOREYS = 2
# Multi-level furniture houses (the user, 2026-10-05): a furniture store with eaves of at least
# 12.25 m and a footprint of at least 2,000 m2, never a warehouse, Abhollager or hall (in the
# type) and no "Halle" / "Abhol" in its name, counts its storeys by height, at most 4. These
# are 9 houses (XXXLutz x5, Porta, POCO, Roller; 1.7 % of Retail_Non-Daily in the synthesis).
FLOOR_FURNITURE_HOUSE_MIN_EAVES_M = 12.25
FLOOR_FURNITURE_HOUSE_MIN_FOOTPRINT_M2 = 2000
FLOOR_FURNITURE_HOUSE_MAX_STOREYS = 4
FLOOR_FURNITURE_HOUSE_EXCLUDE_TYPE = r"warehouse|abhollager|\bhall"
FLOOR_FURNITURE_HOUSE_EXCLUDE_NAME = r"halle|abhol"
# Single-level boxes (the user, 2026-10-05; the stress test found 79 that kept 2-3 storeys only
# because eaves of 5-9 m round to 2): a building of one of these classes without dwellings, of
# at least 1,500 m2, eaves at most 12.5 m, no own POI on level 1 or above, whose type (the whole
# type) names a supermarket, discounter, indoor sport or market hall, counts one storey; so does
# a shopping centre with eaves below 9 m and no POI above level 0. Since 2026-10-08 the words are
# read plural-safe (audit item 2: 'two supermarkets', EDEKA + ALDI Ehmen, and 2 more were missed;
# 2 shopping centres the mall rule set to one storey anyway now count as boxes); 'sports hall'
# stays singular (a sheltered workshop 'with sports halls' is no box).
FLOOR_BOX_CLASSES = frozenset({
    "retail (small-scale)", "Retail", "shopping centers", "fitness / wellness", "Facilities for culture, leisure and sports",
    "entertainment, culture", "Services", "customer-oriented services", "restaurants / gastronomy"})
FLOOR_BOX_TYPE_PATTERN = (r"\b(?:supermarkets?|discount\w*|hypermarkets?|cash and carry|kart\w*|soccer"
                          r"|indoor (?:arena|play|sports?|playground)s?|trampoline|bowling|laser ?tag|climbing|bouldering|paintball"
                          r"|likely a sports hall|sports hall|market halls?|garden cent(?:re|er)s?|beverage (?:stores?|markets?)"
                          r"|getr[aä]nkem[aä]rkte?)\b")
FLOOR_BOX_MIN_FOOTPRINT_M2 = 1500
FLOOR_BOX_MAX_EAVES_M = 12.5
FLOOR_MALL_BOX_MAX_EAVES_M = 9.0
# One storey where only the height says more (the user, 2026-10-08; item 2 of the audit of run 7). The 08b rule counts one
# storey per 3.5 m, so a one-level shop of 5.25-8.75 m counts 2-3 storeys and the floor nobody uses becomes a Workers-only
# remainder: run 10c had 1,700 such remainders with 34,023 W. Where OSM records the levels of shops and restaurants, they are
# one storey in 88-94 % of cases at 5.25-6.0 m, 76 % at 6.0-6.5 m and only about 41 % at 6.5-8.75 m. The user chose:
#   "Below 6.5 m": shops and restaurants without flats count one storey below 6.5 m (and wherever every OSM outline with levels
#     says 1), unless a practice, office, school, Kita or hotel sits in them, their type names upper floors, flats or offices, or
#     residential outlines cover them - 52 of 55 such buildings with OSM levels are one storey; this holds for a branch of a
#     MULTI_LEVEL_CHAINS chain too (two Deichmann buildings: their two floors become the one);
#   "Store evidence + farm halls": shops of 800 m2 or more with store words, a box chain or a box shop tag (eaves up to 8.75 m,
#     9 m from 1,500 m2), shops of 1,000 m2 or more with eaves below 7 m, and shops or restaurants under an OSM barn, shed,
#     greenhouse or roof outline or with an ALKIS farm, depot or car-wash function; the box words of the decided box rule are read
#     plural-safe ('supermarkets': EDEKA + ALDI Ehmen). OSM 'industrial' or 'warehouse' outlines are no evidence (an independent
#     check: such buildings are one storey as rarely as shops are), and the four big halls typed as shops or restaurants
#     (Anssems, VW Halle 31, tankpool24, Stanze Stahl) wait for a fix of their class ("Leave for a class fix");
#   "Shop carries the canopy": fuel-station canopies count one storey wherever OSM gives no levels and form no remainder; the
#     station shop within 15 m takes the canopy's labels and the canopy no unit (Hoyer: the canopy roof held 968 Retail_Daily,
#     95 % of its zone; its cafe now takes 771, the zone's other shops the rest); station shops (ALKIS 2130) count one storey.
# Against run 11: 574 buildings change storeys and 7,179 W move (1.2 %), Retail_Daily 7,093 (0.8 %), Retail_Non-Daily 1,122,
# Leisure 65; remainder W 34,023 -> 27,246; errands -383, business -22, sports -158 (the gym in an Action / Takko box).
FLOOR_ONE_STOREY_RULES = {
    "shop_classes": ["retail (small-scale)", "Retail"],
    "restaurant_classes": ["restaurants / gastronomy"],
    "service_classes": ["customer-oriented services", "customer service", "Services"],
    # OSM outlines: twin, cover or part at role_min; outlines over outline_min_share of the footprint must all say 1 and cover
    # osm_min_cover together; 2 levels over two_min_share of it keep the storeys; a service building (its own unit halves)
    # also needs a level-1 twin or part over osm_min_cover, no roof:levels and a height below osm_service_max_height_m
    "role_min": 0.5,
    "outline_min_share": 0.10,
    "two_min_share": 0.2,
    "osm_min_cover": 0.5,
    "osm_service_max_height_m": 7.5,
    # low_shop
    "low_max_height_m": 6.5,
    "upstairs_groups": ["health_practice", "office", "public_office", "small_school", "childcare", "hotel"],
    "storeyed_pattern": (r"medical cent(?:re|er)|[aä]rzte|health cent(?:re|er)|practices|(?<!post )\boffices?\b|administrat|mixed[- ]use"
                         r"|hotel|guest ?house|gasthaus|gasthof|\bpension\b|\binn\b|residential|apartments?|\bflats?\b|dwellings?"
                         r"|upper[- ]floors?|upstairs|storey"),
    "res_outline_tags": ["apartments", "residential", "house", "detached", "semidetached_house", "terrace", "farm", "bungalow",
                         "dormitory"],
    "res_outline_min_share": 0.2,
    # box_evidence / box_low (shops only; never with an own POI that usually sits upstairs, a gym included)
    "box_type_pattern": (r"\b(?:supermarkets?|discount\w*|hypermarkets?|cash and carry|kart\w*|soccer|indoor (?:arenas?|play\w*|sports?)"
                         r"|trampolines?|bowling|laser ?tag|climbing|bouldering|paintball|likely a sports hall|sports halls?|market halls?"
                         r"|garden cent(?:re|er)s?|beverage (?:stores?|markets?)|getr[aä]nkem[aä]rkte?)\b"
                         r"|\b(?:beverage (?:shops?|retail\w*|outlets?|stores?|markets?)|drinks? (?:stores?|markets?|shops?)|getr[aä]nke\w*"
                         r"|grocery (?:stores?|markets?)|food (?:stores?|markets?|retail\w*|discount\w*)|lebensmittel\w*"
                         r"|drug ?stores?|chemists?(?:'s)? (?:shops?|stores?)|drogerie\w*"
                         r"|pet (?:supply|supplies|shops?|stores?|food|superstores?)|zoo ?(?:&|and) ?co|zoofachmarkt|futterhaus|fressnapf"
                         r"|diy|do-it-yourself|hardware (?:stores?|shops?)|home[- ]improvement"
                         r"|building (?:materials?|supplies|supply) (?:stores?|shops?|centres?|centers?|merchants?|markets?|dealers?)"
                         r"|baumarkt\w*|baustoff\w*|builders'? merchants?"
                         r"|garden (?:cent(?:re|er)s?|markets?|stores?|shops?)|gartencenter|gartenmarkt|plant (?:shops?|stores?|nurser\w*)"
                         r"|horticultural nurser\w*"
                         r"|furniture (?:stores?|shops?|retail\w*|outlets?|markets?|discount\w*)|m[oö]bel\w*|mattress\w*|bed(?:ding)? (?:stores?|shops?)"
                         r"|kitchen (?:stores?|studios?|retail\w*|shops?)"
                         r"|tiles?|fliesen\w*|flooring|carpets?|paint (?:shops?|stores?)|farben"
                         r"|car parts|auto parts|tyres?|tires? (?:shops?|stores?|cent(?:re|er)s?|dealers?)|reifen\w*"
                         r"|motorcycle (?:shops?|stores?|dealers?\w*|retail\w*|sales)"
                         r"|car (?:dealer\w*|showrooms?|sales)|showrooms?|autohaus|agricultural (?:machinery|supply|supplies)|farm (?:supply|supplies)"
                         r"|landhandel|raiffeisen|trailer"
                         r"|variety (?:stores?|shops?|discount\w*)|discount (?:stores?|shops?)|sonderpreis|restposten|thomas philipps"
                         r"|fachmarkt\w*|specialist retail\w*|retail (?:park|warehouse)s?|retail cent(?:re|er)s?|shopping park|big[- ]box"
                         r"|multi[- ‐]?tenant retail\w*"
                         r"|electronics? (?:stores?|retail\w*|markets?|superstores?)|mediamarkt|media markt|saturn)\b"),
    # chains whose stand-alone store is one level, in an own POI's name or brand, the building's or a POI name (not the chains of
    # MULTI_LEVEL_CHAINS: Deichmann, Roller, MediaMarkt, Saturn)
    "box_chain_pattern": (r"\b(?:aldi|lidl|netto|penny|norma|np[- ]?(?:markt|discount)?|rewe|edeka|nah ?(?:&|und) ?gut|combi|famila|marktkauf"
                          r"|kaufland|globus|tegut|denn'?s|alnatura|wolf markt|diska|v-markt"
                          r"|hol['’]?ab|trinkgut|getr[aä]nke\w*|fristo|big durst"
                          r"|dm|rossmann"
                          r"|fressnapf|futterhaus|zoo ?& ?co|kiebitzmarkt|raiffeisen\w*"
                          r"|kik|tedi|nkd|takko\w*|action|woolworth|thomas philipps|sonderpreis\w*|m[aä]c geiz|euroshop|wreesmann|pfennigpfeiffer"
                          r"|kodi|tedox|jawoll|postenb[oö]rse"
                          r"|reno|abc schuh\w*|siemes\w*|ernsting'?s\w*|jeans fritz|adler"
                          r"|jysk|d[aä]nisches bettenlager|matratzen concord|poco|sconto|reddy\w*|swiss sense"
                          r"|hagebau\w*|hornbach|obi|bauhaus|toom|hellweg|b1"
                          r"|expert|euronics|medimax"
                          r"|a\.?t\.?u|euromaster|vergölst|point s|reifen\.com|wessels \+ m[uü]ller|pv automotive|louis motorrad|polo motorrad"
                          r"|harley-davidson|decathlon|intersport)\b"),
    "box_chain_exclude": r"\b(?:c&a|h&m|galeria|karstadt|primark|zara|peek)\b",
    "box_shop_tags": ["supermarket", "beverages", "pet", "doityourself", "hardware", "garden_centre", "tiles", "car_parts", "tyres",
                      "furniture", "bed", "kitchen", "motorcycle", "trade", "agrarian", "variety_store", "paint", "car", "wholesale",
                      "building_materials", "flooring", "fireplace", "trailer", "electrical", "chemist", "electronics", "discount"],
    "box_upper_groups": ["health_practice", "office", "public_office", "small_school", "sport", "childcare", "hotel"],
    "box_evidence_tiers": [[1500, 9.0], [800, 8.75]],       # from m2, eaves at most (m) - each tier up to the next
    "box_low": [1000, 7.0],                                 # from m2, eaves below (m), no evidence needed
    # hall_tag_code: the outline covering the most of the footprint (hall_min_cover or more) or the ALKIS function; 2-3 storeys,
    # no practice or office tenant, no storeyed type, no ALKIS residential code (unless over 1,000 m2 at 2 storeys at most)
    "hall_tags": ["barn", "farm_auxiliary", "greenhouse", "shed", "roof", "carport", "cowshed", "stable", "riding_hall"],
    "hall_codes": [2131, 2410, 2700, 2720, 2721, 2723, 2724, 2726, 2729],
    "hall_roof_tags": ["roof", "carport"],                  # these and car washes count in any street-level class
    "hall_wash_code": 2131,
    "hall_min_cover": 0.5,
    "hall_max_storeys": 3,
    "hall_tenant_groups": ["health_practice", "office", "public_office"],
    "hall_res_codes": [1000, 1313],
    "hall_res_keep": [1000, 2],
    # fuel stations: a canopy is a fuel-station building (ALKIS) under an OSM roof twin or roof outlines over half of it, a
    # building typed as a canopy, or another building with a fuel word or POI under a roof that is no car wash
    "station_code": 2130,
    "station_function": "31001_2130",
    "fuel_pattern": r"gas station|fuel station|petrol station|filling station|service station|tankstelle|\bfuel\b|\bpetrol\b|truck stop|autohof|canop",
    "wash_pattern": (r"car ?wash|wash(?:ing)? (?:bay|hall|street|line|tunnel|plant|facility)|waschstra|waschanlage|waschhalle|waschpark"
                     r"|self[- ]service wash"),
    "canopy_pattern": r"canop",
    "canopy_roof_tags": ["roof", "carport", "canopy"],
    "canopy_roof_min_cover": 0.5,
    "station_shop_max_dist_m": 15.0,
    "station_not_shop_head": (r"repair|workshop|garage|car ?wash|truck wash|\bwash|office|residential|apartment|dwelling|industrial"
                              r"|warehouse|depot|hall\b"),
    "station_shop_groups": ["small_retail", "food_store", "gastronomy"],
    # the station shops the 15 m rule misses (a service area further away or not typed as a station) - and a canopy without a POI
    # on the Salzgitter shopping centre that carries no unit
    "station_extra_pairs": {"DENIAL0500003Czj": "DENIAL0500003DpW",       # HEM -> the touching 'small commercial shop'
                            "DENIAL0600003a3G": "DENIAL0600003a4m",       # Aral -> Raststaette Oderwald
                            "DENIAL03000026au": "DENIAL030000265J",       # Aral Seesen -> Raststaette Harz, 17.5 m
                            "DENIAL0300000GjK": "DENIAL0300000Gtz"},      # Aral -> the motorway service area, 17.4 m
    "canopy_no_unit_ids": ["DENIAL0500003DDr"],
}
# Department stores and shopping centres count storeys of 4.5 m instead of 3.5 m (the user,
# 2026-10-05: retail storeys are 4.5-5 m high; Galeria Braunschweig 6 -> 4 storeys), where OSM
# levels are not mapped, before the mall rule.
FLOOR_RETAIL_STOREY_HEIGHT_M = 4.5
FLOOR_RETAIL_TALL_CLASSES = frozenset({"department stores", "shopping centers"})
# Malls: the distinct whole levels from -1 to 3 mapped on at least 3 of its own POIs, else at
# most 3 storeys; at most 2 in a parking building or with dwellings on 1,000 m2 or less
# (Schloss-Arkaden 5 -> 3). Factory outlet centres sell on at most 2 floors.
FLOOR_MALL_LEVELS = (-1, 3)
FLOOR_MALL_MIN_LEVEL_POIS = 3
FLOOR_MALL_MAX_STOREYS = 3
FLOOR_MALL_SMALL_MAX_STOREYS = 2
FLOOR_MALL_SMALL_FOOTPRINT_M2 = 1000
FLOOR_OUTLET_MAX_STOREYS = 2

# Reclassification (the user, 2026-10-05; the colleague's Stage-8 retail rules): a "shopping
# center" with fewer than 15 POI pairs (site rows included) and a full-range retailer in a POI
# or parent name is a hypermarket - 8 buildings (Globus, Kaufland x3, REWE Center, Edeka Center
# x3): factor 1.2 and a hall of one storey (OSM levels still override: Edeka Center Goerge
# way/799734461 keeps its 2). A shopping centre with "outlet" in a POI or parent name, or an
# outlet POI, is a factory outlet centre - the 8 Designer Outlets Wolfsburg buildings, not the
# Odermark strip centre in Goslar that matched through a tenant's name: factor 2.15, at most 2
# storeys.
RECLASS_HYPERMARKET_PATTERN = r"globus|kaufland|famila|marktkauf|e-center|e center|edeka-center|edeka center|rewe center|rewe-center|\breal\b"
RECLASS_HYPERMARKET_MAX_PAIRS = 15
RECLASS_OUTLET_PATTERN = r"outlet"
RECLASS_OUTLET_USES = frozenset({"outlet"})
RECLASS_OUTLET_EXCLUDE = frozenset({"DENIAL030000hlZX"})

# The residential context RC - does the building have dwellings? It switches only the
# street-level and small-unit uses (shops, gastronomy, services, practices, offices, small
# schools, Kitas, club rooms, gyms); hotels, nursing homes, hospitals, schools, universities,
# research, open-plan offices, big boxes, halls, worship, museums and industry keep their rule
# (ALKIS codes 60 % of hotels and 72 % of nursing homes residential). RC = an ALKIS residential
# code (1000-1313, 2310 / 2320 / 3100 "... with housing") unless the head names a whole office
# building, headquarters, administration or town hall (VW Buerozentrum Nord), the OSM twin is a
# specific non-residential building, or it is a low box (> 1,000 m2, <= 2 storeys) that neither
# type nor twin confirms (Adler, Metro coded 1000); or an OSM residential twin (house / detached
# / bungalow / farm only with 2+ storeys); or a residential noun in the type (never the verb
# "housing": "office building housing a company"). Stress-test fixes: a house twin never makes an
# explicit non-residential code (2xxx / 3xxx) residential (the courthouse and government offices
# tagged house / terrace), and a Kita counts as residential only when its type names dwellings.
RC_ALKIS_RANGE = (1000, 1313)
RC_ALKIS_CODES = frozenset({2310, 2320, 3100})
RC_NONRES_ALKIS_RANGE = (2000, 3999)
RC_RES_TYPE_PATTERN = (r"\bresidential\b(?!\s+(?:care|home|facility|group|school|centre|center))"
                       r"|\bapartments?\b|\bflats?\b|\bdwellings?\b"
                       r"|\b(?:with|and|plus|social|student|shared|staff|residential|upper[- ‐]floor|upper)\s+housing\b"
                       r"|\bhousing\s+(?:above|upstairs|on\s+(?:the\s+)?upper|units?|estate|block|complex)\b|\bhousing\s*$"
                       r"|\b(?:private|clergy|upper[- ‐]floor|official)\s+residence\b|\bparsonage\b|\bpfarrhaus\b|\brectory\b"
                       r"|\b(?:single|two|multi)[- ‐]family\b|\b(?:detached|terraced|row|private|farm|town)\s*houses?\b")
RC_OFFICE_BUILDING_PATTERN = (r"\boffice\s+(?:building|block|complex|tower|park|centre|center|campus)|\bheadquarters\b|\bhead office\b"
                              r"|\badministrat\w*\s+(?:building|centre|center|complex|headquarters)|\b(?:town|city)\s+hall\b|\brathaus\b"
                              r"|\bcorporate offices?\b")
RC_RES_TWINS = frozenset({"apartments", "residential", "dormitory", "terrace", "semidetached_house"})
RC_HOUSE_TWINS = frozenset({"house", "detached", "bungalow", "farm"})
RC_HOUSE_MIN_STOREYS = 2
RC_NONRES_TWINS = frozenset({
    "office", "industrial", "warehouse", "school", "university", "college", "hospital", "hotel", "public", "government", "civic",
    "kindergarten", "church", "chapel", "train_station", "sports_centre", "sports_hall", "fire_station", "manufacture", "hangar",
    "service", "transportation"})
RC_BOX_MIN_FOOTPRINT_M2 = 1000
RC_BOX_MAX_STOREYS = 2

# POI groups (the synthesis's poimap): an asked or sole POI's group comes from its poi_use, else
# from the OSM key its use came from, else from the first key column it carries; "unmapped" if
# none. The group sets its floor family and its POI-level class.
POI_GROUPS = {
    "small_retail": (
        "bakery", "butcher", "kiosk", "convenience", "beverages", "florist", "optician", "hearing_aids", "chemist", "clothes", "shoes",
        "jewelry", "jeweller", "gift", "books", "stationery", "toys", "cosmetics", "perfumery", "mobile_phone", "electronics", "computer",
        "variety_store", "pet", "tobacco", "e-cigarette", "bag", "watches", "art", "music", "musical_instrument", "photo", "second_hand",
        "charity", "deli", "confectionery", "pastry", "tea", "coffee", "wine", "alcohol", "greengrocer", "seafood", "cheese", "organic",
        "health_food", "nutrition_supplements", "medical_supply", "bicycle", "sports", "outdoor", "interior_decoration", "houseware",
        "kitchen", "fabric", "sewing", "wool", "frame", "lottery", "newsagent", "newspaper", "copyshop", "ticket", "pharmacy", "boutique",
        "fashion_accessories", "erotic", "cannabis", "video_games", "antiques", "collector", "gold_buyer", "pawnbroker", "printer_ink",
        "hifi", "souvenir", "nuts", "trophy", "wigs", "bed", "carpet", "lighting", "curtain", "window_blind", "tiles",
        "bathroom_furnishing", "paint", "doors", "fireplace", "flooring", "shop", "retail", "grocery", "food", "ice_cream_shop", "farm",
        "motorcycle_parts", "car_parts", "tyres", "hardware;toys", "tobacco;lottery", "gift;newsagent", "travel_agency;books", "model",
        "handicraft", "fan", "ashtray", "elevator"),
    "food_store": ("supermarket",),
    "big_box": ("doityourself", "garden_centre", "furniture", "trade", "wholesale", "car", "motorcycle", "building_materials", "hardware"),
    "department_store": ("department_store",),
    "gastronomy": ("restaurant", "fast_food", "cafe", "pub", "bar", "ice_cream", "biergarten", "food_court", "hookah_lounge", "internet_cafe",
                   "outdoor_seating", "caterer"),
    "personal_service": ("hairdresser", "beauty", "massage", "tattoo", "piercing", "tailor", "dressmaker", "dry_cleaning", "laundry",
                         "shoe_repair", "shoemaker", "key_cutter", "funeral_directors", "tanning_salon", "pet_grooming", "photographer",
                         "photo_booth", "sharpening", "electronics_repair", "cleaning", "washing_machine", "clothes_dryer", "rental",
                         "ski_rental", "storage_rental"),
    "health_practice": ("doctors", "doctor", "physician", "dentist", "physiotherapist", "podiatrist", "podologist", "therapist",
                        "psychotherapist", "alternative", "healer", "speech_therapist", "occupational_therapist", "midwife", "optometrist",
                        "veterinary", "clinic", "blood_donation", "nursing_service", "healthcare", "laboratory", "lab"),
    "counter": ("bank", "post_office", "travel_agency", "travel_agent", "insurance", "estate_agent", "letting_agency", "car_rental",
                "employment_agency", "bureau_de_change", "money_transfer", "customer_care_center", "reception_desk", "bookmaker", "gambling",
                "telecommunication", "energy_supplier"),
    "office": ("office", "company", "it", "lawyer", "notary", "tax_advisor", "accountant", "consulting", "architect", "engineer", "surveyor",
               "association", "ngo", "union", "foundation", "political_party", "politician", "advertising_agency", "marketing", "financial",
               "financial_advisor", "coworking", "coworking_space", "property_management", "logistics", "cooperative", "religion",
               "publisher", "translator", "design", "web_design", "linux", "event_management", "leasing", "security", "construction_company",
               "moving_company", "energy", "technology", "coaching", "chamber", "administrative", "newspaper_office", "institute",
               "research_office"),
    "public_office": ("townhall", "government", "courthouse", "police", "public_building", "polling_station", "civic", "tax_office",
                      "register_office"),
    "childcare": ("kindergarten", "childcare"),
    "school": ("school", "university", "college", "lecture_hall", "faculty", "research", "research_institute", "educational_institution",
               "education", "institute"),
    "small_school": ("driving_school", "music_school", "language_school", "dancing_school", "prep_school", "first_aid_school", "tutoring",
                     "dojo", "martial_arts"),
    "care_home": ("nursing_home", "assisted_living", "hospice", "social_facility"),
    "hospital": ("hospital",),
    "hotel": ("hotel", "motel", "hostel", "guest_house", "tourist_accommodation"),
    "holiday_flat": ("apartment", "chalet", "room"),
    "culture": ("museum", "theatre", "cinema", "arts_centre", "events_venue", "gallery", "library", "attraction", "castle", "planetarium",
                "concert_hall", "exhibition_centre", "casino", "adult_gaming_centre", "amusement_arcade", "escape_game", "laser_tag",
                "nightclub", "stage", "public_bookcase"),
    "community": ("community_centre", "social_centre", "youth_centre", "club", "fraternity", "student_association", "scout", "youth",
                  "culture", "social", "freemasonry", "parish_hall", "centre", "chess"),
    "worship": ("place_of_worship", "christian", "church", "chapel", "monastery"),
    "sport": ("sports_centre", "fitness_centre", "fitness", "sports_hall", "multi", "shooting", "equestrian", "horse_riding", "tennis",
              "gymnastics", "swimming", "swimming_pool", "dance", "yoga", "sauna", "9pin", "10pin", "climbing", "soccer", "padel", "archery",
              "athletics", "water_park", "indoor_play", "karting", "water_sports", "sport", "public_bath"),
    "craft": ("plumber", "electrician", "carpenter", "roofer", "painter", "hvac", "metal_construction", "gardener", "stonemason", "glaziery",
              "joiner", "upholsterer", "locksmith", "tiler", "builder", "window_construction", "sawmill", "brewery", "winery", "printer",
              "signmaker", "pottery", "atelier", "sculptor", "bookbinder", "floorer", "beekeeper", "renovation", "craft", "electrical",
              "pest_control"),
    "vehicle": ("car_repair", "car_wash", "vehicle_inspection", "car_service", "abschlepp_und_pannendienst"),
    "fuel": ("fuel",),
    "industry": ("industrial", "works", "factory", "manufacture", "warehouse", "depot", "storage", "water_works", "wastewater_plant", "plant",
                 "power", "cooling", "silo", "recycling", "greenhouse", "hall"),
    "transport": ("station", "train_station", "bus_station", "terminal", "post_depot", "aerodrome", "hangar", "luggage_locker"),
    "fire_rescue": ("fire_station", "ambulance_station", "rescue_station"),
    "generic": ("commercial", "building", "public", "house", "historic", "villa", "heritage", "information", "access"),
    "vacant": ("vacant", "ruins", "construction", "disused"),
}
POI_KEY_FALLBACK = {"shop": "small_retail", "office": "office", "craft": "craft", "healthcare": "health_practice"}
# The POI-level class (a step-05 class name) per group, refined by use (the last matching
# refinement wins; None refines every POI of the group not refined before) and for food stores
# by brand. A POI unit takes the Workers factor of its own class (the user, 2026-10-05: FGSV
# rates are per facility type, and a restaurant in a retail building is no shop); generic,
# unmapped and vacant POIs, and the uses without a class, take the building's factor.
POI_GROUP_CLASS = {
    "small_retail": "retail (small-scale)", "department_store": "department stores", "gastronomy": "restaurants / gastronomy",
    "personal_service": "customer-oriented services", "health_practice": "customer-oriented services",
    "counter": "customer-oriented services", "office": "normal office", "public_office": "normal office", "childcare": "kindergartens",
    "small_school": "customer-oriented services", "care_home": "nursing homes", "hospital": "hospitals", "hotel": "hotels",
    "holiday_flat": "hotels", "culture": "entertainment, culture", "community": "entertainment, culture",
    "worship": "entertainment, culture", "sport": "fitness / wellness", "craft": "craft businesses",
    "vehicle": "vehicle / electrical repair", "fuel": "retail (small-scale)", "transport": "Transport", "fire_rescue": "Public facilities",
}
POI_CLASS_BY_USE = (
    ("office", ("lawyer", "notary", "tax_advisor", "accountant", "advertising_agency", "consulting", "architect", "engineer", "surveyor",
                "financial_advisor", "marketing"), "business-oriented services"),
    ("school", ("school",), "schools"),
    ("school", ("university", "college", "lecture_hall", "faculty", "educational_institution", "education"), "universities"),
    ("school", ("research", "research_institute"), "research institutes"),
    ("culture", ("cinema",), "large cinemas"),
    ("culture", ("nightclub",), "large discos, fun / leisure pools"),
    ("sport", ("water_park",), "large discos, fun / leisure pools"),
    ("big_box", ("doityourself", "hardware", "building_materials", "garden_centre"), "DIY stores"),
    ("big_box", ("furniture",), "furniture stores"),
    ("big_box", ("trade", "wholesale"), "wholesale"),
    ("big_box", ("car", "motorcycle"), "car dealerships"),
    ("industry", ("warehouse", "depot", "storage"), "Yards, depots, storage areas, construction yards"),
    ("industry", None, "Industrial operations / Production"),
)
POI_FOOD_STORE_CLASS = "retail (small-scale)"
POI_DISCOUNT_CLASS = "discount stores"
POI_DISCOUNT_PATTERN = r"\b(?:aldi|lidl|netto|penny|norma|np[- ]?markt|np\b)"
POI_HYPER_CLASS = "hypermarkets / superstores"
POI_HYPER_PATTERN = r"\b(?:kaufland|marktkauf|globus|e[- ]?center|real\b|famila|v-markt|toom markt|hit\b)"

# Building units - the building is the sole occupant (no asked POIs): the storeys it takes,
# per class, (with dwellings, without dwellings, condition); None = every storey (ALL); a class
# not listed takes every storey. Where a condition is given it must hold, or the occupant takes
# every storey: not_office_building - the head names no whole office building / headquarters /
# administration; public_office - a parish, social or counselling office, not a care home;
# small_school - a driving, music, language, dance or tutoring school; small_unit - a club room,
# youth centre, arcade, gallery; small_unit_upstairs - the same in a building of 2+ storeys;
# studio - a gym, dance, yoga or martial-arts studio, not a sports hall or pool (a parking
# building counts as dwellings for it); holiday_flat - its only POI is a holiday flat and the
# ALKIS code is residential; small_attraction - a trampoline or adventure hall, tent or kiosk.
# The user's decisions (2026-10-05): shops and restaurants take one storey with AND without
# dwellings (two only by a level tag over 0;1 or for a multi-level chain without dwellings);
# Kitas 1 / 2; department stores 2 with dwellings; outlets 2; the rest from the synthesis.
UNIT_CLASS_STOREYS = {
    "retail (small-scale)":                       (1, 1, None),
    "Retail":                                     (1, 1, None),
    "restaurants / gastronomy":                   (1, 1, None),
    "customer-oriented services":                 (1, None, None),
    "customer service":                           (1, None, None),
    "business-oriented services":                 (1, None, "not_office_building"),
    "normal office":                              (1, None, "not_office_building"),
    "Services":                                   (1, None, None),
    "Public facilities":                          (1, None, "public_office"),
    "schools":                                    (1, None, "small_school"),
    "kindergartens":                              (1, 2, None),
    "Crafts and trades":                          (1, 1, None),
    "craft businesses":                           (1, 1, None),
    "entertainment, culture":                     (1, None, "small_unit"),
    "Facilities for culture, leisure and sports": (1, None, "small_unit_upstairs"),
    "fitness / wellness":                         (1, 2, "studio"),
    "large cinemas":                              (1, None, None),
    "hotels":                                     (1, 1, "holiday_flat"),
    "department stores":                          (2, None, None),
    "factory outlet centers":                     (2, 2, None),
    "theme parks":                                (1, 1, "small_attraction"),
}
# In these street-level classes the building's only POI refines the class rule by its group
# (with dwellings, without, condition). Banks, insurers, the employment agency, energy suppliers
# and customer-care centres take one storey with dwellings and every storey without
# (UNIT_COUNTER_ALL_USES); a holiday flat reads the ALKIS code (condition dwelling_by_code).
UNIT_STREET_CLASSES = frozenset({
    "retail (small-scale)", "Retail", "restaurants / gastronomy", "customer-oriented services", "customer service",
    "business-oriented services", "Services", "normal office"})
UNIT_GROUP_STOREYS = {
    "food_store":       (1, 1, None),
    "vehicle":          (1, 1, None),
    "fuel":             (1, 1, None),
    "big_box":          (1, 1, None),
    "craft":            (1, 1, None),
    "small_retail":     (1, 1, None),
    "gastronomy":       (1, 1, None),
    "personal_service": (1, 1, None),
    "counter":          (1, 1, None),
    "health_practice":  (1, None, "not_office_building"),
    "office":           (1, None, "not_office_building"),
    "public_office":    (1, None, "not_office_building"),
    "small_school":     (1, None, "not_office_building"),
    "holiday_flat":     (1, 1, "dwelling_by_code"),
    "sport":            (1, 2, None),
    "community":        (1, None, None),
    "childcare":        (1, 2, None),
    "department_store": (2, None, None),
}
UNIT_COUNTER_ALL_USES = frozenset({"bank", "insurance", "employment_agency", "energy_supplier", "customer_care_center"})
# A level tag of the only POI moves these: a tag over n floors (0;1) gives n storeys, a level of
# 1 or more one storey; a multi-level chain without dwellings two.
UNIT_LEVEL_TAG_CLASSES = frozenset({"retail (small-scale)", "Retail", "restaurants / gastronomy"})
UNIT_LEVEL_TAG_GROUPS = frozenset({"small_retail", "gastronomy", "personal_service", "counter"})
# Plain homes without POI (about 300, most of them kept only because a commercial or industrial
# site polygon covers them) keep one storey WITH their labels (the user, 2026-10-05). The floors
# above are flats: no remainder.
UNIT_HOME_STOREYS = {"Services": 1}
# The chains that carry a multi-level OSM level tag somewhere in our data (step-01 POIs): a
# branch of one of them takes two floors without dwellings (LOW2 in a shared building), matched
# on the POI's name or brand. Evidence: H&M node/878597604 and node/2138945738 level 0;1 (7 H&M
# POIs); Zara node/6849243002 0;1; MediaMarkt node/2069302320 0;1 (8 POIs); Deichmann
# node/3038616990 0;1 (13 POIs); Buchhandlung Graff node/3069698623 0;1;2; Roller way/74177990 0;1
# (2 POIs). Not chains, their own tag counts anyway: Freise & Heidemann (bicycles), Meine
# Kueche + Raeume, Afghan Warehouse (a department store), four restaurants and a pub, the hotel
# Brusttuch, ver.di.
MULTI_LEVEL_CHAINS = {
    "H&M":                r"^H\s?&\s?M\b",
    "Zara":               r"^Zara\b",
    "MediaMarkt":         r"^Media\s?Markt\b",
    "Deichmann":          r"^Deichmann\b",
    "Buchhandlung Graff": r"^Buchhandlung Graff\b",
    "Roller":             r"^Roller$",
}

# POI units in a shared building: the floor family of each asked POI, from its own group,
# (with dwellings, without). GROUND = a share of the ground floor (all GROUND units together, with
# half of each LOW2 and a third of each CAP3, at most one footprint); ONE = one storey anywhere;
# LOW2 = ground and first floor; CAP2 / CAP3 = at most 2 / 3 storeys; ALL = what the others
# leave, by share, even above its old share. Each unit keeps min(share x FA, its storeys x A).
# The user's changes (2026-10-05): shops GROUND with and without dwellings (LOW2 for a multi-level
# chain without dwellings); generic and unmapped POIs never ALL (the unmapped MobiVersum
# playground took 36,443 m2); holiday flats and dormitories give no unit (they keep their floor).
# Exceptions: in a mall the shops, restaurants, services and unmapped units take ALL (their share
# of the capped mall); a big box in a big-box building ALL; museums, theatres ... (POI_CULTURE_
# ALL_USES) ALL and a cinema CAP2; worship ALL in a worship building; a level tag moves a unit
# up only - level 1 or more -> ONE, 0;1 -> LOW2, 0;1;2 -> CAP3.
POI_GROUP_FAMILY = {
    "small_retail":     ("GROUND", "GROUND"),
    "food_store":       ("GROUND", "GROUND"),
    "big_box":          ("GROUND", "GROUND"),
    "department_store": ("LOW2", "ALL"),
    "gastronomy":       ("GROUND", "GROUND"),
    "personal_service": ("GROUND", "GROUND"),
    "counter":          ("GROUND", "GROUND"),
    "vehicle":          ("GROUND", "GROUND"),
    "fuel":             ("GROUND", "GROUND"),
    "craft":            ("GROUND", "GROUND"),
    "childcare":        ("GROUND", "GROUND"),
    "health_practice":  ("ONE", "ONE"),
    "small_school":     ("ONE", "ONE"),
    "community":        ("ONE", "ONE"),
    "sport":            ("ONE", "ONE"),
    "office":           ("ONE", "ALL"),
    "public_office":    ("ONE", "ALL"),
    "school":           ("ALL", "ALL"),
    "care_home":        ("ALL", "ALL"),
    "hospital":         ("ALL", "ALL"),
    "hotel":            ("ALL", "ALL"),
    "industry":         ("ALL", "ALL"),
    "transport":        ("ALL", "ALL"),
    "fire_rescue":      ("ALL", "ALL"),
    "culture":          ("ONE", "ONE"),
    "worship":          ("ONE", "ONE"),
    "holiday_flat":     ("ONE", "ALL"),
    "generic":          ("GROUND", "ONE"),
    "unmapped":         ("GROUND", "ONE"),
    "vacant":           ("GROUND", "ONE"),
}
POI_MALL_CLASSES = frozenset({"shopping centers", "factory outlet centers"})
POI_MALL_UNIT_GROUPS = frozenset({"small_retail", "gastronomy", "personal_service", "counter", "food_store", "big_box", "culture",
                                  "department_store", "generic", "unmapped"})
POI_BIGBOX_CLASSES = frozenset({"hypermarkets / superstores", "furniture stores", "DIY stores", "wholesale", "car dealerships",
                                "discount stores", "self-service department stores"})
POI_CULTURE_ALL_USES = frozenset({"museum", "theatre", "castle", "attraction", "events_venue", "concert_hall", "exhibition_centre",
                                  "planetarium"})
POI_CHAIN_GROUPS = frozenset({"small_retail", "big_box"})
# One facility (stress-test fix): where all active asked POIs of a building are in one group -
# two or more of them, or a single one whose POI-level class is the building's class (the
# reading taken of "all in one group, or that group is the building's own class"; 868
# buildings, 100 of them with a single POI) - they share the building's sole-occupant floor
# (the building-unit rules above) by their shares, instead of being tenants (Kita
# Abenteuerland: two kindergarten nodes kept only the ground floor; the TU Mensa). Not where a
# vacant, holiday-flat or dormitory place shares the building.
# Holiday flats and student dormitories are dwellings (the user, 2026-10-05): such a POI gives no
# unit, and keeps its floor so that the other tenants do not grow into it.
POI_NO_UNIT_GROUPS = frozenset({"holiday_flat"})
POI_DORM_USES = frozenset({"student_accommodation", "student_accomodation", "dormitory"})
# Landuse pairs (the user, 2026-10-05, reversing the 2026-10-01/02 rule): a landuse polygon
# (landuse=commercial / retail / industrial, 180 pairs) is no tenant, so the shares are re-split
# over the asked POIs - in run 1 it held 99.9 % of the Ring-Center and over half of 126 other
# buildings. A non-asked vacant pair keeps its share as an empty GROUND slot that carries
# nothing and never becomes a remainder.
REDIST_LANDUSE_USES = frozenset({"commercial", "retail", "industrial"})
# The point size cap (the user, 2026-10-05; widened 2026-10-06): a POI mapped as a point (not a building
# unit) in a shared building takes at most the 90th percentile of the mapped polygons of its group - own POI
# polygons smaller than 0.8 of their building's footprint, so not the outline itself - and is never the
# building's main occupant: it keeps min(share x floor area, its cap), the cap applied before the ground-floor
# budget. Every group has a cap (2026-10-06): its own p90 where it has at least POINT_SIZE_CAP_MIN_POLYGONS
# polygons, else the p90 of all groups' polygons (POINT_SIZE_CAP_DEFAULT_M2: department stores, transport); the
# five street-level caps and the office / community / small-school caps are the numbers the user decided on
# (small_school rests on 5 polygons). An anchor (POI_ANCHOR_GROUPS, below) is not capped. The freed floor goes
# to the main occupants; with none it stays free - a remainder without dwellings, nothing with them. Before
# 2026-10-06 a fuel point took 14,172 m2 of VW Halle 52 and a historic well point carried St. Aegidien's
# Workers. Recomputed on the step-06 / step-01 data of 2026-10-05 (the notebook checks every number): group
# cap m2 (polygons).
POINT_SIZE_CAP_QUANTILE = 0.9
POINT_SIZE_CAP_OUTLINE_SHARE = 0.8
POINT_SIZE_CAP_MIN_POLYGONS = 10
POINT_SIZE_CAP_DEFAULT_M2 = 1345.6              # all groups, 1,586 polygons
POINT_SIZE_CAP_M2 = {
    "gastronomy":       438,                    # 137 polygons
    "small_retail":     748,                    # 298
    "personal_service": 187,                    # 38
    "counter":          388,                    # 33
    "health_practice":  319,                    # 30
    "office":           1540,                   # 52
    "community":        779,                    # 37
    "small_school":     692,                    # 5
    "big_box":          4773.5,                 # 35
    "care_home":        1510.1,                 # 25
    "childcare":        454.3,                  # 29
    "craft":            278.1,                  # 21
    "culture":          1112.2,                 # 30
    "fire_rescue":      444.4,                  # 24
    "food_store":       1770.8,                 # 25
    "fuel":             180.9,                  # 12
    "generic":          2459.6,                 # 62
    "hospital":         2053.0,                 # 20
    "hotel":            465.9,                  # 42
    "industry":         12073.9,                # 168
    "public_office":    958.5,                  # 39
    "school":           2208.6,                 # 145
    "sport":            1530.9,                 # 122
    "unmapped":         1267.4,                 # 34
    "vehicle":          491.8,                  # 30
    "worship":          748.7,                  # 51
}
# Anchors (the user, 2026-10-06): a food store or big box in its own big-box building (a POI_BIGBOX_CLASSES
# building: Globus, Kaufland) is the building's main occupant - floor family ALL, no point cap - and so is a
# point whose family is ALL anyway and whose POI-level class is the building's class (a school in a school, a
# hotel in a hotel: the reading taken so that the point cap does not cut such a building to a point's size).
# Before 2026-10-06 the Globus point kept 3,606 of its own 18,030 m2.
POI_ANCHOR_GROUPS = frozenset({"food_store", "big_box"})
# Non-occupants (stress-test fix, put behind this switch - the user has not seen it explicitly):
# amenity features asked as POIs give no unit and their host keeps the floor; decided by TAG,
# not by poi_use, so that kitchen shops (shop=kitchen) and staffed tourist offices
# (tourism=information with information=office, or a step-07 type naming an office, centre,
# desk ...) stay; an "information point" names no staff (the three gates of the VW KundenCenter,
# no information tag) and is dropped; a POI that also carries an occupant key (a chemist with
# amenity=post_box) stays. A building label only a dropped POI carried becomes a rest unit; a
# building left with no asked POI is a building unit.
REDIST_DROP_NON_OCCUPANTS = True
NON_OCCUPANT_TAGS = {
    "amenity": frozenset({"shower", "public_bookcase", "kitchen", "photo_booth", "luggage_locker", "luggage_lockers", "bleachers",
                          "give_box", "washing_machine", "dressing_room", "post_box", "clothes_dryer", "vending_machine", "toilets",
                          "drinking_water", "atm", "reception_desk"}),
    "leisure": frozenset({"bleachers"}),
    "shop":    frozenset({"vending_machine"}),
}
NON_OCCUPANT_KEEP_KEYS = ("shop", "office", "craft", "healthcare")
NON_OCCUPANT_INFO_STAFFED_PATTERN = r"\b(?:office|cent(?:re|er)|desk|reception|service|counter|bureau|shop|store|kiosk)\b"

# Rules on single categories and places without a unit (the user, 2026-10-05, adapted from the
# colleague's Stage 6 / 8):
#   * churches (ALKIS 3041 / 3043 / 3045; 868 zoned): Workers 0 on the church's building and
#     rest units and on its worship POI units - a class rate on a nave is an artefact, the few
#     staff are part-time; other tenants keep their Workers, every non-work label stays;
#   * volunteer fire stations (a fire-station head, inside or outside the cities; never a
#     professional, works or FTZ station - read in the whole type and the name, so "Fire station
#     (Feuerwehrtechnische Zentrale)" and "(county technical centre)" are none - and never an
#     office, a museum or a former station now used otherwise - read in the head and the name, so
#     "Volunteer fire station with municipal office" is one): Workers 0 on the building, rest and
#     fire-station POI units; a station labelled only work gets no unit. "Inside or outside the
#     cities" is read as: Braunschweig, Salzgitter and Wolfsburg have professional brigades, so a
#     station there counts only where its head says volunteer (the colleague's translation; 523
#     stations - read without it, 631: 108 more in the three cities);
#   * sports halls and clubhouses (ALKIS 3200 / 3211, or a sports-hall head - a clubhouse without
#     those codes is not one - in the club-type classes): Workers 0 on the building and rest units
#     and on the POI units that are the hall, its club or the school using it (the sport,
#     community, school, generic and unmapped groups - "Sporthalle" DENIAL8400004shp, the
#     colleague's example, held 138 Workers on its sport POIs); School and the other labels stay;
#     staffed venues keep their Workers, as buildings and as POIs - pools, ice arenas, clinics,
#     hotels, offices, nursing homes, commercial play venues (Monkey Town, Hally Gally), public
#     greenhouses - and so do the other tenants (restaurants, shops, practices, offices);
#   * the no-evidence residential buildings (the colleague's 6.1: ALKIS 31001_1xxx, class normal
#     office / Services / retail (small-scale) / customer-oriented services, no POI, no site, no
#     name; 1,752 zoned + 10 unzoned): one unit at footprint x 1 with Workers only - the labels
#     came from the cadastre code alone; the 51 with a retail / commercial OSM twin keep their
#     labels on footprint x 1;
#   * holiday flats (the colleague's 6.2: class hotels, ALKIS 31001_1xxx, own POIs only holiday
#     flats and chalets, 384, 352 in Goslar district): no unit at all, like dwellings;
#   * dormitories (a dormitory head, and student-accommodation POIs): no unit; other tenants keep
#     theirs;
#   * the last-carrier guard: where one of these rules (or a no-unit rule) leaves a zone with a
#     target but no carrier of a category, the units the rule removed there keep that category at
#     their weight before the rule (zone 315700615: a chapel and a fire station carry its 682
#     Workers). Not for the label mapping: zones that lost their only Retail_Daily carrier with
#     errands use the ring fallback.
CHURCH_ALKIS_CODES = frozenset({3041, 3043, 3045})
CHURCH_POI_USES = frozenset({"place_of_worship", "christian", "church"})
# and, as for sports halls, the POI units of a church without a type - a historic well point carried 17 Workers in St.
# Aegidien (2026-10-06); a parish hall (community) keeps its Workers
CHURCH_POI_GROUPS = frozenset({"generic", "unmapped"})
VOLUNTEER_FIRE_PATTERN = r"\bfire[- ]?(?:station|brigade|department|house)|\bfire and rescue|\bfeuerwehr|\bfeuerwache|\bortswehr"
VOLUNTEER_FIRE_EXCLUDE_PATTERN = (r"\bprofessional|berufsfeuerwehr|\bcompany\b|\bplant\b|\bfactory\b|in-house|werkfeuerwehr|industrial site"
                                  r"|volkswagen|technische zentrale|\bftz\b|feuerwehrtechnisch|technical cent(?:re|er)")
VOLUNTEER_FIRE_EXCLUDE_HEAD_PATTERN = r"\bformer\b|ehemalig|\boffices?\b|administrat|museum"
VOLUNTEER_FIRE_CITY_PATTERN = r"\bvolunteer|\bvoluntary|freiwillig|ortsfeuerwehr|\bortswehr"
VOLUNTEER_FIRE_CITY_AGS = ("03101", "03102", "03103")   # Braunschweig, Salzgitter, Wolfsburg: professional brigades
VOLUNTEER_FIRE_POI_USES = frozenset({"fire_station"})
SPORTS_HALL_ALKIS_CODES = frozenset({3200, 3211})
SPORTS_HALL_TYPE_PATTERN = (r"\bsports? halls?\b|\bgym(?:nastics)? halls?\b|\bturnhalle|\bsporthalle|\bmulti[- ]purpose (?:sports )?hall"
                            r"|\bmehrzweckhalle|\btennis ?halls?\b|tennishalle|\briding (?:hall|arena)|\bindoor riding|reithalle"
                            r"|\b(?:school|primary school) gymnasium|\bshooting (?:sports )?halls?\b|schie(?:ss|ß)halle")
SPORTS_HALL_CLASSES = frozenset({"Facilities for culture, leisure and sports", "schools", "entertainment, culture", "Transport"})
SPORTS_HALL_KEEP_PATTERN = (r"\bpools?\b|swimming|\bbaths?\b|hallenbad|freibad|\btherm|\bice\b|eissport|eishalle|eisstadion|\bindoor play"
                            r"|play ?(?:centre|center|ground|hall|park|land)|spielparadies|trampolin|\bfun ?(?:centre|center|park)"
                            r"|greenhouse|glasshouse|palm house|tropical|\bclinic|klinik|sanatori|\bhotel|nursing|care home|\bpflege|\boffices?\b"
                            r"|\bzoo\b|tierpark|wildpark|arche noah|camp(?:ing)?\s*site|campingplatz|\bmarina\b|yacht ?hafen|sportboothafen")
SPORTS_HALL_KEEP_IDS = frozenset({"DENIAL010000ek41", "DENIAL050000bcvJ"})   # Monkey Town, Hally Gally
# the POI units of a sports hall that get Workers 0, unless the keep pattern matches the POI's use, name or the head of its type
SPORTS_HALL_POI_GROUPS = frozenset({"sport", "community", "school", "generic", "unmapped"})
NO_EVIDENCE_FUNCTION_PREFIX = "31001_1"
NO_EVIDENCE_CLASSES = frozenset({"normal office", "Services", "retail (small-scale)", "customer-oriented services"})
NO_EVIDENCE_KEEP_TWINS = frozenset({"retail", "commercial"})
HOLIDAY_FLAT_CLASS = "hotels"
HOLIDAY_FLAT_FUNCTION_PREFIX = "31001_1"
HOLIDAY_FLAT_USES = frozenset({"apartment", "chalet"})
REDIST_LAST_CARRIER_GUARD = True

# --- The five labels without a zone total: visitors per working day (the user, 2026-10-05/06) ---------------
# value = the label's area (O / k_all) x a visitor rate / 100, never redistributed. A rate is visitor
# ARRIVALS - persons, all modes, staff excluded - per 100 m2 of occupied floor area per average working day
# (Mon-Fri): the day every source counts (FGSV 147, Bosserhoff / Ver_Bau, ITE, TRICS) and German VISUM demand
# models usually run. FGSV "Wege" at the site = 2 x arrivals (Bosserhoff 2011: 2.0 Wege per visitor).
# Persons whose purpose is a redistributed label (pupils, students, Kita children) are left out. The table
# was researched and checked on 2026-10-05 (Bosserhoff, FGSV and Ver_Bau rows as quoted in planning studies;
# KBV, the hairdressers' association, TRICS, ITE, the Berlin music-school standard, church attendance) and
# agreed by the user on 2026-10-06: the middle value is used (VISITOR_RATE_SCENARIO; low and high are kept
# for sensitivity runs); where no published rate exists our chosen number is used and marked assumed - the
# output names the labels whose value rests on such a number, so that it can be replaced. Decided with it:
#   * restaurants and cafes that also carry leisure get no meetup value (their guests are in the Leisure
#     total); hotels no business value; fuel stations 0 (refuelling stops lie on the way); plain homes no
#     meetup; event venues a low rate (used now and then); company academies 0 (the trainees are Workers);
#     lessons anywhere in a school or university building 0 (the pupils and students are in those totals);
#   * staff canteens and occupational-health offices on company sites carry none of the five labels
#     (their users are the Workers of the site);
#   * pharmacies and post offices give a value per outlet instead of per m2 (VISITOR_PER_OUTLET);
#   * a small-format rate (practice, counter, hairdresser, shop, cafe ...) applies only up to its group's
#     point size cap - the rest of a larger unit gets the unit's class rate (a 27,445 m2 hospital typed as
#     a medical centre no longer gets 6,861 patients a day).
# Rate id -> (low, mid, high, assumed, source). B_ business, E_ errands, S_ sports, M_ meetup, L_ lessons.
# The business rates and the generic errands rates are an employee density (BOSSERHOF_WEIGHTS, the FGSV
# ranges) x visitors per employee: office 0.25 / 0.5 / 1.0 (FGSV office 0.5-1.0 Wege, Ver_Bau 0.5-2.0),
# industry 0 / 0.25 / 0.5 (FGSV commercial areas 0.5-1 Wege), craft 0.25 / 0.5 / 0.75 (Freudl 2025 0.25;
# the Bosserhoff 2001 residual of 0.75 also holds the staff's own trips to clients), generic 0.25 / 1.25 /
# 5.0 (the 1.25 assumed: half the FGSV lower bound of 5 Wege for public-facing services).
VISITOR_RATE_SCENARIO = "mid"                   # "low" / "mid" / "high"
VISITOR_RATE_ANCHORS = {
    "ZERO":         (0, 0, 0, False, "a decided zero (the reason is written with the value)"),
    # errands
    "E_PRACTICE":   (15, 24, 50, False, "Heft 42 era 7.5-12.5 patients per employee x 2-4 employees per 100 m2 (VKT 2014); KBV 2026: 7.7-8.3 contacts per staff-day"),
    "E_COUNTER":    (5, 12, 30, True, "FGSV 147 Tab. 3.9 public-facing services 5-50 visitor Wege per employee x 2-4 employees; the 12 is our pick"),
    "E_PERSONAL":   (5, 9, 15, True, "hairdressers' association 2026: 80,118 salons, 7.7 bn EUR, 235,000 staff; 30-50 EUR per visit assumed"),
    "E_PUBOFF":     (1, 3, 7, True, "normal-office density x 1 visitor per employee, assumed; Itzehoe (Ver_Bau 2023) 0.3-0.4 per employee as the low"),
    "E_HOSPITAL":   (0.4, 1.0, 2.0, False, "Landsberg hospital 2024 operator data: outpatients and admissions per day against staff present"),
    "E_SOCIAL":     (1, 2, 5, True, "social facilities and counselling: no source; about the nursing-home visitor rate"),
    "E_VEHICLE":    (0.425, 1.25, 2.475, False, "vehicle-repair density 1.7 / 2.5 / 3.3 x craft visitors per employee"),
    "E_CRAFT":      (0.325, 0.95, 1.875, False, "craft density 1.3 / 1.9 / 2.5 x craft visitors per employee"),
    "E_FUEL":       (0, 0, 0, False, "the user: 0 - refuelling stops are on the way (JET's about 900 customers per station-day are pass-by)"),
    "E_LIBRARY":    (10, 40, 100, False, "Ver_Bau 12/2022 library 0.1-1.0 customers per m2 gross floor area, 0.40 chosen (Obertshausen 2023)"),
    "E_TRANSPORT":  (0, 0.125, 0.25, False, "Transport density 0.5 x industry visitors per employee"),
    "E_PARKING":    (0, 0, 0, False, "parking: the errands happen at the places people walk to"),
    "E_GEN_COS":    (0.5, 3.75, 20, True, "customer-oriented services density 2.0 / 3.0 / 4.0 x generic visitors per employee"),
    "E_GEN_SERVICES": (0.5, 2.95, 16.5, True, "Services density 2.0 / 2.36 / 3.3 x generic visitors per employee"),
    "E_GEN_RETAIL": (0.5, 4.375, 25, True, "small-scale retail density 2.0 / 3.5 / 5.0 x generic visitors per employee"),
    # business
    "B_OFFICE":     (0.625, 1.45, 3.3, False, "normal office 2.5 / 2.9 / 3.3 x office visitors per employee (FGSV 147 2006, Ver_Bau)"),
    "B_OPEN_PLAN":  (0.825, 2.075, 5.0, False, "open-plan office 3.3 / 4.15 / 5.0 x office"),
    "B_BOS":        (0.5, 1.75, 5.0, False, "business-oriented services 2.0 / 3.5 / 5.0 x office"),
    "B_COS":        (0.5, 1.5, 4.0, False, "customer-oriented services 2.0 / 3.0 / 4.0 x office"),
    "B_SERVICES":   (0.5, 1.18, 3.3, False, "Services 2.0 / 2.36 / 3.3 x office"),
    "B_RESEARCH":   (0.25, 0.625, 1.5, False, "research institutes 1.0 / 1.25 / 1.5 x office"),
    "B_PUBLIC":     (0.235, 0.65, 1.68, False, "Public facilities 0.94 / 1.30 / 1.68 x office"),
    "B_CUSTOMER_SERVICE": (0.825, 1.65, 3.3, False, "customer service 3.3 x office"),
    "B_CULTURE":    (0.4175, 0.835, 1.67, False, "entertainment, culture 1.67 x office"),
    "B_RETAIL":     (0.5, 1.75, 5.0, False, "small-scale retail 2.0 / 3.5 / 5.0 x office"),
    "B_HOSPITAL":   (0.25, 0.625, 1.5, False, "hospitals 1.0 / 1.25 / 1.5 x office"),
    "B_INDUSTRY":   (0, 0.3375, 0.75, False, "Industrial operations 1.2 / 1.35 / 1.5 x industry"),
    "B_HIGHLY_PRODUCTIVE": (0, 0.2125, 0.5, False, "highly productive industries 0.7 / 0.85 / 1.0 x industry"),
    "B_YARDS":      (0, 0.2125, 0.5, False, "yards, depots, storage 0.7 / 0.85 / 1.0 x industry"),
    "B_TRANSPORT":  (0, 0.125, 0.25, False, "Transport 0.5 x industry"),
    "B_WHOLESALE":  (0, 0.6125, 1.45, False, "wholesale 2.0 / 2.45 / 2.9 x industry"),
    "B_CRAFT":      (0.325, 0.95, 1.875, False, "craft businesses 1.3 / 1.9 / 2.5 x craft"),
    "B_VEHICLE":    (0.425, 1.25, 2.475, False, "vehicle / electrical repair 1.7 / 2.5 / 3.3 x craft"),
    # sports
    "S_FITNESS":    (15, 22.5, 30, False, "fitness 0.15-0.30 visitors per m2 gross floor area (VKT Usingen 2014, Ver_Bau); ITE 492 18-22.5"),
    "S_HALL":       (6.9, 9.4, 16.9, False, "club use of a single hall: 30.6 h a week x 20 persons x 0.9 (BISp planning parameters, Karlsruhe 2024) on 650-810 m2"),
    "S_POOL":       (10, 12.5, 15, False, "indoor pools 10-15 visitors per 100 m2 gross floor area (HSVV guidance, Oberschleissheim 2015)"),
    "S_ENT":        (10, 20, 30, False, "FGSV 147 Bild 3.11 entertainment 10-30 visitors per 100 m2 gross floor area"),
    "S_TENNIS":     (2.1, 4.5, 5.7, True, "an indoor court: 105 h a week x 85 % x 3 persons on 670 m2 (BISp planning norm, not a count)"),
    "S_RIDING":     (1, 2, 4, True, "no source: 15-30 riders a day plus stable visitors in a riding hall of about 1,200 m2"),
    "S_SHOOT":      (1, 3, 6, True, "no source: 2-3 club evenings a week with 15-40 shooters in about 300 m2"),
    "S_CLUB":       (10, 19, 29, True, "the users of a club's outdoor pitch on its clubhouse: 30 persons x 9.4-20.2 h a week (BISp), 1.5-2 h per visit assumed"),
    # meetup
    "M_CARE":       (0.5, 1.0, 2.5, False, "visitors of residents: 60 a day on 6,400 m2 (IKS Kassel 2018), 0.5 visitors per resident"),
    "M_WORSHIP":    (0.1, 0.3, 1.0, True, "a working day in a church, assumed; the 7-day mean of Sunday attendance (EKD 2024) is about 1.0"),
    "M_GASTRO":     (20, 43, 75, False, "Ver_Bau gastronomy 30-60 guest Wege per employee / 2 x 1.3-2.5 employees per 100 m2 (Ramboll 2024)"),
    "M_COMMUNITY":  (5, 10, 15, False, "TRICS 07/Q community centres: 6.08 vehicle arrivals per 100 m2 on weekdays x 1.8-2.5 persons, staff deducted"),
    "M_CULTURE":    (10, 20, 40, False, "theatre and cinema 20 persons per 100 m2 gross floor area (Ver_Bau, Ramboll 2024)"),
    "M_EVENTS":     (2, 5, 10, True, "event venues and centres used now and then: a quarter of the theatre rate, assumed"),
    "M_ASSOC":      (1.5, 5, 10, True, "associations, parties, parish offices: between the office business rate and the community-centre rate, assumed"),
    "M_HOSPVISIT":  (0.2, 0.4, 1.0, False, "visitors of inpatients: 0.5 per inpatient-day (Landsberg 2024)"),
    "M_PRISON":     (0.1, 0.2, 0.5, True, "inmate visitors: no source"),
    # lessons
    "L_SMALL":      (6, 9, 25, False, "Berlin music-school space standard: 5,238 pupils on 12,113 m2 gross, one lesson a week"),
    "L_DANCE":      (10, 20, 40, True, "a course room of 50 m2 with 12 persons x 3 sessions a day (Berlin standard) at half use, assumed"),
    "L_EDU":        (2.0, 3.3, 4.6, True, "learners per 100 m2 of school-labelled area in our data (VISUM pupils and students) x an attendance factor, assumed"),
    "L_FIRE":       (0.5, 1, 2, True, "volunteer fire, THW, DRK and DLRG training: one evening a week with 20-30 members, assumed"),
}
# Per outlet (errands; the value is split over the unit's non-work labels like an area): customers per
# working day of one outlet, whatever its floor area.
VISITOR_PER_OUTLET = {
    "pharmacy":    (170, 340, 340, False, "Ver_Bau 2012 input (Oberschleissheim 2015 Tab. 2): 5.0 customers per m2 of sales area, 339 for 68 m2"),
    "post_office": (45, 90, 90, True, "DHL 2026: about 2 M customers a day at about 22,400 outlets - seen in a search summary only"),
}
# The lookup (lib/floor_rules.visitor_rate_id): a POI unit by its own group and use, a building unit by its
# only POI's, then by the building's class (CMP: by the building's type words), else the label's default.
VISITOR_GROUP_RATES = {
    "errands": {"health_practice": "E_PRACTICE", "counter": "E_COUNTER", "personal_service": "E_PERSONAL",
                "public_office": "E_PUBOFF", "hospital": "E_HOSPITAL", "care_home": "E_SOCIAL", "vehicle": "E_VEHICLE",
                "fuel": "E_FUEL", "craft": "E_CRAFT", "transport": "E_TRANSPORT"},
    "meetup":  {"care_home": "M_CARE", "worship": "M_WORSHIP", "gastronomy": "M_GASTRO", "community": "M_COMMUNITY",
                "culture": "M_CULTURE", "office": "M_ASSOC", "public_office": "M_ASSOC", "sport": "M_COMMUNITY",
                "hospital": "M_HOSPVISIT", "fire_rescue": "M_ASSOC"},
    "lessons": {"school": "L_EDU", "fire_rescue": "L_FIRE", "community": "M_COMMUNITY", "culture": "M_COMMUNITY",
                "worship": "M_COMMUNITY", "office": "M_ASSOC", "public_office": "M_ASSOC"},
}
VISITOR_CLASS_RATES = {
    "business": {"normal office": "B_OFFICE", "open-plan office": "B_OPEN_PLAN", "business-oriented services": "B_BOS",
                 "customer-oriented services": "B_COS", "Services": "B_SERVICES", "research institutes": "B_RESEARCH",
                 "Public facilities": "B_PUBLIC", "customer service": "B_CUSTOMER_SERVICE", "entertainment, culture": "B_CULTURE",
                 "retail (small-scale)": "B_RETAIL", "hospitals": "B_HOSPITAL", "Industrial operations / Production": "B_INDUSTRY",
                 "highly productive industries / machine / material or space intensive": "B_HIGHLY_PRODUCTIVE",
                 "Yards, depots, storage areas, construction yards": "B_YARDS", "Transport": "B_TRANSPORT",
                 "wholesale": "B_WHOLESALE", "craft businesses": "B_CRAFT", "vehicle / electrical repair": "B_VEHICLE",
                 "hotels": "ZERO"},
    "errands": {"customer-oriented services": "E_GEN_COS", "normal office": "E_PUBOFF", "Services": "E_GEN_SERVICES",
                "hospitals": "E_HOSPITAL", "retail (small-scale)": "E_GEN_RETAIL", "Public facilities": "E_PUBOFF",
                "vehicle / electrical repair": "E_VEHICLE", "Yards, depots, storage areas, construction yards": "B_YARDS",
                "nursing homes": "E_SOCIAL", "craft businesses": "E_CRAFT", "Industrial operations / Production": "B_INDUSTRY",
                "Transport": "E_TRANSPORT", "customer service": "E_COUNTER", "business-oriented services": "B_BOS",
                "open-plan office": "B_OPEN_PLAN", "car dealerships": "E_VEHICLE", "entertainment, culture": "E_PUBOFF"},
    "sports":  {"fitness / wellness": "S_HALL", "Facilities for culture, leisure and sports": "CMP", "schools": "S_HALL",
                "entertainment, culture": "CMP", "large discos, fun / leisure pools": "S_POOL", "arenas, large events": "S_HALL"},
    "meetup":  {"nursing homes": "M_CARE", "restaurants / gastronomy": "M_GASTRO", "Services": "M_ASSOC", "normal office": "M_ASSOC",
                "hospitals": "M_HOSPVISIT", "customer-oriented services": "M_ASSOC", "fitness / wellness": "M_COMMUNITY",
                "entertainment, culture": "CMP", "Public facilities": "CMP", "Facilities for culture, leisure and sports": "CMP"},
    "lessons": {"schools": "L_EDU", "universities": "L_EDU", "customer-oriented services": "L_SMALL", "fitness / wellness": "CMP",
                "Facilities for culture, leisure and sports": "CMP", "Public facilities": "L_FIRE", "normal office": "M_ASSOC",
                "entertainment, culture": "M_COMMUNITY", "Services": "L_FIRE", "business-oriented services": "L_SMALL",
                "Yards, depots, storage areas, construction yards": "L_FIRE", "hospitals": "L_EDU"},
}
# CMP classes: the first pattern found in the building's step-05 type gives the rate, else the second item
VISITOR_TYPE_RATES = {
    "sports":  ([(r"riding|equestrian|\breit", "S_RIDING"), (r"shooting|sch[uü]tzen", "S_SHOOT"),
                 (r"club ?house|sportheim|vereinsheim", "S_CLUB"), (r"swimming|\bpool|\bbad\b", "S_POOL"),
                 (r"sports hall|gymnasium|turnhalle|sporthalle|sports centre|sports facility", "S_HALL")], "S_HALL"),
    "meetup":  ([(r"church|chapel|religious|monastery|parish|kirche|kapelle", "M_WORSHIP"), (r"prison|correctional", "M_PRISON")],
                "M_COMMUNITY"),
    "lessons": ([(r"riding|equestrian|\breit", "S_RIDING"), (r"swimming|\bpool|\bbad\b", "S_POOL"), (r"dance|ballet|martial", "L_DANCE")],
                "S_HALL"),
}
VISITOR_DEFAULT_RATES = {"business": "B_SERVICES", "errands": "E_GEN_SERVICES", "sports": "S_HALL", "meetup": "M_ASSOC",
                         "lessons": "L_EDU"}
# the POI uses of the sports rates (also read for lessons at sport POIs), of dance schools and of event venues
VISITOR_SPORT_USES = {
    "S_FITNESS": frozenset({"fitness_centre", "fitness", "crossfit", "gym"}),
    "S_POOL":    frozenset({"swimming", "swimming_pool", "public_bath", "water_park", "sauna", "diving"}),
    "S_ENT":     frozenset({"9pin", "10pin", "bowling", "karting", "laser_tag", "indoor_play", "trampoline_park", "climbing",
                            "escape_game", "amusement_arcade", "minigolf"}),
    "S_TENNIS":  frozenset({"tennis", "padel", "squash"}),
    "S_RIDING":  frozenset({"equestrian", "horse_riding", "riding_school", "riding_hall"}),
    "S_SHOOT":   frozenset({"shooting", "archery"}),
    "L_DANCE":   frozenset({"dancing_school", "dance", "dojo", "martial_arts", "yoga", "dancing", "ballet"}),
    "S_HALL":    frozenset({"sports_centre", "sports_hall", "multi", "gymnastics", "sport", "athletics", "soccer", "table_tennis",
                            "handball", "basketball", "volleyball", "badminton", "dog_agility", "bowls", "motor", "ice_skating",
                            "boxing", "judo", "karate", "fencing", "roller_skating", "skateboard", "billiards", "darts", "chess",
                            "juggling", "multisport"}),
}
VISITOR_DANCE_USES = VISITOR_SPORT_USES["L_DANCE"]
VISITOR_EVENTS_USES = frozenset({"events_venue", "events_centre"})
VISITOR_CAR_USES = frozenset({"car", "motorcycle", "truck"})
# a small-format rate applies only up to the group's POINT_SIZE_CAP_M2 (or the default cap)
VISITOR_SMALL_FORMAT_GROUPS = frozenset({"gastronomy", "small_retail", "personal_service", "counter", "health_practice",
                                         "community", "small_school"})
# staff-only places: a POI or building whose name or type says so, or a cafe / practice POI in a building of
# these classes (a company site)
VISITOR_STAFF_ONLY_PATTERN = (r"\bcanteen|\bkantine|\bcafeteria|\bstaff (?:restaurant|caf[eé])|\bbetriebsrestaurant|\bwerksrestaurant"
                              r"|\bbetriebsarzt|\bwerksarzt|\barbeitsmedizin|occupational (?:health|medicine)|\bcompany doctor")
VISITOR_STAFF_ONLY_GROUPS = frozenset({"gastronomy", "health_practice"})
VISITOR_STAFF_ONLY_CLASSES = frozenset({"Industrial operations / Production",
                                        "highly productive industries / machine / material or space intensive", "others",
                                        "Yards, depots, storage areas, construction yards", "Transport"})
# Zones with a target of 0 whose places carry the category (the user, 2026-10-06, for Workers): VISUM counts some staff in a
# neighbouring zone - the Autostadt's (Workers target 0) in the VW plant zone: "people also work here along with people
# working in the factories". Such a zone's units join the zones of the nearest ring that have a target, each unit's weight
# split over them in proportion to their targets (so mostly the plant zone), and share those targets by weight with the
# zones' own carriers; the regional total stays VISUM's. Totals are ignored only for the five labels without a total. In
# the first run of the floor rules: 88 zones with 942 active buildings (the Autostadt, WOB Kaestorf 3, WOB Kreuzheide 1,
# Tappenbeck 2, the Koenigslutter hospital zone, the Helmstedt power-plant zone, the Harz zones Torfhaus / Okertalsperre).
# Extended on 2026-10-07 (the user: "Share, touching zones only") to University, Kindergarten and School: a zone border cuts
# through a campus, and VISUM counts all its students or pupils on one side. The TU Braunschweig's Biozentrum, BRICS and
# university library (BS Altes Hochschulviertel 7, University 0) got nothing while the Chemistry Centre next door took 6,131
# students, 16 % of the region; before, 34 zones with university places, 74 with school places and 88 with Kitas had a
# total of 0, and their places 31 % of the university floor. For these three only the zones that touch it count (ring 1):
# a place whose touching zones have no total either takes nothing from the sharing rather than pulling students from a
# campus further away (the ring fallback of a zone without a place may still reach it) - until 2026-10-08, when such a
# place was allowed to look up to ring 3 (REDIST_SHARE_ZERO_TARGET_FAR_RINGS below).
# School goes by type here too: a place that joins a zone takes that zone's types as one of its school places.
# Revised the same day after an independent check (the user: "Spread over touching zones"): a place joins only zones that
# have places of their own. A zone with a target but no place keeps the ring fallback as before (its touching zones, or the
# next ring out where they hold no place); when the places of its zero-total neighbour took its whole target, Seesen 07's
# 587 pupils went to a village hall and a sports hall, and the Otto-Bennemann-Schule fell to 0. A joined school place splits
# its weight by the zones' targets of its own types, so a vocational school parks no weight in zones without vocational
# pupils - unless none of its touching zones has any: it then joins by their School totals and takes only a type its pool
# has no place for (since 2026-10-08 it first looks up to ring 3 for its own types). The reach stayed ring 1 (the user:
# "Touching zones, as decided"); a 500 m limit would have cut long rural joins but returned real village schools and Kitas
# to 0.
REDIST_SHARE_ZERO_TARGET_CATEGORIES = ("Workers", "School", "University", "Kindergarten")
REDIST_SHARE_ZERO_TARGET_MAX_RINGS = {"Workers": None,          # None: the nearest ring with a target, however far (2026-10-06)
                                      "School": 1, "University": 1, "Kindergarten": 1}
# A place with nothing it could take next door (the user, 2026-10-08: "Up to 3 zones"): where no touching zone holds a total
# of the category - a school place: of its own types -, with places or without, the place joins the nearest ring up to this
# one with zones that have such a total and places of their own, its weight split by those totals. Ring 1 alone left 34
# named or mapped places at 0: Schule Stoeckheim (secondary; no secondary pupils next door), Schule Lehndorf-Ort, the
# Johannes-Selenka-Schule branch at the Hamburger Strasse, BBS VII, the Hellwinkel Berufsschule, the Welfenakademie, the TU
# institute on the Pappelberg and 10 Kitas. Up to ring 3 reaches all 34 and moves 1.0 % of School, 2.9 % of University (the
# Welfenakademie takes 451 students from the Ostfalia Wolfenbuettel zones) and 1.1 % of Kindergarten; ring 2 would have left
# BBS VII, the Pappelberg institute, the Welfenakademie and the school in Mariental 4 at 0. A place whose touching zones
# hold a total it could take keeps ring 1 (where that zone has no place, its ring fallback reaches the place): the research
# buildings in Goslar 20, reached that way, would otherwise have pulled 374 more students from the TU Clausthal campus. A
# place fed only by the ring fallback of a zone further out still looks further: the Oskar Kaemmer Bildungswerk goes from 50
# to 175 pupils (Schule Diesterwegstrasse 348 -> 243) and two TU buildings at the Prinzenpark from 125 to 203 students.
REDIST_SHARE_ZERO_TARGET_FAR_RINGS = {"School": 3, "University": 3, "Kindergarten": 3}
# Near-zero totals (the user, 2026-10-08; item 3 of the audit of run 7: "Share below 1 %", "Touching zones only"): a zone
# whose total is above 0 but below max_share of its own Bosserhof expectation (the sum of its Workers weights / 100, i.e.
# occupied floor / 100 m2 x Bosserhof rate), with min_expected or more expected, counts as a zone with a target of 0 for the
# sharing above: its units also join the zones within max_ring that have a total which is not near zero and places of their
# own, each unit's weight split by their totals; it keeps its own small total on its own units and is joined by no zone.
# The 34 such zones are all residential zones in VISUM with a median total of 1.8 Workers (107 together for 19,224
# expected), yet they hold the Staedtisches Klinikum Wolfenbuettel (over 1,300 staff with its subsidiaries, total 5.98), the
# MobileLifeCampus, the Finanzamt Wolfenbuettel and schools; the Workers column is right (SG_3_BE~17 is the sum of the
# sector columns, and no other column holds the jobs). The sharing moves 16,759 Workers (2.8 %): MobileLifeCampus
# 16 -> 2,525, the Klinikum's main building 3 -> 60, the Finanzamt 2 -> 141, Velpke 1 0.02 -> 13. Costs: 24 zones lose over
# a quarter of their total, 16 of them below 3x their expectation (8 below the regional 0.8x; BS Leiferde 1, next to the
# Klinikum, -78 %); inside a near-zero zone every place takes the same multiple of its rate, so Edemissen 07 ends at 5.9x
# its expectation (mostly from Peine 15 and Edemissen 01: Grundschule Abbensen 135 Workers, two Kitas over 100) and WB Krz
# Holz 18 at 5.1x, as the Vechelde villages under the zero-total sharing. Zones with a target of 0 no longer join a
# near-zero zone: Helmstedt 25 goes to ring 2 (0.18 -> 35 Workers), and together they hold 619 fewer (22,733 -> 22,114).
# Hohegeiss 03 (Harz holiday flats) finds no touching zone with a total and keeps only its own; the nearest ring would have
# pulled 1,024 Workers into it, 872 of them from 27-44 km away. Not taken: 2 % (53 zones, 29,557 Workers - the closed
# Fliegerhorst barracks in Goslar 07 would take 531 from a normal industrial zone), sharing only beside over-full zones,
# and leaving the totals as they are. The PTB zone (BS Bundesanstalten 1, 3.8 %) is above the threshold and keeps 161
# Workers for about 1,700 staff, and the Klinikum stays far below its staff, its neighbours holding no surplus - cases for
# the VISUM owner, like the split of SZ Watenstedt 01/02.
REDIST_SHARE_NEAR_ZERO_TARGET = {"Workers": {"max_share": 0.01, "min_expected": 100.0, "max_ring": 1}}
# School by type (the user, 2026-10-06). The School target is three VISUM columns: pupils of primary schools (SG_4_GSCH,
# 39,085), of secondary schools (SG_4_WFSCH, 77,622) and of vocational schools (SG_4_BS, 33,292 - the Braunschweig-Kolleg and
# the Wolfsburg-Kolleg count here too: their zones hold BS pupils and no other school; the largest BS zones hold only BBS).
# Each goes to the zone's school places of its own type, in proportion to their weight. A zone without a place of a type
# gives that type to all its school places, as before, so every zone keeps its School total; a zone without any school
# place sends its target to its ring as before, and the ring's places split it by type the same way. 64 zones have pupils
# of more than one type.
SCHOOL_TYPE_COLUMNS = {"primary": "SG_4_GSCH", "secondary": "SG_4_WFSCH", "vocational": "SG_4_BS"}
# A place's types come from its own name and step-07 type (a POI); else from its building's name, its POI names (step 04),
# its site names (step 06) and its step-05 type; else from the building's ALKIS function; else primary and secondary
# (SCHOOL_TYPE_DEFAULT: general education - vocational schools are named as such, and a zone without a vocational place
# still gives its vocational pupils to all its school places). The names are
# German and are matched without case. The model's types are English, and its secondary-school words are matched with case:
# "(gymnasium)" there is a sports hall, "Gymnasium" or "Lessinggymnasium" a grammar school. Special schools, Waldorf and
# international schools teach primary and secondary pupils ("both"); Fach-, Abend- and berufliche Gymnasien, the Kollegs and
# the nursing and midwifery schools are vocational.
SCHOOL_TYPE_PATTERNS = {
    "vocational":     (r"berufsbild|berufsschul|berufsfach|fachschul|fachober|fachgymn|berufliches gymn|berufskolleg|\bBBS\b|kolleg\b"
                       r"|abendgymn|pflegeschul|hebammenschul|vocational|nursing school|technical college|trade school"
                       r"|evening (?:secondary|grammar) school"),
    "both":           (r"förderschul|foerderschul|förderzentrum|sonderschul|special[- ]needs|special school|special education|waldorf"
                       r"|internationale schule|international school"),
    "primary":        r"grundschul|\bgrund-|primary|elementary|volksschul|\bG(?:H)?S\b",
    "secondary_name": (r"gymnasium|realschul|hauptschul|oberschul|gesamtschul|\bIGS\b|\bKGS\b|sekundar|mittelschul|schulzentrum|\bHRS\b"
                       r"|\bOBS\b|\bGHS\b"),
    "secondary_type": (r"secondary|grammar school|comprehensive|Gymnasium|[a-zäöüß]gymnasium|Realschul|Hauptschul|Oberschul|Gesamtschul"
                       r"|\bIGS\b|\bKGS\b|Schulzentrum"),
}
# cut from the texts before the secondary words are read (these are vocational)
SCHOOL_TYPE_STRIP_PATTERN = r"fach-?gymnasium|abend-?gymnasium|berufliches gymnasium|evening (?:secondary|grammar) school"
SCHOOL_TYPE_ALKIS = {"31001_3021": ("primary", "secondary"),    # general education school
                     "31001_3022": ("vocational",)}             # vocational school
SCHOOL_TYPE_DEFAULT = ("primary", "secondary")                  # no evidence at all (167 units in the first run)
# Who carries School, University and Kindergarten (the user, 2026-10-07; item 5 of the audit of run 7). The education labels come
# from the model (steps 05 and 07); lib/edu_carriers.py corrects them from evidence already in the data - names, ALKIS functions,
# the OSM tags of POIs, sites and building outlines, the model's type text - and never re-runs the model. Decided on an
# independent analysis (five sweeps over every carrier, a design with simulated effects, two checks):
#   * "Drop it, also without evidence": a unit whose own data name another use loses the education label - a former school, a
#     village hall, adult / out-of-school education, a Kita building, another occupant of a school site; a social facility,
#     children's and youth homes, elderly day care, youth clubs, a Kita lot on a church / school / fire station, an all-day school
#     programme; continuing education, a university rest unit without a university building - and so does a place with no
#     evidence at all (an annex within 100 m of a school keeps School). A School place in a zone with a School total of 0 known
#     only from the cadastre or a bare OSM school outline, with no school POI or site within 100 m, joins no neighbour and takes
#     no ring fallback;
#   * "Labels and types": real schools typed after a tenant (their Mensa, their Kita) or labelled lessons get the school label;
#     vocational schools labelled university become vocational School; the school types follow the model's English type words,
#     OSM isced / grades tags, vocational campuses and the Oskar-Kaemmer sites (vocational);
#   * "Drop, Mensas too; 3 unclear keep": non-teaching campus parts - Mensa, administration, computing, events, student body,
#     museum, incubator, boarding houses, toilets ... - lose School / University; a building is the Mensa only where Mensa outlines
#     cover at least 80 % of it; the Gauss-IT-Zentrum, ZeLL and the Haus der Wissenschaft keep their students;
#   * "Cap at own size, lift squeezed": the Kita part of a school weighs at most its own polygons (else the childcare point cap)
#     and gives the rest to School where the unit carries School; a Kita polygon weighs at most its area x its storeys (split
#     over its labels like any weight); a squeezed Kita POI weighs its own extent. Only the Kita weight changes.
# A dropped label leaves its floor share empty (k_red unchanged), so no other category moves, and the last-carrier guard restores a
# zone's only carrier. The two checks of the design (2026-10-07) corrected it before it went in: no Kleine-Burg entry (it named a
# shop building), the Mensa part test also for University, 80 % instead of 50 %, general-school sites are no vocational campus.
# Texts are matched folded (lower case, umlauts as ae / oe / ue, ss).
EDU_CARRIER_RULES = {
    # --- the words ---------------------------------------------------------------------------------------------------
    "school_type_word": (r"berufsbild|berufsschul|berufsfach|fachschul|fachober|fachgymn|berufliches gymn|berufskolleg|\bbbs\b|kolleg\b"
                         r"|abendgymn|pflegeschul|hebammenschul|foerderschul|foerderzentrum|sonderschul|waldorf|internationale schule"
                         r"|grundschul|\bgrund-|volksschul|\bg(?:h)?s\b|gymnasium|realschul|hauptschul|oberschul|gesamtschul|\bigs\b|\bkgs\b"
                         r"|sekundar|mittelschul|schulzentrum|\bhrs\b|\bobs\b|\bghs\b"),
    "school_type_word_en": (r"primary|elementary|secondary|grammar school|comprehensive|special[- ]needs|special school|special education"
                            r"|nursing school|technical college|trade school|gymnasium|realschul|hauptschul|oberschul|gesamtschul"
                            r"|grundschul|berufsschul|\bbbs\b"),
    "vocational_school_name": (r"optiker|physiotherap|ergotherap|logopaed|pflegeschul|krankenpflege|altenpflege|hebammen|rettungs"
                               r"|\bmta\b|\bpta\b|podolog"),     # a health-profession school is vocational (the annex test)
    "school_general_word": (r"grundschul|gymnasium|realschul|hauptschul|oberschul|gesamtschul|\bigs\b|\bkgs\b|foerderschul|schulzentrum"
                            r"|primary|secondary"),
    "school_any": r"schul|school|gymnas",
    "kita_strong": (r"kita|kindertagesstaett|kindergarten|kiga|krippe|hort\b|kindergruppe|spielkreis|kindertagespflege|tagesmutter"
                    r"|tagesvater|grosstagespflege|tagespflegestelle|schulkindbetreuung|schulkindgruppe"),
    "kita_not": (r"kinderheim|jugendheim|jugendhilfe|erziehungshilfe|wohngruppe|kinderdorf|inobhutnahme|jugendwohn|jugendzentrum"
                 r"|jugendtreff|jugendclub|jugendhaus|jugendfreizeit|bauspielplatz|abenteuerspielplatz|(?<!kinder)(?<!gross)tagespflege(?!stelle)"
                 r"|seniorentag|altentages|familienentlast|muetterzentrum|mehrgenerationenhaus"),
    "kita_type_en": r"\bkita\b|kindergarten|kindertages|creche|nursery|day[- ]?care|childcare|child care|krippe",
    "univ_word": r"universit|(?<!volks)hochschul|\btu\b|ostfalia|\bhbk\b|fakult|hoersaal|audimax",
    # --- not that kind of place (D1) and non-teaching parts (D3): School -----------------------------------------------
    "school_alkis": ["31001_3021", "31001_3022"],
    "former_school_name": r"\balte[nrs]?\s+(?:\w+\s+)?\w*schule",
    "village_house": r"\bdgh\b|dorfgemeinschaftshaus|buergerhaus|gemeinschaftshaus|gemeindezentrum|community cent(?:re|er)",
    "adult_education": (r"akademie|academy|volkshochschul|\bvhs\b|bildungshaus|bildungsstaette|bildungswerk|(?<!berufs)(?<!landes)bildungszentrum"
                        r"|lehranstalt|berufsfoerderungswerk|forst\w* (?:bildungs|ausbildungs)|forestry|kunstschule|musikschule|art school"
                        r"|music school|verkehrsschule|traffic school|nachhilfe|tutoring|lernstudio|schuelerhilfe|studienkreis"
                        r"|(?<!state )education(?:al)? cent(?:re|er)|jugendwerkstatt|youth workshop|bildungs-? (?:und|&) kultur"),
    "adult_education_keep": r"technikakademie|steinmetz|os[ck]ar[- ]?k(?:ae|a)mmer",     # vocational schools despite the word
    "other_occupant_ok_uses": ["school", "sports_hall", "sports_centre", "library", "theatre", "kindergarten", "childcare"],
    "type_tail": r"\s+(?:on|at|in|of|near|within)\s+",
    "near_school_m": 100.0,
    "school_mensa_name": r"^\s*(?:mensa|speisesaal|kantine)(?:haus|gebaeude)?\b",
    "school_board_name": r"^\s*(?:internat|jungenhaus)",
    "school_mensa_head": r"canteen|cafeteria|dining hall|mensa",
    "school_other_head": r"boarding house|dormitor|\binternat\b|administrat|secretariat|toilet|sanitary|heating|garage|storage",
    "school_teaching_head": r"boarding school(?!\s+(?:dormitor|house|residence))|classroom|teaching|lecture",
    "school_head_tail": r"\s+(?:of|for|at|on|in)\s+",
    "mensa_outline_name": r"mensa|speisesaal|kantine|canteen|cafeteria|dining|refectory",
    "mensa_min_cover": 0.8,
    # --- Kindergarten ----------------------------------------------------------------------------------------------------
    "kita_uses": ["kindergarten", "childcare"],
    "social_uses": ["social_facility", "day_care"],
    "kita_other_use_alkis": r"^31001_(?:304\d|3061|3072|3211)$",
    "kita_other_use_osm": ["school", "church", "chapel", "cathedral", "fire_station", "sports_hall"],
    "kita_other_use_name": r"schule|kirche|gemeindehaus|dorfgemeinschaftshaus|feuerwehr|sporthalle|turnhalle|jugend",
    "all_day_school": r"ganztag|\bogs\b",
    # --- University ------------------------------------------------------------------------------------------------------
    "univ_alkis": ["31001_3023", "31001_3024"],
    "univ_uses": ["university", "college"],
    "continuing_education": (r"weiterbildung|continuing education|adult education|volkshochschul|\bvhs\b|bundesakademie|handwerker-institut"
                             r"|crafts training|coding|berufsfoerderungswerk|retraining"),
    "univ_non_teaching": (r"\bevents?\b|administrat|verwaltung(?!sgericht)|service office|servicebuero|studienberatung|sekretariat"
                          r"|gleichstellung|personalrat|technologietransfer|geschaeftsstelle|hochschuldidaktik|lehren und lernen|bafoeg"
                          r"|stabsstelle|\basta\b|studierendenhaus|studentenzentrum|fachschaft|museum|sammlung|rechenzentrum|computing cent"
                          r"|data cent|pfoertner|chemikalien|\bsupply\b(?! engineer)|heating plant|betriebstechnik|gruendungszentrum|incubator"),
    "dining": r"mensa|cafeteria|canteen|dining",
    "univ_teaching_head": r"lecture hall|hoersaal|teaching building|faculty building|fakultaetsgebaeude|institut|research cent",
    "univ_keep_ids": ["DENIAL0100005Y9F", "way/24385572", "DENIAL0100005WGk#rest"],   # Gauss-IT-Zentrum, ZeLL, Haus der Wissenschaft
    "univ_drop_ids": ["DENIAL0600001Ate", "DENIAL0300008Gkk"],   # SAB Schiessanlage; Walther-Nernst-Str. 3 Clausthal (no rule fits)
    # --- the right label and type (D2) ------------------------------------------------------------------------------------
    "add_school_min_floor_m2": 2000.0,
    "school_name": (r"(?<!musik)(?<!kunst)(?<!tanz)(?<!fahr)(?<!sprach)(?<!volkshoch)(?<!hoch)(?<!verkehrs)schul|gymnasium|kolleg\b|\bbbs\b"
                    r"|\bigs\b|\bkgs\b"),
    "replaced_use": (r"volkshochschul|\bvhs\b|adult education|akademie|bildungszentrum|bildungswerk|bildungsstaette|berufsfoerderungswerk"
                     r"|musikschul|music school|tanzschul|dance school|museum|jugendamt|refugee|fluechtling|\bdgh\b|dorfgemeinschaft"
                     r"|kulturverein|wohngruppe|ehemalig|former|alte schule|hochschul|universit"),
    "vocational_word": (r"kolleg\b|fachschul|berufsbild|berufsschul|berufsfach|altenpflege|pflegeschul|hebammenschul|rettungsschul|\bbbs\b"
                        r"|vocational|(?<!weiter)bildungszentrum"),
    "not_vocational": r"studienseminar|universit|ostfalia|\btu\b|akademie|berufsfoerderungswerk",
    "not_vocational_type": r"berufsfoerderungswerk",
    "lessons_not_school": (r"musik|music|tanz|dance|ballet|fahrschul|driving|sprach|language|nachhilfe|tutoring|vhs|volkshochschul"
                           r"|studienseminar|teacher[- ]training|lehrerausbildung|flug|flight"),
    "type_text_fixes": [(r"vocational secondary", "vocational"), (r"Gymnasium \((?:sports hall|gym[^)]*)\)", "sports hall")],
    "oskar_kaemmer": r"os[ck]ar[- ]?k(?:ae|a)mmer",
    "oskar_kaemmer_not_site": r"remenhof",
    # --- Kita weights (D4) -----------------------------------------------------------------------------------------------
    "kita_polygon_max_cover": 0.8,
    "kita_point_merge_m": 15.0,
    "kita_squeezed_share": 0.25,
    "kita_median_part_m2": 227.0,
    # --- the inputs ------------------------------------------------------------------------------------------------------
    "outline_buildings": ["school", "university", "college", "kindergarten", "church", "chapel", "cathedral", "fire_station",
                          "sports_hall", "ruins", "abandoned", "disused"],
    "outline_amenities": ["school", "university", "college", "kindergarten", "childcare", "fire_station"],
}
# The Workers sectors - only a check (the user, 2026-10-06). VISUM also splits each zone's Workers into three sectors, each
# in two (SG_3_BES~8 = ~9 + BE~10, BE~11 = ~12 + ~13, BE~14 = ~15 + ~16; the three add up to SG_3_BE~17 in every zone), but
# with one fixed mix per city or district for all its zones (Braunschweig 21.0 / 19.8 / 59.2 %, Wolfsburg 61.1 / 10.4 /
# 28.5 %; in the Landkreise per municipality). So the split says nothing about the places inside a zone and is not used for
# the allocation; notebook 08 prints our Workers per sector and district next to VISUM's. A class's sector is a reading of the
# building type, so the two cannot match exactly: the statistics count a VW office as industry, we count it as an office.
WORKER_SECTOR_COLUMNS = {"industry": "SG_3_BES~8", "trade, transport, hospitality": "SG_3_BE~11", "other services": "SG_3_BE~14"}
WORKER_SECTOR_CLASSES = {                       # every class not listed: other services
    "industry": frozenset({"Industrial operations / Production", "highly productive industries / machine / material or space intensive",
                           "others", "craft businesses", "craft courtyards", "Crafts and trades"}),
    "trade, transport, hospitality": frozenset({"retail (small-scale)", "Retail", "discount stores", "DIY stores", "furniture stores",
                                                "hypermarkets / superstores", "shopping centers", "self-service department stores",
                                                "department stores", "factory outlet centers", "wholesale", "car dealerships",
                                                "suppliers for car dealerships", "vehicle / electrical repair", "restaurants / gastronomy",
                                                "hotels", "hotels with conference areas", "Transport",
                                                "Yards, depots, storage areas, construction yards"}),
}
ZONE_DISTRICT_COL = "RO_LANDK~1"                # the city or district (Landkreis) of a zone
# The labels of steps 06 and 07 reconciled by OSM use (the user, 2026-10-08; item 4 of the audit of run 7; lib/label_rules.py,
# notebook 08 sections 4.4c, 4.6b and after 4.7). Step 06 labelled each building whole - a building with one POI was not asked
# again - and step 07 each POI of a shared building on its own. Both used the same label definitions, yet they read the same kinds
# of place differently: fast food carried retail_daily on 44 % of the one-POI buildings (144 of 326) and on 6 % of the asked POIs
# (14 of 240); 46 of 136 asked pharmacies were errands only while all 128 pharmacy buildings carried retail_daily; a beverage
# market was retail_non_daily in 35 % of the buildings and 4 % of the POIs; a travel agency retail_non_daily in 19 of 31 buildings
# and 0 of 45 POIs; and 46 pools, bowling alleys, climbing halls and an ice rink carried sports without leisure next to 135 venues
# of the listed kinds (92 of them pools) that carry it. The rules set what such a place carries from its own OSM use and data
# (the user chose every recommendation):
#   * eating_places "Leisure, not retail": an eating or drinking place carries leisure instead of retail_daily /
#     retail_non_daily - eating out is free time by the definitions (MiD: Freizeit). A building filed in another class than a
#     restaurant or small shop (a hospital, hotel, clubhouse, pool or parking deck with a cafe) only loses the retail labels;
#     shops with seating (bakery cafes, butchers, a kiosk that is no food or snack kiosk, a book cafe ...) and buildings filed as
#     stores keep theirs, and so do staff canteens and Mensas (item 6 of the audit);
#   * pharmacies and fuel ("All three rules", with daily_shops): a pharmacy carries retail_daily - medicines and drugstore goods
#     are daily needs; this is the pharmacy's own use, not errands feeding Retail_Daily, which still feeds nothing (2026-10-05).
#     A fuel station carries retail_daily for its shop, unless its data show it has none (an automat, a private pump, a gas-only
#     pump, a works, dealer, farm or airfield pump): there retail_daily becomes errands, the refuelling itself (visitor rate 0),
#     after the canopy pass of 4.7, so that a shop a canopy passed it to is caught too. A building typed as a car wash is left alone;
#   * daily_shops: a beverage market, kiosk, newsagent, tobacco or lottery shop carries retail_daily instead of
#     retail_non_daily; wine, spirits, sweets and e-cigarette shops keep their reading (occasional or specialist goods; for tobacco
#     and lottery, which both runs also read as retail_non_daily, the definition and MiD decide), and producers' own shops and
#     souvenir / tourist / pool kiosks are left out;
#   * services "No RND for services": the POI groups counter and personal_service (beauty salons, travel agencies, tailors,
#     rentals, tattoo studios, betting shops, photographers, insurance ...) carry no retail_non_daily - they sell a service;
#     phone shops, post counters and six listed shops that also sell goods keep it. The rest unit of a building whose active asked
#     POIs are all such services loses it too;
#   * venues "Venues get leisure": a public pool, ice rink, bowling alley, climbing hall (and kart track, trampoline park, mini
#     golf, escape room, laser tag, indoor play centre) labelled sports gets leisure too, from its own OSM values, name, type head
#     or ALKIS function; never a school, therapy, hotel, club, fitness or private pool, a private or closed POI, nor a building
#     without a POI, a name or a site (the cadastre still lists the Peine pool demolished in 2018). Sports still never feeds Leisure;
#   * rest_sources "The POI's answer wins": a Retail_Daily, Retail_Non-Daily or Leisure rest label goes where an active asked POI
#     of the same building is its evident source - step 06 gives that label to at least min_rate of the one-POI buildings of that
#     POI's use (of its group where the use has fewer than min_n such buildings) - and step 07 labelled that POI without it
#     (HORNBACH's grill bar gave the DIY store 2,900 Retail_Daily). A rest label that a dropped non-occupant POI carries, or that
#     the building's own data name (own_evidence), stays even where a POI is its evident source, and so does one without any source
#     (keep all, 2026-10-02). For community centres this takes step 07's meetup reading: 7 of their Leisure rest labels go (the
#     guard keeps 2);
#   * a label a rule takes off a POI does not come back as a rest unit of its building; a dropped label's share goes to the unit's
#     other labels and an added label takes a share ("Goes to its other labels": the place then counts like an equal place the
#     model read right), while the education drops of 2026-10-07 keep their share empty.
# The last-carrier guard keeps a zone's only carrier of a category: that category stays on it at its weight before the rules, and
# a label a label rule took off counts again in its unit's split. Effect against run 13: Retail_Daily 42,864 moved (4.72 %),
# Retail_Non-Daily 24,548 (3.16 %), Leisure 9,423 (4.23 %); Workers, School, University and Kindergarten unchanged; errand
# visitors -7,663 a day (the 46 pharmacies share their floor with retail_daily now), sports -2,294 (the venues with leisure).
# HORNBACH's rest unit 2,900 Retail_Daily -> 0, Globus Baumarkt Salzgitter (DENIAL050000bTEd) 1,917 -> 0, VW Halle 6 1,116 -> 0
# (the VW Oase staff restaurant's own rest unit goes 386 -> 1,014 - item 6), SELGROS 432 Retail_Non-Daily -> 0; the Eissporthalle
# Salzgitter 0 -> 1,200 Leisure and the Vereinsheim next to it 1,036 -> 79; Shawarma Hut 703 Retail_Daily -> 55 Leisure; Hol'ab in
# WB Linden 20 (DENIAL060000cN4P) 83 Retail_Non-Daily -> 912 Retail_Daily; the Apotheke Am Schwarzen Berge's Retail_Daily moves
# from a 74 m2 rest unit onto the pharmacy (its building 776 -> 1,164); 33 station units without a shop give up retail_daily for
# errands. Rest units hold Retail_Daily 2,172 (was 15,610), Retail_Non-Daily 10,155 (12,715) and Leisure 648 (1,137). The guard
# restores 17 more rows than in run 13 (27 in all), each a zone's only carrier: the rest unit of the building with two tattoo
# studios keeps the 2,584 Retail_Non-Daily of BS Wilhelmitor - Sued 5, the M+C Doener its 241 Retail_Daily. No zone is newly on
# the ring fallback (Retail_Daily 33 -> 32 zones, Leisure 83 -> 81). The labels in the output file stay as the model gave them;
# the rules show in the values only. Not covered (seen in the scan, not decided): community centres as places (leisure on 52 % of
# the one-POI buildings, 31 % of the asked POIs), coffee shops, wholesale, dance halls, historic places, and step 06's
# retail_daily / retail_non_daily split on buildings without a POI.
LABEL_RULES = {
    "eating_places": {
        "uses": ("restaurant", "fast_food", "cafe", "pub", "bar", "ice_cream", "biergarten", "food_court", "hookah_lounge", "internet_cafe",
                 "outdoor_seating"),                                   # POI_GROUPS gastronomy without the caterers
        "drop": ("retail_daily", "retail_non_daily"),
        "add": ("leisure",),
        "place_classes": ("restaurants / gastronomy", "retail (small-scale)"),      # elsewhere only the retail labels go
        "store_classes": ("Retail", "wholesale", "discount stores", "DIY stores", "furniture stores", "hypermarkets / superstores",
                          "shopping centers", "self-service department stores", "department stores", "factory outlet centers",
                          "car dealerships"),
        "shop_pattern": (r"bakery|b[äa]ck(?:er\b|erei|stube|shop|waren)|konditor|confection|patisserie|butcher|fleischer|metzger"
                         r"|farm shop|hofl[äa]d"
                         r"|regional[- ]products|regionalladen|wine shop|weinladen|garden cent|gartencent|\bbook|buchcaf|buchhandl"
                         r"|roaster|roastery|r[öo]sterei|chocolat|schokolad|with a (?:small )?retail shop|l[äa]dchen"),
        "kiosk_pattern": r"\bkiosk",                                   # a kiosk is a shop with seating ...
        "kiosk_food_pattern": r"\bfood|snack|imbiss|take-?\s?away|ice[- ]?cream",   # ... unless its name or type says food or snacks
        "staff_pattern": r"\bmensa\b",                                 # with VISITOR_STAFF_ONLY_PATTERN and VISITOR_STAFF_ONLY_CLASSES
    },
    "pharmacies": {
        "uses": ("pharmacy",),
        "add": ("retail_daily",),
    },
    "fuel": {
        "uses": ("fuel",),
        "no_shop_add": ("errands",),
        "no_shop_tags": {"automated": "yes", "self_service": "only", "access": ("private", "no"), "shop": ("no",)},   # and vending_machine=fuel
        "diesel_only": True,                   # a truck stop with diesel only (petrol tags present, none yes) has no shop (2026-10-09)
        "gas_only_fuels": ("fuel:lpg", "fuel:cng", "fuel:lng", "fuel:biogas", "fuel:h2", "fuel:hydrogen"),   # only these, no brand
        "no_shop_pattern": (r"automat|\bsb[- ]?tank|self[- ]service fuel|selbstbedien|tankpool|\btinq\b"
                            r"|\blpg\b|autogas|\bcng\b|erdgas|natural gas|\blng\b|biolng|wasserstoff|hydrogen|h²|\bh2\b"
                            r"|diesel (?:fuel )?station|diesel[- ]?tankstelle"
                            r"|premises|factory|volkswagen|\bvw\b|werk\b|on[- ]site fuel|fuel pump building|production hall"
                            r"|industrial facility|industriepark|industrial park|autohaus|dealership"
                            r"|mineral[oö]l|brennstoff|saatzucht|aircraft|\bair ?bp\b"),
        "site_pattern": (r"premises|factory|volkswagen|\bvw\b|werk\b|on[- ]site fuel|fuel pump building|production hall|industrial facility"
                         r"|industriepark|industrial park"),          # a POI's building type that marks a company site
        "shop_type_pattern": r"convenien|(?<!repair )(?<!parcel )(?<!work)shop\b|store\b|bistro|caf[eé]|restaurant|supermarket",
    },
    "daily_shops": {
        "uses": ("beverages", "kiosk", "kiosk;ticket", "lottery", "newsagent", "tobacco", "tobacco;lottery"),
        "named_uses": ("alcohol", "wine"),                             # a beverage market tagged as a liquor shop ...
        "name_pattern": r"getr[äa]nk|durst",                           # ... and named so
        "exclude_pattern": (r"brauerei|brauhaus|braust[äa]tt|brewery|brennerei|distill|destill|mosterei|kelterei|fruchtsaft|fruchtwein"
                            r"|imkerei|honig|honey|fabrikverkauf|werksverkauf|factory|outlet\s+(?:shop|store)|weingut|winery|winzer"
                            r"|kloster|monaster|souvenir|touris|i-?punkt|information|swimming|schwimm|freibad|strandbad|hallenbad"
                            r"|e-?zigarett|e-?cigarett|vape|vaping"),
        "exclude_classes": ("factory outlet centers",),
        "add": ("retail_daily",),
        "drop": ("retail_non_daily",),
    },
    "venues": {
        "classes": {                                                   # OSM uses / leisure / amenity / first sport value, names, type heads
            "pool": {"uses": ("public_bath", "swimming", "swimming_pool", "water_park"),
                     "names": (r"hallenbad|freibad|schwimmbad|schwimmhalle|erlebnisbad|spa(?:ss|ß)bad|freizeitbad|familienbad|sportbad"
                               r"|stadtbad|waldbad|wellenbad|naturbad|strandbad|kombibad|badeland|badezentrum|badeanstalt|badeparadies"
                               r"|wasserwelt|\btherme"),
                     "types": (r"swimming|\bpools?\b|\bbaths?\b|bathing|bathhouse|water ?park|aquatic|\blido\b|\btherme\b"
                               r"|thermal (?:bath|spa|pool)|badeanstalt|freibad|hallenbad|schwimm|freizeitbad|erlebnisbad")},
            "ice": {"uses": ("curling", "ice_hockey", "ice_rink", "ice_skating", "ice_stock"),
                    "names": r"(?<![a-zäöüß])eis(?:halle|sport|stadion|bahn|-?arena|lauf)",
                    "types": r"\bice[- ]?(?:rinks?|arenas?|stadium|halls?|sports?|skating|hockey)\b|(?<![a-zäöüß])eis(?:halle|sport|stadion)"},
            "bowling": {"uses": ("10pin", "9pin", "bowling", "bowling_alley"),
                        "names": r"bowling|kegel",
                        "types": r"bowling|nine-?pin|ten-?pin|9-pin|10-pin|skittle|kegel"},
            "climbing": {"uses": ("bouldering", "climbing", "climbing_adventure"),
                         "names": r"kletter|boulder|hochseilgarten|greifhaus",
                         "types": r"climbing|bouldering|high[- ]ropes|ropes? course"},
            "kart": {"uses": ("karting",),
                     "names": r"\bkart(?!offel|e\b|en\b|ei)",
                     "types": r"\bkart(?:s|ing)?\b|go-?kart"},
            "trampoline": {"uses": ("trampoline", "trampoline_park"),
                           "names": r"trampolin|sprung ?fabrik|you ?jump|jump ?house",
                           "types": r"trampolin"},
            "minigolf": {"uses": ("miniature_golf", "minigolf"),
                         "names": r"mini-?golf|schwarzlicht",
                         "types": r"mini ?golf|minigolf|crazy golf|adventure golf|black[- ]?light golf"},
            "escape": {"uses": ("escape_game",), "names": r"escape", "types": r"escape[- ]?(?:room|game)"},
            "lasertag": {"uses": ("laser_tag",), "names": r"laser ?tag|laser ?game", "types": r"laser[- ]?tag|laser game"},
            "play": {"uses": ("indoor_play",),
                     "names": r"spielparadies|indoor-?spielplatz|monkey ?town|hally ?gally|abenteuerland|tobeland|spielwelt",
                     "types": (r"indoor play|play ?(?:centre|center|hall|land)|soft[- ]?play|indoor playground|adventure park"
                               r"|fun ?(?:park|centre|center)")},
        },
        "exclude_pattern": (r"lehrschwimm|schulschwimm|\bschool|schul|teaching|instruction|bewegungsbad|therap|rehab|\breha\b|physio"
                            r"|clinic|klinik|hospital|medical|\bhotel|club ?house|clubhouse|vereinsheim|sportheim|\bclubs?\b|private|fitness"),
        "class_exclude_patterns": {"pool": r"billiard|billard|pool ?hall|pool ?table|car ?pool"},
        "closed_tag_pattern": r'"access"\s*:\s*"(?:private|no)"|"(?:disused|abandoned|was|demolished|removed|razed):(?:leisure|sport|amenity)"\s*:',
        "alkis_functions": {"pool": ("31001_3221",)},                  # indoor swimming pool
        "never_with": ("school", "university", "childcare"),
        "add": ("leisure",),
    },
    "services": {
        "groups": ("counter", "personal_service"),
        "keep_uses": ("telecommunication", "post_office"),
        "keep_poi_ids": ("node/1374204427", "node/3696421625", "node/5184463568", "node/1708300523", "node/11766518550", "node/3387445099"),
        # Parfuemerie Peter, Haar Pflege Shop, Muranoglas, PKW-Anhaenger Verleih und Verkauf, IRIS Aenderungsschneiderei / Second Hand,
        # Foto Asmus (OSM craft=photographer, a photo shop and studio by its listings)
        "drop": ("retail_non_daily",),
    },
    "rest_sources": {
        "labels": ("retail_daily", "retail_non_daily", "leisure"),
        "min_rate": 0.25,
        "min_n": 5,
        "own_evidence": {                                              # the building's own data that name the label's kind
            "retail_daily": {"sites": ("mall", "marketplace", "supermarket"), "tags": ("supermarket", "kiosk", "mall"), "codes": (),
                             "names": (r"\bmarkt\b|markthalle|supermarkt|einkaufs|center\b|centre\b|passage|arkaden|galerie|shops\b"
                                       r"|laden\b|kiosk")},
            "retail_non_daily": {"sites": ("mall", "marketplace", "outlet", "department_store"), "tags": ("mall", "department_store"),
                                 "codes": (),
                                 "names": (r"\bmarkt\b|markthalle|einkaufs|center\b|centre\b|passage|arkaden|galerie|shops\b|outlet"
                                           r"|kaufhaus|baumarkt|möbel")},
            "leisure": {"sites": ("theme_park", "zoo", "water_park", "resort", "camp_site", "attraction", "museum", "castle",
                                  "golf_course", "stadium"),
                        "tags": ("hotel", "theatre", "cinema", "stadium", "grandstand"),
                        "codes": ("31001_2072", "31001_3031", "31001_3032", "31001_3033", "31001_3034", "31001_3036", "31001_3038"),
                        "names": r"hotel|kino\b|theater|museum|schloss|freizeit|erlebnis|bowling|freibad|stadion"},
        },
    },
}
# Small places stay small (the user, 2026-10-06: "we cannot prevent misclassification but we can prevent the effects of it later
# during redistribution ... by keeping it lower for the small places as intended"). On top of the one-floor rule, a unit of
# small-scale retail or a restaurant occupies at most the typical size of its kind - the p90 of the mapped shops and restaurants,
# the caps the point POIs already take (POINT_SIZE_CAP_M2: small_retail 748 m2, gastronomy 438 m2): a building the model filed as
# one of them (the trailer dealer Anssems, 21,653 m2; garden centres of 11,560 and 10,363 m2; a parking deck typed as a fast-food
# restaurant that took 1,476 of its zone's 5,331 Retail_Daily), its rest unit, and a POI of these groups mapped as a point where it
# shares a building as one facility or is its main occupant (until now the only points without a cap). The cut floor carries
# nothing. Food stores keep their size: a building whose step-05 type names one, or whose only POI is a food store or big box
# (POI_ANCHOR_GROUPS) - a supermarket filed as small-scale retail. Simulated on the run before: 495 building units, moving
# Retail_Daily 1.6 %, Retail_Non-Daily 3.3 %, Leisure 1.1 % and Workers 1.0 % within their zones.
SMALL_PLACE_CAP_GROUPS = {"retail (small-scale)": "small_retail",           # class -> the POI group whose size cap applies
                          "restaurants / gastronomy": "gastronomy"}
SMALL_PLACE_EXEMPT_TYPE_PATTERN = (r"supermarket|discount|grocery|food store|lebensmittel|hypermarket|rewe|edeka|netto|lidl|aldi|penny"
                                   r"|kaufland|globus|famila|combi|markant|nahkauf|marktkauf")
# Places without evidence (the user, 2026-10-06): a building unit with no POI of its own, no name (ALKIS, or on its OSM outline:
# Marktkauf) and no site other than a landuse area (REDIST_LANDUSE_USES; a shop polygon around it - Galeria, Hornbach - is
# evidence) - its labels are the model's reading of the ALKIS function or of a landuse area around it - counts a quarter in these
# categories; Workers and the school categories keep their full weight. Example: a round building in BS Stadtkern 5
# (DENIAL0100005y51) typed "small retail store" from ALKIS "trade and services" and the landuse=retail block around it held 2,167
# Retail_Daily on one floor of 352 m2. Before this rule such places held 17 % of Retail_Daily, 17 % of Retail_Non-Daily and 8 % of
# Leisure; in 40 zones they are the only Retail_Daily carriers and keep the whole target.
REDIST_NO_POI_WEIGHT = 0.25
REDIST_NO_POI_CATEGORIES = ("Retail_Daily", "Retail_Non-Daily", "Leisure")


# ==========================================================================================================================
# The remaining items of the audit of run 7 (2026-10-09). The user: "Complete the task and assume my choice as what you
# recommend" - every decision below is the recommended option of the analysis (SCR rest5/results, checked by an independent
# critic). The effect of each rule alone is against run 14; all together against run 14 at the end of the block.
# ==========================================================================================================================

# --- item 6: staff catering (lib/staff_catering.py; notebook 08 section 4.8) --------------------------------------------------
# Works canteens, staff cafes and snack bars on company sites, school and university Mensas and hospital cafeterias carry none of
# retail_daily / retail_non_daily / leisure: their guests are the staff, pupils and students counted as Workers, School or
# University (the reason behind the decided visitor zero for staff-only places, 2026-10-06, and item 5's Mensa drop). A unit is
# staff catering by its own name, model type or OSM amenity=canteen (words), or as an eating place in a works-class building or
# on a company site; never a shop, a place in a store-class building or a public canteen by name (an allotment canteen, a
# theatre canteen, a pizzeria, an outlet cafe). The rest unit of such a building loses retail_daily and leisure too ("the
# canteen answers": the VW Oase staff restaurant's rest unit held 1,014 Retail_Daily, 81 % of WOB VW-Werk, mostly ring
# inflow). A dropped label's share goes to the unit's other labels (as for item 4); the last-carrier guard keeps a zone's only
# carrier. Ring fallbacks are left as they are: afterwards only about 6.5 Retail_Daily of them reach staff places.
# Alone against run 14: 86 units, 6 rest units; Retail_Daily 8,283 (0.91 %), Leisure 1,357, University 196 and School 184 move
# (the IGS Sassenburg building gains School, the Ostfalia Mensa building in Salzgitter University); business +196 a day.
STAFF_CATERING_RULES = {
    "words": (r"canteen|kantine|caf[eé]teria|\bmensa\b|\bmensen\b|staff (?:restaurant|caf[eé]|dining)|employee(?:s'?)? (?:restaurant|caf[eé]|canteen|dining)"
              r"|workplace (?:restaurant|canteen)|company (?:restaurant|canteen|cafeteria)|works (?:restaurant|canteen)|factory (?:restaurant|canteen)"
              r"|betriebsresta|werksrestaurant|werksgasthaus|personal(?:kantine|restaurant|casino)|mitarbeiter-?(?:restaurant|kantine|caf)"
              r"|speisesaal|dining hall|refectory"),
    "public": r"garten|garden|allotment|theaterkantine|theatre canteen|pizzeria|factory outlet|designer outlet|fabrikverkauf|werksverkauf",
    "shop_groups": ("small_retail", "food_store", "big_box", "department_store", "fuel"),
    "works_classes": ("Industrial operations / Production", "highly productive industries / machine / material or space intensive", "others"),
    "company_site_uses": ("factory", "works"),              # a plant's premises (step-06 site rows)
    "named_site_uses": ("industrial",),                     # ... or an industrial site named after a company, not an estate
    "estate_pattern": r"gewerbe|industrie|gebiet|park\b|stra(?:ss|ß)e|weg\b|allee|platz|hafen|area|estate|zone|viertel",
    "drop": ("retail_daily", "retail_non_daily", "leisure"),
    "rest_labels": ("retail_daily", "leisure"),            # what a canteen can be the source of on its building's rest unit
    "kind_hospital": r"\bhospitals?\b|klinik|krankenhaus|\bclinics?\b",
    "kind_school": r"(?<!hoch)schul|\bschools?\b|gymnas|gesamtschule|\bigs\b|\bkgs\b|bildungshaus|internat",
    "kind_university": r"universit|hochschul|\btu\b|ostfalia|\bhbk\b|studierend|studentenwerk|fachhochschul|\bmensa\b",
    "school_classes": ("schools",), "university_classes": ("universities",), "hospital_classes": ("hospitals",),
    "school_functions": ("31001_3021", "31001_3022", "31001_3020"), "university_functions": ("31001_3023",),
    "hospital_functions": ("31001_3051", "31001_3052"), "hospital_tags": ("hospital", "clinic"),
    # staff shops (round 16, 2026-10-09, on the user's behalf): a shop or kiosk unit inside a plant serves its staff like the
    # canteen - a POI of a shop group (not a big box, car dealer or fuel station: those are public at a works gate), a one-POI
    # building whose POI is one, or a building without a POI whose type head names a kiosk or shop; in a building filed in a works
    # class AND on a company site with a name; never public by its own words. It joins staff catering (no retail / leisure, the
    # share to its other labels, the guard kept) and counts no visitors (the staff-only zero of 2026-10-06). Siemens' 'chicco di
    # caffe' (access=private) held 428.9 Retail_Daily, 26 % of BS Hauptbahnhof 2. Alone against run 15: 8 units, 7 of them with a
    # retail label (the 8th, an OSM elevator in a VW hall filed as small_retail, changes nothing); Retail_Daily 486,
    # Retail_Non-Daily 4 move; errands -181 a day (a bogus 'pharmacy' in a Salzgitter rolling mill).
    "shops": {"groups": ("small_retail", "food_store", "department_store"),
              "head_pattern": r"\bkiosk|\bconvenience\b|\bshop\b|\bstore\b|\bimbiss\b",
              "public": r"\boutlet\b|lagerverkauf|direktverkauf|hofl[aä]den|farm shop|showroom|autohaus|dealership",
              "visitors_zero": True},
}

# --- item 7: OSM-only buildings on step 04's placeholder height (lib/gap_storeys.py; notebook 08 section 3.2b) ----------------
# Where OSM gives neither a height nor building:levels, step 04 wrote 1 x 2.0 m (OSM_GAP_DEFAULT_FLOORS x OSM_GAP_FLOOR_HEIGHT_M),
# a placeholder the 08b rule read as one storey - offices, schools and care homes alike (671 rows; Kindergarten 8.9 % of the
# region sat on them). "The class-and-size median": such a building of a class that is storeyed by kind, below 2,500 m2 and under
# no hall-like OSM outline, takes the median storeys of the ALKIS buildings of its class and footprint band that have a LoD2 eaves
# height, no hall and no dwellings (with fewer than min_n of them, of every class in the band). It replaces the decided 08b mean
# height for these rows; shops, restaurants, Kitas, the leisure classes and larger outlines keep one storey.
# Alone against run 14: 206 rows rise to 2-3 storeys; Workers 1,524 (0.26 %), School 927, University 530 (1.38 %), Leisure 298
# move; business +298, errands +674, meetup +251 a day.
FLOOR_OSM_GAP_STOREYS = {
    "mode": "band",                              # the median of the same class and footprint band; a thin cell: of every class
    "placeholder_height_m": 2.0,                 # = OSM_GAP_DEFAULT_FLOORS x OSM_GAP_FLOOR_HEIGHT_M (step 04)
    "placeholder_tol_m": 0.05,
    "keep_one_classes": ["retail (small-scale)", "Retail", "restaurants / gastronomy"],   # one floor by the decided rule
    "keep_one_tags": ["barn", "farm_auxiliary", "greenhouse", "shed", "roof", "carport", "cowshed", "stable", "riding_hall",
                      "warehouse", "hangar"],    # item 2's hall outlines (FLOOR_ONE_STOREY_RULES hall_tags) + warehouse, hangar
    "only_classes": ["normal office", "business-oriented services", "Services", "Public facilities", "schools", "universities",
                     "research institutes", "hospitals", "nursing homes", "hotels"],
    "max_area_m2": 2500,                         # outlines of 2,500 m2 or more keep one storey (often a hall and its office joined)
    "bands_m2": [150, 400, 1000, 2500],          # < 150, 150-400, 400-1,000, 1,000-2,500, 2,500 m2 and more
    "min_n": 30,                                 # reference buildings a class-and-band median needs
}

# --- item 11: the no-evidence residential rule and landuse areas (notebook 08 section 4.4) -----------------------------------
# The colleague's no-evidence residential rule (2026-10-05) required no site at all, so 929 unnamed residential-coded buildings
# escaped it through a commercial, retail or industrial landuse area around them - while the quarter weight (2026-10-06) already
# reads such an area as no evidence. "Only with dwellings": the rule also takes a building whose only sites are landuse areas, if
# it has dwellings by the residential context and is no plain home (plain homes keep their one storey with labels, 2026-10-05);
# offices in business parks the residential context reads as offices keep their storeys. The rule's footprint x 1 keeps the
# small-place cap (2026-10-06).
# Alone against run 14: 460 buildings; Retail_Daily 6,229 (0.69 %), Retail_Non-Daily 728, Leisure 158 move; errands -2,269 a day.
# The quarter weight for visitor values (item 8) was left as it is: it is a statement about shares, not about how many come.
NO_EVIDENCE_LANDUSE = {"landuse_is_no_site": True, "keep_plain_homes": True, "needs_residential_context": True}

# --- item 8: the visitor rates (lib/visitor_rates.py; notebook 08 section 7, the visitor values) -----------------------------
# Every option applies a decided rate or zero as it was meant (2026-10-06):
#   * sport_words: the sports type words are read for every sports class and before a generic or several-valued sports use, in
#     the unit's own names and type (gyms at S_FITNESS, not the hall rate; riding, shooting and tennis halls at their own rates);
#   * counter_cap: the counter rate covers at most the counter cap (388 m2), whatever gives it; the floor beyond takes the
#     public-office rate (the AOK Braunschweig went from 1,915 to 514 errands a day);
#   * office_box: a building or rest unit of an office or service class in a building over 5,000 m2 with eaves of at most 12 m
#     counts business and errands on one storey (its footprint);
#   * library: a university library counts 0 errands (its users are in the University total); research, specialist, archive and
#     private libraries take the public-office rate instead of the public-library rate;
#   * the leaks of the decided zeros are closed: the cafe zero wherever the gastronomy rate applies, company academies by their
#     own words, no value in no zone, lessons at a school's sports hall count 0;
#   * audience_zero: a leisure venue whose rate counts its whole audience (theatres, cinemas, clubs, event venues) keeps only the
#     meetup value beyond its own Leisure share - the cafe zero for these venues as far as their Leisure share holds them;
#     community arts centres keep it; sports at pools and bowling stays. Round 16 (2026-10-09, on the user's behalf): VISUM's
#     Leisure (SG_6_FR~23) behaves like an attraction value with a resident base of about 70 per 1,000 inhabitants, and holds the
#     venue audiences only in part (the Volkswagen Halle's zone 49 %, the Eintracht-Stadion's 35 % of their published visitors a
#     day; nothing in SZ Lebenstedt 07, whose Leisure is 0). So such a venue keeps max(0, its meetup at the audience rate - its
#     Leisure share) (net_of_leisure): at 60 of the 72 venues (73 units: the KP-ONE meadow has two) the Leisure share already
#     holds it (0 as before), 11 get meetup back (+613 a day; the Kaptan Center and the Event Center Uemit Palace in Lebenstedt
#     366 and 38, the Kaptan Center on its 7,329 m2 footprint at the assumed event rate); the KP-ONE festival meadow keeps 0
#     (keep_zero_buildings: an open-air site used three days a year). Whether VISUM reads the five values as trips or as
#     weights, and what FR~22 / FR~24 hold, is still to be asked;
#   * events: event, conference and exhibition venues take the event rate, not the community-centre rate. With audience_zero,
#     an event hall that carries leisure keeps only the meetup beyond its own Leisure share (round 16): the VW Halle and the
#     Stadthallen 0, the CongressPark hall 7.8, the Kaptan Center 366.4.
# Salzgitter's visitor values get a printed note: its OSM coverage of practices, offices and small shops is thin (round 16 below).
# Alone against run 14 (values only, no category moves): business -2,211 (-5.1 %), errands -7,476 (-3.0 %), sports +4,434
# (+3.7 %), meetup -6,775 (-15.6 %), lessons -1,008 (-6.4 %) a day.
# Round 16 (2026-10-09, on the user's behalf):
#   * the Salzgitter note says that its errands and sports values are probably too low, and Peine's nearly as much: OSM maps few
#     practices and small shops in both (per inhabitant Salzgitter is the lowest district in sports and the second lowest in
#     errands, after Peine; its business values are mid-range);
#   * heritage_poi: a building whose only POI is a heritage feature (a castle, manor, monastery ...) takes its class rate unless
#     it is filed as a culture or leisure facility: the POI names the building's past, not its use - the care home Schloss
#     Schliestedt counted meetup 725.7 at the theatre rate (now 36.3 at the care-home rate), the Bundeslehranstalt Burg Warberg
#     lessons 248.9 at the community rate (now 82.1). Alone against run 15: meetup -687, lessons -167 a day on 3 buildings.
VISITOR_RULES = {
    "sport_words": {
        "generic_uses": frozenset({"sports_centre", "sports_hall", "multi", "multisport", "sport", "gymnastics", "athletics"}),
        "words": [
            (r"riding|equestrian|\breit|pferde", "S_RIDING"),
            (r"shooting|sch[uü]tzen|schie(?:ß|ss)(?:stand|sport|halle|anlage|bahn|heim|verein)|archery|bogenschie", "S_SHOOT"),
            (r"club ?house|clubheim|clubhaus|sportheim|sportlerheim|vereinsheim", "S_CLUB"),
            (r"multi-?sport|several sports|soccer|football|fu(?:ß|ss)ball|badminton|handball|volleyball|basketball", "S_HALL"),
            (r"swimming|\bpools?\b|hallenbad|freibad|schwimm|waldbad|stadtbad|sportbad|freizeitbad|erlebnisbad|badeland|badeanstalt"
             r"|water ?park|\btherme|(?<!salzgitter-)(?<!salzgitter )\bbad\b(?!\s+(?:harzburg|gandersheim|lauterberg|grund|sachsa|helmstedt"
             r"|salzdetfurth|bevensen|bodenteich|pyrmont|nenndorf))", "S_POOL"),
            (r"(?<!table )(?<!tisch)tennis|padel|squash", "S_TENNIS"),
            (r"fitness(?!\s*(?:/|and|&|\+|und)\s*wellness)|crossfit|kraftsport|bodybuilding|mcfit|injoy|clever ?fit|easy ?fitness|kieser"
             r"|john reed|mrs\.? ?sporty", "S_FITNESS"),
            (r"bowling|kegel|climbing|kletter|boulder|trampolin|laser ?tag|karting|kartbahn|go-?kart|indoor kart|minigolf|escape room"
             r"|spielparadies|indoor play", "S_ENT"),
            (r"\bdance|dancing|ballet|\btanz|martial arts|\bdojo|yoga|pilates|tai ?chi|qigong", "L_DANCE"),
            (r"sports hall|gymnasium|turnhalle|sporthalle|sports centre|sports facility", "S_HALL"),
        ],
        "cmp_classes": ("fitness / wellness", "schools", "arenas, large events"),
    },
    "counter_cap": {"cap": 388.0, "beyond": "E_PUBOFF"},
    "office_box": {"labels": ("business", "errands"),
                   "classes": ("normal office", "open-plan office", "business-oriented services", "Services", "customer-oriented services",
                               "customer service"),
                   "min_footprint": 5000.0, "max_eaves": 12.0},
    "library": {"university_classes": ("universities",), "classes": ("research institutes",),
                "words": r"fachbibliothek|forschungs|research|archiv|archive|universit|campus|hochschul|wissenschaft",
                "access": ("private", "no"), "rate": "E_PUBOFF", "university_zero": True},
    "cafe_zero_by_rate": True,
    "academy": {"words": r"acad|akadem|coaching|training|schulung|bildungszentrum|lehrwerkstatt|ausbildungszentrum",
                "company": r"corporate|company|employee|staff|in-house|volkswagen|\bvw\b",
                "classes": ("Industrial operations / Production", "highly productive industries / machine / material or space intensive")},
    "no_zone_zero": True,
    "school_hall": (r"school sports hall|schulsporthalle|(?:gym|sports) hall (?:of|at|for) (?:the |a |an )?[^|]{0,60}?(?:school|schule|gymnasium)"
                    r"|sporthalle der (?:igs|kgs|[^|]{0,30}schule)|turnhalle der [^|]{0,30}schule|school gym"),
    "audience_zero": {"labels": ("meetup",), "rates": ("M_CULTURE", "M_EVENTS"), "exclude_uses": ("arts_centre",),
                      "net_of_leisure": True, "keep_zero_buildings": ("way/1463883217",)},    # round 16; the KP-ONE festival meadow
    "events": {"uses": frozenset({"events_venue", "events_centre", "conference_centre", "exhibition_centre", "convention_centre"}),
               "words": (r"\bevents? (?:venue|centre|center|hall|location)|eventhalle|event-?location|veranstaltungs(?:halle|zentrum|saal|stätte|ort)"
                         r"|\bstadthalle|\bfesthalle|\bfestsa(?:al|le)|kongress|congress|convention (?:centre|center|hall)|conference (?:centre|center|hall)"
                         r"|tagungs(?:zentrum|stätte|haus)|mehrzweckhalle|multi-?purpose (?:hall|events? venue)|exhibition (?:hall|centre|center)|messehalle"
                         r"|konzerthalle|concert hall|kulturhalle"),
               "word_groups": (None, "community", "generic", "unmapped", "industry", "small_retail", "sport", "office", "public_office"),
               "not_words": r"dorfgemeinschaft|village community|gemeinschaftshaus|gemeindesaal|gmdsaal|gemeindehaus|b[uü]rgerhaus|community house"},
    "lower_bound_note": {"district": "Salzgitter", "ags_prefix": "03102"},
    "heritage_poi": {"uses": ("castle", "manor", "palace", "monastery", "ruins", "fort", "city_gate", "tower", "monument", "memorial",
                              "castle_wall"),
                     "keep_classes": ("entertainment, culture", "Facilities for culture, leisure and sports")},
}

# --- item 9: the sizes of POI units (notebook 08 sections 4.4d, 4.5 and 4.7) -------------------------------------------------
# A POI mapped as a point counts about 1 m2 in the step-04.5 shares next to a polygon (862 POI units held less than 5 m2: mall
# tenants, a cinema, the Leis food wholesaler with 0.6 m2). The rules use the statistic the decided point caps use, the mapped
# polygons of each POI group (a quantile, groups with at least POINT_SIZE_CAP_MIN_POLYGONS polygons, else all polygons):
#   * point_min_quantile: a point counts at least its group's median polygon (at most an equal share and the footprint) in its
#     building's shares - not a point that repeats a polygon of its building by name or use;
#   * tenant points outside the shopping and outlet centres get the point cap and are never the main occupant (the KFZ-Zulassung
#     Gifhorn took 18,447 m2);
#   * mall_quantile: in a mall, the tenant points' shares are weighted by their group's typical size (a supermarket about six
#     small shops, not one);
#   * pharmacy_cap_m2: a pharmacy occupies at most 307 m2, the p90 of the mapped pharmacy polygons smaller than their building
#     (5 of them); round 16 checked it on all 33 mapped pharmacy polygons (p90 304 m2) and kept it (UNIT_SIZE_FORMATS: the
#     easyApotheke format up to 400 m2);
#   * chain_cap_group: a building filed as a small shop or restaurant whose own data name a big-box chain (the chain list of the
#     one-storey rule) occupies at most the big-box cap instead of the small-shop cap;
#   * canopy_cap_group: a canopy without a station shop (it keeps its unit) occupies at most the fuel group's cap.
# Alone against run 14: 1,134 POI units resized; Retail_Daily 24,206 (2.66 %), Retail_Non-Daily 11,903 (1.53 %), Leisure 4,646
# (2.08 %), Workers 2,269, University 352 move; errands +2,660 a day. Stations of two buildings stay as they are (at most 45
# Retail_Daily counted twice).
UNIT_SIZE_RULES = {"point_min_quantile": 0.5, "mall_quantile": 0.5, "pharmacy_cap_m2": 307.0, "chain_cap_group": "big_box",
                   "canopy_cap_group": "fuel"}

# --- item 10: the Workers-0 rules and the Workers factors (notebook 08 sections 4 and 4.4) ------------------------------------
# Alone against run 14: Workers 10,368 (1.75 %) move - 21 office buildings, 31 more volunteer stations, 37 parking garages.
# The decided Workers-0 rules (2026-10-05) reach the places their own tests describe:
#   * fitness / wellness halls and clubhouses get the sports-hall rule; staffed fitness and wellness places keep their Workers;
SPORTS_HALL_CLASSES = SPORTS_HALL_CLASSES | {"fitness / wellness"}
SPORTS_HALL_KEEP_PATTERN = SPORTS_HALL_KEEP_PATTERN + (
    r"|\bgym\b(?!\s*halls?\b)|fitness|crossfit|wellness|\bspa\b|sauna|therap|\bhealth\b|gesundheit|genesung|convalescen"
    r"|erholungsheim|kurheim|schwefelbad|physio|rehab|yoga|pilates|\bstudios?\b|bildungsst|training cent(?:re|er)")
#   * a worship building the storey rules count as one (ALKIS worship codes or a worship head) is a church too, unless its head
#     names a shop, a store, an administration or a children's group; and a worship POI gets Workers 0 in any building without a
#     rule (a mosque in a shop building);
CHURCH_FLAG_EXCLUDE_PATTERN = r"\bshops?\b|\bstores?\b|administrat|\bchildren"
#   * a fire station in the three cities is a volunteer station where the volunteer word (or FF) stands in its name, full type,
#     POI names, OSM twin name or its own POIs' names and operators, not only in the head - except the station that is its zone's
#     only Workers carrier (BS Stiddien: the guard would put its Workers on the church instead);
VOLUNTEER_FIRE_OWN_TEXT_PATTERN = VOLUNTEER_FIRE_CITY_PATTERN + r"|\bff\b"
#   * a parking garage or deck (its head names one and no other use, no occupant POI) gets Workers 0 on its own units;
PARKING_OTHER_USE_PATTERN = (r"shop|store|retail|supermarket|market|restaurant|fast[- ]food|imbiss|caf[eé]|\bbars?\b|\bpubs?\b|nightclub|club|fitness"
                             r"|\bgym\b|offices?\b|administrat|community|cent(?:re|er)|venue|hotel|school|kiosk|cinema|workshop|warehouse|hall\b")
#   * a building of an industry, yard or transport class whose head names a whole office building (the residential context's
#     office pattern) and no hall, works, production or storage word takes the normal-office factor (the Salzgitter AG
#     headquarters), on its own units; an industry POI that only repeats the building's OSM outline takes the building's factor.
OFFICE_IN_INDUSTRY_EXCLUDE_PATTERN = (r"\bworks\b|production|manufactur|factory|warehouse|storage|depot|\bhalls?\b|workshop|fabrication|sorting"
                                      r"|printing|\bkaue\b|washroom|garage|vehicle base|operations|control|weighbridge")

# --- the leftovers ------------------------------------------------------------------------------------------------------------
# (a) four big halls the model filed as shops or restaurants take the class of what they are (item 2's "Leave for a class fix");
# round 17 (2026-10-09, on the user's behalf): so do the 23 big low boxes typed 'office' that the web and OSM check found to be
# halls (FLOOR_OFFICE_BOX['hall_ids']) - their Workers factor and visitor rates follow the class:
CLASS_FIX_BUILDINGS = {"DENIAL840000thNC": "car dealerships",                                                  # Anssems trailer megastore
                       "DENIAL0100001rQ5": "highly productive industries / machine / material or space intensive",   # VW Halle 31
                       "DENIAL0500009I8A": "Industrial operations / Production",                               # works hall, tankpool24 pump
                       "DENIAL6100001enN": "wholesale",                                                         # Stanze Stahl, steel stockholder
                       "DENIAL0100001rBq": "Industrial operations / Production",  # Grotrian-Steinweg piano factory
                       "DENIAL0100001rJN": "Industrial operations / Production",  # U.P.R. Fensterwerk
                       "DENIAL0100002Q8e": "Industrial operations / Production",  # Richard Bretschneider GmbH
                       "DENIAL0100002QkY": "Industrial operations / Production",  # Bretschneider / Streiff
                       "DENIAL6100002cXn": "Industrial operations / Production",  # Pelikan PBS Produktion
                       "DENIAL6100002dpv": "Industrial operations / Production",  # HoffmannGlas
                       "DENIAL8400003zjW": "Industrial operations / Production",  # Gebrueder Mayer Produktions- und Vertriebs GmbH
                       "DENIAL910000boZB": "Industrial operations / Production",  # EDAG development centre Birnbaumstuecke 5
                       "DENIAL01000051fb": "highly productive industries / machine / material or space intensive",  # Oettinger brewery Braunschweig
                       "DENIAL84000038p8": "highly productive industries / machine / material or space intensive",  # concrete works
                       "DENIAL0100000U6B": "Yards, depots, storage areas, construction yards",  # Gewerbepark Braunschweig
                       "DENIAL0100000zvs": "Yards, depots, storage areas, construction yards",  # Hch. Perschmann logistics centre
                       "DENIAL0100001rUj": "Yards, depots, storage areas, construction yards",  # Streiff & Helmold
                       "DENIAL0100001s0j": "Yards, depots, storage areas, construction yards",  # Streiff & Helmold
                       "DENIAL0100003emH": "Yards, depots, storage areas, construction yards",  # DHL Supply Chain / DHL Fulfilment GmbH
                       "DENIAL91000005r7": "Yards, depots, storage areas, construction yards",  # Schnellecke logistics site
                       "DENIAL0500000aE6": "Yards, depots, storage areas, construction yards",  # RS Rock-Service
                       "DENIAL0500003lrZ": "Yards, depots, storage areas, construction yards",  # Wilhelm Fromme Landhandel
                       "DENIAL610000389G": "Yards, depots, storage areas, construction yards",  # Albert Elligsen
                       "DENIAL610000eeRp": "Yards, depots, storage areas, construction yards",  # Albert Elligsen
                       "DENIAL0100001rUe": "wholesale",  # Fleischer-Dienst Braunschweig eG
                       "DENIAL0100004xHx": "car dealerships",  # Voets Autozentrum
                       "DENIAL6100006BBQ": "furniture stores"}   # REPO-Moebelmarkt
# (b) the open education cases, by the web check: keep the Ostfalia 'D Rechenzentrum' (PC pools, University) and the
# SOS-Muetterzentrum Salzgitter (it runs a Kita; weighed at most the childcare cap); St. Annen stays dropped (a parish house; the
# Kita St. Annen is another building); drop School on three CJD Jugenddorf Wolfsburg buildings without a school function and on
# the Bornhausen sports hall (Seesen 06).
EDU_CARRIER_LISTS = {"keep": ("DENIAL0600001Aip", "DENIAL0500003D8P"),
                     "drop": (("DENIAL9100005JTe", "school", "School"), ("DENIAL9100005KOs", "school", "School"),
                              ("DENIAL9100005LSg", "school", "School"), ("DENIAL03000026gY", "school", "School")),
                     "kita_cap": ("DENIAL0500003D8P",)}
# (c) the near-zero Workers rule stays as it is (a cap would only push the excess onto the over-full givers).
# (d) buildings that no longer stand: ALKIS (survey 2017/18) still holds them, while OSM shows a construction or brownfield site
# or other buildings there; they give no unit, like a vacant place. Buildings on a site named after an active occupant (Peiner
# Traeger, VW, DLR, the TU campus, the Klinikum, schools) are kept as stand-ins for what is rebuilt there.
GONE_BUILDINGS = frozenset({
    "DENIAL0100000zG3", "DENIAL0100001dUx", "DENIAL0100001dVI", "DENIAL0100001e2b", "DENIAL0100001e2c", "DENIAL0100001ec9",
    "DENIAL0100001ecd", "DENIAL0100001ech", "DENIAL0100001ekP", "DENIAL0100001rUc", "DENIAL0100003vPI", "DENIAL0100005WM9",
    "DENIAL0100005WvF", "DENIAL0100005XmC", "DENIAL0100005XoG", "DENIAL0100005xR5", "DENIAL0100005xSD", "DENIAL0100005xTd",
    "DENIAL0100005xZM", "DENIAL0100005ylW", "DENIAL0300001F9D", "DENIAL0300001FM7", "DENIAL0300001FRI", "DENIAL0300001FTE",
    "DENIAL0300001FuT", "DENIAL0300001G2s", "DENIAL03000046tb", "DENIAL030000478s", "DENIAL03000047YZ", "DENIAL0300005NcP",
    "DENIAL0300006XCM", "DENIAL0300008GwR", "DENIAL030000a6X8", "DENIAL030000a7ek", "DENIAL030000a7mD", "DENIAL0500000MSw",
    "DENIAL0500000MU6", "DENIAL0500000MVx", "DENIAL0500000MXR", "DENIAL0500000MXd", "DENIAL0500000MZB", "DENIAL0500000MZI",
    "DENIAL0500000N0K", "DENIAL0500000N1U", "DENIAL0500000N2Q", "DENIAL0500000N44", "DENIAL0500000N51", "DENIAL0500000N5s",
    "DENIAL0500000N68", "DENIAL0500003DGK", "DENIAL0600001Bto", "DENIAL0600001BzY", "DENIAL6100001c0z", "DENIAL6100002cG0",
    "DENIAL61000038c7", "DENIAL61000047Eg", "DENIAL8400004qvV", "DENIAL8400006cQm", "DENIAL8400009tAR", "DENIAL840000aNQs",
    "DENIAL9100001C7g", "DENIAL9100005JOF", "DENIAL9100005KMp", "DENIAL9100005KjS", "DENIAL9100005KnU", "DENIAL9100005LSI",
    "DENIAL9100005LZG", "DENIAL9100005MQ2", "DENIAL9100006RH8", "DENIAL9100007WUa", "DENIAL910000acWi", "DENIAL910000acWl",
    "DENIAL910000ahdn", "DENIAL910000aheH", "DENIAL910000al0j", "DENIAL910000b4Xh", "DENIAL910000btNP", "DENIAL910000btNR"})
# All together against run 14: Workers 15,835 (2.68 %), School 1,257 (0.84 %), University 1,116 (2.92 %), Kindergarten 43,
# Retail_Daily 37,499 (4.13 %), Retail_Non-Daily 13,138 (1.69 %) and Leisure 6,797 (3.05 %) move; the visitor values: business
# -1,914 (-4.4 %), errands -6,363 (-2.5 %), sports +2,928 (+2.5 %), meetup -6,653 (-15.4 %), lessons -760 (-4.8 %) a day; the
# last-carrier guard restores 55 rows (27 in run 14).


# --- round 16: the things still odd after run 15 (the user, 2026-10-09: "make the changes for the things you mentioned are still
# weird or not right"; every choice below is the recommended option of the analysis, taken on the user's behalf) ---------------
# The file also shows, next to the model's labels, the labels the rules use (labels_used on buildings, poi_labels_used on POIs;
# notebook 08 section 7). The staff shops are a key of STAFF_CATERING_RULES ('shops'); the meetup netting and the heritage POIs are
# keys of VISITOR_RULES ('audience_zero', 'heritage_poi').

# --- big low office and service boxes (notebook 08 section 3.4) ---------------------------------------------------------------
# 30 buildings of the office and service classes with a footprint over 5,000 m2 and eaves of at most 12 m counted 2-3 storeys from
# the height alone (6,686 Workers). Nearly all are halls the model typed 'office building' from the generic ALKIS function of an
# industrial estate: a car-dealer site, a packaging plant, Pelikan's factory, glass production, potato stores, logistics (web and
# OSM checks); item 8b already counts their business and errands on one storey. "The 8b box": such a building counts one storey
# where only the height gave more (no OSM levels, no structure rule, no dwellings, no POI upstairs), unless its own data say office
# floors - OSM outlines with building:levels over at least half of the footprint averaging 1.5 levels or more, an OSM
# building=office outline over at least half of it, or a type that names several floors. It joins the one-storey rules of
# 2026-10-08 after them (the sport boxes of round 17 follow it); 8b's value rule stays (it still acts on two of the four boxes this rule exempts: DENIAL0100001dYC,
# business 126.5, and the XXXLutz DENIAL0100000zPs, errands 219.4).
# Alone against run 15: 26 buildings drop to one storey (4 keep theirs on OSM levels); Workers 2,685 (0.45 %) move, nothing else.
# Round 17 (2026-10-09, on the user's behalf; the user: "Office buildings are usually like normal apartments and therefore they
# have multiple floors - why would you want to apply one storey rule to them?"): the rule hit no office building. The region's
# ALKIS gives every business building a generic function (2000 / 2010 / 2100; not one building carries 2020 Buerogebaeude), the
# model read 'office building' into it, and the firms' own office buildings at these sites are separate buildings that keep their
# storeys; the web and OSM check of all 30 boxes found 23 halls (factories, logistics and storage halls, a meat wholesaler, a
# dealer workshop, a brewery hall, a furniture market), 2 unknown boxes, 1 building that no longer stands and the 4 multi-floor
# buildings the rule already left alone (OSM levels or office outlines). A box now counts one
# storey only with hall evidence: on the list of the checked halls ('hall_ids', with the evidence) or under a hall-type OSM outline
# over at least half of its footprint ('hall_tags'); offices and unknown boxes keep the height storeys (DENIAL0100001rQO,
# Grotrian-Steinweg-Str. 10, and DENIAL9100002sk2, VW Nutzfahrzeuge Heinenkamp 20, go back to 2). The box is read on the model's
# class (class_06), so a listed hall keeps its one storey after its class fix (CLASS_FIX_BUILDINGS: the 23 take the class of what
# they are, and rule 4.0 leaves the class-fix list alone). 8b's value rule stays (it still damps the XXXLutz part and
# DENIAL0100001dYC). Alone against run 16: Workers 1,545 (0.26 %) move and business -984 a day on 9 halls; nothing else.
FLOOR_OFFICE_BOX = {
    "classes": ["normal office", "open-plan office", "business-oriented services", "Services", "customer-oriented services",
                "customer service"],             # = VISITOR_RULES['office_box']['classes']
    "min_footprint_m2": 5000.0,                  # = VISITOR_RULES['office_box']['min_footprint']
    "max_eaves_m": 12.0,                         # = VISITOR_RULES['office_box']['max_eaves']; the mean height where no eaves height
    "osm_min_cover": 0.5,                        # OSM outlines with building:levels over at least half of the footprint ...
    "osm_min_levels": 1.5,                       # ... averaging 1.5 levels or more say several floors
    "office_tags": ["office"],                   # an OSM building=office outline over at least half of the footprint
    "floors_pattern": (r"multi[- ]?stor(?:e)?y|\b(?:two|three|four|five|six|seven|eight|nine|ten|\d+)[- ]?(?:stor(?:e)?y|stories|storeys"
                       r"|floors?|levels?)\b|\bstoreys\b|\bstories\b|\bupper floors?\b|\bupstairs\b|high[- ]rise|hochhaus|\btower\b"
                       r"|office block|office tower"),   # a type that names several floors
    "hall_ids": {                                # the halls the web and OSM check confirmed (2026-10-09), with the evidence
        "DENIAL0100000U6B": ("Gewerbepark Braunschweig, Steinriedendamm 15, Halle 22 (OSM 'Gebaeude 22'): 10,000 m2 hall + 1,200 "
                             "m2 ancillary incl. 934 m2 office, under conversion, let from 06/2027 (mileway.com)"),
        "DENIAL0100000zvs": ("Hch. Perschmann logistics centre, Hauptstrasse 46d, BS-Wenden (regionalheute.de 2019-07-24; "
                             "klinkhammer.com 2021)"),
        "DENIAL0100001rBq": ("Grotrian-Steinweg piano factory, Grotrian-Steinweg-Str. 2 (OSM way/22950062 "
                             "disused:building=commercial; insolvent 2024, production ended 2025)"),
        "DENIAL0100001rJN": ("U.P.R. Fensterwerk, window production, Christian-Pommer-Str. 51 (OSM 'U.P.R.'; production job ad "
                             "2025)"),
        "DENIAL0100001rUe": ("Fleischer-Dienst Braunschweig eG, meat and butcher-supply wholesaler, Christian-Pommer-Str. 31/33 "
                             "(OSM building=industrial; council paper 2024)"),
        "DENIAL0100001rUj": ("Streiff & Helmold, packaging and fulfilment, Carl-Giesecke-Str. 2 (one OSM outline with s0j; 20,000 "
                             "m2 storage)"),
        "DENIAL0100001s0j": "Streiff & Helmold, packaging and fulfilment, Carl-Giesecke-Str. 2 (OSM office=company POI on it)",
        "DENIAL0100002Q8e": ("Richard Bretschneider GmbH (Streiff group), folding boxes and printing, Pippelweg 43 (imprint; ~240 "
                             "staff)"),
        "DENIAL0100002QkY": ("Bretschneider / Streiff, Pippelweg 44 (directory: SF Streiff Freizeit); 80 % one 5.2 m hall part "
                             "(LoD2)"),
        "DENIAL0100003emH": "DHL Supply Chain / DHL Fulfilment GmbH, Marienberger Str. 10 (OSM name 'DHL'; yelp, 11880)",
        "DENIAL0100004xHx": ("Voets Autozentrum, VW commercial-vehicle centre, Alte Leipziger Str. 123 (OSM landuse 'Voets "
                             "Autozentrum')"),
        "DENIAL01000051fb": ("Oettinger brewery Braunschweig (ex Feldschloesschen), Boecklerstrasse 31: a hall of the brewery "
                             "complex; production ended 2025/26 (tageskarte.io, lebensmittelpraxis.de)"),
        "DENIAL0500000aE6": ("RS Rock-Service (event sound and light rental), Am Bahnhof 15 / Thiederhall 40, SZ-Thiede (OSM POI; "
                             "openpr 2010)"),
        "DENIAL0500003lrZ": ("Wilhelm Fromme Landhandel (grain and oilseed trade), Lindenstrasse 21/23, SZ-Ringelheim; OSM silo "
                             "15 m away"),
        "DENIAL6100002cXn": ("Pelikan PBS Produktion, writing-instrument plant Peine-Voehrum (OSM office=company outline; ~230 "
                             "staff)"),
        "DENIAL6100002dpv": ("HoffmannGlas, insulating-glass production, main site Peine (OSM office=company outline; a-w.com "
                             "report)"),
        "DENIAL610000389G": ("Albert Elligsen, potato and onion storage and trade, Peine-Stederdorf (OSM office=company outline; "
                             "potatopro)"),
        "DENIAL610000eeRp": ("Albert Elligsen, potato and onion storage and trade, Peine-Stederdorf (OSM office=company outline; "
                             "potatopro)"),
        "DENIAL6100006BBQ": ("REPO-Moebelmarkt (Rest- und Sonderposten), Gerhard-Lukas-Str. 43, Ilsede (OSM node 6710466935; "
                             "opening hours on the outline way/314164849)"),
        "DENIAL84000038p8": ("concrete works, Gifhorner Str. 65, Wesendorf (OSM node 'Berding Betonwerk'; directory: Frischbeton "
                             "Uelzen)"),
        "DENIAL8400003zjW": ("Gebrueder Mayer Produktions- und Vertriebs GmbH (Mayflor potting soil), Mayflorstrasse 1-3, "
                             "Wahrenholz"),
        "DENIAL91000005r7": ("Schnellecke logistics site, Hafenstrasse, WOB-Fallersleben (OSM site 'Schnellecke'; offices in "
                             "other buildings)"),
        "DENIAL910000boZB": ("EDAG development centre Birnbaumstuecke 5, WOB-Warmenau: OSM building=industrial 'EDAG'; 10,000 m2 "
                             "factory space (EDAG); offices in the 3-4 storey buildings DENIAL910000boZt / boZx")
    },
    "hall_tags": ["industrial", "warehouse", "manufacture", "hangar"],   # a hall-type OSM outline over at least osm_min_cover of the footprint
}

# --- the sizes of single tenants by format (lib/unit_sizes.py; notebook 08 sections 4.4d and 4.5) ----------------------------
# A second look at item 9 (run 15), where one statistic per POI group sized every tenant:
#   * pharmacy_large: the pharmacy cap of 307 m2 stays - the p90 of the 5 mapped pharmacy polygons smaller than their building;
#     of all 33 mapped pharmacy polygons p90 304 m2, median 196 m2 (ApBetrO section 4(2): at least 110 m2 of operating rooms) -,
#     but the easyApotheke format keeps up to 400 m2: its stores have an Offizin of 100-400 m2 (apotheke adhoc 2013-2015,
#     zm-online 2014);
#   * chain_caps: a chain filed as a small shop occupies at most its format's size, not the one big-box cap of 4,774 m2 (which
#     gave a Fressnapf 2,796 m2 and a Rossmann the ground floor of a residential block): drugstores the p90 of the 20 mapped dm /
#     Rossmann polygons (1,103 m2; dm's average store 627-638 m2), pet stores the Fressnapf XXL format (about 1,500 m2), beverage
#     stores the p90 of the 33 mapped polygons named for a beverage chain or 'Getraenke...' (1,487 m2; 1,413 m2 without the
#     4,843 m2 polygon of a beverage and egg trader in no building), textile and shoe discounters the decided small-shop cap
#     (KiK 400-750, Takko 400-500, NKD 300-450 m2); a chain in no listed format keeps the big-box cap;
#   * counters: a counter or kiosk point (kiosk, newsagent, tobacco, lottery, e-cigarette, ticket and post-office uses, a 'Theke'
#     name) counts at least the median of the 31 mapped kiosk polygons (53.4 m2) in its building's shares, not its group's median
#     (178 m2 for small shops: the kiosk in a library cafe took 124 Retail_Daily), and weighs that median in a mall too; the
#     shared ground floor and a listed mall's factor can still leave it lower (as any point minimum);
#   * mall_chains: a mall tenant point whose name or brand is a listed chain weighs its published typical size (sales area;
#     MediaMarkt 2,500 m2, Thalia 400 m2, Kaufland 5,000 m2 ...) instead of its group's median, and counts at least that size in
#     its building's shares (bounded like the point minimum: an equal share of the floor, the footprint; in a listed mall the
#     factor of 4.5b then scales it with the other retail units). The weights act only in the malls whose retail floor is
#     published (MALL_RETAIL_FLOOR): in a mall that still counts its gross floor a chain would take most of it (a Mueller
#     drugstore 10,384 m2); the minimum acts in every mall (Primark and Decathlon in the City-Point Braunschweig). The list has no
#     food chains: a food anchor in a listed mall keeps the food-store weight (1,109 m2), so a listed non-food chain can outweigh
#     it (Forum Wolfenbuettel: Expert 2,777 m2, Rewe 2,054 m2; City-Galerie: MediaMarkt 5,031 m2, REWE 2,232 m2); no published
#     size of these stores was found.
# Alone against run 15 (each): the large pharmacies Retail_Daily 337, Workers 22; the chain caps Retail_Daily 464, Retail_Non-Daily
# 447, Workers 55, Leisure 3, lessons -1 a day; the counters Retail_Daily 881, Retail_Non-Daily 268, Leisure 42, Workers 25,
# errands -46 and sports +6 a day; the mall chains (with the mall floors below) the split inside the 7 listed malls.
UNIT_SIZE_FORMATS = {
    "pharmacy_large": {"pattern": r"\beasy\s*-?\s*apotheke", "cap_m2": 400.0},
    "chain_caps": [                              # (the chain word the box-chain list found, the format's cap in m2); the first match
        (r"^(?:dm|rossmann)$", 1103.0),
        (r"^(?:fressnapf|futterhaus|zoo ?& ?co\.?|kiebitzmarkt)$", 1500.0),
        (r"^(?:hol['’]?ab|holab|trinkgut|getr[aä]nke\w*|fristo|big durst)$", 1487.0),
        (r"^(?:kik|takko\w*|nkd|ernsting'?s\w*|jeans fritz|reno)$", 748.0),
    ],
    "counters": {"uses": ["kiosk", "kiosk;ticket", "newsagent", "tobacco", "lottery", "e-cigarette", "ticket", "post_office"],
                 "name_pattern": r"(?:fleisch(?:er)?|wurst|k[aä]se|fisch|feinkost)theke|\btheke\b",
                 "groups": ["small_retail", "counter"],
                 "kiosk_uses": ["kiosk", "newsagent", "tobacco", "lottery"],     # the mapped polygons the kiosk median is taken of
                 "mall": True},                                                  # in a mall, a counter weighs the kiosk median too
    "mall_chains": [                             # (name or brand, the published typical size in m2, the POI uses it must have or None)
        (r"^primark\b", 6400.0, None),                          # Braunschweig store, five floors (Textilwirtschaft / FashionUnited)
        (r"^kaufland\b", 5000.0, None),                         # Frankfurt-Fechenheim 5,300; Bad Saulgau 4,500; EHI: from 5,000
        (r"^decathlon\b", 2885.0, None),                        # the Braunschweig store as planned (Textilwirtschaft 2018)
        (r"^(?:media\s?markt|saturn)\b", 2500.0, None),         # a German average above 2,400 (the 800 m2 Berlin Hbf store < a third)
        (r"^adler\b", 2200.0, ["clothes"]),                     # Adler expansion: from 2,000 m2 + about 200 m2 side rooms
        (r"^c\s?&\s?a\b", 2000.0, None),                        # 780,000 m2 / about 390 stores; JLL: 2,500 m2 per mall site
        (r"^expert\b", 1500.0, ["electronics", "computer", "mobile_phone", "hifi", "appliance", "electrical"]),  # full range from 800 (GfK)
        (r"^m[uü]ller$", 1422.0, ["chemist", "variety_store", "department_store", "toys", "perfumery"]),  # German average 2023/24
        (r"^woolworth\b", 1250.0, None),                        # 500-2,000 m2 + 100-200 m2 side rooms (brochure 2020)
        (r"^(?:jysk|d[aä]nisches bettenlager)\b", 950.0, None), # Store Concept 3.0: 950 m2 + 250 m2 storage (JYSK 2025)
        (r"^action$", 900.0, ["variety_store"]),                # average 850-1,000 m2 (FIM 2024)
        (r"^trinkgut\b", 850.0, None),                          # new stores 700-1,100 m2 (EDEKA press releases 2022-2026)
        (r"^tedi\b", 700.0, None),                              # from 650 m2 + about 50 m2 side rooms (TEDi flyer 2024)
        (r"^dm(?:[- ]drogerie ?markt|[- ]markt)?$", 630.0, ["chemist"]),   # dm average 627-638 m2
        (r"^rossmann\b", 600.0, None),                          # average 600 m2 (2021)
        (r"^kik$", 575.0, None),                                # 400-750 m2 (KiK expansion)
        (r"^deichmann\b", 500.0, None),                         # from 500 m2, at least 430 m2 of sales area
        (r"^takko\b", 450.0, None),                             # 400-500 m2
        (r"^thalia\b", 400.0, ["books", "stationery"]),         # regular stores 250-565 m2; the BraWo Carree store 367 m2
        (r"^nkd$", 375.0, None),                                # 300-450 m2
    ],
}

# --- the floor of the malls (notebook 08 section 4.5b) --------------------------------------------------------------------------
# A mall's units shared its whole floor area - footprint x storeys, car parks and aisles included: the BraWo Carree counted
# 55,652 m2 against 17,345 m2 published, the seven malls below 284,712 m2 against 149,099 m2. "The published retail floor": the
# shops, restaurants and services of a listed mall occupy at most its published retail floor (one factor for all of them, never
# above 1); its non-retail tenants keep their floor (MALL_NONRETAIL_GROUPS: the castle's library, archive and museum in the
# Schloss-Arkaden, the outlet's Kita); a POI that is the mall's own outline (a generic POI tagged as the building: BraWoPark's
# way/229497782, the only one in the seven) stands for the shops OSM does not map and keeps only the published floor its tenants
# leave (13,238 m2 of 18,500; its 18 tenants keep their sizes - found by the review of run 16); the rest of its floor - car
# parks, aisles, plant, delivery - carries nothing, a Workers remainder included (as the cut floor of the decided small-place
# cap). The storeys stay as decided. Malls without a published figure keep their floor (no ratio: their upper floors are partly
# real sales levels). An unlisted mall next to a listed one gains: the KLL DENIAL9100005KLL in Wolfsburg (Mueller, Naehcenter,
# H&M, an Irish pub, in an ALKIS residential building) keeps its 13,692 m2 and holds 34 % of WOB Stadtmitte 5's Retail_Daily
# and Leisure (run 15: 27 %, 26 %); no published floor was found.
# Alone against run 15: Workers 1,099 (0.19 %), Retail_Daily 3,583 (0.39 %), Retail_Non-Daily 6,564 (0.84 %), Leisure 331
# (0.15 %) move; errands -180 a day (the 8 remainder units of the outlet centre, 4,074 m2 with 50 Workers in run 15, are cut).
MALL_NONRETAIL_GROUPS = frozenset({
    "office", "public_office", "health_practice", "hotel", "school", "small_school", "childcare", "care_home", "hospital", "sport",
    "community", "worship", "culture", "transport", "industry", "fire_rescue", "vehicle"})
MALL_RETAIL_FLOOR = {
    "Schloss-Arkaden Braunschweig": {"ids": ["DENIAL0100005xF6"], "m2": 41754},
    # sales area 34,491 m2 + 7,263 m2 rentable ancillary space (de.wikipedia.org, Braunschweiger Schloss; ECE: 30,000 m2 sales
    # area, 150 shops); the city rents 13,300 m2 of the castle for its library, archive and museum; car park 1,250 spaces
    "BraWo Carree (City Carree) Salzgitter": {"ids": ["DENIAL0500001k0e"], "m2": 17345},
    # a 17,345 sqm food-anchored centre (CRE Herald 2020-06-11); 17,000 m2 of retail plus about 600 parking spaces (PropertyEU
    # 2017-06-01); 570 covered spaces (bahnhof.de)
    "City-Galerie Wolfsburg": {"ids": ["DENIAL9100005MxH"], "m2": 30800},
    # leasable space about 30,800 m2, about 100 shops, about 800 parking spaces (Deutsche EuroShop); ECE: 20,000 m2 sales area
    "BraWoPark Shopping Center Braunschweig": {"ids": ["DENIAL010000dM1V"], "m2": 18500},
    # 18,500 m2, of it 12,510 m2 sales area and 3,000 m2 gastronomy and services; a car park with 1,300 spaces plus 540 open-air
    # spaces (Volksbank BraWo press release 2013-10-29)
    "Forum Wolfenbuettel": {"ids": ["DENIAL0600001A0Y"], "m2": 12000},
    # about 12,000 m2, opened August 1998 (oeffnungszeitenbuch.de - a directory, the measure is not stated; the weakest entry);
    # 420-480 spaces on an open lot
    "City Galerie Peine": {"ids": ["DENIAL610000ghYP"], "m2": 6700},
    # net area 6,700 m2, 20 shop units on two floors (TextilWirtschaft 2009-04-03)
    "Designer Outlets Wolfsburg": {"ids": ["DENIAL9100005JA1", "DENIAL9100005JVD", "DENIAL9100005K3A", "DENIAL9100005KEa",
                                           "DENIAL9100005Khx", "DENIAL9100005KiL", "DENIAL9100005Kyv", "DENIAL9100005LBT",
                                           "DENIAL9100005LS7", "DENIAL9100005M9G", "DENIAL9100005MBi", "DENIAL9100005MOt",
                                           "DENIAL9100005MWY", "DENIAL9100005MYk", "DENIAL9100005Mc5", "DENIAL9100005Na6",
                                           "DENIAL910000bl3U", "DENIAL910000bl4i", "DENIAL910000bl4t", "way/661160910",
                                           "way/793836100", "way/793836101", "way/793836102", "way/793836103", "way/793836104",
                                           "way/793836105", "way/793836107", "way/793836108", "way/793875070"], "m2": 22000},
    # sales area 11,500 -> 17,500 m2 with phase 2 (TextilWirtschaft 2013-11-27) and about 4,500 m2 rentable in phase 3 (opened
    # 2018); Europa Capital: more than 22,000 m2 GLA and 100 stores when built out
}
# All together against run 15 (round 16): Workers 3,892 (0.66 %), Retail_Daily 5,855 (0.64 %), Retail_Non-Daily 6,621 (0.85 %)
# and Leisure 509 (0.23 %) move, School, University and Kindergarten nothing; the visitor values: errands -486 (-0.20 %), sports
# +6, meetup -74 (-0.20 %: +613 from the netting, -687 from the heritage POIs), lessons -168 (-1.11 %) a day, business
# unchanged; 1,085 buildings move by more than 1; the last-carrier guard restores the same 55 rows.


# --- round 17: the user's points on run 16 (2026-10-09: "the idea is we get as close as possible to real world"; every choice
# below is the recommended option of the round-17 analysis, taken on the user's behalf) ----------------------------------------
# The big low office boxes count one storey only with hall evidence and the 23 checked halls take the class of what they are
# (FLOOR_OFFICE_BOX, CLASS_FIX_BUILDINGS above); the OSM signs of non-use are read as the tags say them (VACANCY_OSM_SIGNS, in the
# vacancy block of STEP 08).

# --- sport halls and studios (notebook 08 section 3.4; lib/storey_evidence.py sport_boxes) -------------------------------------
# The user: "Sports halls shouldn't be counted as two floors - apply industry-like correction to them." The sports-hall rule of
# 2026-10-05 sets every building it flags to one storey (713 in run 16), but 419 other buildings with a sport use or a sports value
# counted 2+ storeys, 417 from the height alone: fitness boxes (McFit, INJOY, Fitnessland, Easyfitness), riding and shooting halls,
# pools, tennis, climbing and bowling halls, 'sports centres' without the hall word, clubhouses, dance schools and gyms in mixed
# buildings - 41 % of the region's sports value. The industry rule's model: a sport building - a sport class whose own data name a
# sport use (sport words in the head of its type, an own sport POI, an ALKIS sport function, an OSM sport outline) - counts one
# storey where only the height gave more (eaves up to 12.5 m): a hall activity from 300 m2 (riding stables and shooting ranges at
# any size); a studio (fitness, yoga, dance, martial arts) or a generic sports centre from 300 m2 where the height gave two storeys
# (from 8.75 to 12.25 m OSM levels say one level for only 1 of 18 sport buildings); unless another non-sport occupant, a mixed-use,
# shop or office type, a school, hotel, care home or hospital, a storeyed sport use (administration, academy, boarding, clinic,
# community centre ...: the industry rule's storeyed company uses), a type naming floors or OSM outlines averaging 1.5 levels say
# floors. Clubhouses below 800 m2, boathouses, golf club houses and stadium buildings keep their storeys (the industry rule's
# canteens: OSM shows an upper or attic floor at about half of the mapped ones). A candidate sport building (only the height gave it
# more, eaves up to 12.5 m) whose own OSM outlines all say one level counts one storey too, whatever its kind. Checked: Fitnessland Peine (over 4,000 m2 on a 4,881 m2 footprint) and Goslar (over
# 5,200 m2 on 5,095 m2), EASYFITNESS Gifhorn (1,200 m2), McFit Braunschweig (OSM 1 level), Bowling Base Wolfenbuettel (10 lanes);
# the three studios and the bowling centre on OSM levels (v8 Vorsfelde and Fallersleben, HYGIA Braunschweig, Malibu bowling
# Gifhorn) and Fitness First Gifhorn (upstairs) keep theirs. Alone against run 16: 112 buildings to one storey (floor 265,183 -> 131,389 m2); Workers 886 (0.15 %), Leisure 605
# (0.27 %) and Retail_Non-Daily 9 move; sports -11,650 a day (-9.6 %), lessons -401, meetup -277 (the rates are per m2 of floor).
FLOOR_SPORT_BOX = {
    "classes": ["fitness / wellness", "Facilities for culture, leisure and sports", "large discos, fun / leisure pools",
                "arenas, large events", "entertainment, culture", "theme parks"],   # a sport building is of these classes ...
    "type_pattern": (r"sports?\b(?! shops?| stores?| goods| retail| outlets?| bars?| medicine| clothing| equipment| nutrition)"
                     r"|\bgym\b|\bgyms\b|gymnastics|fitness|turnhalle|sporthalle|tennis|squash|badminton|padel|climb|kletter"
                     r"|boulder|bowling|kegel|skittle|swimming|(?<!pc-)(?<!pc )\bpools?\b|hallenbad|freibad|\bsauna|\btherme"
                     r"|riding|equestrian|\breit|ponyhof|horse[- ](?:riding|stable)|shooting|sch(?:[uü]|ue)tzen(?:haus|heim|halle"
                     "|verein|gesellschaft|klause|bruder|br[uü]der|gilde|korporation)|schie(?:ß|ss)(?:stand|sport|halle|anlage"
                     "|bahn|heim)|archery|ice (?:rink|arena|stadium|hall)|eishalle|trampolin|indoor play|play ?(?:centre|center"
                     r"|hall|park)|kart|laser ?tag|paintball|minigolf|mini-golf|miniature golf|\bdance|dancing|\btanz|ballet"
                     r"|martial|judo|karate|taekwondo|dojo|boxing|kickbox|tai ?chi|qigong|\byoga|pilates|crossfit|mcfit|injoy"
                     "|easy ?fitness|dog (?:agility|sport)|athletic|multi-?sport|clubhouse|club house|sportheim|sportlerheim"
                     "|vereinsheim"),               # ... and names a sport: sport words in the head of its type,
    "codes": [3211, 3221, 3230, 2728],              # an ALKIS sports hall, indoor pool, stadium building, riding hall,
    "osm_tags": ["sports_hall", "sports_centre", "riding_hall", "stadium", "grandstand"],   # an OSM sport outline,
    "sport_uses": ["sports_centre", "fitness_centre", "fitness", "sports_hall", "multi", "shooting", "equestrian", "horse_riding",
                   "tennis", "swimming", "gymnastics", "dance", "sauna", "swimming_pool", "yoga", "9pin", "10pin", "athletics",
                   "water_park", "indoor_play", "climbing", "karting", "water_sports", "sport", "public_bath", "crossfit", "gym",
                   "diving", "bowling", "laser_tag", "trampoline_park", "padel", "squash", "riding_school", "riding_hall",
                   "archery", "dancing_school", "dojo", "martial_arts", "dancing", "ballet", "soccer", "table_tennis", "handball",
                   "basketball", "volleyball", "badminton", "dog_agility", "bowls", "motor", "ice_skating", "ice_rink", "boxing",
                   "judo", "karate", "fencing", "roller_skating", "skateboard", "billiards", "multisport", "climbing_adventure",
                   "fighting", "golf", "miniature_golf", "stadium", "canoe", "rowing", "sailing", "field_hockey", "tanzsport",
                   "pilates", "bowling_alley", "track", "shooting-ground"],   # or an own sport POI (its use, leisure or sport tag)
    "studio_uses": ["fitness_centre", "fitness", "gym", "crossfit", "yoga", "pilates", "dance", "dancing", "dancing_school",
                    "ballet", "tanzsport", "dojo", "martial_arts", "judo", "karate", "boxing", "fighting"],   # a studio POI
    "activity_uses": ["shooting", "equestrian", "horse_riding", "riding_school", "riding_hall", "tennis", "padel", "squash",
                      "badminton", "swimming", "swimming_pool", "public_bath", "water_park", "sauna", "diving", "ice_rink",
                      "ice_skating", "climbing", "climbing_adventure", "9pin", "10pin", "bowling", "bowling_alley", "billiards",
                      "indoor_play", "trampoline_park", "karting", "laser_tag", "miniature_golf", "archery", "shooting-ground",
                      "sports_hall", "dog_agility", "motor"],   # a hall activity POI
    "not_sport_poi_groups": ["small_retail", "big_box", "food_store", "department_store", "vehicle", "fuel", "counter",
                             "personal_service", "gastronomy", "health_practice", "hotel", "holiday_flat", "school", "childcare",
                             "care_home", "hospital", "industry", "transport", "worship", "fire_rescue", "public_office"],   # never a sport POI
    "no_occupant_groups": ["gastronomy", "generic", "unmapped", "vacant"],   # no other occupant (eating places, generic, unmapped, vacant)
    "club_poi_groups": ["office", "community"],     # a club's own office or room named for the club is a sport POI
    "club_not_uses": ["fraternity", "religion", "place_of_worship", "townhall"],
    "club_name_pattern": (r"\bsport|\bturn|\btsv\b|\bsv\b|\bfc\b|\bmtv\b|\bvfl\b|\bvfb\b|\btus\b|\bssv\b|\bfsv\b|\bsc\b|\btsg\b"
                          r"|\bsg\b|\bvfr\b|\bbsv\b|sch[uü]tzen|schie(?:ß|ss)|tennis|\breit|golf|kegel|hockey|\bruder|\bsegel|kanu"
                          r"|fu(?:ß|ss)ball|handball|\bski\b|skizunft|\bangel"),
    "school_poi_groups": ["school", "childcare"],   # a school or Kita POI keeps the storeys ...
    "hotel_poi_groups": ["hotel", "holiday_flat", "care_home", "hospital"],   # ... and so does a hotel, care home or hospital POI
    "school_classes": ["schools", "universities", "kindergartens", "research institutes"],
    "hotel_classes": ["hotels", "nursing homes", "hospitals"],
    "school_pattern": (r"\bschool|schule\b|schulzentrum|realschule|grundschule|hauptschule|oberschule|gesamtschule|\bigs\b|\bkgs\b"
                       r"|universit|hochschule|college|kolleg|\bbbs\b|berufsbild|gymnasium (?:\(|school|building|kleine|am |an "
                       "|im )"),
    "not_school_pattern": ("(?:dance|dancing|ballet|fitness|riding|martial|ski|sailing|swimming|tennis|golf|dog|diving|shooting"
                           "|tanz|ballett|reit|schwimm|segel|tauch)[- ]?(?:school|schule)|tanzschule|ballettschule|reitschule"),
    # a mixed-use, shop or office type keeps the storeys
    "mixed_pattern": ("mixed[- ]?use|multi[- ]?tenant|multi[- ]?purpose commercial|commercial building (?:housing|with)"
                      "|building housing|shared (?:by|with)|alongside|as well as|several (?:businesses|tenants|shops)|shopping"
                      r"|\bshops?\b|supermarket|discounter|\bstores?\b|casino|\boffices?\b"),
    # storeyed sport uses (the industry rule's storeyed company uses)
    "storeyed_pattern": ("administrat|verwaltung|headquarters|gesch[aä]ftsstelle|academy|akademie|bildungsst"
                         "|education(?:al)? (?:and training )?cent|leistungszentrum|performance cent|olympiast|internat|boarding"
                         r"|hostel|jugendherberge|schullandheim|guest ?(?:rooms?|house)|accommodation|hotel|apartments?|\bflats?\b"
                         r"|dwelling|residen|clinic|klinik|\breha|rehabilit|therap|physio|medical|praxis|practice|sanatori"
                         "|kur(?:heim|klinik|zentrum|gast)|erholungsheim|convalescen|research|institut|laborator|haus des sports"
                         "|sportbund|federation|verband|community (?:centre|center|hall|house)|dorfgemeinschaft|gemeinschaftshaus"
                         "|b[uü]rgerhalle|youth (?:centre|center|club|hostel)|jugend(?:heim|zentrum|freizeit)|kindergarten"
                         r"|\bkita\b|daycare|library|b[uü]cherei|museum|gallery|town hall|rathaus|cinema|kino\b|kulturzentrum"
                         "|cultural cent|social (?:centre|center|facility|services)|sozial"),
    "storeyed_name_pattern": ("internat|akademie|academy|bildungsst|leistungszentrum|klinik|clinic|hotel|jugendherberge"
                              "|haus des sports|gesch[aä]ftsstelle|verwaltung|sportbund|gemeinschaftshaus|b[uü]rgerhaus|kurgast"
                              "|kurhaus|kulturzentrum|sozial"),
    "floors_pattern": (r"multi[- ]?stor(?:e)?y|\b(?:two|three|four|five|six|seven|eight|nine|ten|\d+)[- ]?(?:stor(?:e)?y|stories"
                       r"|storeys|floors?|levels?)\b|\bstoreys\b|\bstories\b|\bupper floors?\b|\bupstairs\b|high[- ]rise|hochhaus"
                       r"|\btower\b|obergescho|\betage"),   # a type naming floors
    "activity_pattern": (r"riding|equestrian|\breit|ponyhof|horse[- ](?:riding|stable)|\bstables?\b|shooting|sch(?:[uü]"
                         "|ue)tzen(?:haus|heim|halle)|schie(?:ß|ss)(?:stand|sport|halle|anlage|bahn)|archery|swimming"
                         r"|(?<!pc-)(?<!pc )\bpools?\b|hallenbad|\bsauna|\btherme|\bice |eishalle|tennis|squash|badminton|padel"
                         "|climb|kletter|boulder|bowling|kegel|skittle|trampolin|indoor play|play ?(?:centre|center|hall|park)"
                         "|kart|laser ?tag|paintball|minigolf|mini-golf|miniature golf|sports? halls?|gym(?:nastics)? halls?"
                         "|turnhalle|sporthalle|multi[- ]?purpose (?:sports )?hall|mehrzweckhalle|indoor (?:sports?|arena|multi)"
                         "|dog (?:agility|sport)"), # a hall activity named: one storey from min_m2 ...
    # fitness, yoga, dance, martial arts: a studio
    "studio_pattern": (r"fitness|\bgym\b|\bgyms\b|crossfit|mcfit|injoy|easy ?fitness|\byoga|pilates|\bdance|dancing|\btanz|ballet"
                       "|martial|judo|karate|taekwondo|dojo|boxing|kickbox|tai ?chi|qigong|sportstudio|health (?:club|studio)"),
    "studios": True,                                # False: studios keep their storeys (option B)
    "club_pattern": (r"club ?house|clubheim|clubhaus|sportheim|sportlerheim|vereinsheim|vereinshaus|sporthaus\b|changing rooms?"
                     "|umkleide|club building|clubroom|club room|sports club building|vereinsgastst|sch(?:[uü]|ue)tzen(?:haus|heim"
                     r"|klause)|sch(?:ie(?:ß|ss)heim)|\bpavilion"),
    "club_max_m2": 800.0,                           # a club-typed building from here is a hall with club rooms
    "clubs": False,                                 # True: clubhouses count one storey too (option A2)
    # boathouses, golf club houses, stadium buildings keep their storeys
    "keep_pattern": (r"boat ?house|bootshaus|rowing|\bruder|canoe|\bkanu|sailing|\bsegel|wassersport|wasserwander|golf ?(?:club"
                     r"|klub)|golf-club|stadium|stadion|grandstand|trib[uü]ne|\btribune"),
    "min_m2": 300.0,                                # a hall from here (a single gym hall is 15 x 27 m) ...
    "any_size_pattern": (r"riding|equestrian|\breit|ponyhof|horse[- ](?:riding|stable)|\bstables?\b|shooting|sch(?:[uü]|ue)tzen"
                         "|schie(?:ß|ss)|archery"), # ... except riding stables and shooting ranges (any size)
    "any_size_uses": ["equestrian", "horse_riding", "riding_school", "riding_hall", "shooting", "archery", "shooting-ground"],
    "low_max_storeys": 2,                           # studios and generic types only where the height gave 2 storeys
    "max_eaves_m": 12.5,                            # = FLOOR_BOX_MAX_EAVES_M; the mean height where none
    "osm_min_cover": 0.5,                           # OSM outlines over at least half of the footprint ...
    "osm_min_levels": 1.5,                          # ... averaging this or more say floors
    "osm_one": True,                                # OSM outlines that all say 1 make any candidate sport building one storey
}

# --- places known to be closed (notebook 08 section 4.2) ----------------------------------------------------------------------
# The user: "for known places like Stadthalle Braunschweig which you say is closed: is it closed now in 2026? If yes then let it be
# unassigned". Each place below is closed on CLOSED_AS_OF by a dated source (city, operator, press, OSM history); it gives no unit,
# like a vacant place, nor do the asked POIs in it (except 'keep_pois': an active place in an attached structure). 'since' is the
# closing day where a source gives it, else the earliest dated evidence of the closure. A renovation counts where the whole
# building is a building site; a place whose successor is mapped is not closed. A place an OSM sign or
# GONE_BUILDINGS already leaves out keeps that reason (the Stadthalle, Bad Gliesmarode and the Nordsteimke site carry OSM signs;
# the list is their backstop). The zone totals still hold: the zone's other carriers take the share, or the ring fallback where the
# place was the zone's last carrier (the Holwedestrasse cafeteria's Retail_Daily). Re-check the list at every re-run: section 4.2
# names the entries whose planned reopening year has come - the new Marktkauf Wolfsburg-Nordsteimke opens on 2026-12-03 (then drop
# its entry and re-extract step 01: its building=construction outline keeps it out until then).
# The review of run 17 added the former prison Braunschweig-Rennelberg (cleared in May 2024): it had become the largest Workers
# gainer of its zone when the Klinikum site closed.
# Alone against run 16: 23 buildings in 13 places; Workers 2,829 (0.48 %), Retail_Daily 10,874 (1.20 %) and Leisure 972 (0.44 %)
# move; business -174, errands -379, sports -854, meetup -8 a day.
CLOSED_AS_OF = "2026-10-09"
CLOSED_BUILDINGS = {
    "DENIAL01000051AX": {
        "what": "Stadthalle Braunschweig (Leonhardplatz 14): general renovation into a congress and event hall, a building site",
        "since": "2024-07-31",
        "until": "2028",
        "source": ("https://ratsinfo.braunschweig.de/public/wicket/resource/org.apache.wicket.Application/doc2203829.pdf and "
                   ".../doc2203824.pdf (the city's status report of 2026-05-29 and the update of Nov 2024: closure fixed for 31 "
                   "July 2024, site set up from 1 August, asbestos removal in the Grosser Saal, opening 2028 kept; seen "
                   "2026-10-09 through the search index, the files themselves sit behind a bot check); "
                   "https://www.baulinks.de/webplugin/2025/0688.php4 (2025-05-19: works since 2024, facade panels removed, "
                   "reopening 2028; seen 2026-10-09); https://api.openstreetmap.org/api/0.6/changeset/161729312 (2025-01-24, "
                   "survey: \"Baustelle Stadthalle bis vrsl. 2028\", building=construction; seen 2026-10-09)")},
    "DENIAL0100005xOq": {
        "what": ("Vieweghaus, main building of the Braunschweigisches Landesmuseum (Burgplatz 1): closed for renovation, gutted "
                 "since April 2024 in the second construction phase, a building site"),
        "since": "2024-04-01",
        "until": "2028",
        "source": ("https://3landesmuseen-braunschweig.de/en/braunschweigisches-landesmuseum/the-museum/restoration-works "
                   "(\"currently closed for renovation ... Reopening is planned for late 2028\"; seen 2026-10-09); "
                   "https://www.nlbl.niedersachsen.de/download/206559/Sanierung_des_Vieweghauses.pdf (Staatliches Baumanagement "
                   "Braunschweig, April 2024: both buildings \"komplett entkernt\", works April 2024 to end 2027, the new "
                   "exhibition by end 2028; seen 2026-10-09)")},
    "DENIAL0100005xO5": {
        "what": ("Burg Dankwarderode (Burgplatz 4), branch of the Herzog Anton Ulrich-Museum: closed for serious structural "
                 "defects, its whole collection moved to the HAUM; the Antiquariat Fuhrmann in the small annex stays open"),
        "since": "2023-08-22",
        "until": None,
        "keep_pois": ("way/243689994",),
        "source": ("https://3landesmuseen-braunschweig.de/assets/user_upload/HAUM/Presseinformationen/2025-06-25_PM_HAUM_praesentiert_Zwischenl%C3%B6sung_fuer_Burg_Dankwarderode.pdf "
                   "(HAUM 2025-06-25: \"Aufgrund erheblicher Maengel musste das historische Gebaeude im Sommer 2023 geschlossen "
                   "werden\", the collection shown in the HAUM from 2026-03-05; seen 2026-10-09); "
                   "https://maps.adac.de/poi/burg-dankwarderode-braunschweig (\"Derzeit bis auf weiteres geschlossen (Stand: "
                   "22.8.2023)\"; seen 2026-10-09); the Antiquariat Fuhrmann: OSM way/243689994, shop=books, opening_hours "
                   "Fr,Sa 12:00-18:00 (step-01 extract of 2026-09-10)")},
    "DENIAL0100006qPi": {
        "what": ("Bad Gliesmarode (Am Soolanger 1), indoor pool: closed; renovation decided by the council on 2025-05-27, about "
                 "two thirds of the building to be pulled down"),
        "since": "2024-11-30",
        "until": "2029",
        "source": ("https://www.foerderverein-badezentrum-gliesmarode.de/ (\"am 30. November 2024 vorlaeufig "
                   "geschlossen\"; reopening moved from 2028 to Q2 2029 in April 2026; seen 2026-10-09); "
                   "https://www.braunschweig.de/politik_verwaltung/nachrichten/medien/2025-04-11_Beschlussvorlage_Bad_Gliesmarode.pdf "
                   "(council paper 25-25510: the indoor pool closed at the turn of the year 2024/25, works from end 2026; seen "
                   "2026-10-09)")},
    "DENIAL0100002vwQ": {
        "what": ("Staedtisches Klinikum Braunschweig, site Holwedestrasse: closed for good, its clinics moved to Salzdahlumer "
                 "Strasse (the administration at Freisestrasse 9-13 stays and is not listed) - "
                 "main building Holwedestrasse 16"),
        "since": "2024-12-11",
        "until": None,
        "source": ("https://klinikum-braunschweig.de/lib/files/4b5w26djmmxwc7tAnfrwyzjpgq6tml62n8rxk6lfnz5hglzrg7ztgnzvgyzdgnq/48_2024_12_06-pm-wir-ziehen-um-schliessung-des-klinikstandorts-holwedestrasse-ab-dem-11-dezember-2024.pdf "
                   "(Klinikum press release 2024-12-06: \"Am 11. Dezember 2024 schliesst der Standort Holwedestrasse endgueltig "
                   "seine Tueren\", care bundled at Salzdahlumer Strasse and Celler Strasse; seen 2026-10-09)")},
    "DENIAL0100002vDJ": {
        "what": ("Staedtisches Klinikum Braunschweig, site Holwedestrasse: closed for good, its clinics moved to Salzdahlumer "
                 "Strasse (the administration at Freisestrasse 9-13 stays and is not listed) - "
                 "clinic building"),
        "since": "2024-12-11",
        "until": None,
        "source": ("https://klinikum-braunschweig.de/lib/files/4b5w26djmmxwc7tAnfrwyzjpgq6tml62n8rxk6lfnz5hglzrg7ztgnzvgyzdgnq/48_2024_12_06-pm-wir-ziehen-um-schliessung-des-klinikstandorts-holwedestrasse-ab-dem-11-dezember-2024.pdf "
                   "(Klinikum press release 2024-12-06: \"Am 11. Dezember 2024 schliesst der Standort Holwedestrasse endgueltig "
                   "seine Tueren\", care bundled at Salzdahlumer Strasse and Celler Strasse; seen 2026-10-09)")},
    "DENIAL0100002vnz": {
        "what": ("Staedtisches Klinikum Braunschweig, site Holwedestrasse: closed for good, its clinics moved to Salzdahlumer "
                 "Strasse (the administration at Freisestrasse 9-13 stays and is not listed) - "
                 "clinic wing joined to the main building"),
        "since": "2024-12-11",
        "until": None,
        "source": ("https://klinikum-braunschweig.de/lib/files/4b5w26djmmxwc7tAnfrwyzjpgq6tml62n8rxk6lfnz5hglzrg7ztgnzvgyzdgnq/48_2024_12_06-pm-wir-ziehen-um-schliessung-des-klinikstandorts-holwedestrasse-ab-dem-11-dezember-2024.pdf "
                   "(Klinikum press release 2024-12-06: \"Am 11. Dezember 2024 schliesst der Standort Holwedestrasse endgueltig "
                   "seine Tueren\", care bundled at Salzdahlumer Strasse and Celler Strasse; seen 2026-10-09)")},
    "DENIAL0100002vhq": {
        "what": ("Staedtisches Klinikum Braunschweig, site Holwedestrasse: closed for good, its clinics moved to Salzdahlumer "
                 "Strasse (the administration at Freisestrasse 9-13 stays and is not listed) - "
                 "clinic building"),
        "since": "2024-12-11",
        "until": None,
        "source": ("https://klinikum-braunschweig.de/lib/files/4b5w26djmmxwc7tAnfrwyzjpgq6tml62n8rxk6lfnz5hglzrg7ztgnzvgyzdgnq/48_2024_12_06-pm-wir-ziehen-um-schliessung-des-klinikstandorts-holwedestrasse-ab-dem-11-dezember-2024.pdf "
                   "(Klinikum press release 2024-12-06: \"Am 11. Dezember 2024 schliesst der Standort Holwedestrasse endgueltig "
                   "seine Tueren\", care bundled at Salzdahlumer Strasse and Celler Strasse; seen 2026-10-09)")},
    "DENIAL0100002vkz": {
        "what": ("Staedtisches Klinikum Braunschweig, site Holwedestrasse: closed for good, its clinics moved to Salzdahlumer "
                 "Strasse (the administration at Freisestrasse 9-13 stays and is not listed) - "
                 "clinic building"),
        "since": "2024-12-11",
        "until": None,
        "source": ("https://klinikum-braunschweig.de/lib/files/4b5w26djmmxwc7tAnfrwyzjpgq6tml62n8rxk6lfnz5hglzrg7ztgnzvgyzdgnq/48_2024_12_06-pm-wir-ziehen-um-schliessung-des-klinikstandorts-holwedestrasse-ab-dem-11-dezember-2024.pdf "
                   "(Klinikum press release 2024-12-06: \"Am 11. Dezember 2024 schliesst der Standort Holwedestrasse endgueltig "
                   "seine Tueren\", care bundled at Salzdahlumer Strasse and Celler Strasse; seen 2026-10-09)")},
    "DENIAL0100002vnh": {
        "what": ("Staedtisches Klinikum Braunschweig, site Holwedestrasse: closed for good, its clinics moved to Salzdahlumer "
                 "Strasse (the administration at Freisestrasse 9-13 stays and is not listed) - "
                 "clinic building"),
        "since": "2024-12-11",
        "until": None,
        "source": ("https://klinikum-braunschweig.de/lib/files/4b5w26djmmxwc7tAnfrwyzjpgq6tml62n8rxk6lfnz5hglzrg7ztgnzvgyzdgnq/48_2024_12_06-pm-wir-ziehen-um-schliessung-des-klinikstandorts-holwedestrasse-ab-dem-11-dezember-2024.pdf "
                   "(Klinikum press release 2024-12-06: \"Am 11. Dezember 2024 schliesst der Standort Holwedestrasse endgueltig "
                   "seine Tueren\", care bundled at Salzdahlumer Strasse and Celler Strasse; seen 2026-10-09)")},
    "DENIAL0100002vy2": {
        "what": ("Staedtisches Klinikum Braunschweig, site Holwedestrasse: closed for good, its clinics moved to Salzdahlumer "
                 "Strasse (the administration at Freisestrasse 9-13 stays and is not listed) - "
                 "clinic building"),
        "since": "2024-12-11",
        "until": None,
        "source": ("https://klinikum-braunschweig.de/lib/files/4b5w26djmmxwc7tAnfrwyzjpgq6tml62n8rxk6lfnz5hglzrg7ztgnzvgyzdgnq/48_2024_12_06-pm-wir-ziehen-um-schliessung-des-klinikstandorts-holwedestrasse-ab-dem-11-dezember-2024.pdf "
                   "(Klinikum press release 2024-12-06: \"Am 11. Dezember 2024 schliesst der Standort Holwedestrasse endgueltig "
                   "seine Tueren\", care bundled at Salzdahlumer Strasse and Celler Strasse; seen 2026-10-09)")},
    "DENIAL0100002vBZ": {
        "what": ("Staedtisches Klinikum Braunschweig, site Holwedestrasse: closed for good, its clinics moved to Salzdahlumer "
                 "Strasse (the administration at Freisestrasse 9-13 stays and is not listed) - "
                 "the hospital cafeteria"),
        "since": "2024-12-11",
        "until": None,
        "source": ("https://klinikum-braunschweig.de/lib/files/4b5w26djmmxwc7tAnfrwyzjpgq6tml62n8rxk6lfnz5hglzrg7ztgnzvgyzdgnq/48_2024_12_06-pm-wir-ziehen-um-schliessung-des-klinikstandorts-holwedestrasse-ab-dem-11-dezember-2024.pdf "
                   "(Klinikum press release 2024-12-06: \"Am 11. Dezember 2024 schliesst der Standort Holwedestrasse endgueltig "
                   "seine Tueren\", care bundled at Salzdahlumer Strasse and Celler Strasse; seen 2026-10-09)")},
    "DENIAL0500003Dte": {
        "what": ("St.-Elisabeth-Krankenhaus Salzgitter-Bad (Liebenhaller Strasse 20): closed after the insolvency, patients "
                 "moved, emergency care deregistered (the separate MVZ St. Elisabeth is not listed)"),
        "since": "2026-09-30",
        "until": None,
        "source": ("https://www.aerzteblatt.de/news/krankenhaus-in-salzgitter-schliesst-457df582-069b-420a-91e1-8f23897b0c60 "
                   "(Aerzteblatt 2026-09-28: the hospital \"stellt seinen Betrieb zum Monatsende ein\", about 250 staff affected; "
                   "seen 2026-10-09)")},
    "DENIAL040000er1N": {
        "what": ("former mein real Helmstedt (Werner-von-Siemens-Strasse 3), hypermarket: closed for good, the building stands "
                 "empty"),
        "since": "2024-03-23",
        "until": None,
        "source": ("https://regionalheute.de/die-letzten-real-maerkte-tag-der-schliessung-steht-fest-braunschweig-gifhorn-goslar-harz-helmstedt-peine-salzgitter-wolfenbuettel-wolfsburg-1710333843/ "
                   "(2024-03-13: the mein-real stores Helmstedt, Werner-von-Siemens-Strasse 3, and Wolfsburg-Nordsteimke, "
                   "Hehlinger Strasse 21, close on 23 March; seen 2026-10-09); "
                   "https://www.yumpu.com/de/document/view/71079899/helmstedter-sonntag-vom-05042026 (Helmstedter Sonntag "
                   "2026-04-05: \"Nicht nur der ehemalige Real-Supermarkt steht leer\"; seen 2026-10-09)")},
    "DENIAL9100006RDd": {
        "what": ("former mein real Wolfsburg-Nordsteimke (Hehlinger Strasse 21): closed, the old store pulled down; a new "
                 "Marktkauf is being built on the site, opening planned for 2026-12-03 (re-check then)"),
        "since": "2024-03-23",
        "until": "2026",
        "source": ("https://regionalheute.de/die-letzten-real-maerkte-tag-der-schliessung-steht-fest-braunschweig-gifhorn-goslar-harz-helmstedt-peine-salzgitter-wolfenbuettel-wolfsburg-1710333843/ "
                   "(2024-03-13: the mein-real stores Helmstedt, Werner-von-Siemens-Strasse 3, and Wolfsburg-Nordsteimke, "
                   "Hehlinger Strasse 21, close on 23 March; seen 2026-10-09); "
                   "https://verbund.edeka/verbunds-website/regionsseiten_ez/mh/presse/pdfs-pis/25-11-06-spatenstich-marktkauf-wolfsburg-nordsteimke.pdf "
                   "and .../26-07-16-ein-blick-auf-die-baustelle-des-kuenftigen-marktkauf-wolfsburg-nordsteimke.pdf (EDEKA "
                   "Minden-Hannover: groundbreaking 2025-11-06, opening planned 2026-12-03; seen 2026-10-09 through the search "
                   "index, the files answer 404 now); OSM way/25454662 building=construction, proposed=supermarket (extract "
                   "2026-09-10)")},
    "DENIAL0100001rBq": {
        "what": ("Grotrian-Steinweg piano factory (Grotrian-Steinweg-Strasse 2, Braunschweig): production ended and the factory "
                 "closed after the insolvency of August 2024; OSM marks the outline disused (disused:building=commercial, no "
                 "building tag, so the step-01 extract cannot see it)"),
        "since": "2025-01-31",
        "until": None,
        "source": ("https://en.wikipedia.org/wiki/Grotrian-Steinweg (\"the company filed for insolvency at the end of August "
                   "2024\"; \"In January 2025, Parsons Music Group closed the Grotrian-Steinweg piano factory\"; seen "
                   "2026-10-09); https://api.openstreetmap.org/api/0.6/way/22950062/history (version 6, 2026-05-04: "
                   "building=commercial -> disused:building=commercial; seen 2026-10-09)")},
    "DENIAL0100000U6B": {
        "what": ("Gewerbepark Braunschweig, Steinriedendamm 15, Halle 22 (OSM \"Gebaeude 22\"): empty and under conversion when "
                 "seen on 2026-10-09 (the day it emptied is not known), to let from June 2027"),
        "since": "2026-10-09",
        "until": "2027",
        "source": ("https://mileway.com/de/immobilien/de/portfolio/steinriedendamm-15-halle-22/ (\"Die Halle befindet sich "
                   "derzeit im Umbau und wird voraussichtlich im Q4 2027 fertiggestellt\"; available 01.06.2027; seen 2026-10-09)")},
    "DENIAL0100004ZYO": {
        "what": ("the indoor tennis hall (2 courts) of the Sportanlage Rote Wiese, Braunschweig: closed by the city for "
                 "structural defects of its timber trusses, a repair rejected, demolition decided; today OSM maps no building on "
                 "its footprint"),
        "since": "2022-03-24",
        "until": None,
        "source": ("https://ratsinfo.braunschweig.de/integration/wicket/resource/org.apache.wicket.Application/doc1560592.pdf, "
                   ".../public/.../doc1583149.pdf and .../doc1646107.pdf (city statements 2022-2023: closed on 24 March 2022, "
                   "permanently unusable, Rueckbau planned; seen 2026-10-09 through the search index, the files sit behind a bot "
                   "check); overpass-api.de (no building within 80 m of the footprint centre 52.23779, 10.53213; seen 2026-10-09)")},
    "DENIAL0300001Gif": {
        "what": ("the former Freizeitcenter Seesen (bowling; Hermann-Loens-Strasse 1A, Seesen): OSM has named it \"ehemaliges "
                 "Freizeitcenter Seesen\" since 2019 and carries no leisure or amenity tag (only sport=10pin); its website shows "
                 "only the domain name"),
        "since": "2019-11-13",
        "until": None,
        "source": ("https://api.openstreetmap.org/api/0.6/way/210566593/history (version 4, 2019-11-13: name \"Freizeitcenter "
                   "Seesen\" -> \"ehemaliges Freizeitcenter Seesen\", kept in version 5 of 2026-01-04; no leisure or amenity tag; "
                   "seen 2026-10-09); http://www.freizeitcenter-seesen.de (only the domain name; seen 2026-10-09)")},
    "DENIAL0100002vAV": {
        "what": ("the former prison Braunschweig-Rennelberg (Justizvollzugsanstalt, Rennelbergstrasse 10): cleared in May 2024, "
                 "its security systems removed, the site for sale - the main building"),
        "since": "2024-05",
        "until": None,
        "source": ("https://www.volksstimme.de/panorama/bald-hotel-oder-restaurant-gefangnis-steht-zum-verkauf-4118064 (dpa "
                   "2025-09-19: \"Im Mai 2024 wurde das 1884 fertiggestellte Gefaengnis geraeumt\", the state offers it for sale "
                   "from 3.6 million euros; seen 2026-10-09); https://www.tageskarte.io/war-noch-was/detail/bald-hotel-oder-"
                   "restaurant-gefaengnis-in-braunschweig-steht-zum-verkauf.html (2025-09-21; seen 2026-10-09)")},
    "DENIAL0100002vsh": {
        "what": ("the former prison Braunschweig-Rennelberg (Justizvollzugsanstalt, Rennelbergstrasse 10): cleared in May 2024, "
                 "its security systems removed, the site for sale - a prison building next to it"),
        "since": "2024-05",
        "until": None,
        "source": ("https://www.volksstimme.de/panorama/bald-hotel-oder-restaurant-gefangnis-steht-zum-verkauf-4118064 (dpa "
                   "2025-09-19: \"Im Mai 2024 wurde das 1884 fertiggestellte Gefaengnis geraeumt\", the state offers it for sale "
                   "from 3.6 million euros; seen 2026-10-09); https://www.tageskarte.io/war-noch-was/detail/bald-hotel-oder-"
                   "restaurant-gefaengnis-in-braunschweig-steht-zum-verkauf.html (2025-09-21; seen 2026-10-09)")},
    "DENIAL0100002vn5": {
        "what": ("the former prison Braunschweig-Rennelberg (Justizvollzugsanstalt, Rennelbergstrasse 10): cleared in May 2024, "
                 "its security systems removed, the site for sale - the laundry and kitchen building (OSM way/37808007 \"JVA "
                 "Waschhaus/Kuechengebaeude\")"),
        "since": "2024-05",
        "until": None,
        "source": ("https://www.volksstimme.de/panorama/bald-hotel-oder-restaurant-gefangnis-steht-zum-verkauf-4118064 (dpa "
                   "2025-09-19: \"Im Mai 2024 wurde das 1884 fertiggestellte Gefaengnis geraeumt\", the state offers it for sale "
                   "from 3.6 million euros; seen 2026-10-09); https://www.tageskarte.io/war-noch-was/detail/bald-hotel-oder-"
                   "restaurant-gefaengnis-in-braunschweig-steht-zum-verkauf.html (2025-09-21; seen 2026-10-09)")},
    "DENIAL0100002vBc": {
        "what": ("the former prison Braunschweig-Rennelberg (Justizvollzugsanstalt, Rennelbergstrasse 10): cleared in May 2024, "
                 "its security systems removed, the site for sale - the staff house (OSM way/41853951 \"JVA Beamtenwohnung\")"),
        "since": "2024-05",
        "until": None,
        "source": ("https://www.volksstimme.de/panorama/bald-hotel-oder-restaurant-gefangnis-steht-zum-verkauf-4118064 (dpa "
                   "2025-09-19: \"Im Mai 2024 wurde das 1884 fertiggestellte Gefaengnis geraeumt\", the state offers it for sale "
                   "from 3.6 million euros; seen 2026-10-09); https://www.tageskarte.io/war-noch-was/detail/bald-hotel-oder-"
                   "restaurant-gefaengnis-in-braunschweig-steht-zum-verkauf.html (2025-09-21; seen 2026-10-09)")},
}
# All together against run 16 (round 17 with the fixes of its review): Workers 7,305 (1.23 %), Retail_Daily 12,936 (1.42 %),
# Retail_Non-Daily 2,887 (0.37 %), Leisure 2,045 (0.92 %) and University 49 (0.13 %: the vacant AStA workshop of run 16 now keeps
# the floor it would occupy if active) move, School and Kindergarten nothing; the visitor values: business -1,171 (-2.8 %), errands
# -937 (-0.4 %), sports -12,420 (-10.2 %), meetup -360 (-1.0 %), lessons -401 (-2.7 %) a day; 420 buildings and 20 asked POIs
# give no unit (vacant, gone or closed; 288 and 5 in run 16), 115 buildings change storeys and 23 their class; the last-carrier guard
# restores 54 rows (the closed Holwedestrasse cafeteria's Retail_Daily row goes: its zone's share takes the ring fallback).
REDIST_FALLBACK_MAX_RINGS = None                # None: widen until carriers are found; an int stops there, the rest is logged unassigned
REDISTRIBUTION_FILE = OUTPUT_DIR / "08_redistribution.gpkg"


# =============================================================================
# STEP 08b — floor-area comparison: step 08 on floor area instead of volume
# =============================================================================
# The FGSV Bosserhof factors are workers per 100 m2 of gross floor area, not per m3 (the
# 2026-08-19 bug report on the previous pipeline, BUG-04). Step 08 weights by volume, so a
# 16 m single-storey hall weighs four times a 4 m building of the same footprint. Notebook
# 08b repeats step 08 unchanged except for the size measure and puts both runs side by side.
# Decided with the user 2026-10-05:
#   * floor area = footprint x storeys, storeys = max(1, round(h / FLOOR_STOREY_HEIGHT_M));
#     h = the eaves height (the roof space is not counted), capped at the mean height
#     volume / footprint so that a tower part does not lift the whole footprint; the mean
#     height where no eaves height exists (the 1,600 OSM gap rows);
#   * a hall counts as one storey whatever its height: its Bosserhof class is in
#     HALL_BOSSERHOF_CLASSES or the head of its step-05 type matches HALL_TYPE_PATTERN - but
#     never when the head matches HALL_TYPE_EXCLUDE_PATTERN: an office (the user's rule) and,
#     added on the data, a town or city hall, a headquarters or administration building, a
#     residential or mixed-use building ("a small industrial workshop and commercial units
#     above residential apartments");
#   * the head of the type is the text before the first "with", "housing", "containing",
#     "including", "shared by", comma, semicolon or bracket (HALL_TYPE_HEAD_SPLIT): the words
#     must describe the building, not something in it. Reading the whole type in the first
#     run kept real halls multi-storey on "post office", the verb "housing" or
#     "home-improvement" (VW Halle 16 got 5 storeys and +10,054 workers from its neighbours)
#     and made schools "with sports halls" one storey;
#   * OSM building:levels, where mapped, gives the storeys and overrides both
#     (FLOOR_OSM_LEVELS_MAX);
#   * floor area replaces volume for every category; everything else - units, shares, rest
#     units, vacancy, factors, fallback - is step 08's.
# One storey height for every building makes floor area about volume / 3.5, i.e. nearly
# the volume run: the differences come from the hall rule, the rounding to whole storeys and
# eaves vs mean height.
FLOOR_STOREY_HEIGHT_M = 3.5
# The hall classes: all four groups the user picked (2026-10-05, in a parallel session merged
# into this one): industry, storage and transport; big-box retail and car dealers; crafts and
# vehicle repair; arenas, discos and leisure pools.
HALL_BOSSERHOF_CLASSES = frozenset({
    "Transport",
    "Industrial operations / Production",
    "highly productive industries / machine / material or space intensive",
    "others",                                   # the industrial "others" (BOSSERHOF_NORMALIZATION_MAP)
    "Yards, depots, storage areas, construction yards",
    "wholesale", "discount stores", "DIY stores", "furniture stores", "hypermarkets / superstores",
    "self-service department stores", "car dealerships", "suppliers for car dealerships",
    "Crafts and trades", "craft businesses", "craft courtyards", "vehicle / electrical repair",
    "arenas, large events", "large discos, fun / leisure pools",
})
# OSM building:levels, where mapped as a whole number from 1 to this, gives the storeys and
# overrides the hall rule and the height (the user, 2026-10-05). On the kept buildings it is
# mapped on 212 OSM gap rows only, whose 2 m storey height would otherwise undercount them.
FLOOR_OSM_LEVELS_MAX = 60
HALL_TYPE_HEAD_SPLIT = r"\s+(?:with|housing|containing|including|shared\s+by)\s+|[,;(]"
HALL_TYPE_PATTERN = r"\b(?:halls?|warehouses?|factory|factories|workshops?|depots?)\b"
HALL_TYPE_EXCLUDE_PATTERN = (r"\boffices?\b|\b(?:town|city)\s+halls?\b|\bheadquarters\b|\badministrat\w*"
                             r"|\b(?:residential|apartments?|dwellings?|mixed\W?use)\b")
# For a plausibility check only, never a weight: the FGSV range per class in workers per
# 100 m2 of gross floor area, (low, high), from the previous pipeline's source table
# (Capacity_Calculation-pipeline-original/bosserhof-based-vs-visum-based-redistribution.ipynb).
# BOSSERHOF_WEIGHTS holds the midpoints (notebook 08 checks it). Single values where the table
# gives one; the headline classes and three of the four classes added later (discos / leisure
# pools, arenas, theme parks) have none. That table gives vehicle / electrical repair 1.7-2.3
# and small-scale retail 2.5-5.0; the user fixed both on 2026-10-05 from their sources - 1.7-3.3
# (30-60 m2 per employee, as the bug report quotes FGSV) and 2.0-5.0 (20-50 m2 per employee) -
# and added nursing homes 1.0-1.5 (STEP 08, BOSSERHOF_WEIGHTS).
BOSSERHOF_FGSV_RANGES = {
    "transport": (0.5, 0.5),
    "yards depots storage areas construction yards": (0.7, 1.0),
    "highly productive industries machine material or space intensive": (0.7, 1.0),
    "others industrial": (1.7, 2.0),
    "craft businesses": (1.3, 2.5),
    "craft courtyards": (1.7, 2.0),
    "normal office": (2.5, 3.3),
    "open plan office": (3.3, 5.0),
    "business oriented services": (2.0, 5.0),
    "customer oriented services": (2.0, 4.0),
    "hotels": (1.0, 2.0),
    "hotels with conference areas": (0.7, 0.9),
    "restaurants gastronomy": (1.3, 2.5),
    "suppliers for car dealerships": (1.7, 1.7),
    "vehicle electrical repair": (1.7, 3.3),
    "customer service": (3.3, 3.3),
    "car dealerships": (0.7, 0.7),
    "wholesale": (2.0, 2.9),
    "retail small scale": (2.0, 5.0),
    "discount stores": (0.7, 1.1),
    "diy stores": (0.7, 0.8),
    "furniture stores": (0.4, 0.7),
    "hypermarkets superstores": (1.0, 1.4),
    "shopping centers": (2.2, 4.0),
    "self service department stores": (1.0, 1.2),
    "department stores": (1.3, 1.8),
    "factory outlet centers": (1.8, 2.5),
    "schools": (0.5, 1.5),
    "universities": (0.5, 1.0),
    "research institutes": (1.0, 1.5),
    "kindergartens": (1.7, 2.9),
    "hospitals": (1.0, 1.5),
    "nursing homes": (1.0, 1.5),
    "entertainment culture": (1.67, 1.67),
    "large cinemas": (0.83, 0.83),
    "musical theatres": (1.43, 1.43),
    "fitness wellness": (0.8, 0.8),
}
FLOOR_AREA_COMPARISON_FILE = OUTPUT_DIR / "08b_floor_area_comparison.gpkg"
