# Activities and Potentials Calculation Pipeline

> **Institution:** [Institute of Transportation and Urban Engineering](https://www.tu-braunschweig.de/ivs), TU Braunschweig
> **Authors:** Mayur Patel, Lasse Bienzeisler, Bernhard Friedrich

[![Version](https://img.shields.io/badge/version-1.0.0-informational)](CITATION.cff)
[![Python](https://img.shields.io/badge/Python-3.13%20(tested)-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Code for the paper *Deriving Activities and Their Potentials at Building-Level Using Large Language Models*
(Patel, Bienzeisler, Friedrich; EWGT 2026, under review). It derives, for every building of the region of the
Regionalverband Großraum Braunschweig (Lower Saxony, Germany), which activities take place there and how many people
they attract, from official building data (LoD2 / ALKIS), OpenStreetMap (OSM) and a large language model (LLM).

## What you get

- **Activity labels** per building: zero or more of 12 labels derived from the trip purposes of the German travel
  survey MiD (`work`, `school`, `retail_daily`, `leisure`, `errands`, …; `config.LLM_ACTIVITY_LABELS`).
- **Building-use class** per building: one of 46 classes after Bosserhoff (2000), 8 main groups and 38 subclasses
  (`config.LLM_BOSSERHOF_SUBCATEGORIES`), each with a worker density per 100 m² of floor area.
- **Activity potentials** per building and per POI unit: the building's share of seven zone totals of the region's
  travel demand model (workers; school, university and kindergarten places; daily and non-daily shopping; leisure),
  distributed by occupied floor area, plus visitor estimates for five activities without a zone total.

A rule-based classifier in [`rules/`](rules/) classifies the same buildings without an LLM; it is the benchmark in
the paper.

## Workflow

![Pipeline overview](figures/pipeline_overview.png)

*The four stages of the method (Fig. 1 of the paper); dashed boxes are the benchmark classifier and the optional
region calibration. In this code the region calibration is part of [`config.py`](config.py) and always applied, and
a POI unit's share of its building is its polygon area × its height ([`REDISTRIBUTION.md`](REDISTRIBUTION.md)).*

| Step | Notebook | Paper section | What it does | Main output (`data/output/`) |
|---|---|---|---|---|
| 01 | [`01_osm_extraction`](pipeline/01_osm_extraction.ipynb) | 4.2 | Clips the OSM extract to the study area; extracts activity-related POIs (27,843), building footprints and land use | `01_all_pois.gpkg`, `01_all_buildings_osm.gpkg`, `01_landuse_osm.gpkg` |
| 02 | [`02_alkis_extraction`](pipeline/02_alkis_extraction.ipynb) | 4.1 | Selects, downloads and merges the region's LoD2 tiles | `02_alkis_lod2_raw.gpkg` |
| 03 | [`03_alkis_refinement`](pipeline/03_alkis_refinement.ipynb) | 4.1 | Classifies LoD2 surfaces into ground, wall and roof; derives footprints, eaves and ridge heights per building (869,316) | `03_alkis_by_building.gpkg` |
| 04 | [`04_semantic_enrichment`](pipeline/04_semantic_enrichment.ipynb) | 4.1, 4.2 | Adds the 50,011 OSM footprints missing from ALKIS (919,327 buildings in all), attaches functions, names and land use, places POIs on buildings, keeps the 39,786 buildings of activity | `04_buildings_enriched.gpkg` |
| 05 | [`05_llm_classification`](pipeline/05_llm_classification.ipynb) | 4.3 | Builds one text record per building and asks the LLM for its labels and class (full run: [`scripts/05_run_llm.py`](scripts/05_run_llm.py)) | `05_llm_answers.jsonl` |
| 06 | [`06_llm_assembly`](pipeline/06_llm_assembly.ipynb) | 4.3 | Puts the answers on the buildings; adds `work` by rule | `06_buildings_classified.gpkg` |
| 07 | [`07_poi_classification`](pipeline/07_poi_classification.ipynb) | 4.3 | Asks the LLM for the labels of each POI in a shared building (full run: [`scripts/07_run_llm_pois.py`](scripts/07_run_llm_pois.py)) | `07_building_pois_classified.gpkg` |
| 08 | [`08_redistribution`](pipeline/08_redistribution.ipynb) | 4.4 | Derives storeys and occupied floor area; distributes the zone totals; estimates the five unconstrained activities | `08_redistribution.gpkg` |
| rules | [`classify_buildings`](rules/classify_buildings.ipynb) | 4.3 | Benchmark classifier, after step 04 | `rules_classification.parquet` |

Each notebook opens with its purpose, inputs, outputs, requirements and steps, and keeps the outputs of the run
behind the paper, apart from a few cells listed in [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md); notebook 08 has none,
because its outputs derive from the restricted zone totals. Every setting is in
[`config.py`](config.py), with its reasoning in the comments; shared code is in [`lib/`](lib/).
[`REDISTRIBUTION.md`](REDISTRIBUTION.md) explains step 08.

## Quick start

**1. Install.** Python 3.13 (the only version tested), the packages of [`requirements.txt`](requirements.txt), and
two system tools: `osmium` (step 01) and GDAL's `ogr2ogr` (step 02).

```bash
git clone https://github.com/TUBS-IVS/Activities-and-Potentials-Calculation-Pipeline.git
cd Activities-and-Potentials-Calculation-Pipeline
conda create -n capacity python=3.13 && conda activate capacity
conda install -c conda-forge osmium-tool gdal
pip install -r requirements.txt
python -m ipykernel install --user --name capacity   # the Jupyter kernel for the notebooks
pytest rules/tests                                   # 167 tests of the rule classifier, should pass
```

**2. Get the data.** Place the inputs in `data/input/`, or point the environment variable `CAPACITY_INPUT_DIR` to
the folder that holds them. [`DATA.md`](DATA.md) gives each input's version, source, terms and expected file name.

| Input | Version used | Access |
|---|---|---|
| OpenStreetMap extract of Lower Saxony (`niedersachsen-260910.osm.pbf`) | data up to 2026-09-10T20:21Z | open: [Geofabrik](https://download.geofabrik.de/europe/germany/niedersachsen.html), ODbL |
| LoD2 building models: tile index `lgln-opengeodata-lod2.geojson`, tiles downloaded by step 02 | data currency 2024-05 to 2024-08; tiles downloaded 2026-09-08 | open: [LGLN OpenGeoData](https://opengeodata.lgln.niedersachsen.de/), CC BY 4.0 |
| ALKIS land use (`FS_LN_03_NI_260101.gpkg`) | reference date 2026-01-01 | open: [LGLN STAC catalogue](https://alkis.stac.lgln.niedersachsen.de/collections/alkis-landnutzung), CC BY 4.0 |
| Study-area polygon (`regionalverband_area.gpkg`) | — | any polygon of the study area |
| Reference tables of step 04 (ALKIS function codelist, activity map per code) | — | **included** in [`data/reference/`](data/reference/) |
| Zone totals (`zone_targets.gpkg`, VISUM structure data, 880 zones), step 08 only | — | **restricted**: supplied by the Regionalverband Großraum Braunschweig; not part of this repository |

**3. Set up the LLM.** Steps 05 and 07 call the KI-Toolbox of TU Braunschweig (`LLM_API_URL`, model
`gpt-oss-120b` in `LLM_MODEL`), which is open to members of TU Braunschweig only. Put your token in the environment
variable `TU_KI_TOOLBOX_TOKEN` or in a file `.env` in the repository root:

```
TU_KI_TOOLBOX_TOKEN=<your token>
```

`.env` is git-ignored; never commit it or write the token into a notebook or `config.py`. To use another chat
endpoint, change `LLM_API_URL` and `LLM_MODEL` in `config.py` and adapt the request in
[`lib/llm_client.py`](lib/llm_client.py).

**4. Run.** Open the notebooks with the `capacity` kernel and run them in the order of the table. The two full LLM
runs are scripts: `scripts/05_run_llm.py` after notebook 05, and `scripts/07_run_llm_pois.py` between sections 5 and
6 of notebook 07. The rules notebook can run any time after step 04. To run a notebook without opening it:

```bash
jupyter nbconvert --to notebook --execute pipeline/01_osm_extraction.ipynb \
    --output-dir <folder outside the repository> \
    --ExecutePreprocessor.kernel_name=capacity --ExecutePreprocessor.timeout=-1
```

[`REPRODUCIBILITY.md`](REPRODUCIBILITY.md#regenerating-the-outputs) gives the full procedure step by step.

## Tips

- **Start without the LLM.** Steps 01–04 and the rules notebook need only open data and give the buildings of
  activity with their POIs, functions, land use and rule-based labels and classes. Look at the step-04 output in
  QGIS before you call the LLM.
- **Try the LLM on a sample first.** Section 5 of notebook 05 asks the model for 10 sample buildings, and notebook 07
  for 26 sample POIs (`--sample` in the scripts does the same). Check the answers before the full run.
- **Plan the full runs.** The building run made 34,993 calls at about 9 s each (about 8 days); the POI run 7,864
  calls (about 11 h). Start the scripts on a machine that stays on, e.g.
  `nohup python scripts/05_run_llm.py > data/output/05_llm_run.log 2>&1 &`. They save every answer as it arrives
  and continue where they stopped when restarted. `--limit N` stops after N calls; `--workers N` sends N requests at
  a time (ask the endpoint's operators first).
- **Keep the answer files.** `05_llm_answers.jsonl` and `07_llm_poi_answers.jsonl` store each answer with the hash of
  the prompt it was made with, and answers are read back only under that prompt; a changed prompt in `config.py`
  means new calls.
- **Runtimes and disk.** Without the LLM runs, steps 01–08 and the rules notebook took about 80 minutes on a Windows
  laptop; step 02 writes about 5 GB. Times per step are in [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md#execution-order).
- **Compare outputs by value.** Re-running a step can change the bytes of a GeoPackage without changing its content.
- **Keep restricted results private.** Everything step 08 writes, and executed copies of notebook 08, contain values
  derived from the zone totals. Do not publish them.
- **Another study area.** Replace the inputs and the study-area polygon. For another zone model, set the layer, id
  and column names listed in [`DATA.md`](DATA.md#zone-totals-step-08). Settings in `config.py` that hold published
  facts of the Braunschweig region (staff numbers of large institutions, retail floor areas of shopping centres,
  hand-checked building lists) must be replaced or removed ([`REDISTRIBUTION.md`](REDISTRIBUTION.md#region-calibration)).

## What runs without the restricted data

| Available | What you can run | What you get |
|---|---|---|
| Open data only | steps 01–04 and `rules/` | buildings of activity with their POIs, functions and land use; rule-based labels and classes |
| Open data and an LLM endpoint | steps 01–07 and `rules/` | LLM labels and classes per building, labels per POI; results will differ from the paper's (see Limitations) |
| Open data, an LLM endpoint and lawful access to the zone totals | steps 01–08 | the activity potentials |

Step 08 stops at its input check without `zone_targets.gpkg` and writes nothing. Its open-data parts (storeys, floor
area, visitor estimates) are computed inside step 08 together with the allocation, so this version offers no
open-data estimate of potentials.

## Outputs

All outputs go to `data/output/` (git-ignored). The final output, `08_redistribution.gpkg`, has three layers:

- `buildings` (39,786): class, labels, storeys, floor area, occupied floor area, `assigned_<category>` for the seven
  zone categories, `value_<label>` for the five estimated activities, `value_assumed`;
- `pois` (7,864 POI units of shared buildings): the same values;
- `zones`: each zone's total `target_<category>` and the sum placed on its buildings `assigned_<category>`.

Column names write `Retail_Non-Daily` as `Retail_Non_Daily`. The outputs of the other steps are in the step table and
in each notebook's header.

## Limitations

- The zone totals are restricted, so the activity potentials can be reproduced only with lawful access to them.
- The LLM endpoint offers no temperature or seed control; re-running steps 05 and 07 can give different answers. The
  answers behind the paper are not distributed.
- The open inputs are served in their current release; the versions above must be obtained to rebuild the same data.
- The region calibration in `config.py` holds facts of the Braunschweig region and does not transfer to other regions.
- The five unconstrained activities are estimates from visitor rates per floor area, partly assumed; they are not
  scaled to any total.

A transferable version of the pipeline for other regions is under development.

## Reproducibility

This is **Version 1** (tag [`v1.0.0`](https://github.com/TUBS-IVS/Activities-and-Potentials-Calculation-Pipeline/releases/tag/v1.0.0)).
The paper's results were produced with the code at commit
[`b751cd9`](https://github.com/TUBS-IVS/Activities-and-Potentials-Calculation-Pipeline/commit/b751cd9a6c8a74886ae82bc00df5fe6b7402641c);
later commits change no calculation. A rerun of steps 01–08 and the rules notebook from a fresh clone, with the
stored LLM answers, reproduced the stored outputs. [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) has the procedure,
runtimes, what can and cannot be reproduced, and what was checked. The paper's validation data are not part of this
repository.

## Repository structure

```
.
├── config.py              ← every setting, with the reasoning behind it
├── pipeline/              ← steps 01–08 as notebooks
├── lib/                   ← shared code: LLM record, routing, client and run; floor-area, label and headcount rules of step 08
├── scripts/               ← full LLM runs (05, 07); optional QGIS review project of step 08 (run with QGIS's Python)
├── rules/                 ← rule-based classifier: rule_utils.py, its config, notebook, tests
├── figures/               ← the pipeline overview (Fig. 1 of the paper)
├── data/
│   ├── input/             ← input data (not tracked)
│   ├── output/            ← step outputs (not tracked)
│   ├── reference/         ← the two reference tables of step 04 (tracked)
│   └── experimental_extract/  ← QGIS review layers (not tracked)
├── DATA.md                ← input data: version, source, terms, expected path
├── REDISTRIBUTION.md      ← method note on step 08
├── REPRODUCIBILITY.md     ← how to regenerate the outputs, runtimes, what was checked
├── CITATION.cff, LICENSE
└── requirements.txt
```

## Licence

The code, notebooks and documentation are released under the [MIT Licence](LICENSE). The licence does not cover
the input data, which keep their own terms:

- OpenStreetMap: © OpenStreetMap contributors, [Open Database Licence (ODbL)](https://opendatacommons.org/licenses/odbl/).
- LoD2 building models and ALKIS land use: © GeoBasis-DE/LGLN, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/);
  results derived from them carry the source note "© GeoBasis-DE/LGLN <year of download>, Daten geändert".
- Zone totals: Regionalverband Großraum Braunschweig; not public, not redistributable without their permission.

The test sample `rules/tests/data/sample_condensed_buildings.parquet` (30 buildings of the region) is derived from
OpenStreetMap and LGLN data and is not covered by the MIT Licence: © OpenStreetMap contributors, ODbL;
© GeoBasis-DE/LGLN, CC BY 4.0, Daten geändert ([`DATA.md`](DATA.md#data-included-for-the-rule-classifier)).

## Citation

Please cite the software via [`CITATION.cff`](CITATION.cff) (GitHub's "Cite this repository" button) and the paper:
Patel, M., Bienzeisler, L., Friedrich, B.: *Deriving Activities and Their Potentials at Building-Level Using Large
Language Models*, EWGT 2026 (under review).

## Acknowledgements

This work is part of the **TRANSFORMPATHS** project, funded by the Federal Ministry of Research, Technology and Space
(BMFTR) within the framework of "Research for Sustainability" (FONA), under grant number **01UV2574A**. The authors
thank the [Regionalverband Großraum Braunschweig](https://www.regionalverband-braunschweig.de/) for data provision and
the Gauß-IT-Zentrum of TU Braunschweig for LLM infrastructure.

## Contact

**Mayur Patel**, Institute of Transportation and Urban Engineering, TU Braunschweig
m.patel@tu-braunschweig.de · Tel.: +49-531-391-66809
