# Activities and Potentials Calculation Pipeline — the server branch

This branch (`linux`) is the checkout that runs on the always-on Linux server.
It holds **only what step 05 of the pipeline needs**: the LLM classification
of every building with activity in the Regionalverband Großraum Braunschweig,
one building per call, about 35,000 calls, three to four days of runtime.

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
the Bosserhof building-use class — from that evidence. The prompt, the label
and class lists, the output schema and every path are in `config.py`, which
is why the whole file is here even though most of it describes steps 01–04:
the two machines must read the same constants.

## What is in this branch

| path | role |
|---|---|
| `config.py` | every constant of the pipeline; for step 05: the paths, the column roles, the system prompt (`LLM_SYSTEM_PROMPT`), the label and class lists, the output schema, the routing bins, the client settings. Identical to `final-pipeline` |
| `lib/llm_record.py` | renders the per-building record the model reads (step 05.2) |
| `lib/llm_routing.py` | who is asked: one call per building with evidence, one per signature of class-only buildings (05.4) |
| `lib/llm_client.py` | one building in, one validated answer out: the POST, the JSON parsing, the schema check, the re-ask on failure, the prompt hash (05.5) |
| `lib/llm_run.py` | the resumable run over many buildings, the checkpoint file, the progress line and the status block (05.5) |
| `lib/checks.py` | the input-contract assertions notebook 05 uses |
| `pipeline/05_llm_classification.ipynb` | step 05 as a notebook: builds the two parquet inputs from the two GeoPackages (sections 1–4) and runs the ten-building sample (section 5). The full run is the script |
| `scripts/05_run_llm.py` | the entry point for the machine that stays on: `--sample`, `--limit N`, `--ids`, or everything |
| `docs/linux-server-handoff.md` | the operating manual: what to copy in each direction, how to launch, watch and resume, what was moved out of the server folder and why |
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
05.6. The details, the checks and the caveats (the prompt hash, the token, a
new step-04 build) are in `docs/linux-server-handoff.md`.

## Keeping this branch in sync with `final-pipeline`

Development happens on `final-pipeline`. When `config.py`, `lib/`, the script
or notebook 05 change there, take the same files over — never merge the
branch, which would bring the rest of the pipeline with it:

```bash
git checkout linux
git checkout final-pipeline -- config.py lib/checks.py lib/llm_client.py lib/llm_record.py \
    lib/llm_routing.py lib/llm_run.py scripts/05_run_llm.py pipeline/05_llm_classification.ipynb \
    docs/linux-server-handoff.md .gitignore .gitattributes
git commit -m "Sync step 05 with final-pipeline <commit>"
```

Mind the prompt: a change to `LLM_SYSTEM_PROMPT` changes the hash on every new
answer, and answers under the old hash are ignored by the run and by the
assembly. Sync a prompt change only when a fresh run is intended.
