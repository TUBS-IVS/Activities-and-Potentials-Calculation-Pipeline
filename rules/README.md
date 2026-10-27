# Rule-based classifier

An alternative to the LLM classification of steps 05–06: a deterministic rule engine that gives every building of
step 04 a set of MiD activity labels and one Bosserhoff class, from structured tags alone — no language model, no API
call, no business-name matching. [`rule_utils.py`](rule_utils.py) is the whole classifier: no model weights, no
inference. **Every answer comes from an explicit lookup table: one row per tag value, and the row *is* the rule.**

The folder is self-contained: its own [`config.py`](config.py) (label vocabulary, worker densities, paths), tests and
reference codelist. It reads the outputs of pipeline steps 01 and 04 and never imports the pipeline's root `config.py`.

## Running it

```bash
# after pipeline steps 01–04 have written data/output/
jupyter lab rules/classify_buildings.ipynb       # → data/output/rules_classification.parquet (under a minute)

pytest rules/tests                              # 167 tests, no pipeline data needed (see Tests)
python rules/rule_smoke_test.py --amenity restaurant
```

`rules_classification.parquet` has one row per building: `building_id`; `cls_sites`, `labels_sites`, `layer_sites`
(Bosserhoff class, `;`-separated MiD labels, the deciding layer — the main result); and `cls_own`, `labels_own`,
`layer_own`, the same with only the POIs on the building, without the site polygons it lies in (a sensitivity check).
To read the outputs of steps 01 and 04 from another folder, set `RULES_INPUT_DIR`.

