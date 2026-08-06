"""
rule_utils.py — Deterministic, tag-based building activity / Bosserhof classifier.

WHAT THIS DOES
  Takes one building row and returns two things:
    * mid_labels      — which MiD activities happen there (subset of the 12 in
                        config.TARGET_MID_LABELS)
    * bosserhof_class — one worker-density class (one of the 47 in
                        config.BOSSERHOF_WEIGHTS), used by notebook 07

  Every answer comes from an explicit lookup table below. There is one row per
  tag value, and the row IS the rule — no scoring, no regex ordering, no
  inference. To change what a tag means, edit its row. Nothing else.

THE THREE LAYERS (strict precedence — first layer that answers, wins)
  1. OSM POI tags on the building: amenity / shop / tourism / building /
     information, plus key:value pairs recovered from `additional_information`
     (office=*, craft=*, social_facility=*). A building may carry several POIs;
     each is looked up and the results are reconciled (`reconcile_multi_poi`).
  2. ALKIS building-function code (`function`, e.g. "31001_2000") against
     ALKIS_RULES — one row per code, 71 of which occur in this study area.
  3. OSM footprint type (`osm_building_type`) then OSM land use
     (`osm_landuse_class`) — for buildings with neither a POI nor an ALKIS code.

  Precedence is strict: if a layer returns an answer — including an explicit
  "no activity" — later layers are not consulted. Letting exclusions fall
  through to layer 3 was measured and would reclassify 492 of 252,470
  buildings (0.19%), so it buys nothing and costs predictability.

KEYED ON THE ALKIS CODE, NOT THE ENGLISH LABEL
  The code is the authoritative identifier. The shipped English text is not:
  `31001_3031` is "Schloss" (a palace) but is translated "Lock", and 15 of 301
  codes share a label with another code. Notebook 05 therefore carries
  `function` through, and this module never rules on translated text.

DELIBERATELY NOT USED: `osm_names` / any free-text business name. Knowing that
"Bahlsen" is a food manufacturer is world knowledge a tag rule cannot encode
without becoming a name lookup table for one region — the opposite of a
generalizable pipeline. That is the accepted limitation being measured here,
not an oversight; see data/validation/.

KNOWN CEILING — READ THIS BEFORE INTERPRETING ANY RESULT
  ALKIS code 31001_2000 ("Gebäude für Wirtschaft oder Gewerbe") covers 42.6% of
  this study area and 82.0% of ALL non-residential codes state-wide. Its median
  volume is 126 m³, and the specific code for a garage (31001_2463) exists but
  is used 0 times in 4,878,052 buildings — so garages, sheds and outbuildings
  sit in this bucket alongside genuine commercial premises. No rule can
  separate them from the code alone. This is a property of cadastral coding
  practice and it bounds ANY method reading ALKIS, including an LLM.
  Deliberately left uncorrected so the ceiling is measured, not hidden.
"""

import ast
import pandas as pd

from config import TARGET_MID_LABELS, BOSSERHOF_WEIGHTS

# ──────────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────────

def is_missing(x):
    if x is None: return True
    if isinstance(x, float) and pd.isna(x): return True
    if isinstance(x, str) and x.strip().lower() in ("", "none", "nan", "null"): return True
    if isinstance(x, (list, tuple, set, dict)) and len(x) == 0: return True
    return False


def as_list(x):
    """Normalize a cell into a clean list of individual tag values.

    Handles real lists, stringified lists ("['a', 'b']"), scalars, and missing
    values — and splits on ";", which is OSM's multi-value separator. That last
    step matters: 84 `osm_building_type` values in this dataset are composites
    like "church;yes" or "school;yes" (249 rows). Splitting them here lets the
    existing "church"/"school" rules answer, instead of needing one table row
    per observed combination.
    """
    if is_missing(x):
        return []
    if isinstance(x, (list, tuple, set)):
        raw = [str(v) for v in x if not is_missing(v)]
    else:
        s = str(x).strip()
        raw = None
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = ast.literal_eval(s)
                if isinstance(parsed, (list, tuple, set)):
                    raw = [str(v) for v in parsed if not is_missing(v)]
            except (ValueError, SyntaxError):
                pass
        if raw is None:
            raw = [s]
    out = []
    for item in raw:
        for part in item.split(";"):
            part = part.strip()
            if part and not is_missing(part):
                out.append(part)
    return out


def parse_additional_information(x):
    """`additional_information` is built (notebook 03) as semicolon-separated
    'key: value' pairs from OSM POI columns that weren't promoted to their own
    column (e.g. 'office: government; craft: bakery'). Recover that structure
    so those tags can be ruled on like any other."""
    out = {}
    for item in as_list(x):
        if ":" in item:
            k, v = item.split(":", 1)
            out[k.strip().lower()] = v.strip().lower()
    return out


BOSSERHOF_WEIGHTS_LOWER = {k.lower(): v for k, v in BOSSERHOF_WEIGHTS.items()}


def weight_of(bosserhof_class):
    if not bosserhof_class:
        return -1.0
    return BOSSERHOF_WEIGHTS_LOWER.get(bosserhof_class.lower(), -1.0)


# ══════════════════════════════════════════════════════════════════════════
# LAYER 1 — OSM POI tags on the building itself
#
# Table format, used by every table in this layer:
#     "tag_value": ({mid_labels}, "bosserhof_class")
#
# (set(), None) means "explicitly carries no activity" — NOT an oversight.
# `_lookup_all` treats it as a non-hit, so the building falls through to the
# next layer, but recording it here documents that the value was considered.
#
# `work` is NOT listed in these tables. It is added centrally in
# classify_building() to every building that receives a Bosserhof class,
# because a Bosserhof class IS a worker-density rating. These tables therefore
# describe only the visitor-facing purpose of a POI.
#
# Zone-column note: the 12 MiD labels collapse to 7 zone activity columns in
# config.MID_LABEL_TO_ACTIVITY —
#     work, business                     -> Workers
#     retail_daily, errands              -> Retail_Daily
#     retail_non_daily                   -> Retail_Non-Daily
#     leisure, sports, meetup, lessons   -> Leisure
#     school / university / childcare    -> School / University / Kindergarten
# A distinction within a group (sports vs leisure) is descriptive only; a
# distinction across groups changes the result.
# ══════════════════════════════════════════════════════════════════════════

