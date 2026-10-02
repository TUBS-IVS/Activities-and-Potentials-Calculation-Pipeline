# Step 07 — POI activity classification: what it is, what to build, what the Linux server needs

> **Status 2026-10-02, read first.** This is the spec of 2026-09-30, written
> before the code and kept as it was. The build and the run differ from it here:
>
> - **Scope:** 7,864 calls, not 22,633: only POIs that share their building
>   (`share_in_building < 1`), minus 183 landuse areas and 44 vacant units
>   (decided 2026-10-01). The run finished on 2026-10-02 at 00:53, 0 failed.
> - **Model (§2, §8):** the code sends `gpt-oss-120b` to `/api/v1/chat/send`.
>   TU's model list names gpt-oss `openai/gpt-oss-120b`, an On-Premise model, so
>   which model answered is **unconfirmed**. Write "requested gpt-oss-120b"; see
>   the comment above `LLM_MODEL` in `config.py`.
> - **Reading the answers (§6):** the one-liner there lacks the column list and
>   the id column. Use the two lines in
>   `docs/08-assembly-and-redistribution-handoff.md`, section 4.
> - **Output (§3.3 step 6):** `07_building_pois_classified.gpkg`, layers
>   `building_pois` (the 7,864 asked POIs) and `buildings` (decided 2026-10-01).
> - **Step 08 (§7):** superseded. A POI category its building lacks is merged
>   into the building's labels, not dropped (decided 2026-10-01). How step 08
>   redistributes is decided on the laptop; `docs/08-…` section 5 lists the
>   material.

Knowledge file for the multi-day LLM run on the Linux server and for whoever
prepares it. Written 2026-09-30, before any of the step-07 code exists. Read
`data/output/05-handoff-to-windows.md` first: step 07 is step 05 again, with
the POI instead of the building as the unit.

## 1. Why this step exists

The redistribution (step 08, the last step) needs one weight per building and
per demand category: `weight(b, c) = volume_3d_m3(b) × (share of b used for c)`.

- The **shares** exist: `building_pois.share_in_building` (step 04.5, a
  pseudo-volume split of the building among the POIs inside it; sums to 1.0
  per building). They say **how much** of the building each occupant takes.
- The **labels** exist only per building: `buildings.mid_labels` (step 05).
  They say **which** activities happen somewhere in the building, not which
  occupant serves which. A building labelled `retail_daily; leisure` with a
  bakery at 30 % and a pub at 70 % cannot be split without knowing that the
  bakery is the retail and the pub is the leisure.

Step 07 asks the model, for every POI, the purposes people come to **that
occupant** for — the same twelve MiD labels, the same definitions — so that the
split becomes `share × label`. Measured on `06_buildings_classified.gpkg`
(2026-09-30): 2,895 buildings carry two or more non-worker categories and need
this split (30.1 M m³); 1,539 of them have own POIs (4,154 pairs). All 22,633
own-POI pairs are asked anyway (decision below) so that a workplace-only
occupant (an office next to a shop) also reduces the shop's volume, and so the
labels are a reusable asset.

## 2. Decisions taken (defaults; say so if any is wrong)

| Decision | Value |
|---|---|
| Unit of one call | one POI in one building (`poi_id` is unique across `building_pois`, 22,633 own pairs; the 18,652 `how = 'site'` rows are **not** asked — a site's label is the building's, already in `mid_labels`) |
| Scope | all 22,633 own pairs (`how` in inside 19,003 / snap 2,004 / unit 1,626), not only the 4,154 on multi-category buildings |
| Labels | the twelve `config.LLM_ACTIVITY_LABELS`, definitions **verbatim** from Part A of `LLM_SYSTEM_PROMPT`; `work` by rule afterwards (`lib/llm_run.apply_work_rule`), every occupant is a workplace |
| Output per POI | `interpreted_type`, `mid_labels`, `confidence`, `reason` — **no** `bosserhof_class` (a building property; already drives the Workers weight) |
| Model / endpoint | `gpt-oss-120b` via the TU KI-Toolbox, unchanged (`config.LLM_API_URL`, `LLM_MODEL`, token in `.env` as `TU_KI_TOOLBOX_TOKEN`) |
| Dedupe | **none** (decided 2026-09-30): every own pair is its own call, 22,633 calls. Each POI is answered in its own building's context, there are no copied answers and no signature step in the assembly. (A dedupe by name + tag would have saved ~5,000 calls — not worth the extra logic.) |
| Numbering | `07` = POI classification (notebook + `scripts/07_run_llm_pois.py`); redistribution becomes `08` |
| Where it runs | the Linux server, detached, resumable — the same way as step 05 |
| Duration | step 05 measured 8.0 s median per call and 19.5 s per call wall-clock over the whole run (pauses included): 22,633 calls → 2.5 days of pure call time, plan for 3–5 days |
| Prompt | **reviewed and confirmed by the user before any call is made** — see §4.1 |

