# The Linux server: what it holds, what to bring, what to take back

**Status:** decided 2026-09-16, while the full step-05 run was live. The server
runs **step 05 only** — the LLM run that takes days — from branch `linux`, a
subset of `final-pipeline` that holds just the step-05 code (its README says
what is there and how it is kept in sync). The run of 2026-09-15/16 was
started from a `final-pipeline` checkout; switch this clone to `linux` after
it has finished, not before. Steps 01–04 and everything after 05 (05.6 assembly, the
redistribution) run on the Windows laptop. Steps 01 and 02 ran here once, on
2026-09-14; step 03 crashed the Jupyter kernel here on 2026-09-15 (15 GB of
RAM is not enough for the 5.07 GB raw layer), so steps 01–04 stay on the
laptop and their inputs and outputs were moved out of this clone.

**If you are here to**

- restart the run after a reboot or a closed window → "Launching, watching, resuming";
- bring the results to the laptop and start 05.6 → "Linux → Windows";
- redo notebook 05 here after a new step-04 build → "Windows → Linux";
- find out where a step 01–04 file went and where it comes from → "The cleanup of 2026-09-16".

The run of 2026-09-15/16 is under **prompt `795433ed9feb`** (the first twelve
hex characters of the SHA-1 of `LLM_SYSTEM_PROMPT` in `config.py` at commit
`95f5608`), model **`gpt-oss-120b`**. Every answer line carries that hash.

Notebook cells are named by content below, not by number: VS Code shows no
cell numbers.

## Roles

| machine | does | keeps |
|---|---|---|
| Windows laptop | notebooks 01–04; notebook 05 sections 1–4 when the enriched layer changes; 05.6 and the redistribution | all of `data/input/*`, all step 01–04 outputs, `data/reference/*` |
| Linux server | `scripts/05_run_llm.py` for days, resumable; notebook 05 sections 1–4 when the two GeoPackages are re-ported | the code (git), `.env`, the two GeoPackages (the step-04 enriched layer and the step-01 POI file), the five `05_*` files (six with the log) |

## What the server keeps

After the cleanup the clone is 66 MiB plus 33 MiB of `.git`:

| path | bytes | why it stays |
|---|---|---|
| every git-tracked file (`config.py`, `lib/`, `pipeline/`, `scripts/`, `docs/`; 20 files) | 738,597 | the code; `config.py` holds the prompt whose hash tags every answer |
| `.env` | 54 | `TU_KI_TOOLBOX_TOKEN`. `lib/llm_client.read_token` reads it **before every call**, not once at start — see the token notes under "Launching" |
| `data/output/04_buildings_enriched.gpkg` | 41,967,616 | the laptop's build of 2026-09-15 09:31; what notebook 05 reads (layers `buildings`, 39,786 × 43, and `building_pois`, 41,285 rows). sha256 `0cf836253aa2d303bee7f500f5496dcf7c58bc08c5abb480f3ec8252c6269cf1` |
| `data/output/01_all_pois.gpkg` | 14,229,504 | a step-01 output: notebook 05 joins the OSM key of every POI's use (`poi_use_tag`) from it, because `building_pois` carries no key. Built here on 2026-09-14 from the 2026-09-10 snapshot; passes notebook 05's same-run assertion against the 04 file (24,663 POI ids, 0 disagreements). sha256 `f0c207d11b3cd03e21ea730fc61e7f5c3531fcdc6c6b3946687915e6e6188863` |
| `data/output/05_llm_input.parquet` | 2,919,500 | the records the model reads, plus the model-only columns; `05_run_llm.py` loads it once at start |
| `data/output/05_llm_plan.parquet` | 659,698 | who is asked; loaded once at start |
| `data/output/05_llm_answers.jsonl` | grows to ~25 MB | **the deliverable** — one line per validated answer, flushed and fsynced as it arrives |
| `data/output/05_llm_status.json` | ~1 K | rewritten every 60 s by the run |
| `data/output/05_llm_sample_answers.jsonl` | 14,599 | the ten-building sample: 10 lines under the current prompt, 10 under the pre-review prompt `4ebda0053159` that are ignored |
| `data/reference/*` (3 files) | 55 K | step 04's tables, **not** a step-05 dependency; kept because tiny. The `.xlsx` is read by nothing (converted once to the `.csv`) |
| `data/input/regionalverband_area.gpkg` | 233,472 | the study boundary, hand-made in QGIS on 2026-01-05, needed by notebooks 01 and 02, **irreplaceable** — keep a copy on both machines. Not a step-05 dependency |
| `.vscode/settings.json` | 132 | selects conda as the environment manager on this machine; hidden from `git status` through `.git/info/exclude` |