# ── LAYER 1a — amenity=* ─────────────────────────────────────────────────
AMENITY_RULES = {
    # Food & drink. Eating out is discretionary (MiD "Freizeit"), not a
    # functional task, so this is leisure only — never errands.
    "restaurant":        ({"leisure"}, "restaurants gastronomy"),
    "fast_food":         ({"leisure"}, "restaurants gastronomy"),
    "cafe":              ({"leisure"}, "restaurants gastronomy"),
    "pub":               ({"leisure"}, "restaurants gastronomy"),
    "bar":               ({"leisure"}, "restaurants gastronomy"),
    "biergarten":        ({"leisure"}, "restaurants gastronomy"),
    "ice_cream":         ({"leisure"}, "restaurants gastronomy"),
    "food_court":        ({"leisure"}, "restaurants gastronomy"),
    "nightclub":         ({"leisure"}, "large discos fun leisure pools"),
    "casino":            ({"leisure"}, "large discos fun leisure pools"),
    # Betting/lottery shops: small-format gambling, leisure not errands.
    "gambling":          ({"leisure"}, "customer oriented services"),

    # Education. `lessons` -> Leisure, which is correct here: the School zone
    # target sums general-education pupil counts (SG_4_BS/GSCH/WFSCH), so
    # private course providers do not belong in it.
    "school":            ({"school"}, "schools"),
    "college":           ({"school"}, "schools"),   # German Berufskolleg/Fachschule
    "university":        ({"university"}, "universities"),
    "kindergarten":      ({"childcare"}, "kindergartens"),
    "childcare":         ({"childcare"}, "kindergartens"),
    "driving_school":    ({"lessons"}, "customer oriented services"),
    "music_school":      ({"lessons"}, "customer oriented services"),
    "language_school":   ({"lessons"}, "customer oriented services"),
    "dancing_school":    ({"lessons"}, "customer oriented services"),
    "prep_school":       ({"lessons"}, "customer oriented services"),
    "training":          ({"lessons"}, "customer oriented services"),
    "research_institute":({"work"}, "research institutes"),
    "library":           ({"leisure"}, "public facilities"),

    # Healthcare
    "hospital":          ({"errands"}, "hospitals"),
    "clinic":            ({"errands"}, "hospitals"),
    "doctors":           ({"errands"}, "customer oriented services"),
    "dentist":           ({"errands"}, "customer oriented services"),
    "pharmacy":          ({"retail_daily"}, "customer oriented services"),
    "veterinary":        ({"errands"}, "customer oriented services"),
    "naturopathy":       ({"errands"}, "customer oriented services"),
    "social_facility":   ({"errands"}, "nursing homes"),
    "nursing_home":      ({"errands"}, "nursing homes"),

    # Public / civic
    "townhall":          ({"errands"}, "public facilities"),
    "courthouse":        ({"errands"}, "public facilities"),
    "police":            ({"errands"}, "public facilities"),
    "public_building":   ({"errands"}, "public facilities"),
    "fire_station":      ({"work"}, "public facilities"),
    "post_office":       ({"errands"}, "customer oriented services"),
    "post_depot":        ({"errands"}, "customer oriented services"),
    "community_centre":  ({"meetup", "leisure"}, "public facilities"),
    "social_centre":     ({"meetup", "leisure"}, "public facilities"),
    "fraternity":        ({"meetup"}, "public facilities"),
    "events_venue":      ({"meetup", "leisure"}, "arenas large events"),
    "conference_centre": ({"business", "meetup"}, "hotels with conference areas"),
    "place_of_worship":  ({"meetup", "leisure"}, "public facilities"),
    "arts_centre":       ({"leisure"}, "entertainment culture"),
    "theatre":           ({"leisure"}, "musical theatres"),
    "cinema":            ({"leisure"}, "large cinemas"),
    "exhibition_centre": ({"leisure", "business"}, "arenas large events"),

    # Money
    "bank":              ({"errands"}, "customer oriented services"),
    "bureau_de_change":  ({"errands"}, "customer oriented services"),

    # Vehicles / transport-adjacent enterable buildings
    "fuel":              ({"errands"}, "transport"),
    # A wash hall is largely automated: `car dealerships` (0.7) is the
    # low-density vehicle-premises class. Matches ALKIS 31001_2131.
    "car_wash":          ({"errands"}, "car dealerships"),
    "vehicle_inspection":({"errands"}, "vehicle electrical repair"),
    "car_rental":        ({"errands"}, "car dealerships"),
    "ferry_terminal":    ({"errands"}, "transport"),
    "bus_station":       ({"errands"}, "transport"),

    # Miscellaneous enterable
    "coworking_space":   ({"work", "business"}, "open plan office"),
    "studio":            ({"work", "business"}, "normal office"),
    "gym":               ({"sports"}, "fitness wellness"),
    "spa":               ({"leisure"}, "fitness wellness"),
    "internet_cafe":     ({"leisure"}, "customer oriented services"),
    "ski_rental":        ({"errands"}, "customer oriented services"),
    "animal_shelter":    ({"work"}, "others industrial"),
    "animal_boarding":   ({"work"}, "others industrial"),
    "greenhouse":        ({"work"}, "others industrial"),
    "funeral_hall":      ({"errands"}, "public facilities"),
    "crematorium":       ({"errands"}, "public facilities"),

    # Not buildings / not destinations.
    "public_bookcase":   (set(), None),
    "shower":            (set(), None),
    "photo_booth":       (set(), None),
    "dressing_room":     (set(), None),
    "luggage_locker":    (set(), None),
    # Residential — "home" is not a target MiD label.
    "student_accomodation": (set(), None),
    "dwelling_house":    (set(), None),
}

