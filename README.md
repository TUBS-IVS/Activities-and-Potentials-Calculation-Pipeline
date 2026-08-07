# Building-Level Activity Capacity Pipeline — Rule-Based Classification

> **Institution:** [Institute of Transportation and Urban Engineering](https://www.tu-braunschweig.de/isv), TU Braunschweig
> **Author:** Mayur Patel

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-156%20passing-brightgreen)]()

---

## Overview

Agent-based travel demand models require building-level representations of activity locations and their potentials, yet such data are often unavailable or incomplete. This repository provides a **transferable, open-source pipeline** that derives building-level activity types and geometry-based potentials by combining:

- **ALKIS** — authoritative 3D cadastral building data (Germany / Lower Saxony)
- **OpenStreetMap** — POIs, land-use polygons, and supplementary building footprints
- **A deterministic, tag-based classifier** (`rule_utils.py`) — assigns each building a MiD activity label set and a Bosserhof worker-density class purely from structured OSM tags and official ALKIS building-function codes, with no external API call and no free-text name matching

Zone-level activity totals (workers, pupils, shoppers, etc.) are then redistributed to individual buildings using activity-informed, geometry-aware weights — yielding a disaggregated, building-level activity potential dataset ready for transport modelling and agent-based simulation.

This is a deliberately **rules-only branch**: an experiment testing how far a fully deterministic classifier (see [Classification approach](#classification-approach) below) gets against manually-verified ground truth, without an LLM in the loop anywhere. See [Validation](#validation) for the honest, measured answer.

---

## Pipeline at a Glance

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Stage 1 · Geometric Preprocessing                    (Notebooks 02–01) │
│  ─ Clip the OSM PBF, extract POIs and OSM building footprints           │
│  ─ Clean ALKIS 3D buildings, compute footprint area & volume            │
│  ─ Merge duplicate/overlapping polygons (POI-aware)                     │
├─────────────────────────────────────────────────────────────────────────┤
│  Stage 2 · Semantic Enrichment                        (Notebooks 03–05) │
│  ─ Clean OSM POIs                                                       │
│  ─ Spatial-join ALKIS function labels, OSM land-use, OSM building tags  │
│  ─ Attach POIs to buildings (intersection + 100 m nearest-neighbour)    │
│  ─ Aggregate to one record per building (gml_id)                        │
├─────────────────────────────────────────────────────────────────────────┤
│  Stage 3 · Rule-Based Classification                     (Notebook 06)  │
│  ─ Classify each building via rule_utils.classify_building():           │
│    1. OSM POI tags (amenity/shop/tourism/building/information)          │
│    2. ALKIS building-function code → explicit table, one row per code   │
│    3. OSM building/landuse fallback (for OSM-only buildings)            │
│  ─ Strict precedence: first layer that answers wins                     │
│  ─ Fully deterministic — no API calls, no checkpointing, <1 min/dataset │
├─────────────────────────────────────────────────────────────────────────┤
│  Stage 4 · Activity-Informed Disaggregation           (Notebooks 07–08) │
│  ─ Spatially assign buildings to TAZs                                   │
│  ─ Redistribute zonal totals ∝ building volume × Bosserhof weight       │
│  ─ Hierarchical fallback (TAZ → neighbours → study area)                │
│  ─ Percentile-based volume caps prevent unrealistic concentrations      │
└─────────────────────────────────────────────────────────────────────────┘
```

### Notebook Sequence

> **Run order is 02 → 03 → 01 → 04 → 05 → 06 → 07 → 08, not numeric order.** Notebook 01
> reads notebook 03's cleaned POIs to set `has_poi`, which gates the polygon merge. See
> [Why the run order is not numeric](#why-the-run-order-is-not-numeric).

| Order | Notebook | Stage | Description |
|---|---|---|---|
| 1 | `02_poi_extraction.ipynb` | Geometric | Clip PBF to the study boundary; extract POIs + OSM building footprints |
| 2 | `03_poi_cleaning.ipynb` | Semantic | Normalise names, merge address fields, build search tags |
| 3 | `01_geometry_volume.ipynb` | Geometric | Clean ALKIS buildings, compute volumes, POI-aware polygon merge |
| 4 | `04_building_enrichment.ipynb` | Semantic | Spatial-join GFK codes, ALKIS labels, OSM land-use |
| 5 | `05_poi_building_merge.ipynb` | Semantic | Attach POIs → buildings (intersection + 100 m fallback) |
| 6 | `06_rule_based_classification.ipynb` | Classification | Classify every building: MiD label + Bosserhof class, via `rule_utils.py` |
| 7 | `07_redistribution.ipynb` | Disaggregation | Allocate zone-level targets to buildings |
| 8 | `08_final_results.ipynb` | Disaggregation | Aggregate to zone level, compare with targets, export |
| — | `09_validation_ground_truth.ipynb` | Validation | Decode the colour-coded annotation workbook into a clean ground-truth table |
| — | `10_validation_scoring.ipynb` | Validation | Score the rule engine against that ground truth |

Notebooks 09 and 10 are **independent of 01–08** — they read a pinned building file, not this run's output (see [Why the scored input is pinned](#why-the-scored-input-is-pinned)). Each step reads from and writes to `data/output/` so you can inspect intermediate results or resume from any point.

### Why the run order is not numeric

Notebook 01 contains this branch:

```python
if OSM_POIS_MODIFIED_FILE.exists():        # written by notebook 03
    ...
    gdf['has_poi'] = gdf.index.isin(poi_poly_idx)
else:
    gdf['has_poi'] = False
    print('OSM POI file not found — running without POI flags (run nb 02+03 first for full results)')
```

`has_poi` then **blocks the union-find merge** — two touching polygons with the same ALKIS function are merged only if neither carries a POI:

```python
if has_poi[i] or has_poi[j]:
    continue
```

So on a clean checkout, running 01 first takes the else branch, merges buildings that should have stayed separate, and yields a **smaller, differently-indexed** building set. Because notebook 05 assigns `gml_id` from the positional row index, every downstream id shifts too.

Measured on this dataset: the correct order (02 → 03 → 01 → …) produces **574,435** condensed buildings and reproduces that count exactly across runs. A run that takes the else branch produces **567,961**. Both are internally consistent; only the first is correct.

---

## Classification approach

`rule_utils.py` is the whole classifier — a plain Python module with no model weights, no API and no inference. **Every answer comes from an explicit lookup table: one row per tag value, and the row *is* the rule.** To change what a tag means, edit its row; nothing else reads it.

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

**The reach column is itself a finding.** The richly-specified POI layer resolves only 2.2 % of buildings; 90 % are decided by a cadastral code, and 96 % of *those* by just two codes. Rule quality in layers 1 and 3 has almost no leverage on the aggregate result — see [Why the gap](#why-the-gap--the-mechanisms).

Four properties are worth stating explicitly, because each was a deliberate choice:

- **Strict precedence.** An answer from any layer — *including an explicit "no activity"* — ends classification. Unioning layers instead was rejected: `services` (2.31) would attach to nearly every POI building and, under the highest-weight rule, silently override real classes just below it, turning every `kindergartens` (2.30) into `services`.
- **Keyed on the ALKIS code, never the English label.** `31001_3031` is *Schloss* (a palace) but ships with the label "Lock", and 15 of 301 codes share a label with another code. Notebook 05 therefore carries `function` through, and no rule reads translated text.
- **`work` is added centrally, not per row.** A Bosserhof class *is* a worker-density rating, so anything carrying one is by definition staffed. The tables describe only the visitor-facing purpose; `classify_building` adds `work` once. Writing it into ~200 rows by hand is how it went missing from restaurants and schools the first time.
- **Multi-tenant buildings.** Labels are unioned across all POIs on the building. The Bosserhof class must be single (the capacity formula takes one coefficient), so the highest worker-weight match wins — an explicit rule standing in for judgement the pipeline cannot make, and a known source of upward bias.

**Deliberately not used:** `osm_names` or any free-text business name. Recognizing that "Bahlsen" is a food manufacturer requires world knowledge a tag rule cannot encode without becoming a name lookup table for one region — the opposite of a transferable pipeline. That is the single biggest driver of the gap measured below, and it is the finding, not an oversight.

Every table is statically validated at import (`validate_rule_tables()`): an invalid Bosserhof class or MiD label anywhere fails immediately rather than silently producing an unweighted building that notebook 07 drops.

**To check what the rules predict**, without touching real data:

```bash
python scripts/rule_smoke_test.py --amenity restaurant
python scripts/rule_smoke_test.py --function 31001_2000 --osm_landuse_class industrial
python scripts/rule_smoke_test.py --alkis              # the whole ALKIS table, with German labels
python scripts/rule_smoke_test.py --alkis 31001_3031   # one code
python scripts/rule_smoke_test.py --real 20            # 20 real buildings: tags + prediction
python scripts/rule_smoke_test.py                      # interactive REPL
```

---

## Validation

`data/validation/` holds a real, hand-annotated accuracy check — not a synthetic benchmark. **1,391 buildings** the project author checked one by one against reality, with the verdict recorded as an Excel **cell fill colour** next to each prediction:

| Colour | Meaning |
|---|---|
| 🟩 green `FFC6EFCE` | prediction accepted as correct |
| 🟥 red `FFFFC7CE` | wrong — the corrected value is typed into the same cell |
| 🟨 yellow `FFFFEB9C` | validator could not decide — excluded |
| no fill | never validated — excluded |

```bash
jupyter lab notebooks/09_validation_ground_truth.ipynb   # decode colours -> human ground truth
jupyter lab notebooks/10_validation_scoring.ipynb        # classify + score against it
```

The metric definitions live in [`validation_utils.py`](validation_utils.py) so they are unit-testable and cannot drift from the notebook.

### The annotation workbooks

| File | Role |
|---|---|
| `sample_version_1_balanced.xlsx` | **the input** (`config.VALIDATION_SOURCE_FILE`) — what notebooks 09/10 read |
| `sample_version_1.xlsx` | the reviewer's first pass, kept as the annotation audit trail |

`_balanced` differs from the reviewer's later working copy in exactly **four cell fills** (Excel rows 405, 431, 463, 557), which moved from green to yellow. Those four rows were green on activities but still yellow on Bosserhof, so the reviewed totals came out uneven — 899 activities against 895 Bosserhof. Setting them aside on *both* dimensions makes the reviewed and set-aside splits identical, so the two dimensions are measured over the same buildings:

| | activities | Bosserhof |
|---|---|---|
| reviewed (green + red) | 895 | 895 |
| uncertain | 337 | 337 |
| unvalidated | 159 | 159 |

The opposite fix — turning the four Bosserhof cells green — was rejected deliberately: it would assert an agreement the reviewer never gave. No cell *value* was altered; only fills.

> Equal verdict counts do **not** mean equal scoreable counts. Steps 3 and 4 of notebook 09 drop further rows for reasons unrelated to colour, leaving 882 activities-scoreable against 874 Bosserhof-scoreable. The residual gap is 11 rows scoreable on activities only (8 where several Bosserhof classes were named at once, 3 uncorrected) minus 3 scoreable on Bosserhof only.

### What is compared against what

> **The rule engine is scored against the HUMAN label — never against a model's prediction.**

This needs stating precisely, because of how the workbook was built. The spreadsheet arrived pre-filled with an **earlier LLM run's** predictions. A 🟩 green cell means the human *read that answer and affirmed it*, so the human label equals the LLM's output on those rows. A 🟥 red cell carries the value the human *typed themselves*. Both are human labels; affirmation is a judgement, not the absence of one.

What that construction *does* invalidate is scoring **the LLM** against this ground truth: on green rows it matches by definition, so its "accuracy" is arithmetically the green fraction. No LLM figure is presented here as comparable.

The rule engine has no such circularity — it never saw the workbook, and no rule table was written against it. Notebook 09 strips every pre-fill and prediction column out of the ground truth and asserts their absence, so notebook 10 has no model prediction available to compare against even in principle.

**A limitation to carry into the write-up:** because the human reviewed LLM output rather than labelling from scratch, any tendency to accept a plausible-looking answer is baked into the ground truth, and the rule engine is measured against labels partly shaped by that review. Only a freshly labelled blind sample removes this.

### Why the scored input is pinned

Notebook 05 assigns `gml_id` from the positional row index (`gdf['gml_id'] = gdf.index`), which is meaningful only within one run. The annotated workbook stores those positional ids, so it can only be scored against the building file it was drawn from — a 578,080-building condensed dataset produced by the earlier LLM run.

Re-running the pipeline does not reproduce that file. This run produces 574,435 condensed buildings; a run in the wrong order produces 567,961. Scoring against a regenerated dataset compares *different buildings* while every join looks healthy — measured previously: 94.7 % of ids matched while **0 %** were the same building.

Notebook 10 therefore reads `config.VALIDATION_BUILDINGS_FILE` and verifies identity via `volume_m3` before scoring anything. Both guards pass at **100 %** (1,391 / 1,391 ids present, 1,391 / 1,391 volumes matching), and the second **refuses to score** below 95 % agreement rather than emit numbers about the wrong buildings.

> ⚠️ **This path currently points outside the repository.**
>
> ```python
> VALIDATION_BUILDINGS_FILE = (
>     ROOT.parent / "Capacity_Calculation-pipeline-original" / "Areas-of-interest-POIs"
>     / "condensed_buildings_with_pois.gpkg"
> )
> ```
>
> The file is 337 MB and is **not** distributed with this repository — it exceeds GitHub's 100 MB per-file limit. Notebooks 01–08 do not need it; **only notebook 10 does.** On a machine without that sibling directory, notebook 10 raises `FileNotFoundError` at its input check and the rest of the pipeline is unaffected. To reproduce the published accuracy figures, obtain that file and point `VALIDATION_BUILDINGS_FILE` at it.

### How the annotation resolves

Notebook 09 turns the workbook into a scoreable table. The decisions it has to make are not mechanical, and each is recorded per row so the denominator is always explainable:

| Dimension | scoreable | excluded | why excluded |
|---|---|---|---|
| **activities** | **882** | 509 | 337 uncertain · 159 unvalidated · 13 flagged wrong but never corrected |
| **bosserhof** | **874** | 517 | 337 uncertain · 159 unvalidated · 13 uncorrected · 8 ambiguous (validator named several classes) · plus 7 recovered from free text and 3 kept verbatim |

Three cases needed real handling rather than a `literal_eval`:

- Many activity corrections have quoting damage (`['Retail_Non-Daily]`, `['Workers'; Retail_Non-Daily']`). Parsing matches tokens against the closed 7-name vocabulary instead, which reads those fine.
- **13 rows** were corrected to *living* / *residential*, meaning "no activity here". That is a **real, scoreable ground truth of the empty set** — and the clearest false positives in the sample. Discarding them as unparseable would have hidden exactly the rows that measure over-prediction.
- **8 bosserhof corrections name two or more classes** (`kindergartens public facilities`). No single truth exists, so they are excluded as ambiguous — detected structurally, by counting known class names inside the string, not from a hand-written list.

### Two dimensions, two metrics

- **Activities** is a multi-label set, so precision and recall are reported **separately**. They are not interchangeable: **over-prediction misallocates** zone capacity onto a building with no claim to it, while **under-prediction removes** the building from that activity's redistribution entirely. Notebook 10 micro-averages over label *instances* — a building that invents two activities contributes two false positives.
- **Bosserhof class** is a single label, so plain accuracy. An empty truth (`""`, "no class") matches a prediction of `None`: a correct refusal counts as correct.

### Rule-engine scores — measured, held out

**Activities** (882 buildings, micro-averaged over 1,526 label instances):

| Metric | Value |
|---|---|
| **Precision** | **84.5 %** (TP = 1,198, FP = 220) |
| **Recall** | **78.5 %** (TP = 1,198, FN = 328) |
| F1 | 81.4 % |
| Exact set match | 54.3 % (479 / 882) |

Error direction: 479 exact · 116 over-prediction only · 186 under-prediction only · 101 both.

**Bosserhof class** (874 buildings): **50.3 %** accuracy (440 correct). Excluding the 4 buildings whose true class no rule can emit: **50.6 %** (440 / 870).

### Which activities are invented, and which are overlooked

| Activity | In truth | Over-predicted | Missed | Miss rate |
|---|---|---|---|---|
| Workers | 850 | 21 | 58 | 6.8 % |
| Leisure | 324 | 12 | **118** | 36.4 % |
| Retail_Non-Daily | 189 | 6 | **104** | **55.0 %** |
| **Retail_Daily** | 69 | **174** | 18 | 26.1 % |
| School | 50 | 4 | 15 | 30.0 % |
| University | 25 | 2 | 10 | 40.0 % |
| Kindergarten | 19 | 1 | 5 | 26.3 % |

Leisure and Retail_Non-Daily account for **222 of the 328 misses** — overwhelmingly the name-dependent cases (a restaurant or clothing shop carrying no OSM tag, identifiable only from its business name).

`Retail_Daily` runs the other way: over-predicted 174 times against 69 real instances. That is the `errands` → Retail_Daily collapse in the taxonomy, not a rule defect.

### Accuracy conditioned on the information available

**This is the table to read first.** It separates rule quality from data coverage:

| Information available | Buildings | Precision | Recall | Exact set |
|---|---|---|---|---|
| POI tag on the building | 435 | 83.2 % | **89.3 %** | 61.1 % |
| Generic commercial ALKIS code | 265 | **95.5 %** | 68.8 % | 58.1 % |
| Specific ALKIS code | 110 | 76.3 % | 85.4 % | 50.0 % |
| OSM footprint / land use only | 3 | 75.0 % | 75.0 % | 66.7 % |
| ALKIS code says *no activity* | 57 | 0 % | 0 % | 3.5 % |
| No usable signal | 12 | 0 % | 0 % | 0 % |

Where a building carries a POI tag, recall is **89.3 %**. Where the cadastre states it is a dwelling or supplies nothing at all — 69 buildings, 7.8 % of the sample — the engine outputs nothing and scores zero by construction. That floor is a property of the input data, not of the rules.

The six tiers reconcile exactly with the headline: 435 + 265 + 110 + 3 + 12 + 57 = 882 buildings, and their correct/extra/missing columns sum to 1,198 / 220 / 328.

### Why the gap — the mechanisms

Diagnosed against the real mismatches; see `data/validation/10_score_detail.csv` for row-level detail. These are **structural causes, not a to-do list** — most cannot be closed by writing more rules.

**1. The dominant ALKIS code is an undifferentiated catch-all.** This is the ceiling on any rules-only approach reading ALKIS, and it is a property of cadastral coding practice rather than of the rules:

| Evidence about code `31001_2000` — *Gebäude für Wirtschaft oder Gewerbe* | Value |
|---|---|
| Buildings carrying it, state-wide (raw ALKIS input, 4,878,052 polygons) | 1,434,102 (29.4 %) |
| Buildings carrying it, in the classified set | 244,606 (**42.6 %**) |
| Share of **all** non-residential (2xxx) codes it absorbs, state-wide | **82.0 %** |
| Median volume | **126 m³** (p25 = 75 m³; 38.8 % below 100 m³) |
| Median volume of the *specific* codes `2010` / `2100` | 1,061 / 1,379 m³ |
| Share sitting inside `residential` OSM land use | 92.1 % |
| Specific code for a garage (`31001_2463`) — exists in the codelist | **used 0 times in 4,878,052 buildings** |

Lower Saxony's extract does not populate building subtypes. Because the garage code is never used, garages, sheds and outbuildings sit in this one bucket alongside genuine commercial premises, and **no rule can separate them from the code alone.** Lower Saxony does not contain 1.4 million commercial buildings.

Crucially, this is **not uniform across building types** — the same check per ALKIS range shows where a rules-only approach can and cannot work:

| ALKIS range | Buildings | Share in the generic parent code | Distinct codes used |
|---|---|---|---|
| `1xxx` residential | 253,389 | **96.1 %** | 6 |
| `2xxx` commercial / industrial | 267,552 | **91.4 %** | 22 |
| `3xxx` public / culture / education | 8,870 | **32.1 %** | 31 |

The public, cultural and educational range *is* properly differentiated — schools, churches, hospitals, museums, fire stations and courts all carry specific codes — which is exactly why the engine handles those building types well. The residential and commercial ranges are almost undifferentiated. So the ceiling is **near-total for commercial buildings and near-absent for civic ones**, which is a more useful claim than any single accuracy figure.

The same pattern holds in the supply range: code `31001_2500` carries 4,545 buildings in the classified set (median volume 78 m³) while its specific subtypes are barely populated — only `31001_2513` is used at all (70 buildings here, 309 state-wide), leaving the rest of the energy / water / gas / pumping-station subtypes unused.

This is left uncorrected on purpose. A volume floor would partly escape it — 100 m³ is the 10th percentile of the *specific* commercial codes, so it is a principled rather than tuned threshold — but the ceiling is what this branch exists to measure. The one refinement applied is tag-based: buildings under this code sitting in industrial or retail land use get the corresponding Bosserhof class instead of `services`.

**2. ALKIS and Bosserhof are orthogonal ontologies.** ALKIS is a cadastral register recording a building's permitted physical form; Bosserhof encodes economic worker density. The mapping between them is provably one-to-many — on the verified sample, buildings sharing a single ALKIS label carry many different true Bosserhof classes, spanning a several-fold range of worker weights. No deterministic function of the label can beat picking the modal class.

**3. For cadastrally-residential buildings, the rules are not wrong — the register is stale.** Some buildings carry an ALKIS code stating they are dwellings while the validator found a bank, a bakery or a hotel inside. The engine faithfully reports the authoritative source, so the divergence is data currency in ALKIS rather than a classification error, and it bounds *any* method reading the cadastre — an LLM included.

Measured on the 882-building scored set: **69 buildings (7.8 %)** fall in the two tiers where the engine can emit nothing at all — 57 whose code states no activity, 12 with no usable signal. Those score 0 % recall by construction. That is a real floor, but a modest one: it does **not** account for the bulk of the recall shortfall.

**4. Two failure modes with opposite downstream effects.** *Absence* (no discriminating input) yields an empty result, so the building drops out of redistribution entirely — capacity **removed**. *Ambiguity* (generic code) yields `services`, so the building participates with a possibly-wrong weight — capacity **misallocated**. These are usually reported as one error rate but are different pathologies for a transport model, and they are why precision and recall must be read separately.

**5. The single-class assumption is violated by mixed use.** Bosserhof assumes one dominant use per building; `Deutsche Bank;Ernsting's family` is a bank *and* a clothing store. Any single answer is wrong by construction, so the "highest worker-weight wins" arbitration cannot be validated against ground truth — the limitation is in applying Bosserhof at building level, not in the rule.

**6. Names carry the missing information — and this is the dominant mechanism.** Buildings with a missing label very often carry an OSM *name* but no OSM *tag*, so the name is the only signal available. Real examples, with what the rules produced:

| OSM name | Human label | Rule engine |
|---|---|---|
| `Deutsche Bank;Ernsting's family` | Retail_Non-Daily, Workers | *nothing* |
| `Grundschule Langelsheim` | School, Workers | Leisure, Workers |
| `Musikschule` | Leisure, Workers | Retail_Daily, Workers |
| `Würth Braunschweig` | Retail_Non-Daily, Workers | Workers |
| `Solvis GmbH` | Workers | *nothing* |

Some of these carry a *generic* German business noun a keyword layer could match (`Grundschule`, `Musikschule`); others need genuine world knowledge (`Würth`, `Solvis`, `Ernsting's family`). Deliberately left unaddressed: matching names would tune the pipeline to one region and dissolve the very question this branch exists to answer.

This is the measured cost of classifying without world knowledge. Treat it as the finding, not a limitation to hide.

> **One mechanism has been designed out rather than measured.** An earlier version resolved ALKIS through an ordered, first-match-wins list of regexes over the English label text. That does not compose: a broad pattern placed early silently swallows labels meant for a later rule — `greenhouse|agricultural` captured farm *dwellings* (≈3,800 of them, reported as industrial workplaces); `church|chapel` captured a church *tower*; and `Gotteshaus` matched nothing at all, so one building type got two different answers. Replacing the list with one explicit row per ALKIS code removes the failure mode by construction: there is no ordering to get wrong, and every code's answer is visible on its own line.

### A note on not tuning to the benchmark

The rules are written against the ALKIS and OSM vocabularies — what a tag or code *means* — never against the validation rows. Three episodes show why that distinction is not cosmetic. The figures below are historical, from an earlier and much smaller sample; they are kept because the *lesson* holds regardless of sample size.

**A correct fix made the score go down.** Stopping ~3,800 farm dwellings being reported as industrial workplaces lowered the benchmark score at the time: exactly one validated building carried that ALKIS code, and the buggy engine had emitted `work` for it — scoring a point for entirely the wrong reason. Optimising against the benchmark would have preserved the bug.

**A broken join produced a plausible-looking accuracy figure for weeks.** Earlier runs scored the rule engine against a *regenerated* condensed dataset whose positional `gml_id`s no longer matched the annotated workbook, so every comparison was against the wrong building. Re-scoring the same workbook with the same classifier against the correct building set:

| Building set | Volume identity | Precision | Recall |
|---|---|---|---|
| correct (pinned file) | 100 % | 80.8 % | **72.1 %** |
| misaligned (regenerated 05) | 0 % | 85.4 % | **25.9 %** |

**Precision barely moved — it even rose.** Only recall collapsed. The reason is structural: a misaligned prediction is usually the small set `{Workers}` or empty, which generates few false positives but many false negatives. So the one metric that looked healthy was the one insensitive to the defect. What exposed it was comparing each annotated building's stored `volume_m3` against the freshly computed value — now a hard gate in notebook 10 that **refuses to score** below 95 % agreement.

The lesson worth carrying into the write-up: for a join keyed on anything positional, verify identity with a payload value, not with the join's own match rate. Match rate was 94.7 % while true identity was 0 %.

**A ground-truth bug was found by auditing, not by reading the score.** Two hand-typed corrections contained misspelled activity names — `Kindergarden` and `Leisue` — which the parser matched against nothing and silently dropped, so the human's own label was incomplete on those rows and any classifier that predicted them correctly was scored as inventing them. Notebook 09 now carries a typo map and, more importantly, **asserts that no unrecognised token resembles an activity name**, so a future typo fails loudly instead of quietly corrupting the ground truth.

Every decision in the rule tables was therefore made from the vocabulary side — what does ALKIS code `31001_2500` denote, is a *Schloss* a palace or a lock, does "Handel" justify claiming retail on 13,708 buildings — and the sample is used only to *characterise* the outcome. Land use is used to refine one code because it is an independent tag; building volume is deliberately **not** used to filter the catch-all code, even though it would help, because the ceiling is what this branch exists to measure.

### Known ground-truth defects

Four buildings in the scored set carry a true class no rule can ever produce — a vocabulary limit, not a rule error. Notebook 09 lists them and notebook 10 reports accuracy with and without them:

| gml_id | Human label | Why unproducible |
|---|---|---|
| 550941 | `garbage collection` | not a Bosserhof class |
| 231906 | `factory outlet centers` | valid class, but no rule emits it |
| 345680 | `better school` | not a Bosserhof class — a school sports hall; likely meant `schools` |
| 556702 | `fraternity` | not a Bosserhof class |

Seven of the 47 defined Bosserhof classes are unreachable — no rule in `rule_utils.py` emits them: `craft courtyards`, `crafts and trades`, `customer service`, `factory outlet centers`, `retail wholesale`, `self service department stores`, `suppliers for car dealerships`.

---

## Repository Structure

```
.
├── config.py                   ← All settings — the ONLY file to edit for a new region
├── rule_utils.py               ← The classifier: rule tables + classify_building()
├── validation_utils.py         ← Validation metrics, shared by notebook 10 and the CLI
├── requirements.txt
├── CITATION.cff                ← Machine-readable citation (used by GitHub's "Cite this repository")
│
├── notebooks/                  ← Run 02 → 03 → 01 → 04 → 05 → 06 → 07 → 08
│   ├── 01_geometry_volume.ipynb
│   ├── 02_poi_extraction.ipynb
│   ├── 03_poi_cleaning.ipynb
│   ├── 04_building_enrichment.ipynb
│   ├── 05_poi_building_merge.ipynb
│   ├── 06_rule_based_classification.ipynb
│   ├── 07_redistribution.ipynb
│   ├── 08_final_results.ipynb
│   ├── 09_validation_ground_truth.ipynb
│   └── 10_validation_scoring.ipynb
│
├── scripts/
│   └── rule_smoke_test.py      ← Check what the rules predict for a given set of tags
│
├── data/
│   ├── input/                  ← Place your input files here (not tracked by git)
│   ├── output/                 ← Pipeline outputs (not tracked by git)
│   ├── reference/              ← ALKIS codelists (shipped with repo)
│   │   ├── building_function_codelist.csv    ← code → German/English label
│   │   └── alkis_building_activity_map.xlsx  ← context columns only; the
│   │                                            classifier no longer reads it
│   └── validation/             ← Hand-annotated source + decoded ground truth + scores
│       ├── sample_version_1_balanced.xlsx  ← colour-coded manual annotation (INPUT)
│       ├── sample_version_1.xlsx           ← reviewer's first pass, audit trail
│       ├── 09_ground_truth.parquet         ← decoded by notebook 09
│       ├── 10_score_detail.csv             ← per-building scores from notebook 10
│       └── 10_score_summary.csv
│
└── tests/
    ├── data/                   ← Synthetic + sampled fixtures for fast unit testing
    ├── conftest.py
    ├── create_test_data.py               ← Regenerate synthetic fixtures
    ├── create_classifier_test_sample.py  ← Sample real rows for classifier tests (run after step 05)
    ├── test_01_geometry.py
    ├── test_03_poi_cleaning.py
    ├── test_05_poi_building_merge.py
    ├── test_06_rule_based.py
    └── test_07_redistribution.py
```

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/TUBS-IVS/Activities-and-Potentials-Calculation-Pipeline.git
cd Activities-and-Potentials-Calculation-Pipeline
```

### 2. Create a Python environment

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Install the osmium-tool CLI (for Notebook 02)

Notebook 02 calls `osmium extract` via subprocess to clip the PBF file — a **system package**, not something `pip install` provides.

| Platform | Command |
|---|---|
| Linux (Debian/Ubuntu) | `sudo apt install osmium-tool` |
| macOS | `brew install osmium-tool` |
| Windows / conda | `conda install -c conda-forge osmium-tool` |

Verify: `osmium --version`

> **Note:** `geopandas` and `pyrosm` install cleanly on Linux via pip (they bundle their own GDAL/GEOS via pyogrio). If you encounter GDAL errors, run `sudo apt install libgdal-dev libgeos-dev` first.

### 5. Enable the notebook clean filter *(optional, recommended)*

The notebooks are committed **with their cell outputs** — they are the record of the run every figure in this README comes from, so `nbstripout` is deliberately *not* used. The cost is that editors inject metadata: VS Code's Data Wrangler extension writes a full column schema into every DataFrame output when a notebook is opened, and the kernelspec gets rewritten to whatever kernel you happen to have selected. Both produce large spurious diffs.

`scripts/nb_clean_filter.py` strips exactly that metadata on the way into git while leaving every output, execution count and error intact. `.gitattributes` already routes `*.ipynb` through it; git filter config is local to a clone, so enable it once with:

```bash
git config filter.nbclean.clean "python scripts/nb_clean_filter.py"
git config filter.nbclean.smudge cat
```

Your working copy is never modified — only what git stores. Skipping this step breaks nothing: git ignores an undefined filter, you just get noisier diffs.

---

## Input Data

Place files in `data/input/`:

| File | Format | Required columns / notes |
|---|---|---|
| `buildings.gpkg` | GeoPackage | `gml_id`, `measHeight` (m), `function` (ALKIS code). Optional: `Stadt`, `Strasse`, `HausNr`, `Name` |
| `region.pbf` | OSM PBF | Regional extract from [Geofabrik](https://download.geofabrik.de/) |
| `study_boundary.gpkg` | GeoPackage | Single polygon clipping the study area |
| `zone_targets.gpkg` | GeoPackage | TAZ polygons with activity-demand columns (see `ZONE_COLUMN_MAP` in `config.py`) |
| `landuse_residential.gpkg` | GeoPackage | Residential land-use polygons |
| `landuse_commercial.gpkg` | GeoPackage | Commercial land-use polygons |
| `landuse_industrial.gpkg` | GeoPackage | Industrial land-use polygons |
| `landuse_public.gpkg` | GeoPackage | Public land-use polygons |
| `landuse_sports.gpkg` | GeoPackage | Sports/recreation land-use polygons |
| `landuse_osm.gpkg` | GeoPackage | OSM land-use polygons — supplies `osm_landuse_class`, read by classifier layer 3. **Optional but load-bearing:** notebook 04 guards it with `.exists()`, so a run without it succeeds while classification silently degrades. |
| `osm_buildings.gpkg` *(optional)* | GeoPackage | Pre-extracted OSM building footprints. If absent, Notebook 02 extracts them from the PBF automatically. |

The `data/reference/` folder ships with the ALKIS function codelist and the Bosserhof building-use mapping — **do not modify** these for standard German cadastral data.

### Comparable datasets in other countries

| Country | Dataset | Notes |
|---|---|---|
| Switzerland | [swissBUILDINGS3D](https://www.swisstopo.admin.ch/en/landscape-model-swissbuildings3d-2-0) | 3D building geometries |
| Netherlands | [BAG register](https://data.overheid.nl/en/dataset/basisregistratie-adressen-en-gebouwen--bag-) | Address and building register |
| Germany (other states) | ALKIS (state land survey offices) | Replace the ALKIS codelist in `data/reference/` if needed |

---

## Configuration

**All region-specific settings live in [`config.py`](config.py).** You should not need to edit any notebook.

Key settings to review when adapting to a new region:

```python
# Coordinate reference system
TARGET_CRS = "EPSG:25832"   # UTM Zone 32N — change for your region

# Map your zone file's column names to the 7 pipeline activity categories
ZONE_COLUMN_MAP = {"Workers": "SG_3_BE~17", "School": [...], ...}

# Volume thresholds
MIN_BUILDING_VOLUME_M3  = 1    # geometric artefact filter (Notebook 01)
MIN_CONDENSED_VOLUME_M3 = 30   # unusable space filter (Notebook 05)
```

The classification rule tables themselves (`AMENITY_RULES`, `SHOP_RULES`, `BOSSERHOF_WEIGHTS`, etc.) live in `rule_utils.py` and `config.py` — see [Classification approach](#classification-approach).

---

## Running the Pipeline

```bash
jupyter lab notebooks/
```

Run the notebooks in **dependency order — 02, 03, 01, 04, 05, 06, 07, 08** (09 and 10 are optional validation steps, not required for a normal run). Measured end-to-end on the Greater Braunschweig dataset (4,878,052 raw polygons → 574,435 classified buildings), total **34.7 min**:

| Order | Notebook | Runtime | Output |
|---|---|---|---|
| 1 | 02 poi_extraction | 3.8 min | 68,315 POIs · 509,794 OSM buildings |
| 2 | 03 poi_cleaning | 0.4 min | 68,315 cleaned POIs |
| 3 | 01 geometry_volume | 15.1 min | 663,580 buildings (from 4,878,052 raw) |
| 4 | 04 building_enrichment | 4.8 min | 663,580 enriched |
| 5 | 05 poi_building_merge | 6.8 min | 574,435 condensed |
| 6 | 06 rule_based_classification | **0.7 min** | 282,017 classified (49.1 %) |
| 7 | 07 redistribution | 2.7 min | 880 zones · conservation error 1.5 × 10⁻¹¹ |
| 8 | 08 final_results | 0.2 min | 279,913 buildings matched to a zone |
| — | 09 + 10 validation | 0.3 min | 882 / 874 scored |

---

## Activity Labels

`rule_utils.classify_building()` assigns each building one or more of **12 MiD activity labels**, which collapse to the **7 zone activity columns** the redistribution actually uses (`config.MID_LABEL_TO_ACTIVITY`):

| MiD labels | Zone column | Examples |
|---|---|---|
| `work`, `business` | **Workers** | offices, workplaces, industry |
| `retail_daily`, `errands` | **Retail_Daily** | supermarkets, bakeries, pharmacies, banks, doctors |
| `retail_non_daily` | **Retail_Non-Daily** | clothing, furniture, electronics |
| `leisure`, `sports`, `meetup`, `lessons` | **Leisure** | restaurants, cinemas, gyms, churches, driving schools |
| `school` | **School** | primary, secondary, vocational |
| `university` | **University** | higher education |
| `childcare` | **Kindergarten** | kindergartens, daycare |

**This collapse decides which assignment choices matter.** A distinction *within* a group is descriptive only — whether a gym is `sports` or `leisure` changes nothing downstream. A distinction *across* groups changes the result: whether a restaurant is `leisure` (Leisure) or `errands` (Retail_Daily) does. When reviewing or extending the rules, spend the effort on the cross-group calls.

Two consequences worth stating for interpretation:

- **`errands` routes to Retail_Daily** — *Einkauf täglicher Bedarf*. Hospital, bank and post-office visits therefore land in the daily-shopping column. That conflation comes from the 7 columns the zone data supplies, not from the rules.
- **Both retail columns are fed only by real shop tags.** Generic ALKIS "Handel und Dienstleistungen" codes deliberately claim no retail. Earlier they supplied 84 % of all `retail_non_daily` buildings (9,777 of 11,622) versus 1,832 from actual shop tags, so the Retail_Non-Daily budget spread over ~5.9× more buildings than Retail_Daily purely as an artefact.

Each building also gets one **Bosserhof class** (e.g. `normal office`, `discount stores`, `schools`) supplying a worker-density weight (workers per 100 m³) for redistribution. Anything with a Bosserhof class also carries `work`, added centrally — the class *is* a worker-density rating, so the building is staffed by definition, whatever visitor-facing activities it also has.

---

## Running the Tests

The test suite covers all pipeline logic and runs in under two seconds:

```bash
pytest tests/ -v
```

**156 tests, all passing.**

| Test file | Tests | What it covers |
|---|---|---|
| `test_01_geometry.py` | 8 | Volume computation, deduplication, volume filtering |
| `test_03_poi_cleaning.py` | 7 | POI exclusion rules, address normalisation |
| `test_05_poi_building_merge.py` | 6 | Spatial join, nearest-neighbour fallback |
| `test_06_rule_based.py` | 120 | `classify_building()` on real sampled rows, a static self-check of every rule table, and regression tests pinning each deliberate decision — see below |
| `test_07_redistribution.py` | 15 | Zone-to-building redistribution, Bosserhof weight lookup |

`test_06_rule_based.py` is where the classifier's decisions are held in place. Beyond the real-sample checks it pins: the ALKIS code table (exclusions, the *Schloss*/"Lock" mistranslation, agreement within the religious and public families), the land-use refinement and its confinement to one code, the `work` invariant, layer precedence including the `kindergartens` (2.30) vs `services` (2.31) override that strict precedence prevents, `;`-composite tag splitting, farm-building exclusions, and multi-POI reconciliation. Each of those is a choice that would otherwise be easy to undo by accident.

It reads `tests/data/sample_condensed_buildings.parquet` — rows sampled across 10 signal buckets, including the two ALKIS codes that between them cover 85 % of the dataset, so the fixture exercises the dominant paths rather than only the interesting minority ones. Regenerate after running Notebook 05 on new data:

```bash
python tests/create_classifier_test_sample.py
```

---

## Output Files

All outputs are written to `data/output/` (≈1.96 GB total for this study area):

| File | Produced by | Size | Description |
|---|---|---|---|
| `area_of_study_clipped.pbf` | Notebook 02 | 58 MB | PBF clipped to the study boundary |
| `01_all_pois.gpkg` | Notebook 02 | 26 MB | All OSM POIs in the study area |
| `01_all_buildings_osm.gpkg` | Notebook 02 | 164 MB | OSM building footprints for ALKIS gap-filling |
| `03_osm_pois_modified.gpkg` | Notebook 03 | 17 MB | Normalised, deduplicated POIs |
| `01_building_volumes_filtered.gpkg` | Notebook 01 | 350 MB | Cleaned buildings with computed volumes |
| `04_enriched_building_volume_data.gpkg` | Notebook 04 | 446 MB | Buildings with all spatial-join attributes |
| `05_condensed_buildings_with_pois.gpkg` | Notebook 05 | 325 MB | One row per building with merged POI attributes — classifier input |
| `06_classified_buildings.gpkg` | Notebook 06 | 291 MB | Every building with `mid_label`, `bosserhof_class`, and which rule layer resolved it (282,017 of 574,435 classified — 49.1 %) |
| `07_building_level_redistributed.gpkg` | Notebook 07 | 133 MB | Per-building allocated activity demand |
| `07_redistribution_allocation_log.csv` | Notebook 07 | 13 MB | Per-allocation audit trail |
| `07_redistribution_validation.csv` | Notebook 07 | 0.1 MB | Zone-level conservation check |
| `08_final_results.gpkg` | Notebook 08 | 134 MB | Final dataset: buildings + zones as two layers |

---

## Adapting to a New Region

1. Replace files in `data/input/` with your region's data (see [Input Data](#input-data) table).
2. In [`config.py`](config.py), update:
   - `TARGET_CRS` — coordinate reference system for your region
   - `ZONE_COLUMN_MAP` — map your zone file's columns to the 7 activity categories
   - File path constants if your input files have different names
3. If your region uses a different cadastral building system, update the codelist in `data/reference/`, then add a row to `ALKIS_RULES` in `rule_utils.py` for each code that occurs. Codes absent from the table fall through to the OSM layer rather than being guessed, so an incomplete table degrades gracefully — see which codes you actually need with:

   ```bash
   python scripts/rule_smoke_test.py --alkis     # what the table currently covers
   ```

4. Run the notebooks in dependency order: **02, 03, 01, 04, 05, 06, 07, 08** (then 09–10 if you have an annotated validation sample and the pinned building file).

No notebook code needs to be edited.

### Where the rules live

| To change… | Edit |
|---|---|
| what an OSM POI tag means | `AMENITY_RULES` / `SHOP_RULES` / `TOURISM_RULES` / `BUILDING_TAG_RULES` in `rule_utils.py` |
| what an ALKIS code means | `ALKIS_RULES` in `rule_utils.py` — one row per code, with its German label and building count as a comment |
| the land-use refinement | `LANDUSE_BOSSERHOF_REFINEMENT` in `rule_utils.py` |
| worker densities, activity taxonomy, zone column names | `config.py` |

---

## Licence

Source code, notebooks and documentation are released under the [MIT Licence](LICENSE).

The **input data is not covered** and is not distributed here: ALKIS cadastral data is licensed by the responsible state survey authority, OpenStreetMap extracts are © OpenStreetMap contributors under the ODbL, and the zone-level activity targets were provided by Regionalverband Großraum Braunschweig. See [`LICENSE`](LICENSE) for details.

---

## Citation

See [`CITATION.cff`](CITATION.cff) for machine-readable citation metadata (used by GitHub's "Cite this repository" feature).

---

## Acknowledgements

This work is part of the **TRANSFORMPATHS** project, funded by the Federal Ministry of Research, Technology and Space (BMFTR) within the framework of "Research for Sustainability" (FONA), under grant number **01UV2574A**.

The author thanks [Regionalverband Großraum Braunschweig](https://www.regionalverband-braunschweig.de/) for data provision.

---

## Contact

**Mayur Patel**
Institute of Transportation and Urban Engineering, TU Braunschweig
m.patel@tu-braunschweig.de · Tel.: +49-531-391-66809