Nothing else in `data/` is needed here. Step 05 (`scripts/05_run_llm.py`,
`lib/llm_*.py`, notebook 05) reads no file under `data/input/`, none under
`data/reference/`, and no step 01–03 output except `01_all_pois.gpkg`.
`__pycache__/` folders reappear whenever anything imports `config` or `lib`;
they are git-ignored.

## Windows → Linux: to (re)start step 05 here

1. **Environment** (already present on this box; only for a fresh machine):
   conda env `capacity-final`, Python 3.12 —
   `pyogrio geopandas pandas pyarrow requests pyrosm gdal osmium-tool shapely
   pyproj numpy jupyter ipykernel`. The run itself needs only `pandas`,
   `pyarrow`, `requests`. Its interpreter works without `conda activate`:
   `/home/mayur/miniconda3/envs/capacity-final/bin/python`.
2. **Code:** first `git checkout -- pipeline/05_llm_classification.ipynb`
   (its only local change is cell outputs from the sample run here; once the
   laptop has edited that notebook the pull is refused without this), then
   `git pull` on `linux`. The `linux` branch is updated from
   `final-pipeline` by copying the step-05 files across (the README shows the
   command), so a change made on the laptop reaches the server only after
   that sync. The `config.py` here must be the one of commit `95f5608` or a
   later one that did not touch the prompt. **A pull that
   changes one character of `LLM_SYSTEM_PROMPT` makes every existing answer
   stale**: `valid_answers` ignores them and the run starts from zero. Do not
   edit the prompt — nor `LLM_ACTIVITY_LABELS`, `LLM_BOSSERHOF_CLASSES`,
   `WORK_IMPLIED_BY`, which the answers were validated against — until 05.6
   has consumed the answers.
3. **`.env`** with `TU_KI_TOOLBOX_TOKEN=...` — git-ignored, copied by hand,
   never committed.
4. **`data/output/04_buildings_enriched.gpkg` and `data/output/01_all_pois.gpkg`,
   as a pair from one laptop run of steps 01→04**, whenever step 04 is
   re-run. Notebook 05's section-2 code cell (the one that reads
   `building_pois` and joins `poi_use_tag`) asserts that every `poi_id` exists
   in the POI layer with the same `poi_use`, and raises "the two files are
   from different runs" otherwise. Do **not** re-run steps 01–04 on the laptop
   before 05.6 has run on the current answers: a new enriched layer changes
   building ids and signature representatives.
5. **Before the first run on a new plan, move the old results aside:**
   `mkdir -p data/output/archive && mv data/output/05_llm_answers.jsonl data/output/archive/05_llm_answers_795433ed9feb.jsonl`
   (also `05_llm_status.json` and `05_llm_run.log`). The resume keys on
   building id and prompt hash only: with the old file in place, every id that
   survived into the new layer keeps its old answer even where its record
   changed. Check that the ten `LLM_SAMPLE_BUILDING_IDS` in `config.py` still
   exist in the new layer, or the sample cell stops with "sample buildings
   without a record".
6. Then run notebook 05 sections 1–4 here (kernel `capacity-final`) to write
   `05_llm_input.parquet` and `05_llm_plan.parquet`; `build_records` and
   `build_plan` are deterministic, so the same inputs give the same ids and
   records. Or, if notebook 05 already ran on the laptop against the same
   enriched layer, copy those two files (3.6 MB together). For a bare restart
   the two parquets and `.env` are all the script needs; the two GeoPackages
   are only for regenerating them.

## Launching, watching, resuming