# ── LAYER 1b — shop=* ────────────────────────────────────────────────────
# The daily/non-daily split is the load-bearing decision here: convenience and
# food goods -> retail_daily; durables and specialty goods -> retail_non_daily;
# service-type premises (hairdresser, optician, bank-like) -> errands.
SHOP_RULES = {
    # Daily / convenience goods
    "supermarket":       ({"retail_daily"}, "discount stores"),
    "hypermarket":       ({"retail_daily", "retail_non_daily"}, "hypermarkets superstores"),
    "discount":          ({"retail_daily"}, "discount stores"),
    "convenience":       ({"retail_daily"}, "retail small scale"),
    "bakery":            ({"retail_daily"}, "retail small scale"),
    "butcher":           ({"retail_daily"}, "retail small scale"),
    "greengrocer":       ({"retail_daily"}, "retail small scale"),
    "kiosk":             ({"retail_daily"}, "retail small scale"),
    "beverages":         ({"retail_daily"}, "retail small scale"),
    "alcohol":           ({"retail_daily"}, "retail small scale"),
    "wine":              ({"retail_daily"}, "retail small scale"),
    "coffee":            ({"retail_daily"}, "retail small scale"),
    "tea":               ({"retail_daily"}, "retail small scale"),
    "chemist":           ({"retail_daily"}, "retail small scale"),
    "general":           ({"retail_daily"}, "retail small scale"),
    "variety_store":     ({"retail_daily"}, "retail small scale"),
    "farm":              ({"retail_daily"}, "retail small scale"),
    "deli":              ({"retail_daily"}, "retail small scale"),
    "confectionery":     ({"retail_daily"}, "retail small scale"),
    "pastry":            ({"retail_daily"}, "retail small scale"),
    "dairy":             ({"retail_daily"}, "retail small scale"),
    "seafood":           ({"retail_daily"}, "retail small scale"),
    "health_food":       ({"retail_daily"}, "retail small scale"),
    "newsagent":         ({"retail_daily"}, "retail small scale"),
    "stationery":        ({"retail_daily"}, "retail small scale"),
    "tobacco":           ({"retail_daily"}, "retail small scale"),

    # Non-daily / durable / specialty goods
    "clothes":           ({"retail_non_daily"}, "retail small scale"),
    "boutique":          ({"retail_non_daily"}, "retail small scale"),
    "fashion_accessories": ({"retail_non_daily"}, "retail small scale"),
    "shoes":             ({"retail_non_daily"}, "retail small scale"),
    "bag":               ({"retail_non_daily"}, "retail small scale"),
    "jewelry":           ({"retail_non_daily"}, "retail small scale"),
    "watches":           ({"retail_non_daily"}, "retail small scale"),
    "cosmetics":         ({"retail_non_daily"}, "retail small scale"),
    "perfumery":         ({"retail_non_daily"}, "retail small scale"),
    "electronics":       ({"retail_non_daily"}, "retail small scale"),
    "mobile_phone":      ({"retail_non_daily"}, "retail small scale"),
    "computer":          ({"retail_non_daily"}, "retail small scale"),
    "video_games":       ({"retail_non_daily"}, "retail small scale"),
    "e-cigarette":       ({"retail_non_daily"}, "retail small scale"),
    "florist":           ({"retail_non_daily"}, "retail small scale"),
    "books":             ({"retail_non_daily"}, "retail small scale"),
    "toys":              ({"retail_non_daily"}, "retail small scale"),
    "baby_goods":        ({"retail_non_daily"}, "retail small scale"),
    "sports":            ({"retail_non_daily"}, "retail small scale"),
    "outdoor":           ({"retail_non_daily"}, "retail small scale"),
    "bicycle":           ({"retail_non_daily"}, "retail small scale"),
    "musical_instrument":({"retail_non_daily"}, "retail small scale"),
    "photo":             ({"retail_non_daily"}, "retail small scale"),
    "art":               ({"retail_non_daily"}, "retail small scale"),
    "antiques":          ({"retail_non_daily"}, "retail small scale"),
    "craft":             ({"retail_non_daily"}, "retail small scale"),
    "fabric":            ({"retail_non_daily"}, "retail small scale"),
    "houseware":         ({"retail_non_daily"}, "retail small scale"),
    "interior_decoration": ({"retail_non_daily"}, "retail small scale"),
    "fireplace":         ({"retail_non_daily"}, "retail small scale"),
    "weapons":           ({"retail_non_daily"}, "retail small scale"),
    "erotic":            ({"retail_non_daily"}, "retail small scale"),
    "pet":               ({"retail_non_daily"}, "retail small scale"),
    "second_hand":       ({"retail_non_daily"}, "retail small scale"),
    "charity":           ({"retail_non_daily"}, "retail small scale"),
    "gift":              ({"retail_non_daily"}, "retail small scale"),
    "variety":           ({"retail_non_daily"}, "retail small scale"),
    "furniture":         ({"retail_non_daily"}, "furniture stores"),
    "kitchen":           ({"retail_non_daily"}, "furniture stores"),
    "bathroom_furnishing": ({"retail_non_daily"}, "furniture stores"),
    "bed":               ({"retail_non_daily"}, "furniture stores"),
    "doityourself":      ({"retail_non_daily"}, "diy stores"),
    "hardware":          ({"retail_non_daily"}, "diy stores"),
    "garden_centre":     ({"retail_non_daily"}, "diy stores"),
    "paint":             ({"retail_non_daily"}, "diy stores"),
    "tiles":             ({"retail_non_daily"}, "diy stores"),
    "trade":             ({"retail_non_daily", "business"}, "wholesale"),
    "wholesale":         ({"retail_non_daily", "business"}, "wholesale"),
    "agrarian":          ({"retail_non_daily", "business"}, "wholesale"),
    "department_store":  ({"retail_non_daily"}, "department stores"),
    "mall":              ({"retail_non_daily"}, "shopping centers"),
    "car":               ({"retail_non_daily"}, "car dealerships"),
    "car_parts":         ({"retail_non_daily"}, "car dealerships"),
    "motorcycle":        ({"retail_non_daily"}, "car dealerships"),

    # Service premises — a visit is a functional task, not shopping.
    "car_repair":        ({"errands"}, "vehicle electrical repair"),
    "tyres":             ({"errands"}, "vehicle electrical repair"),
    "laundry":           ({"errands"}, "customer oriented services"),
    "dry_cleaning":      ({"errands"}, "customer oriented services"),
    "hairdresser":       ({"errands"}, "customer oriented services"),
    "beauty":            ({"errands"}, "customer oriented services"),
    "tattoo":            ({"errands"}, "customer oriented services"),
    "pet_grooming":      ({"errands"}, "customer oriented services"),
    "optician":          ({"errands"}, "customer oriented services"),
    # Fitted medical devices sold with a professional service component —
    # treated like `optician`, the closest analogue.
    "hearing_aids":      ({"errands"}, "customer oriented services"),
    "medical_supply":    ({"errands"}, "customer oriented services"),
    "funeral_directors": ({"errands"}, "customer oriented services"),
    "travel_agency":     ({"errands"}, "customer oriented services"),
    "ticket":            ({"errands"}, "customer oriented services"),
    "rental":            ({"errands"}, "customer oriented services"),
    "pawnbroker":        ({"errands"}, "customer oriented services"),
    "massage":           ({"leisure"}, "customer oriented services"),
    "lottery":           ({"leisure"}, "customer oriented services"),
    "bookmaker":         ({"leisure"}, "customer oriented services"),
    "tailor":            ({"errands"}, "craft businesses"),
    "shoe_repair":       ({"errands"}, "craft businesses"),
    "locksmith":         ({"errands"}, "craft businesses"),
    "copyshop":          ({"errands", "business"}, "business oriented services"),
    "estate_agent":      ({"business"}, "business oriented services"),
    "insurance":         ({"business"}, "business oriented services"),
    "storage_rental":    (set(), None),   # self-storage: unstaffed

    # shop=yes states that it IS retail but not which kind — so it gets the
    # generic `retail` class, exactly as building=retail does.
    "yes":               ({"retail_daily", "retail_non_daily"}, "retail"),
    "no":                (set(), None),
    "vacant":            (set(), None),
    "empty":             (set(), None),
}

