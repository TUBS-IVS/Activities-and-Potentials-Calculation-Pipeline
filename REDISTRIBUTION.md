# Step 08: from zone totals to buildings

Step 08 ([`pipeline/08_redistribution.ipynb`](pipeline/08_redistribution.ipynb)) turns the classified buildings of
steps 06 and 07 into activity potentials per building and per POI unit. It treats two kinds of activity
differently:

| | Activities | Source of the amount | Result |
|---|---|---|---|
| **Constrained** | Workers, School, University, Kindergarten, Retail_Daily, Retail_Non-Daily, Leisure | the zone totals of the region's travel demand model (`zone_targets.gpkg`) | `assigned_<category>` |
| **Estimated** | `business`, `errands`, `sports`, `meetup`, `lessons` | floor area × visitor rate | `value_<label>` |

Each of the seven constrained categories is fed by exactly one activity label (`work`, `school`, `university`,
`childcare`, `retail_daily`, `retail_non_daily`, `leisure`; `config.MID_LABEL_TO_ACTIVITY`). Labels are never merged:
`errands` does not feed Retail_Daily, and `sports`, `meetup` and `lessons` do not feed Leisure. A grouping of labels
into fewer categories, as used for scoring in the paper's validation, is not part of the pipeline.

Step 08 always reads `zone_targets.gpkg`. There is no rate-based route for the seven constrained categories, so the
pipeline does not run on open data alone. All settings named below are in [`config.py`](config.py), each with its
reasoning.

## 1. Occupied floor area

- **Storeys.** Storeys = max(1, round(h / 3.5 m)) (`FLOOR_STOREY_HEIGHT_M`), with h the LoD2 eaves height, capped at
  the mean height (volume / footprint), or the mean height where there is no eaves height (`lib/floor_rules.py`).
  Halls count as one storey (`HALL_BOSSERHOF_CLASSES`, `HALL_TYPE_PATTERN`). An OSM `building:levels` tag on the
  building's own footprint takes precedence over both; parking structures keep one storey. Levels from OSM outlines
  lying over an ALKIS building replace a storey count that comes from the height alone, where the outlines cover at
  least half of the building and imply a plausible storey height (`FLOOR_OSM_ALKIS_LEVELS`). Further storey rules
  cover culture buildings, department stores and shopping centres, buildings filled in from OSM, and buildings where
  only the height suggests more than one storey (`lib/gap_storeys.py`, `lib/storey_evidence.py`).
- **Floor area** = footprint × storeys. The **occupied floor area** O is the part of it the building's uses take, by
  rules per class and POI family (`lib/floor_rules.py`): for example, a shop under flats takes the ground floor, and
  free floors with dwellings carry nothing. Free floors without dwellings form a remainder unit that carries Workers
  only: at the normal-office factor (`REDIST_REMAINDER_WORKERS_FACTOR`) in shop and office buildings
  (`REDIST_REMAINDER_OFFICE_CLASSES`), and at the building's own factor in any other building.
- **Units.** A building without POIs of its own that step 07 classified is one unit. In a building shared by several
  POIs, each POI is a unit. Its starting share of the building comes from step 04 (`share_in_building`): the POI's
  split area × its split height, over the sum for all POIs on the building. The split area is a polygon POI's own
  area; a point POI takes the median area of the polygon POIs on the same building, and where the building has none,
  every POI counts `POI_SPLIT_AREA_FALLBACK_M2`, an even split of the area. A unit inside a mall or another POI takes
  the area step 01 gave it by the same rule among the units of its parent. The split height is the OSM `height`,
  else `building:levels` × 3.0 m (`POI_SPLIT_STOREY_HEIGHT_M`), else the building's mean height, so a tall tower on a
  low base takes more than its footprint. Step 08 then sizes the units: a point POI counts at least the median
  polygon of its POI group (`UNIT_SIZE_RULES`) and, unless it is an anchor (`POI_ANCHOR_GROUPS`), at most its
  group's cap, mostly the 90th percentile of the group's mapped polygons (`POINT_SIZE_CAP_M2`), with further rules
  for mall tenants, pharmacies, chains and formats (`UNIT_SIZE_RULES`, `UNIT_SIZE_FORMATS`, `lib/unit_sizes.py`). A
  label of the building that none of its POIs carries stays on a rest unit on the floor the POIs leave free.