- [Input: one row per building](#input-one-row-per-building)
- [Output](#output)
- [Three layers, strict precedence](#three-layers-strict-precedence)
- [Design decisions](#design-decisions)
- [Activity labels](#activity-labels)
- [Bosserhoff classes](#bosserhoff-classes)
- [Where the rules live](#where-the-rules-live)
- [Checking what the rules predict](#checking-what-the-rules-predict)
- [Tests](#tests)

---

## Input: one row per building

`classify_building(row)` takes a dict (or pandas Series) with these fields. Any field may be missing or `None`.

| Field | Type | Meaning |
|---|---|---|
| `gml_id` | any | building id, passed through to the output |
| `amenity`, `shop`, `tourism`, `building`, `information`, `leisure`, `healthcare`, `club`, `sport` | list of str | the OSM tag values of the POIs on the building, main occupant first |
| `additional_information` | list of str | further POI tags as `"key: value"` pairs (several in one string are separated by `; `), read for `office`, `craft` and `social_facility`; where a key occurs more than once, the last value counts |
| `shop_count` | int | the number of the building's own POIs with a `shop` value (the shopping-centre rule) |
| `function` | str | the ALKIS building-function code, e.g. `31001_2000` |
| `osm_building_type` | str | the OSM `building=*` tag of the footprint |
| `osm_landuse_class` | str | the OSM land use of the parcel, e.g. `industrial`, `retail` |

POI values are lists, not `;`-joined strings, and a missing value is `None`, never `NaN` or the text `"nan"`.
[`classify_buildings.ipynb`](classify_buildings.ipynb) shows how such rows are built from the
preprocessed buildings and POIs, and checks every row before classifying it.

## Output

```python
{"gml_id": ..., "mid_labels": ["childcare", "work"], "bosserhof_class": "kindergartens",
 "interpreted_type": "poi_tags", "reason": "rule_source=poi_tags"}
```

`mid_labels` is a sorted list of [MiD activity labels](#activity-labels) (empty: no activity), `bosserhof_class` one of
the [Bosserhoff classes](#bosserhoff-classes) or `None`, and `interpreted_type` the layer that decided.

---

## Three layers, strict precedence

The table format is the same everywhere:

```python
"tag_value": ({mid_labels}, "bosserhof_class")
```

`classify_building(row)` tries three layers in order and stops at the first that answers:

| Layer | Reads | Tables | Decides (Braunschweig run) |
|---|---|---|---|
| **1 · POI tags** | `amenity`, `shop`, `tourism`, `building`, `information`, `leisure`, `healthcare`, `club`, `sport`, and `office` / `craft` / `social_facility` from `additional_information`; the number of the building's own shops | `AMENITY_RULES` (111), `SHOP_RULES` (125), `TOURISM_RULES` (13), `BUILDING_TAG_RULES` (85), `INFORMATION_RULES` (1), `LEISURE_RULES` (46), `HEALTHCARE_RULES` (7), `CLUB_RULES` (5), `SPORT_RULES` (7), + 3 key:value tables (64 / 26 / 15), and a default row for 7 keys | 18,706 · 47.0 % |
| **2 · ALKIS code** | `function` | `ALKIS_RULES` — 71 codes (21 marked "no activity", 50 active) | 20,100 · 50.5 % |
| **3 · OSM fallback** | `osm_building_type`, then `osm_landuse_class` | `BUILDING_TAG_RULES`, `OSM_LANDUSE_FALLBACK` (3) | 855 · 2.1 % |
| — *no usable signal* | | | 125 · 0.3 % |

*Measured on the 39,786 buildings of the Braunschweig preprocessing (main run: own POIs and site polygons). 38,299 of
them (96.3 %) receive a Bosserhoff class; the rest carry an ALKIS code that denotes no activity (garages, sheds, homes)
or no signal at all.*

## Design decisions

- **Labels are the purposes a place clearly serves.** The labels follow the definitions the LLM classifier of steps
  05–06 receives. A place gets the labels whose core idea a main purpose of a place of that kind meets; a purpose it
  only may serve is left out: a company office's occasional business visitor, a church's leisure. So `business` (a
  visitor's professional matter) is claimed only where professionals come as visitors — conference and exhibition
  centres, exhibition halls (ALKIS `31001_2060`), wholesale — never from a generic ALKIS code, a footprint type or a
  plain office, whose staff are `work`. Offices that private clients visit to settle a matter (insurance, lawyer, tax
  adviser, job centre) are `errands`; care homes are visited (`meetup`).
- **Classes follow the class meanings.** *Public facilities* is a building for education, research, health or care:
  administrations are *Services* (a town hall with its counter *customer-oriented services*, an authority *normal
  office*), places of worship, community and club houses *entertainment, culture*, fire stations *yards, depots*.
  A building with ten or more shops of its own is a *shopping centre* (the class meaning: "on the order of ten or
  more" separate shops).
- **A default row per key, where a key's values share one meaning.** Any `shop=*` sells goods, any `office=*` is
  office work, any `craft=*` is a craft business, any `sport=*` is a place of sport. For these seven keys (shop,
  office, craft, social_facility, healthcare, club, sport) an unlisted value takes the key's default row; listed
  rows, including explicit "no activity" rows, come first. `amenity`, `tourism`, `building`, `information` and
  `leisure` have no default: their values are too diverse. The rows were written from every value that occurs on a
  placed POI in the Braunschweig region.
- **Strict precedence.** An answer from a layer ends classification. An ALKIS row marked "no activity" is such an
  answer; a POI-tag row marked "no activity" (`(set(), None)`) is not, and the building falls through to the next
  layer as if it had no tag.
  Unioning layers instead was rejected: `services` (2.31) would attach to nearly every POI building and, under the
  highest-weight rule, silently override real classes just below it, turning every `kindergartens` (2.30) into
  `services`.
- **Keyed on the ALKIS code, never the English label.** `31001_3031` is *Schloss* (a palace) but carries the label
  "Lock" in this folder's codelist copy
  ([`reference/building_function_codelist.csv`](reference/building_function_codelist.csv)); the pipeline's table
  (`data/reference/building_function_codelist_de_en.csv`) says "Castle". In both, 15 of 301 codes share an English
  label with another code. No rule reads translated text.
- **`work` is added centrally, not per row.** A Bosserhoff class *is* a worker-density rating, so anything carrying one
  is by definition staffed. The tables describe only the visitor-facing purpose; `classify_building` adds `work` once.
- **Multi-tenant buildings.** Labels are unioned across all POIs on the building. The Bosserhoff class must be single
  (a capacity formula takes one coefficient), so the highest worker-weight match wins — an explicit rule standing in
  for judgement the pipeline cannot make, and a known source of upward bias.
- **No names.** No rule reads a business name. Recognising that "Bahlsen" is a food manufacturer requires world
  knowledge a tag rule cannot encode without becoming a name lookup table for one region — the opposite of a
  transferable classifier. Buildings identifiable only by name are the classifier's main blind spot.
- **One row per ALKIS code.** Regexes matched over the label text in order, first match wins, do not compose —
  `greenhouse|agricultural` would capture ≈3,800 farm *dwellings*, `church|chapel` a church *tower*. One explicit row
  per code removes the failure mode: there is no ordering to get wrong.

Every table is statically validated at import (`validate_rule_tables()`): an invalid Bosserhoff class or MiD label
anywhere fails immediately.

---

## Activity labels

Each building gets zero or more of the **12 MiD activity labels** (`TARGET_MID_LABELS` in [`config.py`](config.py)),
the labels the LLM classifier of steps 05–06 assigns:

| MiD label | Examples of what the rules give it |
|---|---|
| `work` | every building with a Bosserhoff class (added centrally) |
| `business` | conference and exhibition centres, exhibition halls, wholesale |
| `retail_daily` | supermarkets, bakeries, chemists, pharmacies |
| `retail_non_daily` | clothing, furniture, electronics; any unlisted `shop=*` value |
| `errands` | banks, doctors, dentists, post offices, town halls |
| `leisure` | restaurants, cafés, cinemas, theatres, libraries |
| `sports` | fitness and sports centres |
| `meetup` | places of worship, community centres, nursing homes |
| `lessons` | driving, music and language schools |
| `school` | schools, colleges |
| `university` | universities |
| `childcare` | kindergartens |

Every label counts on its own, as in the pipeline: step 08 feeds each of its seven zone categories from exactly one
label (`work`, `school`, `university`, `childcare`, `retail_daily`, `retail_non_daily`, `leisure`) and estimates
`business`, `errands`, `sports`, `meetup` and `lessons` separately, from floor area and visitor rates
([`../REDISTRIBUTION.md`](../REDISTRIBUTION.md)). So whether a gym is `sports` or `leisure`, or a doctor's practice
`errands` or `retail_daily`, would change step 08's result. `MID_LABEL_TO_ACTIVITY` in [`config.py`](config.py)
groups the 12 labels into 7 coarser groups; neither the classifier, its notebook nor the pipeline reads it (the
pipeline uses the mapping of the same name in the root [`config.py`](../config.py), one label per category).

Retail labels come only from tags that name a sale: `shop=*`, a pharmacy (`amenity`, `healthcare`), a bakery, butcher
or confectioner (`craft`), the building types `retail`, `supermarket` and `kiosk`, and, where neither POI tags nor an
ALKIS code answer, retail land use. No ALKIS code claims a retail label, not even the generic "trade and services"
codes; on the generic commercial code `31001_2000` retail land use refines only the class.

## Bosserhoff classes

Each building gets at most one **Bosserhoff class** (e.g. `normal office`, `discount stores`, `schools`), which carries
a worker density in workers per 100 m² of floor area (`BOSSERHOF_WEIGHTS` in [`config.py`](config.py)). The table
has 47 entries, written in lower case without punctuation: 45 of the pipeline's 46 classes, `others industrial` for
the pipeline's `others` (main group *Industrial operations / Production*), and `retail wholesale`. Six of them no rule
emits: `craft courtyards`, `crafts and trades`, `factory outlet centers`, `retail wholesale`,
`self service department stores`, `suppliers for car dealerships` (`reachable_bosserhof_classes()` lists the rest).

---

## Where the rules live

| To change… | Edit |
|---|---|
| what an OSM POI tag means | `AMENITY_RULES` / `SHOP_RULES` / `TOURISM_RULES` / `BUILDING_TAG_RULES` / `INFORMATION_RULES` / `LEISURE_RULES` / `HEALTHCARE_RULES` / `CLUB_RULES` / `SPORT_RULES` and the `*_KV_RULES` in `rule_utils.py` |
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
`classify_building()` on a sample of 30 real input rows shipped with the tests
([`tests/data/sample_condensed_buildings.parquet`](tests/data/sample_condensed_buildings.parquet), derived from
OpenStreetMap (ODbL) and LGLN (CC BY 4.0) data), statically checks every rule table, and pins each deliberate
decision: the ALKIS code table (exclusions, the *Schloss*/"Lock" mistranslation of the codelist copy in
[`reference/`](reference/)), the land-use refinement, the `work` invariant, layer precedence including the
`kindergartens` vs `services` case, `;`-composite tag splitting, farm-building exclusions, multi-POI reconciliation,
where `business` may and may not be claimed, the keys `leisure`, `healthcare`, `club` and `sport`, the key defaults and
the shopping-centre count.