# ── LAYER 1c — tourism=* ─────────────────────────────────────────────────
# Accommodation keeps `leisure`: hotels host resident-facing functions (bars,
# restaurants, events) and Leisure is the only zone column those can reach.
TOURISM_RULES = {
    "hotel":       ({"leisure"}, "hotels"),
    "guest_house": ({"leisure"}, "hotels"),
    "hostel":      ({"leisure"}, "hotels"),
    "chalet":      ({"leisure"}, "hotels"),
    "apartment":   ({"leisure"}, "hotels"),
    "motel":       ({"leisure"}, "hotels"),
    "museum":      ({"leisure"}, "entertainment culture"),
    "gallery":     ({"leisure"}, "entertainment culture"),
    "theme_park":  ({"leisure"}, "theme parks"),
    "aquarium":    ({"leisure"}, "entertainment culture"),
    "zoo":         ({"leisure"}, "entertainment culture"),
    "attraction":  ({"leisure"}, "entertainment culture"),
}

# ── LAYER 1d — building=* ────────────────────────────────────────────────
# Shared vocabulary, applied to BOTH the POI-level `building` column (layer 1)
# and the footprint-level `osm_building_type` column (layer 3). Same OSM tag
# semantics, attached at different pipeline stages, so one table serves both.
BUILDING_TAG_RULES = {
    # Residential — "home" is not a target MiD label.
    "house": (set(), None), "detached": (set(), None), "semidetached_house": (set(), None),
    "apartments": (set(), None), "dormitory": (set(), None), "bungalow": (set(), None),
    "residential": (set(), None), "terrace": (set(), None), "static_caravan": (set(), None),
    "cabin": (set(), None),

    # Vehicle storage — not a destination in its own right. `garage` is the
    # single most frequent value that would otherwise go unmapped (~1,900).
    "garage": (set(), None), "garages": (set(), None), "carport": (set(), None),
    "parking": (set(), None),

    # Agriculture. ALKIS already excludes "Land- und forstwirtschaftliches
    # Betriebsgebäude" (config.LABELS_TO_REMOVE), so the OSM side matches:
    # livestock and farm structures carry no destination activity. Greenhouses
    # are the exception — commercial horticulture — mirroring ALKIS keeping
    # 31001_2740 "Gewächshaus".
    "barn": (set(), None), "stable": (set(), None), "cowshed": (set(), None),
    "sty": (set(), None), "farm": (set(), None), "farm_auxiliary": (set(), None),
    "allotment_house": (set(), None), "slurry_tank": (set(), None),
    "digester": (set(), None), "silo": (set(), None), "aviary": (set(), None),
    "greenhouse":   ({"work"}, "others industrial"),
    "conservatory": (set(), None),          # Wintergarten, part of a dwelling
    "riding_hall":  ({"sports"}, "fitness wellness"),   # Reithalle is a venue

    # No usable information, or not an enterable staffed structure.
    "yes": (set(), None), "no": (set(), None),
    "roof": (set(), None), "shed": (set(), None), "hut": (set(), None),
    "container": (set(), None), "outbuilding": (set(), None),
    "construction": (set(), None), "ruins": (set(), None),
    "hall": (set(), None),          # Halle: could be industrial, sport, events
    "service": (set(), None),       # OSM wiki: small unstaffed utility building
    "storage_tank": (set(), None), "transformer_tower": (set(), None),
    "toilets": (set(), None), "windmill": (set(), None), "tower": (set(), None),
    "bunker": (set(), None), "boathouse": (set(), None), "guardhouse": (set(), None),
    "grandstand": (set(), None),    # open-air, no enclosed volume
    "pavilion": (set(), None),

    # Commercial / industrial
    "commercial":   ({"work", "business"}, "services"),
    "office":       ({"work", "business"}, "normal office"),
    "retail":       ({"retail_daily", "retail_non_daily"}, "retail"),
    "supermarket":  ({"retail_daily"}, "discount stores"),
    "kiosk":        ({"retail_daily"}, "retail small scale"),
    "restaurant":   ({"leisure"}, "restaurants gastronomy"),
    "industrial":   ({"work"}, "industrial operations production"),
    "manufacture":  ({"work"}, "industrial operations production"),
    "factory":      ({"work"}, "industrial operations production"),
    "warehouse":    ({"work"}, "yards depots storage areas construction yards"),
    "hangar":       ({"work"}, "yards depots storage areas construction yards"),

    # Religious — one answer for the whole family (see ALKIS 3041/3043/3045).
    "church":    ({"meetup", "leisure"}, "public facilities"),
    "chapel":    ({"meetup", "leisure"}, "public facilities"),
    "cathedral": ({"meetup", "leisure"}, "public facilities"),
    "mosque":    ({"meetup", "leisure"}, "public facilities"),
    "synagogue": ({"meetup", "leisure"}, "public facilities"),
    "temple":    ({"meetup", "leisure"}, "public facilities"),
    "religious": ({"meetup", "leisure"}, "public facilities"),

    # Education & health
    "school":       ({"school"}, "schools"),
    "college":      ({"school"}, "schools"),
    "university":   ({"university"}, "universities"),
    "kindergarten": ({"childcare"}, "kindergartens"),
    "hospital":     ({"errands"}, "hospitals"),

    # Public
    "public":         ({"errands"}, "public facilities"),
    "civic":          ({"errands"}, "public facilities"),
    "government":     ({"errands"}, "public facilities"),
    "community_centre": ({"meetup", "leisure"}, "public facilities"),
    "fire_station":   ({"work"}, "public facilities"),
    "train_station":  ({"errands"}, "transport"),
    "transportation": ({"errands"}, "transport"),
    "railway":        ({"work"}, "transport"),

    # Leisure & accommodation
    "hotel":        ({"leisure"}, "hotels"),
    "palace":       ({"leisure"}, "entertainment culture"),
    "stadium":      ({"sports", "leisure"}, "arenas large events"),
    "sports_hall":  ({"sports"}, "fitness wellness"),
    "sports_centre":({"sports"}, "fitness wellness"),
}