## 3. What must be built before the run (on Windows, where `data/output` lives)

Nothing of step 07 exists yet. Build in this order; every item is small
because step 05 already has the machinery.

### 3.1 `config.py` — a `STEP 07` block

- `LLM_POI_OUTPUT_SCHEMA`: `LLM_OUTPUT_SCHEMA` minus `bosserhof_class`.
- `LLM_POI_SYSTEM_PROMPT`: a new prompt whose LABEL DEFINITIONS section is
  the exact text of Part A (the notebook asserts the two prompts share it, so
  neither can drift alone); Part B gone; the framing rewritten for one
  occupant — see §4.
- Files: `LLM_POI_INPUT_FILE = OUTPUT_DIR / "07_llm_poi_input.parquet"`
  (the records; with no dedupe it is also the plan — every `poi_id` in it
  is asked, so there is no plan file),
  `LLM_POI_ANSWERS_FILE = OUTPUT_DIR / "07_llm_poi_answers.jsonl"`,
  `LLM_POI_SAMPLE_ANSWERS_FILE`, `LLM_POI_STATUS_FILE`, and a
  `LLM_POI_SAMPLE_IDS` tuple of ~20 `poi_id`s that cover the record kinds:
  named chain, named one-off, unnamed, `unit` inside a mall, `snap` from
  outside, a POI on a building with a site, a POI with a generic tag
  (`office=company`, `building=commercial`), a multi-value tag.

### 3.2 `lib/` — three generalisations, no new behaviour

- `lib/llm_client.py`: `validate_answer` is hard-wired to the building fields
  (it reads `bosserhof_class`). Make it schema-driven: canonicalise every
  enum property in `schema["properties"]`, pass every string property
  through `_text`, keep the `mid_labels` list handling. `classify` gains
  `schema=` next to `system_prompt=` and passes both through. `prompt_sha`
  already takes the prompt as an argument.
- `lib/llm_run.py`: `ANSWER_COLUMNS` starts with `building_id` and contains
  `bosserhof_class`; `run` / `load_answers` / `valid_answers` / `done_ids`
  key on `building_id`. Give the module an `id_col` and a column list that
  follow the schema (default = today's building values, so step 05 and the
  handoff note stay true), and let `run` take `system_prompt` and `schema`
  to hand to `classify`. The status block's class mix becomes label mix.
- `lib/llm_record.py`: add `build_poi_record(pair_row, building_row,
  sibling_pairs)` next to `build_record`, reusing `_tag`, `_name`, `_quote`,
  `_format_pois` and the same cleaning rules (key=value tags, no thousands
  separators, no line breaks, city suffix dropped). It must stay free of call
  logic, like `build_record`, so the validation can re-render what the model
  saw.

### 3.3 `pipeline/07_poi_classification.ipynb`

Same shape as notebook 05:

1. **Input contract** — reads `06_buildings_classified.gpkg` layers
   `buildings` and `building_pois`, plus `01_all_pois.gpkg` layer `pois` for
   `poi_use_tag` (the OSM key; without it a tag is written as the bare value,
   which the 05 dry run showed the model cannot read) and the folded `tags`
   JSON (for `brand`, `operator`, `cuisine`, `level` if the record wants
   them). Asserts: every own pair has a building row; `poi_id` unique;
   `share_in_building` sums to 1.0 per building (unchanged from 04.5).
2. **Records** — one per own pair, written to `07_llm_poi_input.parquet`
   with columns `poi_id, building_id, how, evidence, record, n_chars`.
   Prints samples per record kind. Every line starts with a known prefix
   (the 05 line-prefix check).
3. **Prompt check** — prints `LLM_POI_SYSTEM_PROMPT`, asserts its
   definitions block equals Part A of the building prompt and its label list
   equals `LLM_ACTIVITY_LABELS`; prints the sha.
4. **The call list** — with no dedupe this is just the count: 22,633
   `poi_id`s, printed with the mix of `how` and record kinds so the run's
   size is on record.
5. **Prompt review gate, stand-in dry run, then the sample** — the prompt
   review of §4.1 comes first and blocks everything after it; then the
   stand-in (render the ~20 sample records, read them as the model would,
   fix the renderer); then `run(...)` on `LLM_POI_SAMPLE_IDS` against the
   sample answers file, printed next to the building's `mid_labels` for
   review. **No full run before the sample is reviewed** (the step-05 rule).