- **Corrections from OSM evidence** remove or relabel units: vacant places (`REDIST_EXCLUDE_VACANT`,
  `VACANCY_OSM_SIGNS`), labels of steps 06 and 07 reconciled by the OSM use (`LABEL_RULES`), staff canteens and staff
  shops (`STAFF_CATERING_RULES`), and which buildings carry School, University and Kindergarten
  (`lib/edu_carriers.py`).

## 2. The seven categories with a zone total

Each zone total is shared over the eligible units in the zone in proportion to a weight:

| Category | Weight of a unit |
|---|---|
| Workers | O × f |
| School, University, Kindergarten, Retail_Daily, Retail_Non-Daily, Leisure | ε × O / k |

- O is the unit's occupied floor area.
- f is the worker density of its building-use class after Bosserhoff (workers per 100 m² of floor area, the
  midpoint of each class's range, three rates corrected against their sources; `BOSSERHOF_WEIGHTS`). It acts as a
  relative weight: the zone total sets the number.
- k is the number of the unit's labels among the six non-work categories (`REDIST_MULTI_CATEGORY_SPLIT = "even"`).
- ε = 0.25 (`REDIST_NO_POI_WEIGHT`) for units without a POI of their own, a name or a site (other than a land-use
  area) in Retail_Daily, Retail_Non-Daily and Leisure (`REDIST_NO_POI_CATEGORIES`); otherwise ε = 1.

School is shared by school type (primary, secondary, vocational; `SCHOOL_TYPE_COLUMNS`), each type's total over the
schools of that type.

A unit's value is weight / Σ weights of the zone × zone total, and a building's value is the sum of its units. The
regional totals are kept exactly: in the run behind the paper the buildings add up to the regional total of each of the seven
categories, with nothing unassigned. A zone's placed sum can differ from its own total where the rules below move
amounts between zones (ring fallback, sharing of zero and near-zero totals, Workers caps and the raise of named
institutions); the `zones` layer of the output holds both.

### General rules

These rules are written for any region with zone totals:

- **Ring fallback.** A zone with a total but no eligible unit passes it to the zones that touch it, ring by ring,
  until carriers are found (`REDIST_FALLBACK_MAX_RINGS`).
- **Zones with a total of zero.** Units in zones whose Workers, School, University or Kindergarten total is zero (or,
  for Workers, near zero) join the sharing of neighbouring zones that have a total: for Workers the nearest ring
  with a total, for the other three the touching zones, or up to three rings away where nothing next door holds a
  total (`REDIST_SHARE_ZERO_TARGET_CATEGORIES`, `REDIST_SHARE_NEAR_ZERO_TARGET`).
- **Workers headcount caps.** Each unit has a realistic headcount for its kind and size (from published sizes of
  such establishments) and an upper limit derived from it: twice the realistic headcount for establishments such as
  shops, schools or hotels, three times the Bosserhoff value for open-ended employers such as offices, five times for
  industry, logistics and transport. What a zone's units cannot hold moves to units in neighbouring zones that hold
  less than their realistic headcount, up to three rings away (`WORKERS_HEADCOUNT`, `lib/workers_headcount.py`).

### Region calibration

Some settings hold published facts of the Braunschweig region and do not transfer to another region: the published
staff numbers of large institutions (`WORKERS_INSTITUTIONS`, to which their Workers are raised), the retail floor
areas of shopping centres (`MALL_RETAIL_FLOOR`), and lists of specific buildings and places checked by hand, such
as closed places (`CLOSED_BUILDINGS`), class fixes (`CLASS_FIX_BUILDINGS`) and the storeys of the Volkswagen plant
halls (`FLOOR_OSM_HALL_LEVELS`). In this repository they are part of the configuration and always applied (the
paper's Fig. 1 shows the calibration as an optional step of the method); for another region they have to be
replaced with local reference information or removed.

## 3. The five activities without a zone total

`business`, `errands`, `sports`, `meetup` and `lessons` (`REDIST_AREA_LABELS`) have no zone total. They are
estimated, not constrained:

value = (O / k_all) × r / 100

- O / k_all is the label's floor area: the unit's occupied floor area split evenly over all its non-work labels.
- r is a visitor rate: visitor arrivals (all modes, staff excluded) per 100 m² of occupied floor area per average
  working day (Monday to Friday). It is chosen by building-use class, POI type or group (`lib/visitor_rates.py`,
  `VISITOR_RATE_ANCHORS`); pharmacies and post offices take a value per outlet instead (`VISITOR_PER_OUTLET`).
- Each rate has a low, middle and high value; the run uses the middle one (`VISITOR_RATE_SCENARIO = "mid"`), the
  others are kept for sensitivity runs.
- The rates are drawn partly from Bosserhoff (Ver_Bau) and partly from other sources: FGSV, ITE, TRICS and further
  published studies and statistics named next to each rate in `config.py`. The rates for business and generic
  errands are the worker density of the building-use class (`BOSSERHOF_WEIGHTS`) × visitors per employee.
- Some rates are assumed where no source was found; they are flagged in `config.py`, and the output column
  `value_assumed` names the labels whose value rests on such a rate.

These values are estimates of visitor numbers. They are not scaled to any total and are not comparable in kind with
the seven constrained categories.

## 4. Output

`data/output/08_redistribution.gpkg`, three layers:

- **`buildings`** (39,786): building id, zone, name, ALKIS function label, building-use class, labels, storeys,
  floor area and occupied floor area, `assigned_<category>` for the seven categories, `value_<label>` for the five
  labels, `value_assumed`.
- **`pois`** (7,864): the POI units of shared buildings with the same value columns.
- **`zones`** (880): each zone's total (`target_<category>`) and the sum placed on its buildings
  (`assigned_<category>`).

Column names write `_` for the `-` of Retail_Non-Daily: `assigned_Retail_Non_Daily`, `target_Retail_Non_Daily`.

## 5. Without the zone data

Step 08 cannot run without `zone_targets.gpkg`; it stops at its input check and writes nothing. Which quantities
depend on the zone data:

| Quantity | Depends on |
|---|---|
| `assigned_<category>`, the `zones` layer | the zone totals |
| storeys, `floor_area_m2` | no zone data, except the storeys of the Volkswagen plant halls (`FLOOR_OSM_HALL_LEVELS` names their zone) |
| `occupied_m2`, the unit split | mostly no zone data; a guard that keeps the last carrier of a zone total restores some labels and their floor |
| `value_<label>`, `value_assumed` | floor area × visitor rate, no zone totals; but a building outside every zone gets no value, a venue's meetup value is net of its assigned Leisure, and the guard above changes some splits |
| the worker estimate O × f / 100 inside the headcount rule | no zone data; it is an intermediate, not an output |

The floor-area and visitor-rate parts of the method therefore need no zone totals in principle, but in this version
they are computed only inside step 08, together with the allocation. An open-data estimate of potentials would need
changes to the code, and its values would differ from the zone-constrained results described here.

## Volume

The method weights by floor area, not by building volume; volume is never a weight of the allocation. Step 03
computes it from the LoD2 surfaces, and step 04 estimates it for OSM footprints from their height tags. It is used
in two ways:

- **Mean height** = volume / footprint. In step 08 it caps the eaves height from which the storeys are counted,
  stands in where there is no eaves height (`lib/floor_rules.py`, `lib/storey_evidence.py`) and marks the OSM
  footprints that carry only step 04's placeholder height (`lib/gap_storeys.py`); in step 04 it is the last rung of
  the split height of `share_in_building` (section 1, Units).
- **`share_of_site`** (step 04): a building's volume over the total volume of the buildings on a site polygon such
  as a campus (an even split where none of them has a volume). It only orders the sites in the LLM's record
  (`lib/llm_record.py`) and in the lists the rule classifier reads (`rules/classify_buildings.ipynb`); step 08 does
  not use it.

Some step-03 and step-04 statistics are reported in m³; they are not weights.