# ── LAYER 1e — information=* ─────────────────────────────────────────────
# 0 occurrences in this study area. Retained because
# config.ALLOWED_INFORMATION_TYPES lets the column survive upstream, so
# another region could populate it.
INFORMATION_RULES = {
    "office": ({"work", "business"}, "customer oriented services"),
}

# ── LAYER 1f — key:value tags recovered from `additional_information` ─────
# Genuine OSM tag vocabulary (office=*, craft=*, social_facility=*), not names.
# Low counts in this dataset but region-independent.
OFFICE_KV_RULES = {
    "government":            ({"errands"}, "public facilities"),
    "administrative":        ({"business"}, "normal office"),
    "association":           ({"business"}, "normal office"),
    "ngo":                   ({"business"}, "normal office"),
    "political_party":       ({"business"}, "normal office"),
    "diplomatic":            ({"business"}, "normal office"),
    "religion":              ({"meetup"}, "normal office"),
    "company":               ({"business"}, "normal office"),
    "telecommunication":     ({"business"}, "normal office"),
    "newspaper":             ({"business"}, "normal office"),
    "insurance":             ({"business"}, "business oriented services"),
    "lawyer":                ({"business"}, "business oriented services"),
    "notary":                ({"business"}, "business oriented services"),
    "accountant":            ({"business"}, "business oriented services"),
    "tax_advisor":           ({"business"}, "business oriented services"),
    "financial":             ({"business"}, "business oriented services"),
    "financial_advisor":     ({"business"}, "business oriented services"),
    "consulting":            ({"business"}, "business oriented services"),
    "estate_agent":          ({"business", "errands"}, "customer oriented services"),
    "employment_agency":     ({"errands"}, "customer oriented services"),
    "physician":             ({"errands"}, "customer oriented services"),
    "therapist":             ({"errands"}, "customer oriented services"),
    "it":                    ({"business"}, "open plan office"),
    "engineering":           ({"business"}, "open plan office"),
    "architect":             ({"business"}, "open plan office"),
    "coworking":             ({"business"}, "open plan office"),
    "research":              ({"work"}, "research institutes"),
    "educational_institution": ({"lessons"}, "schools"),
    "logistics":             ({"work"}, "yards depots storage areas construction yards"),
    "moving_company":        ({"work"}, "yards depots storage areas construction yards"),
    "energy_supplier":       ({"work"}, "industrial operations production"),
    "water_utility":         ({"work"}, "industrial operations production"),
}

CRAFT_KV_RULES = {
    "bakery":         ({"retail_daily"}, "craft businesses"),
    "butcher":        ({"retail_daily"}, "craft businesses"),
    "brewery":        ({"work"}, "craft businesses"),
    "winery":         ({"work"}, "craft businesses"),
    "distillery":     ({"work"}, "craft businesses"),
    "carpenter":      ({"work"}, "craft businesses"),
    "electrician":    ({"work"}, "craft businesses"),
    "plumber":        ({"work"}, "craft businesses"),
    "hvac":           ({"work"}, "craft businesses"),
    "metal_construction": ({"work"}, "craft businesses"),
    "painter":        ({"work"}, "craft businesses"),
    "pottery":        ({"work"}, "craft businesses"),
    "glaziery":       ({"work"}, "craft businesses"),
    "gardener":       ({"work"}, "craft businesses"),
    "roofer":         ({"work"}, "craft businesses"),
    "photographer":   ({"errands"}, "craft businesses"),
    "tailor":         ({"errands"}, "craft businesses"),
    "shoemaker":      ({"errands"}, "craft businesses"),
    "watchmaker":     ({"errands"}, "craft businesses"),
    "jeweller":       ({"errands"}, "craft businesses"),
}

SOCIAL_FACILITY_KV_RULES = {
    "shelter":         ({"errands"}, "nursing homes"),
    "group_home":      ({"errands"}, "nursing homes"),
    "nursing_home":    ({"errands"}, "nursing homes"),
    "assisted_living": ({"errands"}, "nursing homes"),
    "ambulatory_care": ({"errands"}, "hospitals"),
    "outreach":        ({"errands"}, "customer oriented services"),
    "food_bank":       ({"errands"}, "customer oriented services"),
    "day_care":        ({"childcare"}, "kindergartens"),
}


# ── LAYER 1 driver ───────────────────────────────────────────────────────

def _lookup_all(values, table):
    """Look up every value against `table`, returning only real hits.

    An entry of (set(), None) is NOT a hit: it means "explicitly no activity",
    so the building falls through to the next layer exactly as it would with
    no tag at all. That is what makes the explicit-null entries above safe to
    add for documentation purposes.
    """
    hits = []
    for v in values:
        key = str(v).strip().lower()
        if key in table:
            labels, cls = table[key]
            if labels or cls:
                hits.append((labels, cls))
    return hits