6. *(after the Linux run, on Windows)* **Assembly** — apply the work rule,
   join the answers onto `building_pois` by `poi_id` as `poi_mid_labels`,
   `poi_confidence`, `poi_reason`; assert every own pair has an answer;
   print the disagreement table POI labels vs the building's `mid_labels`
   per `poi_use`; write the agreed output (proposal:
   `07_building_pois_classified.gpkg`, one layer `building_pois`, the 04.5
   columns plus the three above — the buildings layer is untouched). This
   is the only place the output file is created; it never happens on the
   server (§5.1).

### 3.4 `scripts/07_run_llm_pois.py`

`scripts/05_run_llm.py` with the `LLM_POI_*` constants, `id_col="poi_id"`,
the POI prompt and schema, and the id list taken from the input parquet
(no plan file); same options (`--sample`, `--ids`, `--limit`, `--workers`,
`--answers`, `--status-every`), same detached usage.

## 4. The record and the prompt — design notes for the draft

The record is the building record with the occupant pulled out in front:

    occupant: "La Cupola" (amenity=restaurant)
    role: inside the building
    building: cadastre: Public building, named "Haus der Wissenschaft" |
              also inside: "Haus der Wissenschaft" (amenity=events_venue) |
              place: Braunschweig | footprint 1798 m2 | height 41 m

`role` is one of: `inside the building`; `a unit inside "<parent>" (<tag>)`
(the `unit` rows, parent from `parent_name` / `parent_use`); `placed on the
nearest building, N m away` (the `snap` rows). The building block is the
existing `build_record` output minus the occupant itself, prefixed so the
model cannot mistake context for the thing to label.

Prompt framing (to be written by the same rules as the building prompt:
definitions, not examples; understanding, not clues; no scope text): the
model receives ONE occupant of a building; it lists the purposes people come
to **this occupant** for and maps them with the definitions; the building
lines say where the occupant is and what else is there — they never add a
purpose of their own, except that an occupant which *is* the institution the
building or site belongs to (a faculty in a university building) serves that
institution's purpose. Names carry world knowledge, as before. Output JSON
only, the exact strings.

Every POI carries its building block: with no dedupe each answer is used
for exactly one POI in exactly one building, so the context can only help.

### 4.1 The prompt review gate (mandatory, before the sample run)

The POI prompt is derived from `LLM_SYSTEM_PROMPT` and the user confirms
it before a single call is made. Whoever drafts it presents it as a marked
change against the building prompt, in three groups, so every difference
is visible and nothing is changed silently:

1. **Removed** — Part B (the whole Bosserhof section), the "You must produce
   TWO outputs" framing, `bosserhof_class` in the output JSON and in the
   closing instructions.
2. **Kept verbatim** — the ALLOWED ACTIVITY LABELS list and the LABEL
   DEFINITIONS block (the notebook asserts byte equality with Part A, so
   POI labels mean exactly what building labels mean).
3. **Changed or new, each one highlighted with its reason** — the opening
   role sentence (one occupant instead of one building); the description of
   the record lines (`occupant`, `role`, `building`, replacing the six
   building-record sources); the PROCEDURE rewritten for one occupant (list
   the purposes people come to this occupant for; the building lines locate
   it and never add a purpose, except the institution rule of §4); the
   output JSON block without `bosserhof_class`; the confidence wording if
   it referred to the building.

The user reads the marked-up prompt, says what to change, and only the
confirmed text goes into `config.LLM_POI_SYSTEM_PROMPT`. The sha of that
text is what every answer will carry; changing it later invalidates the
run.

## 5. What the Linux server needs

`data/` is git-ignored on both machines; code moves by git, data by copy.

| Item | How it gets there |
|---|---|
| The repo at branch `final-pipeline` with the step-07 code of §3 committed (config.py, lib/, scripts/07_run_llm_pois.py) | `git pull` |
| `config.py` **identical** to the one that produced the records — `prompt_sha(LLM_POI_SYSTEM_PROMPT)` must print the same twelve characters on both machines, otherwise `valid_answers` returns nothing and the run re-asks everything | comes with the pull; check the sha before starting |
| `data/output/07_llm_poi_input.parquet` (the records; every `poi_id` in it is asked) | copy from Windows; `sha256sum` on both sides |
| `.env` with `TU_KI_TOOLBOX_TOKEN=…` (or the variable exported) | already on the server from step 05; check it is not expired with `--sample` |
| conda env `capacity-final` (has pandas, pyarrow, requests; the base env lacks pyarrow) | already there |
| Nothing else: the run script reads one parquet file and writes JSONL; no GeoPandas, no GDAL, no gpkg needed on the server | — |

### 5.1 Resource care on the server

The run is an API loop, not a computation. Keep it that way:

- **RAM** — the script holds the 22,633 record strings (a few MB) and one
  reply at a time, and appends one line per answer; expect well under
  1 GB. Do not load `06_buildings_classified.gpkg`, `01_all_pois.gpkg` or
  any GeoDataFrame on the server; the records are already rendered in the
  parquet. If memory ever grows during the run, something is wrong — stop
  and look, do not add swap.
