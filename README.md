# Activities and Potentials Calculation Pipeline

> **Institution:** [Institute of Transportation and Urban Engineering](https://www.tu-braunschweig.de/ivs), TU Braunschweig
> **Authors:** Mayur Patel, Lasse Bienzeisler, Bernhard Friedrich

[![Python](https://img.shields.io/badge/Python-3.13%20(tested)-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Agent-based travel demand models need to know **which activities take place in each building and how many**: how many
workers, pupils, shoppers or visitors a building holds. Such data are rarely available at building level; travel
demand models usually hold them only as totals per traffic zone. This pipeline derives, for every building of a
region, the activities it serves and its share of the zone totals, from official building and cadastral data,
OpenStreetMap (OSM) and a large language model (LLM).

For each building it produces:

- its **activity labels**: zero or more of 12 activity labels derived from the trip purposes of the German travel
  survey MiD (`work`, `school`, `retail_daily`, `leisure`, `errands`, …; `config.LLM_ACTIVITY_LABELS`);
- its **building-use class**: one of 46 classes after Bosserhoff (2000), 8 main groups and 38 subclasses
  (`config.LLM_BOSSERHOF_SUBCATEGORIES`), each with a typical worker density;
- its **activity potentials**: its share of seven zone totals (workers; school, university and kindergarten places;
  daily and non-daily shopping; leisure), and an estimate for five further activities that have no zone total.

The pipeline was built and run for the area of the Regionalverband Großraum Braunschweig (Lower Saxony, Germany). It
accompanies the paper *Deriving Activities and Their Potentials at Building-Level Using Large Language Models*
(Patel, Bienzeisler, Friedrich; EWGT 2026, under review). A region-independent version is under development (not yet
public).

---

## The pipeline

![Pipeline overview](figures/pipeline_overview.png)

*Fig. 1 of the paper: the four stages (colours) and the steps of each. Dashed: the benchmark classifier and the
region calibration. In this implementation step 07 asks the LLM for the POIs' activity labels only; a POI's
building-use class is assigned by rule in step 08 from its OSM use (else the building's class applies). The region calibration is part of the
configuration and always applied (see [`REDISTRIBUTION.md`](REDISTRIBUTION.md)).*

| Paper section | Steps | What happens |
|---|---|---|
| 4.1 Geometric preprocessing | 02, 03, and section 6 of 04 | LoD2 surfaces are classified into ground, wall and roof; the ground surface becomes the footprint; ridge and eaves heights are kept; parts under 1 m² are removed; parts are aggregated per ALKIS building (869,316). OSM footprints that ALKIS covers by less than 10 % are added (919,327). |
| 4.2 Semantic enrichment and activity filtering | 01, 04 | 27,843 activity-related OSM POIs (as points and polygons) are extracted; ALKIS function and name, the OSM footprint tag and name, and ALKIS and OSM land use are attached; POIs are placed on buildings; buildings that are not a place of activity are dropped. 39,786 buildings remain. |
| 4.3 LLM-based and rule-based classification | 05, 06, 07, [`rules/`](rules/) | One text record per building; the LLM returns its activity labels and building-use class; `work` is added by rule; POIs in shared buildings are classified one by one. A deterministic rule-based classifier serves as benchmark. |
| 4.4 Activity-informed disaggregation | 08 | Zone totals are distributed over the buildings and their POI units by occupied floor area; the five activities without a zone total are estimated from floor area and visitor rates. |

| Step | Notebook | What it does | Main output (`data/output/`) |
|---|---|---|---|
| 01 | [`01_osm_extraction`](pipeline/01_osm_extraction.ipynb) | Clips the OSM extract to the study area; extracts the POIs that describe an indoor activity (roles point, footprint, site, unit), every OSM building footprint and the OSM land use | `01_all_pois.gpkg`, `01_all_buildings_osm.gpkg`, `01_landuse_osm.gpkg` |
| 02 | [`02_alkis_extraction`](pipeline/02_alkis_extraction.ipynb) | Selects, downloads and merges the region's LoD2 tiles (LGLN open data) | `02_alkis_lod2_raw.gpkg` |
| 03 | [`03_alkis_refinement`](pipeline/03_alkis_refinement.ipynb) | Turns 3D surfaces into 2D footprints with heights and volumes, per LoD2 part and per ALKIS building | `03_alkis_buildings.gpkg`, `03_alkis_by_building.gpkg` |
| 04 | [`04_semantic_enrichment`](pipeline/04_semantic_enrichment.ipynb) | Adds function labels and land use, fills ALKIS gaps with OSM footprints, drops what is not a place of activity, and places every POI on its building | `04_buildings_enriched.gpkg` |
| 05 | [`05_llm_classification`](pipeline/05_llm_classification.ipynb) | Builds one record per building (lines by source, strongest evidence first) and asks the LLM for its activity labels and building-use class | `05_llm_answers.jsonl` |
| 06 | [`06_llm_assembly`](pipeline/06_llm_assembly.ipynb) | Puts the answers on the building polygons and adds `work` by rule | `06_buildings_classified.gpkg` |
| 07 | [`07_poi_classification`](pipeline/07_poi_classification.ipynb) | Asks the LLM, for each POI in a building with several POIs, which activities that POI serves | `07_building_pois_classified.gpkg` |
| 08 | [`08_redistribution`](pipeline/08_redistribution.ipynb) | Distributes each traffic zone's totals over its buildings and POI units by occupied floor area; estimates the five activities without a zone total | `08_redistribution.gpkg` |

Each notebook opens with what it reads, what it writes and what it needs. Run them in order; each
reads only earlier steps' outputs. Every setting is in [`config.py`](config.py), with the reasoning behind it in the
comments; shared code is in [`lib/`](lib/). The notebooks are committed with their outputs from the Braunschweig
run.

### Rule-based classifier (benchmark)

[`rules/`](rules/) classifies the same 39,786 buildings without an LLM: a deterministic rule engine with three layers
in strict order (OSM POI tags, then the ALKIS building-function code, then the OSM building tag or land use). It reads
no names, and every answer is traceable to one row of a lookup table. It reads the outputs of steps 01 and 04 and
writes `data/output/rules_classification.parquet` in seconds. See [`rules/README.md`](rules/README.md).

### How the zone totals are distributed (step 08)

- **Seven categories with a zone total** (Workers, School, University, Kindergarten, Retail_Daily, Retail_Non-Daily,
  Leisure) come from the region's travel demand model (VISUM structure data, 880 zones). Each zone total is shared
  over the eligible units in the zone: Workers by occupied floor area × the worker density of the building-use class,
  the other six by occupied floor area split evenly over the unit's categories (down-weighted to 0.25 for units
  without their own POI, name or site in the two retail categories and Leisure).
- **Five activities without a zone total** (`business`, `errands`, `sports`, `meetup`, `lessons`) are estimated, not
  constrained: the label's share of the occupied floor area × an activity-specific visitor rate per 100 m², drawn
  partly from Bosserhoff and partly from other sources (FGSV, ITE, TRICS and others).
- Labels are never merged: `errands` does not feed Retail_Daily, and `sports`, `meetup` and `lessons` do not feed
  Leisure.

Step 08 always reads the zone totals; it has no route that works from open data alone.
[`REDISTRIBUTION.md`](REDISTRIBUTION.md) explains the method in full.

---

## Quick start

```bash
git clone https://github.com/TUBS-IVS/Activities-and-Potentials-Calculation-Pipeline.git
cd Activities-and-Potentials-Calculation-Pipeline
conda create -n capacity python=3.13 && conda activate capacity
conda install -c conda-forge osmium-tool gdal
pip install -r requirements.txt

pytest rules/tests                                   # 167 tests of the rule classifier, no data needed
python rules/rule_smoke_test.py --amenity restaurant # what the rules answer for one tag
```

`osmium` (step 01) and `ogr2ogr` (step 02) are system tools, not pip packages; see
[`requirements.txt`](requirements.txt). To run the pipeline itself, place the input data (below) and run the
notebooks in `pipeline/` in order, 01 to 08.

### Data

None of the data is distributed with this repository. Place the inputs in `data/input/` (or point the environment
variable `CAPACITY_INPUT_DIR` at another folder) and the reference tables in `data/reference/`.
[`DATA.md`](DATA.md) gives each file's role, version, source and terms.

| File | Content | Version used | Access |
|---|---|---|---|
| `niedersachsen-260910.osm.pbf` | OpenStreetMap extract of Lower Saxony | data up to 2026-09-10T20:21Z | open, [Geofabrik](https://download.geofabrik.de/europe/germany/niedersachsen.html), ODbL |
| `lgln-opengeodata-lod2.geojson` | index of the LoD2 building tiles; step 02 downloads the tiles | 37,928 tiles, data currency 2024-05 to 2024-08; tiles downloaded 2026-09-08 | open, [LGLN OpenGeoData](https://opengeodata.lgln.niedersachsen.de/), CC BY 4.0 |
| `FS_LN_03_NI_260101.gpkg` | ALKIS land use (*Landnutzung*), statewide | reference date 2026-01-01 | open, [LGLN STAC catalogue](https://alkis.stac.lgln.niedersachsen.de/collections/alkis-landnutzung), CC BY 4.0 |
| `regionalverband_area.gpkg` | study-area polygon | — | any polygon of the study area |
| `zone_targets.gpkg` | traffic zones with their totals (VISUM structure data), step 08 | — | **not public**; supplied by Regionalverband Großraum Braunschweig |
| `data/reference/building_function_codelist_de_en.csv`, `data/reference/alkis_building_activity_map.csv` | ALKIS building-function codes with labels; activity map per code (step 04) | — | **not distributed** in this repository; see [`DATA.md`](DATA.md) |

### LLM access (steps 05 and 07)

Steps 05 and 07 call the KI-Toolbox of TU Braunschweig (`LLM_API_URL` in `config.py`), requesting the model
`gpt-oss-120b` (`LLM_MODEL`). The KI-Toolbox is available to members of TU Braunschweig only. Put the access token in
a `.env` file in the repository root (git-ignored):

```
TU_KI_TOOLBOX_TOKEN=...
```

Elsewhere, point `LLM_API_URL` and `LLM_MODEL` at another chat endpoint and adapt the request in
[`lib/llm_client.py`](lib/llm_client.py). Every reply is validated against a JSON schema and re-asked when invalid.
Buildings described by their cadastral class alone are grouped by class, tags, land use and size and height band,
and each group is asked once, so the 39,786 buildings of step 05 need 34,993 calls; step 07 asks for
7,864 POIs. The full runs are resumable and meant for a machine that stays on:
[`scripts/05_run_llm.py`](scripts/05_run_llm.py), [`scripts/07_run_llm_pois.py`](scripts/07_run_llm_pois.py). The
notebooks prepare the inputs, run a sample, and read the answers back.

### Optional: QGIS review project

`scripts/08_qgis_values_*.py` build and render a QGIS project of the distributed values for visual checking. They
run with QGIS's own Python and are not needed for the results.

---

## Reproducibility

The results in the paper were produced with the code at commit
[`60469fa`](https://github.com/TUBS-IVS/Activities-and-Potentials-Calculation-Pipeline/commit/60469fa22244bf4af3ed456a4d1fff4ae0eda34b)
of this repository. The stored LLM answers were made with the prompts in `config.py` at that commit. Exact paper
numbers cannot be reproduced from a clean clone: the zone totals are not public, the reference tables and the stored
LLM answers are not distributed, and the LLM endpoint offers no temperature or seed control, so new runs of steps 05
and 07 may give different answers. [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) lists what can be re-run, in which
order, how long each step takes, and what was checked.

The paper validates the classification on a sample of buildings of the region. The validation data and code are not
part of this repository.

---

## Repository structure

```
.
├── config.py              ← every setting of steps 01–08, with the reasoning behind it
├── pipeline/              ← steps 01–08 as notebooks, with their outputs
├── lib/                   ← shared code: LLM record, routing, client and run; floor-area, label and headcount rules of step 08
├── scripts/               ← long LLM runs (05, 07), the QGIS review project (08)
├── rules/                 ← rule-based classifier: rule_utils.py, its config, notebook, tests
├── figures/               ← the pipeline overview (Fig. 1 of the paper)
├── data/
│   ├── input/             ← input data (not tracked)
│   ├── output/            ← step outputs (not tracked)
│   ├── reference/         ← reference tables (not tracked)
│   └── experimental_extract/  ← QGIS review layers (not tracked)
├── DATA.md                ← input data: role, version, source, terms
├── REDISTRIBUTION.md      ← method note on step 08
├── REPRODUCIBILITY.md     ← execution order, runtimes, what can be reproduced
└── requirements.txt
```

---

## Licence

Source code, notebooks and documentation are released under the [MIT Licence](LICENSE).

The **data are not covered** and not distributed here:

- OpenStreetMap data: © OpenStreetMap contributors, [Open Database Licence (ODbL)](https://opendatacommons.org/licenses/odbl/).
- LoD2 building models and ALKIS land use: © GeoBasis-DE/LGLN, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
  Results derived from them carry the source note "© GeoBasis-DE/LGLN <year of download>, Daten geändert".
- Zone totals: provided by Regionalverband Großraum Braunschweig; not public.

## Citation

If you use this software, please cite it via [`CITATION.cff`](CITATION.cff) (GitHub's "Cite this repository" button)
and the accompanying paper (Patel, Bienzeisler, Friedrich: *Deriving Activities and Their Potentials at
Building-Level Using Large Language Models*, EWGT 2026, under review).

## Acknowledgements

This work is part of the **TRANSFORMPATHS** project, funded by the Federal Ministry of Research, Technology and Space
(BMFTR) within the framework of "Research for Sustainability" (FONA), under grant number **01UV2574A**.

The authors thank [Regionalverband Großraum Braunschweig](https://www.regionalverband-braunschweig.de/) for data
provision and the Gauß-IT-Zentrum of TU Braunschweig for LLM infrastructure.

## Contact

**Mayur Patel**
Institute of Transportation and Urban Engineering, TU Braunschweig
m.patel@tu-braunschweig.de · Tel.: +49-531-391-66809
