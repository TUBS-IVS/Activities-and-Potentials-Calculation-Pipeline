# Reproducibility

## Code version

This is Version 1 of the pipeline, tagged `v1.0.0`; cite the tag, which gives a fixed state of the code that later
changes cannot alter. The results in the paper were produced with the code at commit
[`b751cd9a6c8a74886ae82bc00df5fe6b7402641c`](https://github.com/TUBS-IVS/Activities-and-Potentials-Calculation-Pipeline/commit/b751cd9a6c8a74886ae82bc00df5fe6b7402641c).
The one exception is the text of the building records the LLM answered (`05_llm_input.parquet`), which was written
before a final change to step 04's `share_in_building` rule; see [What was checked](#what-was-checked).
`v1.0.0` differs from that commit only in documentation, code comments, a few descriptive strings in `config.py`,
notebook text and saved outputs, the added reference tables of step 04, the figure, the licence and citation files
and `.gitignore`; no code cell and no calculation changed.

The repository history was rewritten on 27 October 2026 to remove values derived from the restricted zone totals
from code comments and saved notebook outputs; no calculation changed. Commit IDs from before that date, such as
`60469fa` for the code behind the paper, are no longer valid.

Notebooks 01–07 and `rules/classify_buildings.ipynb` keep the saved outputs of the stored run, with local paths
replaced by `<repo>` and `<conda env>`, except for these cells: the setup cell and the cell that writes the
building layer in notebook 03, the cell that reports the progress of the full run in notebook 05, and sections 2–5
of notebook 07, which were run on the machine that made the model calls (notebook 07 keeps the outputs of its setup
cell, section 1 and section 6, the assembly). Notebook 08 has no saved outputs, because they derive from the
restricted zone totals.

## Environment

The notebooks were run with Python 3.13; no other version was tested. The full LLM runs of steps 05 and 07 were
made with the two scripts on a separate Linux machine.

- Notebooks 01–03, 05 and `rules/classify_buildings.ipynb` ran on Python 3.13.15 (notebook metadata), with
  osmium 1.19.1 (step 01) and GDAL/ogr2ogr 3.13.3 (step 02) as printed in their outputs. The metadata of notebook 08
  also names Python 3.13.15; it has no saved outputs.
- Notebooks 04 and 06 ran on Python 3.13.5, in a separate environment with an older pandas (2.x).
- Notebook 07 records no Python version in its metadata.
- The regeneration test ([What was checked](#what-was-checked)) ran every notebook in one Python 3.13 environment
  on one Windows machine.

[`requirements.txt`](requirements.txt) lists the minimum package versions. Re-running a step in another environment
can change the bytes of a GeoPackage, and the dtypes a notebook prints, without changing the content, so compare
outputs by value, not by checksum.

## Execution order

| Step | Entry point | External service | Runtime of the notebook (regeneration test) |
|---|---|---|---|
| 01 | `pipeline/01_osm_extraction.ipynb` | — (the OSM extract is obtained by hand) | ~7 min (425 s) |
| 02 | `pipeline/02_alkis_extraction.ipynb` | downloads the 3,620 LoD2 tiles (0.44 GB) of the region from the LGLN, unless they are already in `lod2_cache/` of the input folder | ~25 min (1,504 s) with the tiles cached; writes 5.07 GB |
| 03 | `pipeline/03_alkis_refinement.ipynb` | — | ~23 min (1,406 s) |
| 04 | `pipeline/04_semantic_enrichment.ipynb` | — | ~9 min (513 s) |
| 05 | `pipeline/05_llm_classification.ipynb` (records, plan, sample), then `scripts/05_run_llm.py` (full run) | LLM endpoint | notebook ~6 min (340 s) without the sample calls; full run 34,993 calls, about 9 s per call in the stored sample; the stored full run took about 8 days |
| 06 | `pipeline/06_llm_assembly.ipynb` | — | 36 s |
| 07 | `pipeline/07_poi_classification.ipynb` sections 1–5 (records, sample), then `scripts/07_run_llm_pois.py` (full run), then section 6 of the notebook | LLM endpoint | notebook ~4.5 min (266 s) without the sample calls; full run 7,864 calls, the stored run took about 11 h |
| 08 | `pipeline/08_redistribution.ipynb` | — (needs the restricted zone totals) | ~7 min (439 s) |
| rules | `rules/classify_buildings.ipynb` (after step 04) | — | 34 s |

The runtimes are the wall times of the headless run of each notebook in the regeneration test, on one Windows
laptop; the notebook headers give the times of the stored run, which were shorter for some steps. Times depend on
the machine and the disk. Steps 01–08 and the rules notebook took about 83 minutes together, without the LLM runs.

Manual steps:

1. Obtain the inputs and place them in `data/input/` ([`DATA.md`](DATA.md)); the two reference tables of step 04 are
   already in `data/reference/`.
2. For steps 05 and 07, put the endpoint's token in the environment or in `.env` (`TU_KI_TOOLBOX_TOKEN=<your token>`),
   or adapt [`lib/llm_client.py`](lib/llm_client.py) to another endpoint (`LLM_API_URL`, `LLM_MODEL`).
3. Run the two LLM scripts on a machine that stays on, for example
   `nohup python scripts/05_run_llm.py > data/output/05_llm_run.log 2>&1 &`. Both write each valid answer as it
   arrives and skip answered ids when restarted (`--sample`, `--ids`, `--limit` and `--workers` are described in each
   script's docstring). Answers are read back only under the prompt they were made with.

## Regenerating the outputs

1. **Environment.** Create the environment of the [README](README.md#requirements): Python 3.13, the packages of
   `requirements.txt`, and `osmium-tool` and GDAL. Register the environment as a Jupyter kernel, for example
   `python -m ipykernel install --user --name capacity`, and run every notebook with it (headless:
   `--ExecutePreprocessor.kernel_name=capacity`).
2. **Inputs.** Place the inputs listed in [`DATA.md`](DATA.md) in `data/input/`, or set `CAPACITY_INPUT_DIR` to the
   folder that holds them. The reference tables of step 04 are part of the repository. Step 02 downloads the LoD2
   tiles into `lod2_cache/` of the input folder unless they are already there; the LGLN serves its current tiles,
   which may differ from those used for the paper.
3. **Zone totals.** Step 08 needs `zone_targets.gpkg` in the input folder (`ZONE_TARGETS_FILE`), which is available
   only with lawful access from the Regionalverband Großraum Braunschweig
   ([`DATA.md`](DATA.md#zone-totals-step-08)). Without it, stop after step 07 and the rules notebook.
4. **LLM access.** Steps 05 and 07 read the token from the environment variable `TU_KI_TOOLBOX_TOKEN` or from a
   `.env` file in the repository root with the line `TU_KI_TOOLBOX_TOKEN=<your token>`. The token is read at call
   time and never printed. `.env` is git-ignored: never commit it, and never write the token into a notebook,
   `config.py` or a log. For another endpoint, change `LLM_API_URL` and `LLM_MODEL` in `config.py` and adapt the
   request in [`lib/llm_client.py`](lib/llm_client.py); its answers will differ from the paper's.
5. **Order.**
   1. Notebooks 01, 02, 03 and 04.
   2. `rules/classify_buildings.ipynb`, at any time after step 04.
   3. Notebook 05: sections 1–4 write the records (`05_llm_input.parquet`) and the plan (`05_llm_plan.parquet`)
      and need no token; section 5 checks the token and asks the model for the 10 sample buildings.
   4. `python scripts/05_run_llm.py`: the full run, written to `05_llm_answers.jsonl`.
   5. Notebook 06.
   6. Notebook 07, sections 1–5: section 2 writes the records (`07_llm_poi_input.parquet`), and section 5 checks the
      token and asks the model for the 26 sample POIs.
   7. `python scripts/07_run_llm_pois.py`: the full run, written to `07_llm_poi_answers.jsonl`.
   8. Notebook 07, the setup cell, section 1 and section 6: the answers onto the POIs, written to
      `07_building_pois_classified.gpkg`. Running notebook 07 from top to bottom instead, as in the regeneration
      test, also rewrites the records of section 2 and gives the same result.
   9. Notebook 08.
6. **Headless run.** From the repository root, run each notebook in turn with

   ```bash
   jupyter nbconvert --to notebook --execute pipeline/01_osm_extraction.ipynb \
       --output-dir <folder outside the repository> \
       --ExecutePreprocessor.kernel_name=capacity --ExecutePreprocessor.timeout=-1
   ```

   Each notebook runs in its own folder and finds the repository root by itself. `--output-dir` leaves the tracked
   notebooks unchanged. Keep the executed copies outside the repository and do not publish them: they show local
   paths, and those of notebook 08 show values derived from the zone totals. Without a token, add `--allow-errors`
   for notebooks 05 and 07: only their token check and sample cells should fail (check the executed copies for any
   other error), and the steps after them need answer files (next point).
7. **Existing answer files.** To use the answers of an earlier run instead of new calls, place
   `05_llm_answers.jsonl` and `07_llm_poi_answers.jsonl` in `data/output/` before running notebooks 06 and 07 (the
   answers behind the paper are not distributed). The scripts are then not needed; if started, they ask only for
   the ids that have no valid answer under the current prompt. Answers are read back only under the prompt hash
   they were made with, stored with every answer in `prompt_sha`: notebook 06 keeps the answers under the hash of
   the current `config.LLM_SYSTEM_PROMPT` and stops if a planned call has none, and section 6 of notebook 07 reads
   the answers under the hash pinned in `LLM_POI_RUN_PROMPT_SHA` and stops if a POI of the records has none. Answers
   are matched by building id and POI id, so records whose text differs slightly still get their answer. With a
   token, the sample cells of notebooks 05 and 07 ask the model again unless `05_llm_sample_answers.jsonl` and
   `07_llm_poi_sample_answers.jsonl` already hold valid answers.
8. **Outputs.** Every step writes to `data/output/`; notebooks 01 and 04, and the optional QGIS scripts of step 08,
   also write review layers to `data/experimental_extract/`. Both folders and `data/input/` are git-ignored; do not
   publish the step-08 outputs or the QGIS layers made from them. Compare regenerated outputs with earlier ones by
   value.

## What can and cannot be reproduced

| | From a clean clone | Why |
|---|---|---|
| Rule classifier tests (`pytest rules/tests`) | yes | they use only the 30-building sample in `rules/tests/data/` |
| Steps 01–03 | yes, if the same data versions can be obtained | OSM, LoD2 and ALKIS land use are open, but their providers serve the current release: the OSM extract of the date used must be rebuilt, and the LoD2 tiles and the land-use cut used may have been replaced (see [`DATA.md`](DATA.md)) |
| Step 04 | yes, after steps 01–03 | the two reference tables are included |
| Steps 05–07, exactly | no | the KI-Toolbox is internal to TU Braunschweig, and the endpoint offers no temperature or seed control, so new calls can give different answers; the stored answers are not distributed |
| Steps 05–07, with another LLM | yes, after adapting `lib/llm_client.py` | results will differ from the paper |
| Steps 01–08 and rules, given the inputs, the zone totals and the answer files of the stored run | yes, verified | a regeneration from a fresh clone gave the stored outputs (see below); the zone totals and the answer files are not distributed |
| Rule classifier on the data | yes, after step 04 | deterministic |
| Step 08 | only with lawful access to the zone totals | `zone_targets.gpkg` is restricted; without it step 08 stops at its input check. This version has no open-data mode for step 08 |
| The paper's numbers | no | they rest on the zone totals and the stored LLM answers, which are not distributed; the validation figures rest on a manual check whose data are not part of this repository |

## What was checked

- **Prompts of the stored answers.** All 34,993 building answers and 7,864 POI answers were made with the model
  name `gpt-oss-120b` and with the prompts in `config.py` at b751cd9: prompt hash `795433ed9feb` (buildings) and
  `257a72e709cb` (POIs). The answer files record the hash in the field `prompt_sha`; the hash of the current prompts
  is printed by

  ```bash
  python -c "import config; from lib.llm_client import prompt_sha; print(prompt_sha(config.LLM_SYSTEM_PROMPT), prompt_sha(config.LLM_POI_SYSTEM_PROMPT))"
  ```

  The endpoint does not report which model answered; `gpt-oss-120b` is the model name the requests asked for.
- **Regeneration from a fresh clone.** A fresh clone with the code of `v1.0.0` was run headless with `jupyter nbconvert`
  as above: notebooks 01–08 and the rules notebook, in order. The inputs were local copies of those listed in
  [`DATA.md`](DATA.md), including the LoD2 tile cache (so step 02 downloaded nothing) and the zone totals; the two
  answer files of the stored run were placed in `data/output/`, and no LLM token was set. Every notebook ran to the
  end; notebooks 05 and 07 ran with `--allow-errors`, and only their token check and sample cells failed. Each output
  was compared with the stored output by value, attributes and geometry (the 4,891,343 rows of step 02 row by row),
  and was equal; both answer files stayed byte-identical. The one exception is `05_llm_input.parquet`: 35 of its
  39,786 records list the POIs of their `inside:` line in another order. The stored file was written when the LLM
  answers were made, before step 04 was re-run with a changed `share_in_building` rule, by which these POIs are
  ordered; the records are otherwise identical. The answers are joined to the buildings by building id, so step 06
  and all later outputs are unchanged. Not tested: new LLM calls (neither the samples nor the full runs were
  repeated), a fresh download of the inputs (local copies were used), and any machine other than one Windows
  machine with Python 3.13.
- **Step 08.** Re-running notebook 08 in this regeneration, with lawful access to the zone totals, reproduced the
  stored `08_redistribution.gpkg` by value: every attribute and geometry of the `buildings`, `pois` and `zones`
  layers.
- **Rule classifier.** Re-running the committed rule classifier reproduced `rules_classification.parquet` with no
  difference. The hash of `rule_utils.py` stored in the notebook's output equals that of the committed file.
- **Tests.** `pytest rules/tests` passes (167 tests).
