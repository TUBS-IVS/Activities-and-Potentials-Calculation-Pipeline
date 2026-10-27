# Reproducibility

## Code version

The results in the paper were produced with the code at commit
[`60469fa22244bf4af3ed456a4d1fff4ae0eda34b`](https://github.com/TUBS-IVS/Activities-and-Potentials-Calculation-Pipeline/commit/60469fa22244bf4af3ed456a4d1fff4ae0eda34b).
Later commits that change only documentation do not change any result.

## Environment

The notebooks were run with Python 3.13; no other version was tested. The full LLM runs of steps 05 and 07 were
made with the two scripts on a separate Linux machine.

- Notebooks 01–03, 05, 08 and `rules/classify_buildings.ipynb` ran on Python 3.13.15 (notebook metadata), with
  osmium 1.19.1 (step 01) and GDAL/ogr2ogr 3.13.3 (step 02) as printed in their outputs.
- Notebooks 04 and 06 ran on Python 3.13.5, in a separate environment with an older pandas (2.x).

[`requirements.txt`](requirements.txt) lists the minimum package versions. Re-running a step in another environment
can change the bytes of a GeoPackage without changing its content, so compare outputs by value, not by checksum.

## Execution order

| Step | Entry point | External service | Runtime (as stated or stored in the notebook) |
|---|---|---|---|
| 01 | `pipeline/01_osm_extraction.ipynb` | — (the OSM extract is downloaded by hand) | 3–5 min |
| 02 | `pipeline/02_alkis_extraction.ipynb` | downloads 3,620 LoD2 tiles (0.44 GB) of the LGLN | ~24 min; writes 5.07 GB |
| 03 | `pipeline/03_alkis_refinement.ipynb` | — | ~10 min |
| 04 | `pipeline/04_semantic_enrichment.ipynb` | — | about 4 min (stored cell times) |
| 05 | `pipeline/05_llm_classification.ipynb` (input, sample), then `scripts/05_run_llm.py` (full run) | LLM endpoint | 34,993 calls; about 9 s per call in the stored sample; the stored full run took about 8 days |
| 06 | `pipeline/06_llm_assembly.ipynb` | — | seconds |
| 07 | `pipeline/07_poi_classification.ipynb` (input, sample), then `scripts/07_run_llm_pois.py` (full run), then section 6 of the notebook | LLM endpoint | 7,864 calls; the stored run took about 11 h |
| 08 | `pipeline/08_redistribution.ipynb` | — | about 2.3 min (stored cell times) |
| rules | `rules/classify_buildings.ipynb` (after step 04) | — | seconds |

Manual steps:

1. Place the inputs in `data/input/` and the two reference tables in `data/reference/` ([`DATA.md`](DATA.md)).
2. For steps 05 and 07, put the endpoint's token in `.env` (`TU_KI_TOOLBOX_TOKEN=...`) or adapt
   [`lib/llm_client.py`](lib/llm_client.py) to another endpoint (`LLM_API_URL`, `LLM_MODEL`).
3. Run the two LLM scripts on a machine that stays on, for example
   `nohup python scripts/05_run_llm.py > data/output/05_llm_run.log 2>&1 &`. Both write each valid answer as it
   arrives and skip answered ids when restarted (`--sample`, `--ids`, `--limit` and `--workers` are described in each
   script's docstring). Answers are read back only under the prompt they were made with.

## What can and cannot be reproduced

| | From a clean clone | Why |
|---|---|---|
| Rule classifier tests (`pytest rules/tests`) | yes | no data needed |
| Steps 01–03 | yes, if the same data versions can be obtained | OSM, LoD2 and ALKIS land use are open, but their providers serve the current release: the OSM extract of the date used must be rebuilt, and the LoD2 tiles and the land-use cut used may have been replaced (see [`DATA.md`](DATA.md)) |
| Step 04 | only with the two reference tables | they are not distributed |
| Steps 05–07, exactly | no | the KI-Toolbox is internal to TU Braunschweig, and the endpoint offers no temperature or seed control, so new calls can give different answers; the stored answers are not distributed |
| Steps 05–07, with another LLM | yes, after adapting `lib/llm_client.py` | results will differ from the paper |
| Rule classifier on the data | yes, after step 04 | deterministic |
| Step 08 | only with the zone totals | `zone_targets.gpkg` is not public |
| The paper's numbers | no | they rest on the zone totals, the reference tables and the stored LLM answers |

## What was checked

- **Prompts of the stored answers.** All 34,993 building answers and 7,864 POI answers were made with the model
  name `gpt-oss-120b` and with the prompts in `config.py` at 60469fa: prompt hash `795433ed9feb` (buildings) and
  `257a72e709cb` (POIs). The answer files record the hash in the field `prompt_sha`; the hash of the current prompts
  is printed by

  ```bash
  python -c "import config; from lib.llm_client import prompt_sha; print(prompt_sha(config.LLM_SYSTEM_PROMPT), prompt_sha(config.LLM_POI_SYSTEM_PROMPT))"
  ```

  The endpoint does not report which model answered; `gpt-oss-120b` is the model name the requests asked for.
- **Rule classifier.** Re-running the committed rule classifier reproduced `rules_classification.parquet` with no
  difference. The hash of `rule_utils.py` stored in the notebook's output equals that of the committed file.
- **Step 08.** The stored step-08 output was written shortly before the code was committed and was not re-run from
  the committed code; that it matches the committed code is assumed, not verified.
- **Tests.** `pytest rules/tests` passes (167 tests).