def classify_from_tags(row):
    hits = []
    hits += _lookup_all(as_list(row.get("amenity")), AMENITY_RULES)
    hits += _lookup_all(as_list(row.get("shop")), SHOP_RULES)
    hits += _lookup_all(as_list(row.get("tourism")), TOURISM_RULES)
    hits += _lookup_all(as_list(row.get("building")), BUILDING_TAG_RULES)
    hits += _lookup_all(as_list(row.get("information")), INFORMATION_RULES)

    extra = parse_additional_information(row.get("additional_information"))
    if "office" in extra:
        hits += _lookup_all([extra["office"]], OFFICE_KV_RULES)
    if "craft" in extra:
        hits += _lookup_all([extra["craft"]], CRAFT_KV_RULES)
    if "social_facility" in extra:
        hits += _lookup_all([extra["social_facility"]], SOCIAL_FACILITY_KV_RULES)

    if not hits:
        return None
    return reconcile_multi_poi(hits)


def reconcile_multi_poi(hits):
    """Combine several POI hits on one building (e.g. shop=[florist, clothes]).

    mid_labels are UNIONED — a building genuinely can host several activities.
    bosserhof_class must be a single value (the capacity formula in notebook 07
    takes one worker-density coefficient), so the highest-weight matched class
    wins: the most capacity-relevant tenant sets the building's rating. This is
    an explicit rule standing in for judgement the pipeline cannot make, and a
    known source of upward bias on mixed-tenant buildings.
    """
    mid_labels = set()
    best_class, best_weight = None, -1.0
    for labels, cls in hits:
        mid_labels |= {l for l in labels if l in TARGET_MID_LABELS}
        w = weight_of(cls)
        if cls and w > best_weight:
            best_class, best_weight = cls, w
    return mid_labels, best_class


# ══════════════════════════════════════════════════════════════════════════
# LAYER 2 — ALKIS building-function code
#
# One row per code. Keyed on `function` (e.g. "31001_2000"), never on the
# English label — see the module docstring. The German label and this study
# area's building count follow each row as a comment, so a reader can see both
# what the code means and how much it matters.
#
# All 71 codes present in this study area are listed. A code absent from this
# table returns None and the building falls through to layer 3.
# ══════════════════════════════════════════════════════════════════════════

