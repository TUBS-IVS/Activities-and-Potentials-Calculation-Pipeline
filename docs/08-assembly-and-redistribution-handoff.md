# Step 07 results for the laptop: what the server delivers and what it can be used for

Hand-off from the Linux server (branch `linux`, 2026-10-01) to the laptop
(branch `final-pipeline`). It says what was done on the server, what arrives
from it, how to read it, and which data and earlier work can feed the
redistribution (step 08). **How** step 08 redistributes is not decided here:
that is discussed and written on the laptop. Every number was measured on the
server's copies of `06_buildings_classified.gpkg` and `01_all_pois.gpkg`
(checksums in section 3). Anything that could not be checked on the server is
marked **unverified**.

## 1. Where the pipeline stands

| step | where | state |
|---|---|---|
| 01–04 extraction, enrichment, POI split | laptop | done: `04_buildings_enriched.gpkg` |
| 05 building classification, 34,993 calls | server | done 2026-09-23, prompt `795433ed9feb` |
| 06 assembly of the building answers | laptop | done (`final-pipeline` 1cfdad0): `06_buildings_classified.gpkg` |
| 07 POI classification, 7,864 calls | server | **running** since 2026-10-01 afternoon, about 5 s per call, ends around the morning of 2026-10-02 (`eta_at` in `07_llm_poi_status.json`); prompt `257a72e709cb` |
| 07.6 the answers onto the POIs | laptop | to write: notebook 07 section 6 (section 4 below) |
| 08 redistribution | laptop | to discuss, then write |

What was done on the server for step 07 (branch `linux`, commits `e886b6f`,
`33458f1`, `4ae3495`):

- **Generalised, not copied.** `lib/llm_client.py` and `lib/llm_run.py` take the
  prompt, the output schema and the id column as arguments. Step 05 keeps its
  defaults and its behaviour: its 39,786 records re-render byte for byte.
- **One record per POI** (`lib/llm_record.build_poi_record`): the occupant
  (name, else brand, else operator; its OSM tag), its role in the building,
  then the building's other evidence (other occupants, footprint tag, site,
  cadastre class, place).
- **Scope, decided by the user:** only POIs that share their building
  (`share_in_building < 1`), minus 183 landuse areas (zoning polygons, not
  occupants) and 44 vacant units: 7,864 calls on 2,913 buildings.
- **Prompt reviewed and confirmed by the user** before any call. Its label
  definitions are byte-identical to the building prompt (notebook 07 asserts
  it). No Bosserhof class per POI.
- **Sample on the real model:** 26 of 26 valid, no retries, all high
  confidence. An office gets `work` only, a shop gets retail, a library gets
  leisure.
- **Run verified and hardened** before the full start (89 checks): a torn last
  line no longer swallows the next answer, a second instance refuses to start
  (`07_llm_poi_answers.jsonl.lock`), and reading an answers file with the
  other step's column list raises instead of returning rows without the id.

## 2. Labels: building level and POI level

Every building is labelled already, by step 06: **all 39,786 carry
`mid_labels`**, none empty. Step 07 adds labels at POI level only where two
or more occupants share a building.

| level | what | count | labels from |
|---|---|---|---|
| building | buildings with their own step-05 call | 33,734 | their own answer |
| building | class-only buildings grouped in signatures (same cadastre class, footprint, land use, area band, height band) | 6,052 in 1,259 signatures | the answer for the signature's median-area member: 1,259 asked, 4,793 copied (`answer_copied`; `answered_by` names the member asked). Copied answers: 4,686 medium, 82 low, 25 high confidence |
| POI | POIs that share their building | 7,864 on 2,913 buildings | their own step-07 answer, plus `work` by rule |

Left out at POI level, because the building polygon already carries them:

- **Sole occupants** (`share_in_building = 1`): 14,542 POIs. Their information
  went into their building's step-05 call, so the building's labels are
  theirs.
- **Site rows** (`how = 'site'`): 18,652. The site's purpose is in the
  building's labels; `share_of_site` is an audit column.
- **Landuse areas and vacant units** in shared buildings: 183 + 44 pairs. They
  are not occupants, and their share carries no activity: 1.33 M and 0.16 M m³,
  0.5 % of all volume. Two buildings had only such pairs
  (`DENIAL0300008jmn`, `DENIAL0600001zkC`), so they stay at building level.

## 3. What comes from the server

### Data, once the run has finished

The run has finished when its log ends with `full: done N, ok N, failed 0`
and `pgrep -f 'python scripts/07_run_llm_pois.py'` prints nothing on the
server. If failures remain, start the script again there. It asks only what
has no valid answer yet.

```
scp mayur@<server>:~/Documents/Activities-and-Potentials-Calculation-Pipeline/data/output/07_llm_poi_{answers.jsonl,input.parquet,status.json,run.log} data\output\
```