The plan has 39,786 buildings and **34,993 calls**: 33,734 buildings asked on
their own, 1,259 signature representatives answering for 6,052 class-only
buildings. Observed: a median of 7.4 s and a mean of 8.8 s per call including
retries, one request at a time, about 410 answers an hour over the run so far
(the instance started 2026-09-16 09:12 does about 450). The whole plan takes 3
to 3.5 days of continuous running. On 2026-09-16 at 14:39, 11,021 calls were
answered, 0 failed, 23,972 pending; the status block projected the end for
2026-09-18 around 20:00.

```bash
cd ~/Documents/Activities-and-Potentials-Calculation-Pipeline
pgrep -af 05_run_llm.py                   # must print nothing: two instances would ask every pending building twice
conda activate capacity-final
nohup python scripts/05_run_llm.py >> data/output/05_llm_run.log 2>&1 &   # detached; >> keeps earlier sessions' blocks
tail -f data/output/05_llm_run.log        # a status block every minute
cat  data/output/05_llm_status.json       # the same block as JSON
```

Starting it again is the resume: every building with a valid answer under the
current prompt is skipped, failed ones are asked again, nothing is asked
twice. The restart of 2026-09-16 09:12 re-asked 0 buildings.

**How the current run was actually started.** The instance running since
2026-09-16 09:12 (PID 189835) is the **foreground job of a VS Code integrated
terminal**, started without `nohup`, with no log file. Until it finishes:

- do not close VS Code, do not close or reload that terminal tab, do not type
  in it (Ctrl-C stops the run, Ctrl-Z suspends it, Ctrl-S freezes its output
  and with it the run);
- do not rename or move the repo folder, `.env`, or the conda env — the paths
  were fixed at start and `.env` is read before every call;
- do not re-execute notebook 05's sample cell (`run(LLM_SAMPLE_BUILDING_IDS, …)`):
  it rewrites `05_llm_status.json` with the sample's status; do not re-run
  sections 2 or 4 unless the same 04 and 01 files are in place;
- progress is only in `data/output/05_llm_status.json` (rewritten every 60 s;
  its `done/total` counts the current session, which started with 26,426
  pending) and in the answers file itself.

The true count, from the repo root with the `capacity-final` interpreter:

```bash
python - <<'EOF'
import pandas as pd, sys; sys.path.insert(0, '.')
from lib.llm_run import load_answers, valid_answers
from lib.llm_client import prompt_sha
ok = valid_answers(load_answers('data/output/05_llm_answers.jsonl'), prompt_sha())
plan = pd.read_parquet('data/output/05_llm_plan.parquet')
missing = set(plan['answered_by']) - set(ok['building_id'])
print(f"{len(ok):,} of {plan['answered_by'].nunique():,} calls answered under prompt {prompt_sha()}; {len(missing):,} still to ask")
EOF
```

**The token.** A missing or renamed `.env` makes `read_token` raise, and the
run dies with a traceback (checkpoint intact). An **expired token does not
stop the run**: HTTP 401/403 is a transport error, retried three times with
pauses, then the building is written as failed and the run moves on — one
failed line every ~90 s for every remaining building. If `failed` climbs in
the status block with an HTTP 401 as the last error, paste a new token into
`.env`: it is read before every call, no restart needed. Start the script once
more at the end to ask the failed buildings again.

**The end.** The run has exited when `pgrep -af 05_run_llm.py` prints
nothing and the terminal or log ends with
`full: done N, ok N, failed N -> …/05_llm_answers.jsonl` (exit status 1 if
anything failed). If it dies early (a closed window, a reboot) nothing is
lost but time: every answer is on disk the moment it is validated. Start it
again, detached, as above. `tmux` and `screen` are not installed on this box;
`nohup` is.

## Linux → Windows: to continue with 05.6 and the redistribution

Copy these **three files together**, to the same relative paths, after the
run has exited (a copy taken mid-run is a valid prefix — lines are complete
or absent, and `load_answers` skips a torn last line). `sshd` runs on the
server, so from the laptop:

```
scp mayur@<server>:~/Documents/Activities-and-Potentials-Calculation-Pipeline/data/output/05_llm_{answers.jsonl,plan.parquet,input.parquet} data\output\
```

