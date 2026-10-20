# Activities and Potentials Calculation Pipeline

> **Institution:** [Institute of Transportation and Urban Engineering](https://www.tu-braunschweig.de/isv), TU Braunschweig
> **Author:** Mayur Patel

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Agent-based travel demand models need to know **what happens in each building and how much of it**: how many workers,
pupils, shoppers or visitors each building holds. Such data are rarely available. This pipeline derives them for every
building of a region from open and official data, and shares the region's zone-level activity totals out over the
buildings.

For each building it produces:

- the **activities** that happen inside — the 12 MiD activity labels (`work`, `school`, `retail_daily`, `leisure`, …);
- its **Bosserhof class** — the kind of workplace it is (`normal office`, `schools`, `retail small scale`, …);
- its **share of each zone total** — workers, school, university and kindergarten places, daily and non-daily
  shopping, leisure — in proportion to the floor area each occupant uses.

It was built and run for the region of the Regionalverband Großraum Braunschweig (Lower Saxony, Germany).

---

## The pipeline

```
 OSM extract                LoD2 / ALKIS tiles
      │                            │
 01 OSM extraction          02 ALKIS extraction ──> 03 ALKIS refinement
      │                                                   │
      └─────────────────> 04 semantic enrichment <────────┘
                           (which buildings, which POIs on them)
                                   │
              ┌────────────────────┴──────────────────────┐
              │                                           │
 05 LLM classification ──> 06 assembly           rules/  (alternative:
              │                                   deterministic classifier)
 07 POI classification
              │
 08 redistribution  <── zone totals
```

| Step | Notebook | What it does | Main output (`data/output/`) |
|---|---|---|---|
| 01 | [`01_osm_extraction`](pipeline/01_osm_extraction.ipynb) | Clips the OSM extract to the study area; extracts the POIs that describe an indoor activity, every OSM building footprint and the OSM land use | `01_all_pois.gpkg`, `01_all_buildings_osm.gpkg`, `01_landuse_osm.gpkg` |
| 02 | [`02_alkis_extraction`](pipeline/02_alkis_extraction.ipynb) | Selects, downloads and merges the region's LoD2 tiles (LGLN open data) | `02_alkis_lod2_raw.gpkg` |
| 03 | [`03_alkis_refinement`](pipeline/03_alkis_refinement.ipynb) | Turns 3D surfaces into 2D footprints with heights and volumes, per LoD2 part and per ALKIS building | `03_alkis_buildings.gpkg`, `03_alkis_by_building.gpkg` |
| 04 | [`04_semantic_enrichment`](pipeline/04_semantic_enrichment.ipynb) | Adds function labels and land use, fills ALKIS gaps with OSM footprints, drops what is not a place of activity, and places every POI on its building | `04_buildings_enriched.gpkg` |
| 05 | [`05_llm_classification`](pipeline/05_llm_classification.ipynb) | Builds one compact record per building and asks an LLM for its activity labels and Bosserhof class | `05_llm_answers.jsonl` |
| 06 | [`06_llm_assembly`](pipeline/06_llm_assembly.ipynb) | Puts the answers on the building polygons and adds `work` by rule | `06_buildings_classified.gpkg` |
| 07 | [`07_poi_classification`](pipeline/07_poi_classification.ipynb) | Asks the LLM, per occupant of a shared building, which activities that occupant serves | `07_building_pois_classified.gpkg` |
| 08 | [`08_redistribution`](pipeline/08_redistribution.ipynb) | Shares each traffic zone's targets out over its buildings and occupants by occupied floor area; zone totals are kept exactly | `08_redistribution.gpkg` |

Each notebook opens with what it reads, what it writes, what it needs and how long it takes. Run them in order; each
reads only earlier steps' outputs. Settings for every step are in [`config.py`](config.py); shared code is in
[`lib/`](lib/).

### Rule-based classifier (alternative to steps 05–06)

[`rules/`](rules/) classifies the same buildings with a deterministic rule engine instead of an LLM: from OSM POI tags,
the ALKIS building-function code and OSM building / land-use tags, with every answer traceable to one row of a lookup
table. It reads the outputs of steps 01 and 04 and writes `data/output/rules_classification.parquet` in seconds. See
[`rules/README.md`](rules/README.md).

---

## Setup

```bash
git clone https://github.com/TUBS-IVS/Activities-and-Potentials-Calculation-Pipeline.git
cd Activities-and-Potentials-Calculation-Pipeline
conda create -n capacity python=3.13 && conda activate capacity
conda install -c conda-forge osmium-tool gdal
pip install -r requirements.txt
```

`osmium` (step 01) and `ogr2ogr` (step 02) are system tools, not pip packages; see
[`requirements.txt`](requirements.txt).

### Input data

Place in `data/input/` (or point the environment variable `CAPACITY_INPUT_DIR` at another folder). None of it is
distributed with this repository.

| File | Content | Source |
|---|---|---|
| `regionalverband_area.gpkg` | the study-area polygon | your region |
| `niedersachsen-*.osm.pbf` | OpenStreetMap extract (file name in `config.OSM_PBF_FILE`) | [Geofabrik](https://download.geofabrik.de/europe/germany/niedersachsen.html) |
| `lgln-opengeodata-lod2.geojson` | index of the LoD2 building tiles; step 02 downloads the tiles | [LGLN OpenGeoData](https://opengeodata.lgln.niedersachsen.de/) |
| `FS_LN_03_NI_260101.gpkg` | ALKIS land use (*Landnutzung*), statewide | [LGLN STAC catalogue](https://alkis.stac.lgln.niedersachsen.de/collections/alkis-landnutzung) |
| `zone_targets.gpkg` | traffic zones with their activity targets (VISUM structure data), step 08 | Regionalverband Großraum Braunschweig — not public |

### LLM access (steps 05 and 07)

Steps 05 and 07 call the KI-Toolbox of TU Braunschweig (`LLM_API_URL` in `config.py`), requesting the model
`gpt-oss-120b`. Put the token in a `.env` file in the repository root (git-ignored):

```
TU_KI_TOOLBOX_TOKEN=...
```

Outside TU Braunschweig, point `LLM_API_URL` and `LLM_MODEL` in `config.py` at another chat endpoint and adapt the
request in [`lib/llm_client.py`](lib/llm_client.py). Every reply is validated against a JSON schema and re-asked when
invalid. The full runs (39,786 buildings in step 05, 7,864 POIs in step 07) are resumable and meant for a machine that
stays on: [`scripts/05_run_llm.py`](scripts/05_run_llm.py), [`scripts/07_run_llm_pois.py`](scripts/07_run_llm_pois.py).
The notebooks prepare the inputs, run a sample, and read the answers back.

### Optional: QGIS review project

`scripts/08_qgis_values_*.py` build and render a QGIS project of the redistributed values for visual checking. They run
with QGIS's own Python and are not needed for the results.

---

## Repository structure

```
.
├── config.py              ← every setting of steps 01–08, with the reasoning behind it
├── pipeline/              ← the steps 01–08 as notebooks with their outputs
├── lib/                   ← shared code: LLM record, routing, client and run; floor-area and label rules of step 08
├── scripts/               ← long LLM runs (05, 07), the QGIS review project (08)
├── rules/                 ← rule-based classifier: rule_utils.py, its config, notebook, tests
├── data/
│   ├── input/             ← input data (not tracked)
│   ├── output/            ← step outputs (not tracked)
│   ├── reference/         ← region reference tables (not tracked)
│   └── experimental_extract/  ← QGIS review layers (not tracked)
└── requirements.txt
```

The notebooks are committed with their outputs from the Braunschweig run.

---

## Licence

Source code, notebooks and documentation are released under the [MIT Licence](LICENSE).

The **input data is not covered** and is not distributed here: ALKIS and LoD2 data are licensed by the Landesamt für
Geoinformation und Landesvermessung Niedersachsen (LGLN), OpenStreetMap data is © OpenStreetMap contributors under the
ODbL, and the zone-level activity targets were provided by Regionalverband Großraum Braunschweig. See
[`LICENSE`](LICENSE) for details.

## Citation

If you use this software, please cite it via [`CITATION.cff`](CITATION.cff) (GitHub's "Cite this repository" button).

## Acknowledgements

This work is part of the **TRANSFORMPATHS** project, funded by the Federal Ministry of Research, Technology and Space
(BMFTR) within the framework of "Research for Sustainability" (FONA), under grant number **01UV2574A**.

The author thanks [Regionalverband Großraum Braunschweig](https://www.regionalverband-braunschweig.de/) for data
provision.

## Contact

**Mayur Patel**
Institute of Transportation and Urban Engineering, TU Braunschweig
m.patel@tu-braunschweig.de · Tel.: +49-531-391-66809
