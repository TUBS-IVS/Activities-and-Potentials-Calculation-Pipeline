# Rules vs LLM on the same buildings (notebooks 11–12, step 13)

The companion `final-pipeline` branch of this repository (called **FINAL** below) classifies buildings with a large
language model (gpt-oss-120b) instead of tag rules. Steps 11–13 answer one question: **on the same buildings, scored
against the same truth, how much does the LLM gain over the deterministic rule engine?**

The rule engine is not changed for this: `rule_utils.py` runs with its own tables and weights, on FINAL's buildings and
POIs. FINAL is only ever read, never written.

- [Setup: FINAL next to this repository](#setup-final-next-to-this-repository)
- [Step 11 — the rule engine on FINAL's data](#step-11--the-rule-engine-on-finals-data)
- [Step 12 — scoring against FINAL's validation](#step-12--scoring-against-finals-validation)
- [Step 13 — a new, blind validation](#step-13--a-new-blind-validation)
- [What the two validations say together](#what-the-two-validations-say-together)

---

## Setup: FINAL next to this repository

Steps 11–13 read FINAL's outputs from a sibling folder (`FINAL_DIR` in [`config.py`](../config.py)):

```
GitHub/
├── Capacity_Calculation-pipeline-RULES/    ← this branch (Rules-based-pipeline)
└── Capacity_Calculation-pipeline-FINAL/    ← the final-pipeline branch, already run
```

For example, from inside this repository:

```bash
git worktree add ../Capacity_Calculation-pipeline-FINAL final-pipeline
```

FINAL must have been run through its classification (step 06) and its validation (notebook 09). The files read are
listed in `config.py` under *RULES ON THE FINAL PIPELINE'S DATA*:

| FINAL file | Used for |
|---|---|
| `data/output/04_buildings_enriched.gpkg` (layers `buildings`, `building_pois`) | the buildings and which POIs sit on them |
| `data/output/01_all_pois.gpkg` (layer `pois`) | every OSM tag of each POI |
| `data/output/06_buildings_classified.gpkg` | the LLM's answers |
| `data/experimental_extract/09_validation.gpkg` (layer `units`) | the validated places and their truth |
| `config.py`, `lib/validation.py` | FINAL's class catalogue, label maps and scoring functions — both classifiers are scored by FINAL's own code |

If FINAL lives elsewhere, edit `FINAL_DIR`.

---

## Step 11 — the rule engine on FINAL's data

[`notebooks/11_rules_on_final.ipynb`](../notebooks/11_rules_on_final.ipynb) → `data/output/11_rules_on_final.parquet`

Runs `classify_building()` on the **39,786 buildings** FINAL's step 04 kept (38,186 ALKIS, 1,600 OSM gap-fill), keyed on
FINAL's `building_id` so every answer joins one-to-one to the LLM's. The translation of FINAL's data into the engine's
input was fixed before any score was looked at:

1. **POI tags.** Every key the engine reads (`amenity`, `shop`, `tourism`, `building`, `information`, and `office` /
   `craft` / `social_facility` as `additional_information`) comes from FINAL's POI table. FINAL's own POI filters stand.
2. **Two runs.** `sites` (main): the POIs placed on the building *plus* the site polygons it lies in (campus, plant,
   estate) — the same evidence the LLM sees. `own`: POIs on the building only, close to how the engine was fed in this
   pipeline.
3. **Order.** Where the engine has to pick one value, the building's main occupant wins: own POIs before sites, a larger
   share before a smaller one, POI id as tie-break.
4. **Building fields.** ALKIS code, OSM footprint tag and land use from FINAL's step 04. Three codes on 350 buildings
   have no ALKIS rule (agricultural, road-traffic operations, barracks), because this pipeline removes them before
   classifying; here they are decided by POI tags, footprint tag or land use.
5. **Nothing else.** No names, no sizes, no change to a rule or a weight.

The evidence is therefore close but not identical: the LLM also reads names, the city, footprint size, height and the
ALKIS land use; the engine reads every tag key of a POI where the LLM's record shows one.

---

## Step 12 — scoring against FINAL's validation

[`notebooks/12_rules_vs_llm.ipynb`](../notebooks/12_rules_vs_llm.ipynb) — tables only, no output file.
[`scripts/12_rules_vs_llm_workbook.py`](../scripts/12_rules_vs_llm_workbook.py) writes the same comparison, place by
place, to `data/output/12_rules_vs_llm_side_by_side.xlsx` for reading.

Both classifiers are scored on the same **1,101 validation units**, against the same truth, by FINAL's own scoring code
(the LLM figures reproduce FINAL's notebook 09 exactly). Differences are tested pairwise: exact McNemar for the
Bosserhof class, a paired bootstrap (2,000 resamples, seed 42) for the activity F1.

| | LLM (FINAL 06) | Rules, sites (main) | Rules, own POIs | LLM − rules (main) |
|---|---|---|---|---|
| Bosserhof, exact class (1,025 units) | **64.8 %** | 59.6 % | 58.1 % | 159 vs 106 units right only by one · **p = 0.0014** |
| Bosserhof, right main group | 78.5 % | 76.6 % | 75.5 % | p = 0.19 |
| Activities F1, old label merge (1,034 units) | 67.1 % | 65.4 % | 64.1 % | +1.6 pts [−0.4, +3.7] · p = 0.12 |
| Activities F1, FINAL's label map | 71.2 % | **72.6 %** | 71.1 % | −1.3 pts [−3.7, +1.0] · p = 0.26 |

**Read with care: this truth is not neutral.** It is a human check of the *original* pipeline's LLM answers, made with
the same model. Where the validator accepted the old answer (845 of 1,025 Bosserhof units) the truth *is* that answer,
and the LLM's whole lead sits there (73.0 vs 65.8 %, p < 0.001). Where the validator rejected it (180 units) the rules
are ahead, 30.6 vs 26.1 %, but not significantly (p = 0.29).

Other findings:

- **Offsetting categories.** The LLM is clearly better on Retail_Non-Daily (F1 0.74 vs 0.63 — the rules find only half,
  mostly name-only shops); the rules are better on Leisure. Both over-predict Retail_Daily (precision 0.24), mostly
  through `errands` → Retail_Daily.
- **Sites help the rules** a little but significantly: +1.5 exact points, +1.4 F1 points.
- **The sample is POI-heavy.** POI tags decide 77 % of the scored units but only 43 % of the region's buildings. On the
  units the ALKIS code decides, both are weak and level (exact 41.2 vs 38.2 %), so this sample says little about half
  of the region.
- **Across all 39,786 buildings** (no truth involved) the two give the same class on 50 % and the same main group on
  67 %. The largest disagreements are the rules' generic `services` against the LLM's `normal office`, `retail small
  scale` and `customer oriented services` — two of those three inside the same main group.

---

## Step 13 — a new, blind validation

Because the step-12 truth leans on old LLM answers, the same places were judged again, **blind**, in FINAL's own label
and class scheme. Three scripts carry it; all write to `data/output/13_new_validation/` (git-ignored):

| Script | Does |
|---|---|
| [`13_new_validation_prepare.py`](../scripts/13_new_validation_prepare.py) | writes the judging guide (`guide.md`: FINAL's label and class definitions verbatim, plus rulings for frequent cases) and 30 batches of places to judge. A batch holds only the evidence — the record the LLM saw, the other OSM tags of the POIs, the address — and no answer of either pipeline or the old truth. 60 places appear twice, under another id in another batch, to measure agreement between judges. |
| [`13_new_validation_review.py`](../scripts/13_new_validation_review.py) | collects the blind judgments (`blind.json`), measures how often the 60 repeated places agree (`reliability.json`), and writes review files: for each place where an answer falls outside the blind judgment, the evidence, the judgment and the two answers — anonymous and in a fixed random order. |
| [`13_new_validation_workbook.py`](../scripts/13_new_validation_workbook.py) | merges blind judgments and review into `truth.json`, scores both classifiers against it and writes `data/output/13_new_validation_side_by_side.xlsx`. |

**The judges are AI agents (Claude), not people.** Thirty judge agents each judged about 37 places blind, with web
search for unclear or possibly changed places. Review agents then saw both classifiers' answers, anonymised, and could
add an answer to the accepted classes or labels only where a careful validator would accept it. The judging and review
were run as agent workflows outside this repository; the scripts above prepare their inputs and process their outputs.

The new truth holds, per place, the class judged best plus classes also accepted, and the labels required plus labels
optional (an optional label is neither credited nor counted wrong).

| Against the new truth | LLM | Rules (sites) | Paired test |
|---|---|---|---|
| Bosserhof, exact class (1,014 places) | **90.1 %** | 77.4 % | 175 vs 46 places right only by one · p < 0.001 |
| Bosserhof, right main group | **93.5 %** | 83.6 % | p < 0.001 |
| Activities F1, 11 MiD labels (1,035 places) | **88.7 %** | 82.3 % | +6.4 pts [+4.2, +8.6] · p < 0.001 |
| Activities F1, high-confidence places only (713) | 91.2 % | 88.8 % | +2.4 pts |

The rules' weakest labels are `sports` (recall 0.29), `meetup` (0.62) and `retail_non_daily` (0.79); on `retail_daily`
and `leisure` they score higher than the LLM.

**How good the new truth is.** The 60 places judged twice by different judges got the same best class 90 % of the time,
each other's best class accepted 93 %, and the same required labels 93 %. Judges' confidence: high on 713 places,
medium 171, low 151. Of 546 places where an answer fell outside the blind judgment, review changed 61 (accepting the
LLM's class at 14, the rules' at 17).

**Read with care: this truth has its own lean.** It was not seeded by either classifier's answers, but:

- the judge is itself a language model, so LLM-shaped readings of the evidence may be favoured;
- it judges in FINAL's own definitions, which the LLM was prompted with — the rules use their own taxonomy and map to
  it;
- it had web search, i.e. more evidence than either classifier, and no imagery.

---

## What the two validations say together

| | Step 12 (human check of old LLM answers) | Step 13 (blind AI re-judgment) |
|---|---|---|
| Bosserhof exact — LLM vs rules | 64.8 vs 59.6 % | 90.1 vs 77.4 % |
| Bosserhof main group | 78.5 vs 76.6 % (n.s.) | 93.5 vs 83.6 % |
| Activities F1, FINAL's six categories | 71.2 vs 72.6 % (n.s.) | 89.7 vs 91.6 % |

On the coarse question that matters most for redistribution — *which of the six zone activities does a building
serve?* — the rule engine is level with the LLM under both truths (slightly ahead in both, significantly in neither:
step 12 tested it, step 13 does not test this collapsed view). The LLM's advantage is in the **fine Bosserhof
class** and in the labels that only a business name can reveal (non-daily retail, sports, meetup). That matches the
mechanism found in [validation.md](validation.md#why-the-gap--the-mechanisms): the rules lack world knowledge about
names, not knowledge about tags.

A fully neutral verdict still needs human truth that neither classifier seeded, and repeated LLM runs (the LLM
answered each building once, so its run-to-run spread is not in these numbers).
