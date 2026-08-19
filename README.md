# LLM vs Rule-Based Building Classification — `experiment` branch

> **Institution:** [Institute of Transportation and Urban Engineering](https://www.tu-braunschweig.de/isv), TU Braunschweig
> **Author:** Mayur Patel

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/)

---

## What this branch is for

One question: **for classifying buildings into activity types, does an LLM beat a
deterministic rule engine?**

Both classifiers are run over the same 889 human-verified buildings and scored by the
same code, so the numbers are directly comparable.

| | reads | how it decides |
|---|---|---|
| **rule engine** (`rule_utils.py`) | structured tags + ALKIS codes | hand-written lookup tables. Cannot use business names — no rule can act on free text. |
| **LLM** (`llm_utils.py`) | all 16 evidence columns, names included | `gpt-oss-120b` via the TU KI-Toolbox API, one building per request |

The LLM is given business names and the rule engine is not. That asymmetry is the
point: names are what a language model's world knowledge can exploit and a rule table
cannot, and the comparison exists to price that difference.

Each building gets two labels:

- **activities** — a set drawn from 7 zone types (`Workers`, `Retail_Daily`, …)
- **bosserhof_class** — exactly one of 47 building-use classes, used for capacity estimation

---

## Running it

```bash
pip install -r requirements.txt
echo "TU_KI_TOOLBOX_TOKEN=..." > .env
```

| step | notebook | time |
|---|---|---|
| build the validation set | `06_validation_prep` | ~2 min |
| classify with the rule engine | `07_rule_based_validation` | seconds |
| classify with the LLM | `08_llm_validation` | 889 API calls, ~2 h |
| score whichever arms have run | `09_validation_scoring` | seconds |
| measure LLM reproducibility | `10_llm_reproducibility` | 889 × N calls |
| the accuracy section + its workbook | `11_accuracy` | seconds |

Notebooks 07 and 08 each write two files: a `*_predictions.parquet` for the scorer, and
a **`*_comparison.csv` laid out for reading by eye** — one row per building with the
earlier model's answer, the validator's verdict, the resulting truth and this arm's
prediction all side by side, evidence text last.

Notebook 09 scores every arm it finds, so it works with one arm or both.

---

## Results

`11_accuracy` is the whole accuracy section, and writes
`data/validation/11_accuracy_results.xlsx`. It scores the buildings that carry an OSM
POI name — 655 for Bosserhof, 663 for activities — because those are the ones a human
can review by eye, and the model was given the names. Named buildings are the easier
half, so these figures describe the arms on reviewable buildings, not on the region.

| | rule engine | LLM (5 runs) |
|---|---|---|
| **bosserhof accuracy** | **57.7%** (378/655) | **78.5%** (514/655) |
| activities precision | 83.1% | 83.9% |
| activities recall | 82.9% | 82.3% |
| **activities F1** | **83.0%** | **83.1%** |
| activities exact set match | 54.6% | 56.3% |

The LLM's edge is **entirely on Bosserhof class** — +20.8pp, far outside both Wilson
intervals — and that is what business names buy: the rule engine's own docstring records
that ALKIS code `31001_2000` covers 42.6% of the study area and cannot be split further
from the code alone. On activity **sets the two arms are tied**, 83.1 vs 83.0 F1, a gap
smaller than the LLM's own run-to-run margin.

Three findings that came out of the 5 repeats:

* **Re-running does not change the picture.** Activity F1 varies 0.4pp across runs
  against a ±1.8pp bootstrap CI from the sample size — the sampling error is 9× wider.
  Bosserhof single-run accuracy spans 2.1pp.
* **`Retail_Daily` is over-predicted by both arms** (+226% LLM, +251% rule; 63 true
  buildings, ~206 predicted) and is 75% of all LLM false positives. Two independent
  methods failing the same way points at the daily/non-daily label boundary, not at
  either classifier.
* **A hand review of the 253 buildings where the repeats disagreed with the sheet
  accepted 169 of them**, lifting Bosserhof to 88.1% (580/658). That review is
  one-sided — only disagreements were examined — and on comparable rows it rejected
  13.6% of labels the sheet had endorsed, so treat it as a bound, not an estimate.

The pre-filled labels score 86.9% on the same rows, but that number is **definitional**:
green *means* the pre-filled label was correct, so it cannot be compared with the arms.

