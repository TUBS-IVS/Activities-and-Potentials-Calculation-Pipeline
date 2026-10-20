# Rule-based classifier

An alternative to the LLM classification of steps 05–06: a deterministic rule engine that gives every building of
step 04 a set of MiD activity labels and one Bosserhof class, from structured tags alone — no language model, no API
call, no business-name matching. [`rule_utils.py`](rule_utils.py) is the whole classifier: no model weights, no
inference. **Every answer comes from an explicit lookup table: one row per tag value, and the row *is* the rule.**

The folder is self-contained: its own [`config.py`](config.py) (label vocabulary, worker densities, paths), tests and
reference codelist. It reads the outputs of pipeline steps 01 and 04 and never imports the pipeline's root `config.py`.

## Running it

```bash
# after pipeline steps 01–04 have written data/output/
jupyter lab rules/classify_buildings.ipynb       # → data/output/rules_classification.parquet (seconds)

pytest rules/tests                              # 167 tests, no data needed
python rules/rule_smoke_test.py --amenity restaurant
```

`rules_classification.parquet` has one row per building: `building_id`; `cls_sites`, `labels_sites`, `layer_sites`
(Bosserhof class, `;`-separated MiD labels, the deciding layer — the main result); and `cls_own`, `labels_own`,
`layer_own`, the same with only the POIs on the building, without the site polygons it lies in (a sensitivity check).
To read step 04's outputs from another folder, set `RULES_INPUT_DIR`.

