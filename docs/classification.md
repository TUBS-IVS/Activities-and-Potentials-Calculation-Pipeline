# The rule-based classifier

[`rule_utils.py`](../rule_utils.py) is the whole classifier — a plain Python module with no model weights, no API and
no inference. **Every answer comes from an explicit lookup table: one row per tag value, and the row *is* the rule.**
To change what a tag means, edit its row; nothing else reads it.

- [Three layers, strict precedence](#three-layers-strict-precedence)
- [Design decisions](#design-decisions)
- [Activity labels](#activity-labels)
- [Checking what the rules predict](#checking-what-the-rules-predict)
- [Where the rules live](#where-the-rules-live)
- [Tests that hold the rules in place](#tests-that-hold-the-rules-in-place)

---

## Three layers, strict precedence

The table format is the same everywhere:

```python
"tag_value": ({mid_labels}, "bosserhof_class")
```

`classify_building(row)` tries three layers in order and stops at the first that answers:

| Layer | Reads | Table | Measured reach |
|---|---|---|---|
| **1 · POI tags** | `amenity`, `shop`, `tourism`, `building`, `information`, plus `office=`/`craft=`/`social_facility=` recovered from `additional_information` | `AMENITY_RULES` (76), `SHOP_RULES` (110), `TOURISM_RULES` (12), `BUILDING_TAG_RULES` (85), + 3 key:value tables (32/20/8) | 12,485 · **2.2 %** |
| **2 · ALKIS code** | `function` (e.g. `31001_2000`) | `ALKIS_RULES` — 71 codes (21 excluded, 50 active) | 517,939 · **90.2 %** |
| **3 · OSM fallback** | `osm_building_type`, then `osm_landuse_class` | `BUILDING_TAG_RULES`, `OSM_LANDUSE_FALLBACK` (3) | 590 · 0.1 % |
| — *no usable signal* | | | 43,421 · 7.6 % |

*Reach measured on the 574,435-building classified set; 282,017 of them (49.1 %) receive a Bosserhof class.*

**The reach column is itself a finding.** The richly-specified POI layer resolves only 2.2 % of buildings; 90 % are
decided by a cadastral code, and 96 % of *those* by just two codes. Rule quality in layers 1 and 3 has almost no
leverage on the aggregate result — see [Why the gap](validation.md#why-the-gap--the-mechanisms).

## Design decisions

Four properties are worth stating explicitly, because each was a deliberate choice:

- **Strict precedence.** An answer from any layer — *including an explicit "no activity"* — ends classification.
  Unioning layers instead was rejected: `services` (2.31) would attach to nearly every POI building and, under the
  highest-weight rule, silently override real classes just below it, turning every `kindergartens` (2.30) into
  `services`.
- **Keyed on the ALKIS code, never the English label.** `31001_3031` is *Schloss* (a palace) but ships with the label
  "Lock", and 15 of 301 codes share a label with another code. Notebook 05 therefore carries `function` through, and
  no rule reads translated text.
- **`work` is added centrally, not per row.** A Bosserhof class *is* a worker-density rating, so anything carrying one
  is by definition staffed. The tables describe only the visitor-facing purpose; `classify_building` adds `work` once.
  Writing it into ~200 rows by hand is how it went missing from restaurants and schools the first time.
- **Multi-tenant buildings.** Labels are unioned across all POIs on the building. The Bosserhof class must be single
  (the capacity formula takes one coefficient), so the highest worker-weight match wins — an explicit rule standing in
  for judgement the pipeline cannot make, and a known source of upward bias.

**Deliberately not used:** `osm_names` or any free-text business name. Recognising that "Bahlsen" is a food
manufacturer requires world knowledge a tag rule cannot encode without becoming a name lookup table for one region —
the opposite of a transferable pipeline. That is the single biggest driver of the gap measured in
[validation.md](validation.md), and it is the finding, not an oversight.

Every table is statically validated at import (`validate_rule_tables()`): an invalid Bosserhof class or MiD label
anywhere fails immediately rather than silently producing an unweighted building that notebook 07 drops.

> **One failure mode has been designed out.** An earlier version resolved ALKIS through an ordered, first-match-wins
> list of regexes over the English label text. That does not compose: a broad pattern placed early silently swallows
> labels meant for a later rule — `greenhouse|agricultural` captured farm *dwellings* (≈3,800 of them, reported as
> industrial workplaces); `church|chapel` captured a church *tower*; and `Gotteshaus` matched nothing at all, so one
> building type got two different answers. One explicit row per ALKIS code removes the failure mode by construction:
> there is no ordering to get wrong, and every code's answer is visible on its own line.

---

## Activity labels

`classify_building()` assigns each building one or more of **12 MiD activity labels**, which collapse to the **7 zone
activity columns** the redistribution actually uses (`config.MID_LABEL_TO_ACTIVITY`):

| MiD labels | Zone column | Examples |
|---|---|---|
| `work`, `business` | **Workers** | offices, workplaces, industry |
| `retail_daily`, `errands` | **Retail_Daily** | supermarkets, bakeries, pharmacies, banks, doctors |
| `retail_non_daily` | **Retail_Non-Daily** | clothing, furniture, electronics |
| `leisure`, `sports`, `meetup`, `lessons` | **Leisure** | restaurants, cinemas, gyms, churches, driving schools |
| `school` | **School** | primary, secondary, vocational |
| `university` | **University** | higher education |
| `childcare` | **Kindergarten** | kindergartens, daycare |

**This collapse decides which assignment choices matter.** A distinction *within* a group is descriptive only —
whether a gym is `sports` or `leisure` changes nothing downstream. A distinction *across* groups changes the result:
whether a restaurant is `leisure` (Leisure) or `errands` (Retail_Daily) does. When reviewing or extending the rules,
spend the effort on the cross-group calls.

Two consequences worth stating for interpretation:

- **`errands` routes to Retail_Daily** — *Einkauf täglicher Bedarf*. Hospital, bank and post-office visits therefore
  land in the daily-shopping column. That conflation comes from the 7 columns the zone data supplies, not from the
  rules.
- **Both retail columns are fed only by real shop tags.** Generic ALKIS "Handel und Dienstleistungen" codes
  deliberately claim no retail. Earlier they supplied 84 % of all `retail_non_daily` buildings (9,777 of 11,622)
  versus 1,832 from actual shop tags, so the Retail_Non-Daily budget spread over ~5.9× more buildings than
  Retail_Daily purely as an artefact.

Each building also gets one **Bosserhof class** (e.g. `normal office`, `discount stores`, `schools`) supplying a
worker-density weight (workers per 100 m³) for redistribution. Anything with a Bosserhof class also carries `work`,
added centrally — the class *is* a worker-density rating, so the building is staffed by definition, whatever
visitor-facing activities it also has.

---

## Checking what the rules predict

Without touching real data:

```bash
python scripts/rule_smoke_test.py --amenity restaurant
python scripts/rule_smoke_test.py --function 31001_2000 --osm_landuse_class industrial
python scripts/rule_smoke_test.py --alkis              # the whole ALKIS table, with German labels
python scripts/rule_smoke_test.py --alkis 31001_3031   # one code
python scripts/rule_smoke_test.py --real 20            # 20 real buildings: tags + prediction (needs notebook 05 output)
python scripts/rule_smoke_test.py                      # interactive REPL
```

## Where the rules live

| To change… | Edit |
|---|---|
| what an OSM POI tag means | `AMENITY_RULES` / `SHOP_RULES` / `TOURISM_RULES` / `BUILDING_TAG_RULES` in `rule_utils.py` |
| what an ALKIS code means | `ALKIS_RULES` in `rule_utils.py` — one row per code, with its German label and building count as a comment |
| the land-use refinement | `LANDUSE_BOSSERHOF_REFINEMENT` in `rule_utils.py` |
| worker densities, activity taxonomy, zone column names | `config.py` |

## Tests that hold the rules in place

`tests/test_06_rule_based.py` (120 tests) is where the classifier's decisions are held in place. Beyond the
real-sample checks it pins: the ALKIS code table (exclusions, the *Schloss*/"Lock" mistranslation, agreement within
the religious and public families), the land-use refinement and its confinement to one code, the `work` invariant,
layer precedence including the `kindergartens` (2.30) vs `services` (2.31) override that strict precedence prevents,
`;`-composite tag splitting, farm-building exclusions, and multi-POI reconciliation. Each of those is a choice that
would otherwise be easy to undo by accident.

It reads `tests/data/sample_condensed_buildings.parquet` — rows sampled across 10 signal buckets, including the two
ALKIS codes that between them cover 85 % of the dataset, so the fixture exercises the dominant paths rather than only
the interesting minority ones. Regenerate after running notebook 05 on new data:

```bash
python tests/create_classifier_test_sample.py
```