| file | why the laptop needs it |
|---|---|
| `data/output/05_llm_answers.jsonl` | one JSON object per line: `building_id`, `ok`, `interpreted_type`, `mid_labels`, `bosserhof_class`, `confidence`, `reason`, `attempts`, `error`, `error_kind`, `retry_errors`, `raw_on_fail`, `elapsed_s`, `model`, `prompt_sha`, `ts` (`ANSWER_COLUMNS` in `lib/llm_run.py`). `valid_answers` keeps `ok == true` under the current `prompt_sha`, the latest `ts` per building. Keyed by `building_id == plan.answered_by` |
| `data/output/05_llm_plan.parquet` | the plan the run actually used: `building_id`, `evidence`, `route`, `signature`, `answered_by`, `n_in_signature`. 05.6 looks up each building's answer through `answered_by` and copies the representative's answer to the 6,052 members marked `route == 'signature'` |
| `data/output/05_llm_input.parquet` | the exact record each call sent (`record` — it exists nowhere else), `evidence`, `n_chars`, plus the model-only columns 05.6 and the redistribution need: `volume_3d_m3` (the weight), `activities` (the rule baseline), `alkis_id`, `ags`, `function`, `source`, `n_pois`, `n_sites`, `address` |

**Do not regenerate the two parquets on the laptop:** sections 2 and 4 of
notebook 05 rewrite them on every execution, so after copying run only the
05.6 cells, not "Run All". While the 04 file is unchanged the rewrite is
byte-for-byte harmless (both builders are deterministic), but the copies are
the record of what the run used.

