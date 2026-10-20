# Validation against a hand-annotated sample (notebooks 09–10)

`data/validation/` holds a real, hand-annotated accuracy check — not a synthetic benchmark. Notebook 09 decodes it into
a ground-truth table; notebook 10 runs the rule engine and scores it. This page explains how the ground truth was made,
what it can and cannot show, and what the scores mean. For the head-to-head comparison with the LLM classifier, see
[rules-vs-llm.md](rules-vs-llm.md).

- [The annotation](#the-annotation)
- [The annotation workbooks](#the-annotation-workbooks)
- [What is compared against what](#what-is-compared-against-what)
- [Why the scored input is pinned](#why-the-scored-input-is-pinned)
- [How the annotation resolves](#how-the-annotation-resolves)
- [Two dimensions, two metrics](#two-dimensions-two-metrics)
- [Rule-engine scores](#rule-engine-scores--measured-held-out)
- [Which activities are invented, and which are overlooked](#which-activities-are-invented-and-which-are-overlooked)
- [Accuracy conditioned on the information available](#accuracy-conditioned-on-the-information-available)
- [Why the gap — the mechanisms](#why-the-gap--the-mechanisms)
- [A note on not tuning to the benchmark](#a-note-on-not-tuning-to-the-benchmark)
- [Known ground-truth defects](#known-ground-truth-defects)

---

## The annotation

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

The metric definitions live in [`validation_utils.py`](../validation_utils.py) so they are unit-testable and cannot drift from the notebook.

## The annotation workbooks

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

## What is compared against what

> **The rule engine is scored against the HUMAN label — never against a model's prediction.**

This needs stating precisely, because of how the workbook was built. The spreadsheet arrived pre-filled with an **earlier LLM run's** predictions. A 🟩 green cell means the human *read that answer and affirmed it*, so the human label equals the LLM's output on those rows. A 🟥 red cell carries the value the human *typed themselves*. Both are human labels; affirmation is a judgement, not the absence of one.

What that construction *does* invalidate is scoring **the LLM** against this ground truth: on green rows it matches by definition, so its "accuracy" is arithmetically the green fraction. No LLM figure is presented here as comparable.

The rule engine has no such circularity — it never saw the workbook, and no rule table was written against it. Notebook 09 strips every pre-fill and prediction column out of the ground truth and asserts their absence, so notebook 10 has no model prediction available to compare against even in principle.

**A limitation to carry into the write-up:** because the human reviewed LLM output rather than labelling from scratch, any tendency to accept a plausible-looking answer is baked into the ground truth, and the rule engine is measured against labels partly shaped by that review. Only a freshly labelled blind sample removes this.

## Why the scored input is pinned

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

## How the annotation resolves

Notebook 09 turns the workbook into a scoreable table. The decisions it has to make are not mechanical, and each is recorded per row so the denominator is always explainable:

| Dimension | scoreable | excluded | why excluded |
|---|---|---|---|
| **activities** | **882** | 509 | 337 uncertain · 159 unvalidated · 13 flagged wrong but never corrected |
| **bosserhof** | **874** | 517 | 337 uncertain · 159 unvalidated · 13 uncorrected · 8 ambiguous (validator named several classes) · plus 7 recovered from free text and 3 kept verbatim |

Three cases needed real handling rather than a `literal_eval`:

- Many activity corrections have quoting damage (`['Retail_Non-Daily]`, `['Workers'; Retail_Non-Daily']`). Parsing matches tokens against the closed 7-name vocabulary instead, which reads those fine.
- **13 rows** were corrected to *living* / *residential*, meaning "no activity here". That is a **real, scoreable ground truth of the empty set** — and the clearest false positives in the sample. Discarding them as unparseable would have hidden exactly the rows that measure over-prediction.
- **8 bosserhof corrections name two or more classes** (`kindergartens public facilities`). No single truth exists, so they are excluded as ambiguous — detected structurally, by counting known class names inside the string, not from a hand-written list.

## Two dimensions, two metrics

- **Activities** is a multi-label set, so precision and recall are reported **separately**. They are not interchangeable: **over-prediction misallocates** zone capacity onto a building with no claim to it, while **under-prediction removes** the building from that activity's redistribution entirely. Notebook 10 micro-averages over label *instances* — a building that invents two activities contributes two false positives.
- **Bosserhof class** is a single label, so plain accuracy. An empty truth (`""`, "no class") matches a prediction of `None`: a correct refusal counts as correct.

## Rule-engine scores — measured, held out

**Activities** (882 buildings, micro-averaged over 1,526 label instances):

| Metric | Value |
|---|---|
| **Precision** | **84.5 %** (TP = 1,198, FP = 220) |
| **Recall** | **78.5 %** (TP = 1,198, FN = 328) |
| F1 | 81.4 % |
| Exact set match | 54.3 % (479 / 882) |

Error direction: 479 exact · 116 over-prediction only · 186 under-prediction only · 101 both.

**Bosserhof class** (874 buildings): **50.3 %** accuracy (440 correct). Excluding the 4 buildings whose true class no rule can emit: **50.6 %** (440 / 870).

## Which activities are invented, and which are overlooked

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

## Accuracy conditioned on the information available

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

## Why the gap — the mechanisms

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

## A note on not tuning to the benchmark

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

## Known ground-truth defects

Four buildings in the scored set carry a true class no rule can ever produce — a vocabulary limit, not a rule error. Notebook 09 lists them and notebook 10 reports accuracy with and without them:

| gml_id | Human label | Why unproducible |
|---|---|---|
| 550941 | `garbage collection` | not a Bosserhof class |
| 231906 | `factory outlet centers` | valid class, but no rule emits it |
| 345680 | `better school` | not a Bosserhof class — a school sports hall; likely meant `schools` |
| 556702 | `fraternity` | not a Bosserhof class |

Seven of the 47 defined Bosserhof classes are unreachable — no rule in `rule_utils.py` emits them: `craft courtyards`, `crafts and trades`, `customer service`, `factory outlet centers`, `retail wholesale`, `self service department stores`, `suppliers for car dealerships`.
