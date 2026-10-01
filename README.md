# Activities and Potentials Calculation Pipeline — the server branch

This branch (`linux`) is the checkout that runs on the always-on Linux server.
It holds **only what the two LLM steps of the pipeline need**: step 05, the
classification of every building with activity in the Regionalverband
Großraum Braunschweig, one building per call, about 35,000 calls, three to
four days of runtime (finished 2026-09-23); and step 07, the same question
asked of every POI that shares its building with other POIs, 7,864 calls,
about a day.

Everything else — the extraction and enrichment steps before it (01–04) and
the assembly and redistribution after it — lives on branch
[`final-pipeline`](../../tree/final-pipeline) and runs on the developer's
laptop. This branch is a *subset* of that one, never a fork of it: every file
here is byte-identical to its copy on `final-pipeline`.

## Why the LLM step runs on a separate machine

- **It takes days.** The TU Braunschweig KI-Toolbox answers one request in
  about 7–9 s and its rate limit is undocumented, so the run sends one request
  at a time: 34,993 calls ≈ 3–3.5 days of continuous running. A laptop that
  sleeps, reboots or travels cannot do that; a server that stays on can.
- **It is resumable and needs no attention.** Every validated answer is
  appended and fsynced to `data/output/05_llm_answers.jsonl` the moment it
  arrives, tagged with the hash of the prompt it was given. A crash or a
  restart loses at most the call in flight; starting the script again asks
  only what has no valid answer yet.
- **It needs almost no data.** The run reads two small parquet files (the
  records the model sees and the plan of who is asked, 3.6 MB together) and
  the API token. Nothing from the 9 GB of raw inputs of steps 01–04 is
  needed here, so none of it is here.

## How the whole pipeline flows, and where each part runs

```
laptop  (final-pipeline)                     server  (this branch)                    laptop  (final-pipeline)
────────────────────────                     ────────────────────────                    ────────────────────────
01 OSM extraction                             notebook 05, sections 1–4                  05.6 assembly and validation
02 ALKIS / LoD2 extraction        ──copy──▶     04_buildings_enriched.gpkg               (answers joined to buildings,
03 ALKIS refinement                two files     01_all_pois.gpkg                        signature answers copied,
04 semantic enrichment                        ▶ 05_llm_input.parquet  (the records)      work by rule, baseline check)
   └─ 04_buildings_enriched.gpkg              ▶ 05_llm_plan.parquet   (who is asked)
      01_all_pois.gpkg                                                                   volume redistribution
                                              scripts/05_run_llm.py, for days   ──copy──▶  (weights: volume_3d_m3)
                                              ▶ 05_llm_answers.jsonl           three files
```

