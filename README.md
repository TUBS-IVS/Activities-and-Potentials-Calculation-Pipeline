# LLM vs Rule-Based Building Classification — `experiment` branch

> **Institution:** [Institute of Transportation and Urban Engineering](https://www.tu-braunschweig.de/isv), TU Braunschweig
> **Author:** Mayur Patel

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-279%20passing-brightgreen)]()

---

## What this branch is for

One question: **for classifying buildings into activity types, does an LLM beat a
deterministic rule engine?**

Both classifiers are run over the same 885 human-verified buildings and scored by the
same code, so the numbers are directly comparable.

| | reads | how it decides |
|---|---|---|
| **rule engine** (`rule_utils.py`) | structured tags + ALKIS codes | hand-written rules. Cannot use business names — no rule can act on free text. |
| **LLM** (`llm_utils.py`) | all 16 evidence columns, names included | `gpt-oss-120b` via the TU KI-Toolbox API, one building per request |

The LLM is given business names and the rule engine is not. That asymmetry is the
point: names are what a language model's world knowledge can exploit and a rule table
cannot, and the comparison exists to price that difference. The rule engine's blindness
to names is its limitation, not a handicap the LLM should adopt.

Each building gets two labels:

- **activities** — a set drawn from 7 MiD types (`Workers`, `Retail_Daily`, …)
- **bosserhof_class** — exactly one of 47 building-use classes, used for capacity estimation

---

## Running it

```bash
pip install -r requirements.txt          # add -r requirements-preproc.txt only to rerun 01-05
cp .env.example .env                     # add TU_KI_TOOLBOX_TOKEN
pytest -q                                # 279 tests, no credentials or data needed
```

Then:

| step | notebook | time |
|---|---|---|
| classify with the LLM | `06b_llm_classification` | 885 API calls |
| score both arms | `10_validation_scoring` | seconds |

The rule engine is not run from a notebook for scoring — `10` calls `classify_building`
in-process over the same rows, so both arms share the function and never a file.

`scripts/llm_smoke_test.py --n 2` makes two real calls and catches configuration faults
before you commit to a long run.

---

## Two things that will bite you

**1. `gml_id` is a positional row index, so the validation set is welded to one file.**

Notebook 05 ends with `gdf['gml_id'] = gdf.index`. Rerunning preprocessing renumbers
every building. Measured against the annotation workbook:

| classifier input | ids resolve | volume agreement |
|---|---|---|
| freshly regenerated `05` output | 1,312 / 1,391 | **0** |
| `config.VALIDATION_BUILDINGS_FILE` (frozen) | 1,391 / 1,391 | **100.00%** |

A regenerated file joins cleanly and compares unrelated buildings. So the benchmark
reads the frozen file, which lives **outside this repo** and is not distributed.
Notebook 10 refuses to score if the volumes disagree.

*Fix for the future: keep the real ALKIS `gml_id` instead of overwriting it, and mint
content-based ids for OSM-added rows.*

**2. The annotation workbook was seeded by an earlier LLM run.**

It arrived pre-filled with that run's answers; the reviewer ticked or corrected them.
So on rows the reviewer ticked ("green"), the truth **is** an LLM answer:

| | green (truth = the earlier answer) | red (reviewer typed it) |
|---|---|---|
| n (Bosserhof) | 719 | 155 |
| what a high score there means | the model reproduced itself | genuine |

Green is an upper bound and red a lower bound for any LLM — never an estimate. Notebook
10 reports both and measures the self-consistency directly.

`scripts/make_unbiased_sample.py` builds the way out: 200 buildings to be labelled from
raw evidence with no classifier output visible. `12_unbiased_validation` scores it.

---

## Results

Rule engine, on the 885-building validation set:

| dimension | metric | value |
|---|---|---|
| activities | precision / recall | 0.845 / 0.785 |
| activities | exact set match | 0.543 |
| bosserhof | accuracy | 0.503 |

**Always read a precision figure next to its floor.** A classifier that ignores its
input and always answers `{Workers}` scores **0.964** precision, because activity
precision rewards predicting less. Notebook 10 computes three such constant baselines
for exactly this reason.

LLM results are pending the run in `06b`.

---

## Layout

```
config.py               all paths and settings; edit here to move region
rule_utils.py           the deterministic classifier
llm_utils.py            prompt, API transport, per-row driver
validation_utils.py     the metrics — precision/recall, accuracy, Wilson intervals

notebooks/01-05         preprocessing: geometry, POIs, enrichment, condensing
         06            rule-based classification
         06b           LLM classification (the benchmark)
         07-08         redistribution and final results
         09            decode the annotation workbook -> ground truth
         10            score every arm
         12            score the unbiased sample (once annotated)

data/validation/        the benchmark: workbook, ground truth, scores
tests/                  279 tests; run without credentials or input data
```

**Run order is `02 → 03 → 01 → 04 → 05`**, not `01 → 05`. Notebook 01 reads notebook 03's
output and silently disables POI-aware merging if it is absent.

---

## Notes

- `data/validation/09_ground_truth.parquet` is committed and should be reused, not
  regenerated. Notebook 09 asserts on unrecognised activity spellings by design; a
  regenerated truth table risks differing from the one the published numbers used.
- The LLM stage checkpoints every 25 rows and errors never enter the checkpoint, so
  re-running `06b` retries exactly the failures and resumes otherwise.
- `LLM_MAX_WORKERS = 1` by default. The endpoint's rate limit is undocumented and the
  retry path treats HTTP 429 like a network error, so raise it only after asking.
