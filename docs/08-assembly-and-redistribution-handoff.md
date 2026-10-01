# Steps 07.6 and 08 on the laptop: from the POI answers to the redistribution

Hand-off from the Linux server (branch `linux`, 2026-10-01) to the laptop
(branch `final-pipeline`). It says what has been done, what arrives from the
server, what to build next, and what to decide before building it. Every
number was measured on the server's copies of `06_buildings_classified.gpkg`
and `01_all_pois.gpkg` (checksums in section 3). Anything that could not be
checked on the server is marked **unverified**.

## 1. Where the pipeline stands

| step | where | state |
|---|---|---|
| 01–04 extraction, enrichment, POI split | laptop | done: `04_buildings_enriched.gpkg` |
| 05 building classification, 34,993 calls | server | done 2026-09-23, prompt `795433ed9feb` |
| 06 assembly of the building answers | laptop | done (`final-pipeline` 1cfdad0): `06_buildings_classified.gpkg` |
| 07 POI classification, 7,864 calls | server | **running** since 2026-10-01 afternoon, about 5 s per call, ends around the morning of 2026-10-02 (`eta_at` in `07_llm_poi_status.json`); prompt `257a72e709cb` |
| 07.6 assembly of the POI answers | laptop | to write: notebook 07 section 6 (section 4 below) |
| 08 redistribution | laptop | to write: design in section 5 below |

What was done on the server for step 07 (branch `linux`, commits `e886b6f`
and `33458f1`):

- **Generalised, not copied.** `lib/llm_client.py` and `lib/llm_run.py` now take
  the prompt, the output schema and the id column as arguments. Step 05 keeps
  its defaults and its behaviour: its 39,786 records re-render byte for byte.
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

## 2. Who gets labels from where

Buildings that shared the same input and were asked once are already
labelled. Step 06 did that: **all 39,786 buildings carry `mid_labels`**, none
empty. Step 07.6 applies the same idea to POIs: wherever the model would only
see the same evidence again, its earlier answer is reused instead of asking.

| units | count | labels come from | done in |
|---|---|---|---|
| buildings with their own step-05 call | 33,734 | their own answer | 06 |
| class-only buildings grouped in signatures (same cadastre class, footprint, land use, area band, height band) | 6,052 in 1,259 signatures | the answer for the signature's median-area member: 1,259 asked, 4,793 copied (`answer_copied`; `answered_by` names the member asked). Copied answers: 4,686 medium, 82 low, 25 high confidence | 06 |
| buildings without own POIs | 22,329 (12,646 with only a site around them, 9,683 with nothing) | the building's `mid_labels` | 06 |
| sole occupants (`share_in_building = 1`) | 14,542 POIs | their building's `mid_labels`: their evidence was the building's call | 07.6, a copy |
| POIs sharing a building | 7,864 asked, of 8,091 pairs on 2,915 buildings | their own step-07 answer, plus `work` by rule | 07.6 |
| not asked: landuse areas, vacant units | 183 + 44 pairs | none, they are not occupants | 07.6 marks them |
| site rows (`how = 'site'`) | 18,652 | none: the site's purpose is in the building's labels; `share_of_site` is an audit column | — |

Two multi-occupant buildings have no asked POI at all, because all their
pairs are landuse or vacant (`DENIAL0300008jmn`, `DENIAL0600001zkC`). Their
categories get the fallback weight of section 5.2.

## 3. What comes from the server

### Data, once the run has finished

The run has finished when its log ends with `full: done N, ok N, failed 0` and
`pgrep -f 'python scripts/07_run_llm_pois.py'` prints nothing on the server.
If failures remain, start the script again there. It asks only what has no
valid answer yet.

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
`certutil -hashfile <file> SHA256` on the laptop. The laptop's inputs must
be the files the step-07 records were built from:

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