---

## Three things that will bite you

### 1. `gml_id` is a positional row index and means nothing across runs

Notebook 05 ends with `gdf['gml_id'] = gdf.index`. Rerunning preprocessing renumbers
every building — 578,080 then, 574,435 now. A join on `gml_id` against a different run
**succeeds** for ~95% of rows and every one of them is a different building.

The fix is `source_gml_id`: the ALKIS cadastral id, or `osm_<id>` for OSM-only rows.
It comes from the source registers rather than our row ordering, so it is stable.

Notebook 06 recovers it **through geometry**, which never moved — one spatial join:

```
workbook gml_id → frozen-run footprint → representative point
                → which current-run building contains it → its source_gml_id
```

All 889 resolve, none ambiguous. The validation set then carries exactly two ids:

| column | what it is | use it for | stable? |
|---|---|---|---|
| `gml_id` | the workbook's row id | identity **inside** the validation set | ❌ no |
| `source_gml_id` | register id of the current-run building | **joining** to pipeline output | ✅ yes |

Both are needed. `source_gml_id` is the only safe join key, but it is **not unique**
across these rows — 13 of them share 6 buildings, because notebook 05 merges footprints
that were annotated separately. Keying on it alone would silently collapse 889
annotations into 882, and two of those groups hold *conflicting* human verdicts, so
merging would mean discarding one of them arbitrarily.

### 2. The annotation workbook was seeded by an earlier LLM run

It arrived pre-filled with that run's answers; the reviewer ticked or corrected them.
So on rows the reviewer ticked green, the truth **is** an LLM answer:

| | green (truth = the earlier answer) | red (reviewer typed it) |
|---|---|---|
| n (Bosserhof) | 719 | 158 |
| what a high score there means | the model reproduced itself | genuine |

Green is an upper bound and red a lower bound for any LLM — never an estimate. Notebook
09's last cell reports the split rather than averaging over it. Measured:

| arm | green | red |
|---|---|---|
| rule | 0.609 | 0.127 |
| llm | 0.808 | 0.089 |

### 3. The LLM is not reproducible run to run

Asked the same question twice about the same building, the model does not reliably give
the same answer, and the flips cross headline categories rather than neighbouring
subcategories. That means **any single-run accuracy figure is one draw from a
distribution**, and a gap between two arms can be smaller than one arm's own spread.

`10_llm_reproducibility` measures it directly: N runs per building, side by side in one
sheet, with per-run accuracy, an all-agree rate and a majority vote.

---

## Layout

```
config.py               all paths and settings; edit here to move region
rule_utils.py           the deterministic classifier
llm_utils.py            prompt, API transport, per-row driver
validation_utils.py     ground-truth decoding, metrics, the comparison sheet

notebooks/01-05         preprocessing: geometry, POIs, enrichment, condensing
         06            decode the annotation workbook -> the validation set
         07            rule engine on the validation set
         08            LLM on the validation set
         09            score every arm that has been run
         10            LLM reproducibility across N repeats
         11            the accuracy section: both arms, both metrics, one workbook

data/validation/
  sample_version_1.xlsx   the hand-annotated workbook — THE irreplaceable input
  06_validation_set.csv   everything else is derived from it and regenerable
```

**Run order for preprocessing is `02 → 03 → 01 → 04 → 05`**, not `01 → 05`. Notebook 01
reads notebook 03's output and silently disables POI-aware merging if it is absent.

---

## Notes

- Notebook 06 needs `config.VALIDATION_BUILDINGS_FILE`, the frozen condensed file from
  the original run. It lives **outside this repo**, is read-only, and is not
  distributed. It is the only file the workbook's positional ids can be resolved
  against; notebook 06 asserts on `volume_m3` agreement and refuses to proceed if it is
  pointed at the wrong one.
- Notebooks 08 and 10 checkpoint as they go, so an interrupted run resumes instead of
  re-paying for completed calls. **Delete the checkpoint to force a fresh run** — which
  you must do after changing `llm_utils.SYSTEM_PROMPT`, or the file will mix answers
  from two different prompts under one accuracy number.
- `LLM_MAX_WORKERS = 1` by default. The endpoint's rate limit is undocumented and the
  retry path treats HTTP 429 like a network error, so raise it only after asking.