Step 04 decides *which* buildings are places of activity and collects the
evidence per building (POIs with names and OSM tags, the site around it, the
cadastre class and name, the OSM footprint tag, land use, size). Step 05 asks
the model, per building, *what happens inside* — the MiD activity labels and
the Bosserhof building-use class — from that evidence. Step 06 (laptop) puts
the answers on the polygons. **Step 07** asks the same question of every POI
that shares its building with other POIs (`share_in_building < 1`; a sole
occupant already carries the building's labels) — *which occupant serves
which of the building's labels* — so that step 08 can split a building's
volume by `share_in_building × label`: the records come from `06_buildings_classified.gpkg`
and `01_all_pois.gpkg` (notebook 07 sections 1–4), the run is
`scripts/07_run_llm_pois.py`, keyed by `poi_id`, with the POI prompt and
schema; the answers go back to the laptop for the assembly (notebook 07
section 6). The prompts, the label and class lists, the output schemas and
every path are in `config.py`, which is why the whole file is here even
though most of it describes steps 01–04: the two machines must read the same
constants.

## What is in this branch

| path | role |
|---|---|
| `config.py` | every constant of the pipeline; for step 05: the paths, the column roles, the system prompt (`LLM_SYSTEM_PROMPT`), the label and class lists, the output schema, the routing bins, the client settings; for step 07: the POI prompt (`LLM_POI_SYSTEM_PROMPT`, sharing the label definitions byte for byte), the POI schema, the sample POIs and the `07_*` paths. Identical to `final-pipeline` |
| `lib/llm_record.py` | renders the per-building record the model reads (step 05.2) and the per-POI record (`build_poi_record`, step 07.2) |
| `lib/llm_routing.py` | who is asked in step 05: one call per building with evidence, one per signature of class-only buildings (05.4). Step 07 has no plan: every POI of its input file is asked |
| `lib/llm_client.py` | one record in, one validated answer out: the POST, the JSON parsing, the schema-driven check, the re-ask on failure, the prompt hash (05.5). Takes the prompt and the schema as arguments; the defaults are step 05's |
| `lib/llm_run.py` | the resumable run over many records, the checkpoint file, the progress line and the status block (05.5). `id_col`, prompt and schema as arguments: `building_id` for step 05, `poi_id` for step 07 |
| `lib/checks.py` | the input-contract assertions the notebooks use |
| `pipeline/05_llm_classification.ipynb` | step 05 as a notebook: builds the two parquet inputs from the two GeoPackages (sections 1–4) and runs the ten-building sample (section 5). The full run is the script |
| `pipeline/07_poi_classification.ipynb` | step 07 as a notebook: the input contract, the records (`07_llm_poi_input.parquet`, sections 1–2), the prompt check (3), the call list (4), the review gate and the sample (5); the assembly (6) runs on the laptop after the run |
| `scripts/05_run_llm.py` | the step-05 entry point for the machine that stays on: `--sample`, `--limit N`, `--ids`, or everything |
| `scripts/07_run_llm_pois.py` | the step-07 entry point, same options, keyed by `poi_id`; reads only the input parquet, writes `07_llm_poi_answers.jsonl` |
| `docs/linux-server-handoff.md` | the step-05 operating manual: what to copy in each direction, how to launch, watch and resume, what was moved out of the server folder and why. Step 07 runs the same way with the `07_*` files |
| `environment.yml`, `.env.example` | the conda environment and the shape of the token file |

**Not here, on purpose:** notebooks 01–04 and `lib/schema.py` (steps 01–04,
laptop only); no data of any kind (`data/` is git-ignored on every branch —
the inputs are 9 GB of public downloads, the outputs are regenerable, and the
answers file belongs to the project, not to GitHub); no token (`.env` is
git-ignored and created by hand).

## Running it

```bash
git clone -b linux https://github.com/TUBS-IVS/Activities-and-Potentials-Calculation-Pipeline.git
cd Activities-and-Potentials-Calculation-Pipeline
conda env create -f environment.yml && conda activate capacity-final
cp .env.example .env            # then paste the KI-Toolbox token

# bring the two GeoPackages from the laptop into data/output/ (same run of steps 01-04),
# run notebook 05 sections 1-4 once -> 05_llm_input.parquet, 05_llm_plan.parquet, then:
python scripts/05_run_llm.py --sample                 # ten buildings, to see it work
nohup python scripts/05_run_llm.py >> data/output/05_llm_run.log 2>&1 &   # everything, detached
cat data/output/05_llm_status.json                    # progress, rewritten every minute
```

Start the script again after any interruption; it resumes. When it prints
`full: done N, ok N, failed 0`, copy `05_llm_answers.jsonl`,
`05_llm_plan.parquet` and `05_llm_input.parquet` back to the laptop for step
06. The details, the checks and the caveats (the prompt hash, the token, a
new step-04 build) are in `docs/linux-server-handoff.md`.

Step 07 runs the same way, from `06_buildings_classified.gpkg` and
`01_all_pois.gpkg` (or from a copied `07_llm_poi_input.parquet`):

```bash
# notebook 07 sections 1-4 once -> 07_llm_poi_input.parquet (7,864 records), then:
python scripts/07_run_llm_pois.py --sample                 # the 26 sample POIs, to see it work
nohup nice -n 10 python scripts/07_run_llm_pois.py > data/output/07_llm_poi_run.log 2>&1 &
cat data/output/07_llm_poi_status.json                     # progress, rewritten every minute
```

`07_llm_poi_answers.jsonl` is the one artefact that goes back to the laptop.

## Keeping this branch in sync with `final-pipeline`

Development happens on `final-pipeline`. When `config.py`, `lib/`, the script
or notebook 05 change there, take the same files over — never merge the
branch, which would bring the rest of the pipeline with it:

```bash
git checkout linux
git checkout final-pipeline -- config.py lib/checks.py lib/llm_client.py lib/llm_record.py \
    lib/llm_routing.py lib/llm_run.py scripts/05_run_llm.py scripts/07_run_llm_pois.py \
    pipeline/05_llm_classification.ipynb pipeline/07_poi_classification.ipynb \
    docs/linux-server-handoff.md .gitattributes
git commit -m "Sync steps 05 and 07 with final-pipeline <commit>"
```

Step 07 was written on this branch (2026-09-30) and goes the other way once:
the same files, copied onto `final-pipeline` by hand.

Mind the prompts: a change to `LLM_SYSTEM_PROMPT` or `LLM_POI_SYSTEM_PROMPT`
changes the hash on every new answer, and answers under the old hash are
ignored by the run and by the assembly. Sync a prompt change only when a
fresh run is intended.