| file | needed for |
|---|---|
| `07_llm_poi_answers.jsonl` | **required.** One JSON object per line, keyed by `poi_id`: `poi_id, ok, interpreted_type, mid_labels, confidence, reason, attempts, error, error_kind, retry_errors, raw_on_fail, elapsed_s, model, prompt_sha, ts`. About 5 MB |
| `07_llm_poi_input.parquet` | **required** for the coverage check: the 7,864 asked POIs and the exact record each call sent (`poi_id, building_id, how, evidence, record, n_chars`) |
| `07_llm_poi_status.json`, `07_llm_poi_run.log` | optional: pace, failures, label mix |
| `07_llm_poi_answers.jsonl.lock` | do not copy: an empty lock file that belongs to the server |

Compare checksums on both sides: `sha256sum <file>` on the server and
`certutil -hashfile <file> SHA256` on the laptop. The laptop's inputs must be
the files the step-07 records were built from:

| file | sha256 |
|---|---|
| `06_buildings_classified.gpkg` | `d5baa3f235d2cca8928773faf1d83d6e8abcfd933f3b270397cab92a2208c90b` |
| `01_all_pois.gpkg` | `1e59d2bd360f76c2f1b616ef328ced1cab539032d6e5b657cfd63e47a0b5482a` |
| `07_llm_poi_input.parquet` | `3b562af9bbea267743229f296374970bae3c4e75148be6fc8f7bc1487f9c8cc1` |

### Code

```
git fetch origin
git checkout final-pipeline
git status          # no local changes to the files below, else add the STEP 07 block by hand
git checkout origin/linux -- config.py lib/llm_client.py lib/llm_record.py lib/llm_run.py ^
    scripts/07_run_llm_pois.py pipeline/07_poi_classification.ipynb ^
    docs/08-assembly-and-redistribution-handoff.md
git commit -m "Step 07 from the linux branch"
python -c "from config import LLM_POI_SYSTEM_PROMPT as p; from lib.llm_client import prompt_sha; print(prompt_sha(p))"
```

The last line must print `257a72e709cb`. Copying is safe: the four `lib/`
files on `final-pipeline` are unchanged since the server took them (checked
against `fcad281`). The server's `config.py` is `final-pipeline`'s plus the
appended STEP 07 block, with no line removed. Never merge the two branches.
`README.md` and `docs/linux-server-handoff.md` describe the server; leave
them there. The run lock uses `fcntl`, which Windows lacks; the code then
simply skips the lock.

## 4. Step 07.6: the answers onto the POIs (notebook 07, section 6)

Run section 1 (the input contract), then section 6. Skip sections 2 to 5 on
the laptop. Section 2 rewrites the input parquet: it is deterministic, but
the copy is the record of what was asked. Section 5 needs the API token.

1. **Read the answers.** Pin the prompt hash in config, so a later prompt edit
   cannot hide the answers: add `LLM_POI_RUN_PROMPT_SHA = "257a72e709cb"`.
   ```python
   cols = answer_columns("poi_id", LLM_POI_OUTPUT_SCHEMA)
   ans = valid_answers(load_answers(LLM_POI_ANSWERS_FILE, cols), LLM_POI_RUN_PROMPT_SHA, "poi_id")
   ```
   `load_answers` with its default columns raises here, because those are
   step 05's, keyed by `building_id`. Assert that every `poi_id` of
   `07_llm_poi_input.parquet` is in `ans`. If any is missing, re-ask on the
   server with `python scripts/07_run_llm_pois.py --ids a,b,c`.
2. **Labels on each of the 7,864 asked POIs:**
   - `poi_llm_labels`: the model's labels, as given;
   - `poi_mid_labels`: plus `work` by rule (`lib/llm_run.apply_work_rule`), as
     a set ordered like `LLM_ACTIVITY_LABELS` and joined with `;`, the same
     form as the buildings' `mid_labels`;
   - `poi_type`, `poi_confidence`, `poi_reason`: `interpreted_type`,
     `confidence`, `reason`;
   - with `building_id`, `poi_use`, `name` and `share_in_building` from
     `building_pois`.
3. **Print the label clash table:** per `poi_use`, the POI categories its
   building does not carry. Early result from the first 301 answers: 24 POIs
   (8 %), for example a shop answered `retail_daily` in a building labelled
   `work` only. Decided 2026-10-01: merge. The building's label set takes
   its POIs' labels as well, each label once, and every POI keeps its own
   labels.
4. **Write `07_building_pois_classified.gpkg`** (name decided): layer
   `building_pois` with the 7,864 asked POIs and the columns above, and layer
   `buildings` from step 06 with the merged labels, so that step 08 reads one
   file.

## 5. What can be used for the redistribution

This is material for step 08, not a method.

### 5.1 The columns