ALKIS_RULES = {

    # ── Not a destination: dwellings, unstaffed infrastructure, structures ──
    # with no enclosed staffed volume. An explicit answer, so classification
    # halts here rather than falling through to OSM.
    "31001_1000": (set(), None),   # Wohngebäude                              243,502
    "31001_2500": (set(), None),   # Gebäude zur Versorgung                     4,545
    #   Versorgung = transformer kiosks, pump houses, valve chambers. Mostly
    #   unmanned, and config.LABELS_TO_REMOVE already drops the sibling code
    #   "Gebäude für die Energieversorgung" — this keeps the two consistent.
    "31001_1210": (set(), None),   # Land-/forstw. Wohngebäude (farmhouse)      3,798
    "31001_2461": (set(), None),   # Parkhaus                                      93
    "31001_3081": (set(), None),   # Trauerhalle                                   89
    "31001_2462": (set(), None),   # Parkdeck                                      85
    "31001_2513": (set(), None),   # Wasserbehälter                                70
    "31001_3281": (set(), None),   # Schutzhütte                                   66
    "51001_1005": (set(), None),   # Kühlturm                                      50
    "51001_1002": (set(), None),   # Kirchturm                                     45
    "31001_1223": (set(), None),   # Forsthaus (a dwelling)                        37
    "51006_1431": (set(), None),   # Zuschauertribüne, überdacht (open-air)        22
    "51007_1400": (set(), None),   # Befestigung (Burgruine) — a ruin              13
    "31001_2073": (set(), None),   # Hütte mit Übernachtung — like Schutzhütte     12
    "51009_1750": (set(), None),   # Denkmal                                       11
    "51006_1432": (set(), None),   # Zuschauertribüne, nicht überdacht             10
    "51001_1010": (set(), None),   # Förderturm                                     7
    "51001_1012": (set(), None),   # Palast-, Schlossturm                           5
    "51001_1009": (set(), None),   # Stadttorturm                                   5
    "51001_1004": (set(), None),   # Kontrollturm                                   4
    "51001_1007": (set(), None),   # Feuerwachturm                                  1

    # ── Generic commercial ──────────────────────────────────────────────────
    # 31001_2000 is the study area's single largest code and its least
    # informative. See the KNOWN CEILING note in the module docstring: it is
    # left as generic commercial on purpose so the ceiling is measurable.
    # Its Bosserhof class is refined by land use below — the only refinement
    # in the pipeline, and it uses an OSM tag, not volume.
    "31001_2000": ({"work", "business"}, "services"),  # Gebäude f. Wirtschaft/Gewerbe  244,607
    "31001_2010": ({"work", "business"}, "services"),  # Gebäude f. Handel u. Dienstl.    7,414
    "31001_1120": ({"work", "business"}, "services"),  # Wohnen + Handel/Dienstl.         5,338
    "31001_2310": ({"work", "business"}, "services"),  # Handel/Dienstl. + Wohnen           956
    #   No retail label on these. "Handel" does imply trade, but attaching
    #   retail_non_daily to 13,708 generic buildings swamped the 1,832
    #   buildings actually tagged as shops (84% of the column came from here).
    #   Both retail columns are now fed only by real shop tags.
    #   Mixed residential+commercial codes get the same answer as their pure
    #   counterpart: the building does host the business, and notebook 07
    #   normalises to zone totals, so only relative weight matters.

    "31001_2100": ({"work", "business"}, "industrial operations production"),  # Gewerbe u. Industrie  7,953
    "31001_1130": ({"work", "business"}, "industrial operations production"),  # Wohnen + Gewerbe/Ind.   611
    "31001_2320": ({"work", "business"}, "industrial operations production"),  # Gewerbe/Ind. + Wohnen   115

    # ── Public administration ───────────────────────────────────────────────
    # The generic code gets the same answer as its specific siblings.
    "31001_3000": ({"errands"}, "public facilities"),  # Gebäude f. öffentliche Zwecke  2,851
    "31001_3100": ({"errands"}, "public facilities"),  # öffentl. Zwecke + Wohnen         131
    "31001_3012": ({"errands"}, "public facilities"),  # Rathaus                           91
    "31001_3071": ({"errands"}, "public facilities"),  # Polizei                           83
    "31001_3015": ({"errands"}, "public facilities"),  # Gericht                           24
    "31001_3017": ({"errands"}, "public facilities"),  # Kreisverwaltung                   24
    "31001_3019": ({"errands"}, "public facilities"),  # Finanzamt                          5
    "31001_3011": ({"errands"}, "public facilities"),  # Parlament                          2
    # Staff only — no public counter.
    "31001_3072": ({"work"}, "public facilities"),     # Feuerwehr                        656
    "31001_3075": ({"work"}, "public facilities"),     # Justizvollzugsanstalt             23
    #   Inmates are residents, not visitors, so no errands claim.

    # ── Religious ───────────────────────────────────────────────────────────
    "31001_3041": ({"meetup", "leisure"}, "public facilities"),  # Kirche       691
    "31001_3043": ({"meetup", "leisure"}, "public facilities"),  # Kapelle      481
    "31001_3045": ({"meetup", "leisure"}, "public facilities"),  # Gotteshaus    55

    # ── Education & research ────────────────────────────────────────────────
    "31001_3021": ({"school"}, "schools"),                 # Allgemeinbild. Schule  782
    "31001_3022": ({"school"}, "schools"),                 # Berufsbildende Schule  163
    "31001_3023": ({"university"}, "universities"),        # Hochschulgebäude       204
    "31001_3024": ({"work"}, "research institutes"),       # Forschungsinstitut     133

    # ── Health & care ───────────────────────────────────────────────────────
    "31001_3051": ({"errands"}, "hospitals"),              # Krankenhaus            136
    "31001_1110": ({"errands"}, "nursing homes"),           # Wohngeb. m. Gemeinbedarf 107

    # ── Sport ───────────────────────────────────────────────────────────────
    "31001_3211": ({"sports"}, "fitness wellness"),        # Sporthalle             462
    "31001_3221": ({"sports"}, "fitness wellness"),        # Hallenbad               55
    "31001_3230": ({"sports"}, "fitness wellness"),        # Gebäude im Stadion      54
    #   3230 is ancillary stadium building; the arena itself is 51006_1440.

    # ── Large venues ────────────────────────────────────────────────────────
    "31001_3036": ({"leisure", "meetup"}, "arenas large events"),    # Veranstaltungsgebäude  83
    "31001_2060": ({"leisure", "business"}, "arenas large events"),  # Messehalle             16
    "51006_1440": ({"sports", "leisure"}, "arenas large events"),    # Stadion                13

    # ── Culture ─────────────────────────────────────────────────────────────
    "31001_3034": ({"leisure"}, "entertainment culture"),  # Museum                 159
    "31001_3031": ({"leisure"}, "entertainment culture"),  # Schloss (NOT "Lock")    10
    #   The shipped English label for 3031 is "Lock", a mistranslation of
    #   Schloss. It is a palace, normally operated as a museum or venue.
    "31001_3038": ({"leisure"}, "entertainment culture"),  # Burg, Festung             3
    "31001_2212": ({"leisure"}, "entertainment culture"),  # Wassermühle               5
    "31001_3032": ({"leisure"}, "musical theatres"),       # Theater, Oper            11
    "31001_3033": ({"leisure"}, "musical theatres"),       # Konzertgebäude            5

    # ── Recreation & accommodation ──────────────────────────────────────────
    "31001_3200": ({"leisure"}, "facilities for culture leisure and sports"),  # Erholungszwecke  1,332
    "31001_2072": ({"leisure"}, "hotels"),                 # Jugendherberge           15

    # ── Industry, agriculture, disposal ─────────────────────────────────────
    "31001_2600": ({"work"}, "yards depots storage areas construction yards"),  # Entsorgung  635
    "31001_2740": ({"work"}, "others industrial"),         # Gewächshaus             483
    "31001_2171": ({"work"}, "highly productive industries machine material or space intensive"),
    #                                                        Bergwerk                 28

    # ── Transport ───────────────────────────────────────────────────────────
    "31001_2130": ({"errands"}, "transport"),              # Tankstelle              322
    "31001_2131": ({"errands"}, "car dealerships"),        # Waschanlage              43
    "31001_3091": ({"errands"}, "transport"),              # Bahnhofsgebäude          12
    #   Passenger-facing, so travellers are counted. The four operations
    #   buildings below are staff-only technical facilities.
    "31001_2420": ({"work"}, "transport"),                 # Bahnbetriebsgebäude      90
    "31001_2430": ({"work"}, "transport"),                 # Flugbetriebsgebäude      38
    "31001_2450": ({"work"}, "transport"),                 # Seilbahnbetriebsgebäude  21
    "31001_2440": ({"work"}, "transport"),                 # Schifffahrtsbetriebsgeb. 20
}

# Land-use refinement, applied ONLY to the generic commercial code. Buildings
# under 31001_2000 that sit in industrial or retail land use have 2-3x the
# median volume of the rest, so the polygon carries real information the code
# does not. Checked in order; first match wins; no match keeps `services`.
GENERIC_COMMERCIAL_CODES = {"31001_2000"}
LANDUSE_BOSSERHOF_REFINEMENT = [
    ("industrial", "industrial operations production"),
    ("retail",     "retail"),
]


def refine_by_landuse(bosserhof_class, osm_landuse_class):
    """Replace a generic commercial Bosserhof class using the OSM land-use
    polygon the building sits in. Returns the class unchanged if nothing
    matches."""
    text = str(osm_landuse_class or "").lower()
    for key, cls in LANDUSE_BOSSERHOF_REFINEMENT:
        if key in text:
            return cls
    return bosserhof_class