## 4. Step 07.6: the POI answers onto the pairs (notebook 07, section 6)

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
2. **Labels on every own pair** (`how != 'site'` in `building_pois`):
   - `poi_llm_labels`: the model's labels, as given;
   - `poi_mid_labels`: plus `work` by rule (`lib/llm_run.apply_work_rule`),
     as a set ordered like `LLM_ACTIVITY_LABELS` and joined with `;`, the same
     form as the buildings' `mid_labels`;
   - `poi_type`, `poi_confidence`, `poi_reason`: `interpreted_type`,
     `confidence`, `reason`;
   - `poi_labels_from`: `llm` for an asked POI, `building` for a sole occupant
     (it takes its building's `mid_labels`), `not_asked` for a landuse area or
     vacant unit (labels empty). Site rows stay empty.
3. **Disagreement table:** per `poi_use`, the POI categories (after the
   12-to-7 collapse in section 5) that its building does not carry. Early
   result from the first 301 answers: 24 POIs (8 %) disagree, for example a
   shop answered `retail_daily` in a building labelled `work` only. Another
   28 are work-only occupants such as offices, and 7 have two or more
   non-worker categories. This table decides question 2 in section 6.
4. **Write** `07_building_pois_classified.gpkg`. The name is a proposal and
   still open. It holds layer `building_pois` with the new columns, plus the
   06 `buildings` layer copied unchanged, so that step 08 reads one file.

## 5. Step 08: the redistribution

### 5.1 What the previous pipeline did

The previous pipeline's notebooks 10 and 11 and its `config.py` are only in
the history of branch `linux`, commit `54629cb`:
`git show 54629cb:notebooks/10_redistribution.ipynb` and
`git show 54629cb:config.py`.

- **Zone totals:** `data/input/zone_targets.gpkg`, layer
  `regionbsstructuredata_zone` (VISUM structure data), reprojected to
  EPSG:25832. Seven categories come from VISUM columns (`ZONE_COLUMN_MAP`), and
  the twelve labels collapse into them (`MID_LABEL_TO_ACTIVITY`). The step-07
  hand-off §7 uses the same collapse.

  | category | VISUM column(s) | labels |
  |---|---|---|
  | Workers | `SG_3_BE~17` | work, business |
  | School | `SG_4_BS` + `SG_4_GSCH` + `SG_4_WFSCH` | school |
  | University | `SG_4_HS` | university |
  | Kindergarten | `SG_4_KITA` | childcare |
  | Retail_Daily | `SG_5_EK_TB` | retail_daily, errands |
  | Retail_Non-Daily | `SG_5_EK~19` | retail_non_daily |
  | Leisure | `SG_6_FR~23` | leisure, sports, meetup, lessons |

- **Weights per building and category.** Workers uses volume times
  `BOSSERHOF_WEIGHTS[class]`, which covers 47 classes: for example normal
  office 2.9, retail small scale 3.75, schools 1.0. Volume was capped at the
  class's 75th percentile for six retail and gastronomy classes, and at the
  95th for five large-format classes. Every other category got the volume
  divided by the number of the building's non-worker categories, an even
  split.
- **Zone of a building:** the zone that contains its centroid.
- **Allocation, per category and zone:** each building gets the zone total
  times its weight, divided by the summed weight of the pool. The pool is the
  zone's buildings with that category. If that is empty, it is the
  neighbouring zones' buildings, and failing that, every building with the
  category.
- **Check:** per zone and category, the assigned sum equals the zone total.
  Notebook 11 then summed the buildings back to zones.
- **Outputs:** `10_building_level_redistributed.gpkg` with
  `assigned_<category>` per building, an allocation log, a validation CSV, and
  `11_final_results.gpkg` with `buildings` and `zones` layers.

Three things not to carry over:

- The neighbour fallback calls `STRtree.nearest(geom, return_distance=False,
  exclusive=True)`. Shapely 2.1.2, the version in `capacity-final`, rejects
  those arguments with a `TypeError`, so that branch could never have run.
  Use `query_nearest(geom, exclusive=True)` or the touching zones instead.
- It loops with `iterrows` over zones, categories and candidates. Group by
  zone and category instead.
- A centroid can fall outside a concave footprint. Use
  `representative_point()`.

### 5.2 What changes now

The weight is computed per **unit**. A unit is an own POI where the building
has POIs, and the building itself where it has none. A building's value is
the sum over its units, and POI values come out directly, which is what the
step-07 labels are for: the office's share feeds Workers only, the shop's
share feeds its retail category.

| unit | count | share `s` | categories |
|---|---|---|---|
| asked POI in a shared building | 7,864 | `share_in_building`, used as step 04.5 computed it | the POI's own (question 2) |
| sole occupant | 14,542 | 1 | the building's |
| building without own POIs | 22,329 | 1 | the building's |
| landuse area or vacant unit | 227 pairs | not a unit: its share carries no activity (1.33 M and 0.16 M m³, 0.5 % of all volume) | — |

The shares are final: step 04.5 split each building among its own POIs by
pseudo-volume (`split_area_m2` × `split_h_m`), and `share_in_building` sums to
1 per building. Step 08 uses it as it is and recomputes nothing.

- **Workers**, per building: `volume_3d_m3 × factor(bosserhof_class)`,
  uncapped in run 1 (step-07 hand-off §7). Each POI's part is the building's
  Workers value times its `share_in_building`, because every occupant carries
  `work`. The share of a landuse area or vacant unit stays with the building.
- **Any other category `c`**, per unit:
  `w(unit, c) = volume_3d_m3 × s × [c in categories(unit)] × 1/k`. Here `k` is
  the unit's number of non-worker categories after the collapse, or 1 if each
  category gets the full share (question 1). A gym labelled sports and lessons
  has one category, Leisure, so `k = 1`.
- **A category the building carries but none of its asked POIs does:** the
  previous even split, the volume divided by the building's number of
  non-worker categories. It is never zero (§7). This also covers the two
  buildings with no asked POI.
- **Bosserhof factor:** the 06 class names have capitals and punctuation, for
  example `retail (small-scale)` and `Industrial operations / Production`.
  Lower-case them, replace every non-letter with a space and collapse the
  spaces. All 43 classes in 06 then match the old keys except `others`
  (4 buildings), which the old `BOSSERHOF_NORMALIZATION_MAP` sends to
  `others industrial`. Assert that no factor is missing.

### 5.3 Config: a STEP 08 block

Port these from `git show 54629cb:config.py`: `ZONE_TARGETS_FILE`,
`ZONE_LAYER`, `ZONE_COLUMN_MAP`, `ZONE_ACTIVITY_COLUMNS`,
`MID_LABEL_TO_ACTIVITY`, `BOSSERHOF_WEIGHTS`, `BOSSERHOF_NORMALIZATION_MAP`,
`STRICT_CAP_CLASSES` and `LARGE_FORMAT_CAP_CLASSES`. Then add the output
paths. The zone file is not on the server, so it is **unverified** that it
still has these columns. The `~17`, `~19` and `~23` names are truncated by an
export, so list the file's columns first.

### 5.4 Outputs (proposal)

`08_redistribution.gpkg` with three layers. Layer `buildings`: `building_id`,
`zone_id`, `volume_3d_m3`, `mid_labels`, `bosserhof_class`, the factor,
`w_<category>` and `assigned_<category>`. Layer `pois`: `building_id`,
`poi_id`, `s`, `poi_mid_labels` and `assigned_<category>`. Layer `zones`: the
zone total against the assigned sum, per category. Add
`08_redistribution_validation.csv` beside it.

## 6. Decisions to take before writing step 08

| # | question | options | measured |
|---|---|---|---|
| 1 | A unit with several non-worker categories | **even split `1/k`**: the previous pipeline's rule and the fallback's, so a unit's non-worker weight sums to its volume (recommended). Or the **full share to each**, as the step-07 hand-off §7 says | 7 of the first 301 answered POIs |
| 2 | A POI category its building does not carry | **drop it**: the building is the authority (§7). Or **keep it** for that POI's share: the occupant-level answer saw the occupant, the building's call saw everything at once | 24 of 301 (8 %) |
| 3 | Workers caps | none in run 1 (§7), or the old 75th/95th percentile caps | — |
| 4 | File names of 07.6 and 08 | the proposals above | — |

Decided by the user on 2026-10-01: the shares are `share_in_building` as step
04.5 computed them, with no renormalisation.

For scale: all buildings hold 277.2 M m³, and the 2,915 multi-occupant
buildings, the only ones where POI labels change anything, hold 64.6 M m³
(23.3 %).

## 7. Checks to keep as assertions

- every asked `poi_id` has a valid answer under `257a72e709cb`;
- `share_in_building` sums to 1 per building over its own pairs (0 buildings
  off by more than 1e-6 today) and is used unchanged;
- every building has a Bosserhof factor, and a zone or a logged reason for
  having none;
- every category a building carries gets a weight above zero in at least one
  of its units;
- per zone and category, the assigned sum equals the zone total;
- per building and category, the building's value equals the sum over its
  POIs plus any fallback part; for Workers, its POIs together get the
  building's value times the sum of their shares.