| level | column | meaning |
|---|---|---|
| building | `volume_3d_m3` | the volume; 277.2 M m³ over all buildings |
| building | `mid_labels` | the labels after the work rule, `;`-joined; `llm_labels` holds the model's own |
| building | `bosserhof_class` | the building-use class, 43 distinct values in 06 |
| building | `llm_confidence`, `route`, `answered_by`, `answer_copied` | how sure the answer is, and whether it is a signature copy |
| building | `ags`, `city`, `function`, `label_en` | municipality and cadastre class |
| POI | `share_in_building` | the POI's part of its building from step 04.5: `split_area_m2` × `split_h_m` over the building's own pairs. Sums to 1 per building; checked exact on all 22,633 own pairs. Final, never recomputed (decided 2026-10-01) |
| POI | `poi_mid_labels` and the other columns of section 4 | from step 07.6 |

The 2,915 shared buildings hold 64.6 M m³ (23.3 % of all volume). That is the
only volume where the POI labels change anything.

### 5.2 From the previous pipeline

The previous pipeline's redistribution is in notebooks 10 and 11 and in
`config.py` of commit `54629cb`, which is only in the history of branch
`linux`: `git show 54629cb:notebooks/10_redistribution.ipynb`,
`git show 54629cb:config.py`.

- **Zone totals:** `data/input/zone_targets.gpkg`, layer
  `regionbsstructuredata_zone` (VISUM structure data), reprojected to
  EPSG:25832. Seven categories come from VISUM columns (`ZONE_COLUMN_MAP`), and
  the twelve labels collapse into them (`MID_LABEL_TO_ACTIVITY`):

  | category | VISUM column(s) | labels |
  |---|---|---|
  | Workers | `SG_3_BE~17` | work, business |
  | School | `SG_4_BS` + `SG_4_GSCH` + `SG_4_WFSCH` | school |
  | University | `SG_4_HS` | university |
  | Kindergarten | `SG_4_KITA` | childcare |
  | Retail_Daily | `SG_5_EK_TB` | retail_daily, errands |
  | Retail_Non-Daily | `SG_5_EK~19` | retail_non_daily |
  | Leisure | `SG_6_FR~23` | leisure, sports, meetup, lessons |

  The zone file is not on the server, so it is **unverified** that it still
  has these columns. The `~17`, `~19` and `~23` names are truncated by an
  export, so list the file's columns first.
- **Bosserhof factors:** `BOSSERHOF_WEIGHTS` covers 47 classes, for example
  normal office 2.9, retail small scale 3.75, schools 1.0. The 06 class names
  have capitals and punctuation, such as `retail (small-scale)` and
  `Industrial operations / Production`. Lower-case them, replace every
  non-letter with a space and collapse the spaces: all 43 classes in 06 then
  match the old keys, except `others` (4 buildings), which the old
  `BOSSERHOF_NORMALIZATION_MAP` sends to `others industrial`.
- **The old method, for reference:**
  1. Workers were weighted by volume times the Bosserhof factor, with volume
     caps for some retail and large-format classes.
  2. Every other category got the building's volume split evenly over its
     categories.
  3. Each building was put in the zone containing its centroid.
  4. Each zone's total per category was split over its buildings in
     proportion to those weights.
  5. The check was that the assigned sums equal the zone totals.
- **If old code is reused:** the neighbour-zone fallback calls
  `STRtree.nearest(geom, return_distance=False, exclusive=True)`, which
  shapely 2.1.2 (in `capacity-final`) rejects with a `TypeError`;
  `query_nearest` is its replacement. The allocation loops with `iterrows`
  over zones, categories and buildings, which is slow.

### 5.3 The idea for step 08, as the user put it (2026-10-01)

- The building's amount comes from its volume, Workers included.
- Each POI in a shared building gets its part of that amount by its
  `share_in_building`, so a smaller share gets a smaller part. With a bakery
  at 0.3 and a pub at 0.7, the pub gets 70 % of the building's workers and
  the bakery 30 %. The bakery's part goes to `retail_daily`, the pub's to
  `leisure`.
- Labels are merged: a building carries its own labels and those of its
  POIs, each label once.

The details are worked out on the laptop.

## 6. Facts for the later discussion

Measured on the first 301 answers; recount them in 07.6 on the full set.

- **Label clash:** 24 POIs (8 %) carry a category their building does not.
  Decided: merge, each label once (section 5.3).
- **Several categories on one POI:** 7 POIs have two or more non-worker
  categories, for example a community centre with leisure and childcare.
- **Work-only occupants:** 28 POIs, mostly offices, have only `work` or
  `business`.

## 7. Checks on what is delivered

- every asked `poi_id` has a valid answer under `257a72e709cb`;
- the checksums in section 3 match on both machines;
- `prompt_sha(LLM_POI_SYSTEM_PROMPT)` prints `257a72e709cb` on the laptop;
- `share_in_building` sums to 1 per building over its own pairs (0 buildings
  off by more than 1e-6 today).