- **CPU / network** — one request at a time (`--workers 1`); the process
  sleeps while the model answers. Start it with `nice -n 10` so other users
  of the server are not affected. Do not raise `--workers` without asking
  the operators (step 05 saw 429s on fast retries).
- **Disk** — the answers file grows to ~15–20 MB, the status file is
  overwritten every minute, the log gets one status block per minute
  (≈ 5 MB over a five-day run). Nothing else is written.
- **No merging on the server** — the assembly (work rule, join onto
  `building_pois`, disagreement table, writing the gpkg) is notebook 07
  section 6 on Windows, where the geodata and the GDAL stack are. The
  server produces exactly one artefact: `07_llm_poi_answers.jsonl`.
- **The answers file while the run is on** — do not open it in an editor
  or copy it mid-run for anything but a look; the run appends and flushes
  per line. Copy it back after the run has been stopped or has finished
  (`load_answers` tolerates a torn last line, but a partial copy is not the
  run).

Run, in this order:

    cd <repo>
    conda activate capacity-final
    python -c "from config import LLM_POI_SYSTEM_PROMPT; from lib.llm_client import prompt_sha; print(prompt_sha(LLM_POI_SYSTEM_PROMPT))"
    python scripts/07_run_llm_pois.py --sample          # the ~20 sample POIs -> 07_llm_poi_sample_answers.jsonl; read them
    python scripts/07_run_llm_pois.py --limit 200       # the first 200 pending calls, watch pace and failures
    nohup nice -n 10 python scripts/07_run_llm_pois.py > data/output/07_llm_poi_run.log 2>&1 &
    tail -f data/output/07_llm_poi_run.log              # or: cat data/output/07_llm_poi_status.json

It appends one line per validated answer, skips everything already valid
under the current prompt, and can be stopped and restarted at any time.
Keep `--workers 1` unless the operators say otherwise (step 05 saw 429s on
fast retries). Do **not** edit `LLM_POI_SYSTEM_PROMPT` once the full run has
started — the sha changes and every answer so far becomes invalid.

## 6. What comes back to Windows

| File | Needed for |
|---|---|
| `data/output/07_llm_poi_answers.jsonl` | **required** — one JSON object per call, keyed by `poi_id`; fields as `lib/llm_run` writes them: `poi_id, ok, interpreted_type, mid_labels, confidence, reason, attempts, error, error_kind, retry_errors, raw_on_fail, elapsed_s, model, prompt_sha, ts` |
| `data/output/07_llm_poi_status.json`, `07_llm_poi_run.log` | optional — the run's own account of pace and failures, for the notebook's run summary |

Checksum the jsonl on both sides. Then notebook 07 section 6 (assembly) on
Windows: `valid_answers(load_answers(...), prompt_sha(LLM_POI_SYSTEM_PROMPT))`
must cover every `poi_id` of the input parquet — missing 0 — before anything
is joined. Failed calls are re-asked with `--ids <poi_id,...>` on the server.

## 7. How step 08 uses the result

Per building `b` and per demand category `c` (the seven VISUM categories,
via the same 12 → 7 collapse as the original pipeline: work, business →
Workers; retail_daily, errands → Retail_Daily; retail_non_daily →
Retail_Non-Daily; leisure, sports, meetup, lessons → Leisure; school /
university / childcare → School / University / Kindergarten):

- `weight(b, c) = volume_3d_m3(b) × Σ share_in_building(p)` over the own
  POIs `p` of `b` whose labels collapse to `c` (a POI with two non-work
  categories contributes its full share to each — the zone pools are
  normalised per category, so nothing has to sum across categories);
- the building's own `mid_labels` remain the authority on **which**
  categories exist for `b`; a POI category the building does not carry is
  counted and printed, not used;
- a category the building carries with no POI evidence (no own POIs: 9,683
  buildings; site-only: 12,646; or no POI labelled with it) falls back to
  the previous pipeline's even split of the volume, never zero;
- Workers is separate: `volume × Bosserhof factor(bosserhof_class)` on every
  building, uncapped in run 1; caps are decided from run 1's diagnostics;
- `share_of_site` is an audit column, not a multiplier.

## 8. Confirmed and still open

Confirmed 2026-09-30: all 22,633 own pairs, no dedupe, the Linux server,
gpt-oss-120b, no Bosserhof per POI, the prompt review gate of §4.1 before
any call, resource care of §5.1.

Still open:

1. Whether the sample (§3.3 step 5) runs on Windows (needs the token there)
   or on the server before the full run.
2. The step-07 output file name and columns of §3.3 step 6.