- [Input: one row per building](#input-one-row-per-building)
- [Output](#output)
- [Three layers, strict precedence](#three-layers-strict-precedence)
- [Design decisions](#design-decisions)
- [Activity labels](#activity-labels)
- [Bosserhof classes](#bosserhof-classes)
- [Where the rules live](#where-the-rules-live)
- [Checking what the rules predict](#checking-what-the-rules-predict)
- [Tests](#tests)

---

## Input: one row per building

`classify_building(row)` takes a dict (or pandas Series) with these fields. Any field may be missing or `None`.

| Field | Type | Meaning |
|---|---|---|
| `gml_id` | any | building id, passed through to the output |
| `amenity`, `shop`, `tourism`, `building`, `information` | list of str | the OSM tag values of the POIs on the building, main occupant first |
| `additional_information` | list of str | further POI tags as `"key: value"` pairs separated by `; `, read for `office`, `craft` and `social_facility` |
| `function` | str | the ALKIS building-function code, e.g. `31001_2000` |
| `osm_building_type` | str | the OSM `building=*` tag of the footprint |
| `osm_landuse_class` | str | the OSM land use of the parcel, e.g. `industrial`, `retail` |

POI values are lists, not `;`-joined strings, and a missing value is `None`, never `NaN` or the text `"nan"`.
[`notebooks/classify_buildings.ipynb`](classify_buildings.ipynb) shows how such rows are built from the
preprocessed buildings and POIs, and checks every row before classifying it.

## Output

```python
{"gml_id": ..., "mid_labels": ["childcare", "work"], "bosserhof_class": "kindergartens",
 "interpreted_type": "poi_tags", "reason": "rule_source=poi_tags"}
```

`mid_labels` is a sorted list of [MiD activity labels](#activity-labels) (empty: no activity), `bosserhof_class` one of
the [Bosserhof classes](#bosserhof-classes) or `None`, and `interpreted_type` the layer that decided.

---

## Three layers, strict precedence

The table format is the same everywhere:

```python
"tag_value": ({mid_labels}, "bosserhof_class")
```

`classify_building(row)` tries three layers in order and stops at the first that answers:

| Layer | Reads | Tables | Decides (Braunschweig run) |
|---|---|---|---|
| **1 · POI tags** | `amenity`, `shop`, `tourism`, `building`, `information`, `leisure`, `healthcare`, `club`, `sport`, and `office` / `craft` / `social_facility` from `additional_information`; the number of the building's own shops | `AMENITY_RULES` (111), `SHOP_RULES` (125), `TOURISM_RULES` (13), `BUILDING_TAG_RULES` (85), `LEISURE_RULES` (46), `HEALTHCARE_RULES` (7), `CLUB_RULES` (5), `SPORT_RULES` (7), + 3 key:value tables (64 / 26 / 15), and a default row for 7 keys | 18,706 · 47.0 % |
| **2 · ALKIS code** | `function` | `ALKIS_RULES` — 71 codes (21 marked "no activity", 50 active) | 20,100 · 50.5 % |
| **3 · OSM fallback** | `osm_building_type`, then `osm_landuse_class` | `BUILDING_TAG_RULES`, `OSM_LANDUSE_FALLBACK` (3) | 855 · 2.1 % |
| — *no usable signal* | | | 125 · 0.3 % |

*Measured on the 39,786 buildings of the Braunschweig preprocessing (main run: own POIs and site polygons). 38,299 of
them (96.3 %) receive a Bosserhof class; the rest carry an ALKIS code that denotes no activity (garages, sheds, homes)
or no signal at all.*

## Design decisions

- **Labels are the purposes a place clearly serves.** The labels follow the definitions the LLM classifier of steps
  05–06 receives. A place gets the labels whose core idea a main purpose of a place of that kind meets; a purpose it
  only may serve is left out: a company office's occasional business visitor, a church's leisure. So `business` (a
  visitor's professional matter) is claimed only where professionals come as visitors — conference and exhibition
  centres, trade fairs, wholesale — never from an ALKIS code, a footprint type or a plain office, whose staff are
  `work`. Offices that private clients visit to settle a matter (insurance, lawyer, tax adviser, job centre) are
  `errands`; care homes are visited (`meetup`).
- **Classes follow the class meanings.** *Public facilities* is a building for education, research, health or care:
  administrations are *Services* (a town hall with its counter *customer-oriented services*, an authority *normal
  office*), places of worship, community and club houses *entertainment, culture*, fire stations *yards, depots*.
  A building with ten or more shops of its own is a *shopping centre* (the class meaning: "on the order of ten or
  more" separate shops).
- **A default row per key, where a key's values share one meaning.** Any `shop=*` sells goods, any `office=*` is
  office work, any `craft=*` is a craft business, any `sport=*` is a place of sport. For these seven keys (shop,
  office, craft, social_facility, healthcare, club, sport) an unlisted value takes the key's default row; listed
  rows, including explicit "no activity" rows, come first. `amenity`, `tourism`, `building` and `leisure` have no
  default: their values are too diverse. The rows were written from every value that occurs on a placed POI in the
  Braunschweig region.
- **Strict precedence.** An answer from any layer — *including an explicit "no activity"* — ends classification.
  Unioning layers instead was rejected: `services` (2.31) would attach to nearly every POI building and, under the
  highest-weight rule, silently override real classes just below it, turning every `kindergartens` (2.30) into
  `services`.
- **Keyed on the ALKIS code, never the English label.** `31001_3031` is *Schloss* (a palace) but ships with the label
  "Lock", and 15 of 301 codes share a label with another code. No rule reads translated text.
- **`work` is added centrally, not per row.** A Bosserhof class *is* a worker-density rating, so anything carrying one
  is by definition staffed. The tables describe only the visitor-facing purpose; `classify_building` adds `work` once.
- **Multi-tenant buildings.** Labels are unioned across all POIs on the building. The Bosserhof class must be single
  (a capacity formula takes one coefficient), so the highest worker-weight match wins — an explicit rule standing in
  for judgement the pipeline cannot make, and a known source of upward bias.
- **No names.** No rule reads a business name. Recognising that "Bahlsen" is a food manufacturer requires world
  knowledge a tag rule cannot encode without becoming a name lookup table for one region — the opposite of a
  transferable classifier. Buildings identifiable only by name are the classifier's main blind spot.
- **One row per ALKIS code.** Regexes matched over the label text in order, first match wins, do not compose —
  `greenhouse|agricultural` would capture ≈3,800 farm *dwellings*, `church|chapel` a church *tower*. One explicit row
  per code removes the failure mode: there is no ordering to get wrong.

Every table is statically validated at import (`validate_rule_tables()`): an invalid Bosserhof class or MiD label
anywhere fails immediately.

---

## Activity labels

Each building gets zero or more of **12 MiD activity labels**, which collapse to **7 activity groups**
(`MID_LABEL_TO_ACTIVITY` in [`config.py`](config.py)):

| MiD labels | Group | Examples |
|---|---|---|
| `work`, `business` | **Workers** | offices, workplaces, industry |
| `retail_daily`, `errands` | **Retail_Daily** | supermarkets, bakeries, pharmacies, banks, doctors |
| `retail_non_daily` | **Retail_Non-Daily** | clothing, furniture, electronics |
| `leisure`, `sports`, `meetup`, `lessons` | **Leisure** | restaurants, cinemas, gyms, churches, driving schools |
| `school` | **School** | primary, secondary, vocational |
| `university` | **University** | higher education |
| `childcare` | **Kindergarten** | kindergartens, daycare |

A distinction *within* a group is descriptive only — whether a gym is `sports` or `leisure` changes nothing for a
group-level use. A distinction *across* groups does: whether a restaurant is `leisure` or `errands`. Both retail groups
are fed only by real shop tags; generic ALKIS "trade and services" codes deliberately claim no retail.

## Bosserhof classes

Each building gets at most one **Bosserhof class** (e.g. `normal office`, `discount stores`, `schools`), which carries
a worker density in workers per 100 m³ of building volume (`BOSSERHOF_WEIGHTS` in [`config.py`](config.py), 47
classes). Six of them no rule emits: `craft courtyards`, `crafts and trades`, `factory outlet centers`,
`retail wholesale`, `self service department stores`, `suppliers for car dealerships`
(`reachable_bosserhof_classes()` lists the rest).

---

## Where the rules live

| To change… | Edit |
|---|---|
| what an OSM POI tag means | `AMENITY_RULES` / `SHOP_RULES` / `TOURISM_RULES` / `BUILDING_TAG_RULES` / `LEISURE_RULES` / `HEALTHCARE_RULES` / `CLUB_RULES` / `SPORT_RULES` and the `*_KV_RULES` in `rule_utils.py` |
| what an unlisted value of a key means | the key's `*_DEFAULT` row in `rule_utils.py` |
| how many shops make a shopping centre | `SHOPPING_CENTRE_MIN_SHOPS` in `rule_utils.py` |
| what an ALKIS code means | `ALKIS_RULES` in `rule_utils.py` — one row per code, with its German label as a comment |
| the land-use refinement of the generic commercial code | `LANDUSE_BOSSERHOF_REFINEMENT` in `rule_utils.py` |
| the label vocabulary, the worker densities | `TARGET_MID_LABELS`, `BOSSERHOF_WEIGHTS` in `config.py` |

For another German state the ALKIS codes are the same; outside Germany, replace `ALKIS_RULES` with a table for your
cadastre's codes. Codes absent from the table fall through to the OSM layer rather than being guessed.

## Checking what the rules predict

Without any data:

```bash
python rules/rule_smoke_test.py --amenity restaurant
python rules/rule_smoke_test.py --function 31001_2000 --osm_landuse_class industrial
python rules/rule_smoke_test.py --alkis              # the whole ALKIS table, with German labels
python rules/rule_smoke_test.py --alkis 31001_3031   # one code
python rules/rule_smoke_test.py                      # interactive: type field=value lines
```

## Tests

`pytest rules/tests` runs 167 tests in under a second. [`tests/test_rule_utils.py`](tests/test_rule_utils.py) checks
`classify_building()` on real sampled input rows, statically checks every rule table, and pins each deliberate
decision: the ALKIS code table (exclusions, the *Schloss*/"Lock" mistranslation), the land-use refinement, the `work`
invariant, layer precedence including the `kindergartens` vs `services` case, `;`-composite tag splitting, farm-building
exclusions, multi-POI reconciliation, where `business` may and may not be claimed, the new keys, the key defaults and
the shopping-centre count.