Also worth taking: the final `05_llm_status.json` (the run's statistics),
`05_llm_run.log` if the run was started detached, and
`05_llm_sample_answers.jsonl` (15 KB; lets notebook 05's sample cell pass on
the laptop without spending ten calls — a `.env` with a token is still
required, `run` reads it even when nothing is pending).

Before assembling, check on the laptop:

- **no planned call without a valid answer**: notebook 05's last code cell
  (`if LLM_ANSWERS_FILE.exists(): …`) prints
  `34,993 of 34,993 calls answered under the current prompt` when everything
  is there. Lines with `ok == false` may remain for buildings that failed
  once and were answered on a later pass — `valid_answers` ignores them.
  Only if the valid count is short, run `scripts/05_run_llm.py` on the server
  once more; it asks exactly the missing ones;
- every line `prompt_sha == '795433ed9feb'` and `model == 'gpt-oss-120b'`;
- `config.py` on the laptop hashes `LLM_SYSTEM_PROMPT` to `795433ed9feb`
  (commit `95f5608` or a later one that did not touch the prompt). Safer:
  when writing 05.6, add `LLM_RUN_PROMPT_SHA = "795433ed9feb"` to `config.py`
  (it does not exist yet) and filter on it instead of `prompt_sha()`, so a
  later prompt edit cannot hide the answers;
- `04_buildings_enriched.gpkg` on the laptop is still the 2026-09-15 09:31
  build: `certutil -hashfile data\output\04_buildings_enriched.gpkg SHA256`
  must give `0cf836253aa2d303bee7f500f5496dcf7c58bc08c5abb480f3ec8252c6269cf1`
  (and `01_all_pois.gpkg`: `f0c207d11b3cd03e21ea730fc61e7f5c3531fcdc6c6b3946687915e6e6188863`).
  The plan's 39,786 building ids are that build's ids.

05.6 itself is **not written yet** (notebook 05, "Next"): the answers joined
to the buildings; every signature's answer copied to its members and marked;
`work` added by rule where any other label is present
(`lib/llm_run.apply_work_rule`, `WORK_IMPLIED_BY`) with `work_from` = llm |
rule | both; then the comparison with the `activities` baseline and the
annotated Bosserhof set. A building whose call failed for good should come out
unclassified, not dropped.

## The cleanup of 2026-09-16

Done from a second shell while the run continued (answers file untouched,
process alive before and after). Repo: 9.6 GB → 66 MiB.

**Deleted outright** (regenerable): `data/experimental_extract/01_dropped_pois.gpkg`
(16,347,136 B; a QGIS audit layer notebook 01 rewrites, read by nothing; the
laptop produced an identical one) and the `__pycache__/` folders (which come
back on the next import).

**Removed from the server** (first moved to a quarantine folder, then deleted
the same day once the laptop copies were confirmed). The table stays as the
provenance record of what the laptop holds and where each file came from:

Re-downloadable or regenerable:

| file | bytes | source, and whether it was still there on 2026-09-16 |
|---|---|---|
| `data/output/02_alkis_lod2_raw.gpkg` | 5,074,554,880 | notebook 02's merge cell from the tile cache: 633 s here, 1,081 s on the laptop |
| `data/input/FS_LN_03_NI_260101.gpkg` | 3,389,366,272 | LGLN STAC *alkis-landnutzung*, yearly cut 2026-01-01: `https://landnutzung.s3.eu-de.cloud-object-storage.appdomain.cloud/FS_LN_03_NI_260101.gpkg` (online, Last-Modified 2026-03-17); cheaper as the `.zip` (1,156,030,193 B) that holds the `.gpkg` and the `.json` |
| `data/input/FS_LN_03_NI_260101.json` | 400,836 | the download's metadata sidecar; inside the `.zip` only; read by nothing |
| `data/input/lgln-opengeodata-lod2.geojson` | 23,032,477 | the statewide LoD2 tile index (37,928 tiles): `https://arcgis-geojson.s3.eu-de.cloud-object-storage.appdomain.cloud/lod2/lgln-opengeodata-lod2.geojson` (online, byte-identical, md5 `cf1e17d05ebd2c27193d475e5d0a03d1`) |
| `data/input/lod2_cache/zip/` (3,620 tiles; `shp/`, `reduced/` empty) | 443,887,482 | notebook 02's download cell re-fetches them from `https://lod2.s3.eu-de.cloud-object-storage.appdomain.cloud/SHP/<tile>.zip` in about 70 s |
| `data/output/01_all_buildings_osm.gpkg` | 165,433,344 | notebook 01 (the whole notebook: about four minutes; needs the 2026-09-10 snapshot back) |
| `data/output/01_study_area_clipped.pbf` | 59,667,295 | notebook 01's osmium clip, 12 s |
| `data/output/01_landuse_osm.gpkg` | 25,759,744 | notebook 01 |
| `data/output/02_lod2_region_tiles.gpkg` | 1,642,496 | notebook 02's tile-selection cell, seconds |

The two Geofabrik daily snapshots. Geofabrik keeps dated files for about a
week (on 2026-09-16 it listed the dailies 260909–260915, the monthlies and
the 1-January yearlies only), so the laptop copies are the reference:

| file | bytes | status |
|---|---|---|
| `data/input/niedersachsen-260910.osm.pbf` | 504,682,810 | `OSM_PBF_FILE`, the snapshot every output of this study is built on. Online on 2026-09-16, gone within days. The laptop has it (notebook 01's committed output shows it) — verify the size |
| `data/input/niedersachsen-260113.osm.pbf` | 478,239,569 | the January snapshot the study started on; already **404** at Geofabrik. Referenced only by the comment at `config.py:40` (between the two snapshots the region gained 4 % POI-tagged objects and 1.4 % footprints). Deleted from the server on 2026-09-16 by decision: every result was rebuilt on the 2026-09-10 snapshot, so the January file is not needed |

**Also done:** `git checkout` of notebooks 01, 02 and 03 (only cell outputs
from the runs here differed; sources verified identical to HEAD, whose 01 and
02 hold the laptop's complete runs and whose 03 holds the laptop's run through
section 8). `.vscode/` added to `.git/info/exclude` (local to this clone).

**Not done, for later, none urgent:** this file is untracked on the server —
commit it so the laptop has it. Notebook 05 still carries its local outputs
(the sample run on this box) while its kernel is attached; check it out
before the next pull as step 2 above says, or commit it from here once the
kernel is closed. The `.gitignore` comment on `data/experimental_extract`
says notebook 03 writes it; notebooks 01 and 04 do. `config.py` could name
the tile-index URL above beside `LOD2_TILE_INDEX_FILE`.