def classify_from_alkis(row):
    code = row.get("function")
    if is_missing(code):
        return None
    code = str(code).strip()
    if code not in ALKIS_RULES:
        return None

    labels, cls = ALKIS_RULES[code]
    if cls and code in GENERIC_COMMERCIAL_CODES:
        cls = refine_by_landuse(cls, row.get("osm_landuse_class"))
    return set(labels), cls


# ══════════════════════════════════════════════════════════════════════════
# LAYER 3 — OSM-only buildings (no POI tag, no ALKIS code)
# ══════════════════════════════════════════════════════════════════════════

OSM_LANDUSE_FALLBACK = {
    "commercial": ({"work", "business"}, "services"),
    "industrial": ({"work"}, "industrial operations production"),
    "retail":     ({"retail_daily", "retail_non_daily"}, "retail"),
}


def classify_from_osm_fallback(row):
    hits = _lookup_all(as_list(row.get("osm_building_type")), BUILDING_TAG_RULES)
    if hits:
        return reconcile_multi_poi(hits)

    landuse = str(row.get("osm_landuse_class") or "").lower()
    for key, (labels, cls) in OSM_LANDUSE_FALLBACK.items():
        if key in landuse:
            return set(labels), cls
    return None


# ══════════════════════════════════════════════════════════════════════════
# Top-level entry point
# ══════════════════════════════════════════════════════════════════════════

def classify_building(row):
    """Classify one building row (a pandas Series or dict following the
    05_condensed_buildings_with_pois.gpkg schema). Returns
    {gml_id, interpreted_type, mid_labels, bosserhof_class, reason}."""
    result = classify_from_tags(row)
    source = "poi_tags"
    if result is None:
        result = classify_from_alkis(row)
        source = "alkis_code"
    if result is None:
        result = classify_from_osm_fallback(row)
        source = "osm_fallback"
    if result is None:
        result = (set(), None)
        source = "no_signal"

    mid_labels, bosserhof_class = result
    mid_labels = set(mid_labels)
    if bosserhof_class:
        # A Bosserhof class IS a worker-density rating (workers per 100 m³ —
        # see BOSSERHOF_WEIGHTS). Any building assigned one is by definition
        # staffed, whatever else happens there. The rule tables above encode
        # only the visitor-facing side of a POI (a restaurant's "leisure"),
        # so this adds the staff side back in once, centrally, instead of
        # hand-writing "work" into ~200 table rows where one omission would
        # be a silent undercount.
        mid_labels.add("work")
    mid_labels = sorted(l for l in mid_labels if l in TARGET_MID_LABELS)

    return {
        "gml_id": row.get("gml_id"),
        "interpreted_type": source,
        "mid_labels": mid_labels,
        "bosserhof_class": bosserhof_class,
        "reason": f"rule_source={source}",
    }


# ══════════════════════════════════════════════════════════════════════════
# Static self-check — runs at import.
#
# Every mid_label and bosserhof_class string used anywhere above must be one
# of the fixed valid values (TARGET_MID_LABELS / BOSSERHOF_WEIGHTS). Because
# this module is pure lookup, that can be a hard guarantee rather than a
# per-prediction check: any future typo fails LOUDLY at import instead of
# silently producing an unweighted building that notebook 07 drops.
# ══════════════════════════════════════════════════════════════════════════

_ALL_TAG_TABLES = {
    "AMENITY_RULES": AMENITY_RULES,
    "SHOP_RULES": SHOP_RULES,
    "TOURISM_RULES": TOURISM_RULES,
    "BUILDING_TAG_RULES": BUILDING_TAG_RULES,
    "INFORMATION_RULES": INFORMATION_RULES,
    "OFFICE_KV_RULES": OFFICE_KV_RULES,
    "CRAFT_KV_RULES": CRAFT_KV_RULES,
    "SOCIAL_FACILITY_KV_RULES": SOCIAL_FACILITY_KV_RULES,
    "ALKIS_RULES": ALKIS_RULES,
    "OSM_LANDUSE_FALLBACK": OSM_LANDUSE_FALLBACK,
}


def reachable_bosserhof_classes():
    """The set of Bosserhof classes any rule in this module can actually emit.

    Not the same as the 47 classes defined in config.BOSSERHOF_WEIGHTS: several are
    defined but unreachable, because no tag value or ALKIS code maps to them. That
    distinction matters when scoring — a building whose true class is unreachable is
    a guaranteed miss, which is a limitation of the rule vocabulary rather than a
    case of the rules picking the wrong class. Notebook 09 uses this to label those
    rows explicitly instead of letting them blend into ordinary errors.

    Returned lowercased, matching BOSSERHOF_WEIGHTS_LOWER.
    """
    reachable = set()
    for table in _ALL_TAG_TABLES.values():
        for _labels, cls in table.values():
            if cls:
                reachable.add(cls.lower())
    for _key, cls in LANDUSE_BOSSERHOF_REFINEMENT:
        reachable.add(cls.lower())
    return reachable


def validate_rule_tables():
    """Raise ValueError listing every invalid entry in the rule tables.
    Returns True if everything is valid."""
    errors = []

    def check(source, labels, cls):
        if cls is not None and cls.lower() not in BOSSERHOF_WEIGHTS_LOWER:
            errors.append(f"{source}: unknown bosserhof_class {cls!r}")
        for lab in labels:
            if lab not in TARGET_MID_LABELS:
                errors.append(f"{source}: unknown mid_label {lab!r}")

    for table_name, table in _ALL_TAG_TABLES.items():
        for key, (labels, cls) in table.items():
            check(f"{table_name}[{key!r}]", labels, cls)

    for key, cls in LANDUSE_BOSSERHOF_REFINEMENT:
        check(f"LANDUSE_BOSSERHOF_REFINEMENT[{key!r}]", set(), cls)

    # A row with labels but no class can never gain `work`, and a row with a
    # class but no labels is fine (work is added). Catch the former: it would
    # mean a building with activities that the capacity formula cannot rate.
    for table_name, table in _ALL_TAG_TABLES.items():
        for key, (labels, cls) in table.items():
            if labels and not cls:
                errors.append(f"{table_name}[{key!r}]: has mid_labels but no bosserhof_class")

    if errors:
        raise ValueError(
            f"rule_utils: {len(errors)} invalid rule table entries:\n" + "\n".join(errors)
        )
    return True


validate_rule_tables()
