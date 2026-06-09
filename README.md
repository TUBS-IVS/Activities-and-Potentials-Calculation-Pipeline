# Deriving Activities and Their Potentials at Building-Level Using Large Language Models

> **Paper:** Patel, M., Bienzeisler, L., & Friedrich, B. Deriving Activities and Their Potentials at Building-Level Using Large Language Models. *Preprint — submitted to Transportation Research Procedia, EWGT2026.*
>
> **Authors:** Mayur Patel · Lasse Bienzeisler · Bernhard Friedrich
>
> **Institution:** [Institute of Transportation and Urban Engineering](https://www.tu-braunschweig.de/isv), TU Braunschweig

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-61%20passing-brightgreen)]()
[![Paper](https://img.shields.io/badge/Paper-PrePrint-orange)](https://www.sciencedirect.com/journal/transportation-research-procedia)

---

## Overview

Agent-based travel demand models require building-level representations of activity locations and their potentials, yet such data are often unavailable or incomplete. This repository provides a **transferable, open-source pipeline** that derives building-level activity types and geometry-based potentials by combining:

- **ALKIS** — authoritative 3D cadastral building data (Germany / Lower Saxony)
- **OpenStreetMap** — POIs, land-use polygons, and supplementary building footprints
- **Large Language Model** — semantic classification of each building into standardised activity types and Bosserhof worker-density classes

Zone-level activity totals (workers, pupils, shoppers, etc.) are then redistributed to individual buildings using activity-informed, geometry-aware weights — yielding a disaggregated, building-level activity potential dataset ready for transport modelling and agent-based simulation.

The pipeline was applied to the **Greater Braunschweig Region, Germany** and achieves **82.4 % F1-score** on activity-label classification and **81.3 % accuracy** on dominant building-use class prediction across 123 manually validated buildings.

---

## Pipeline at a Glance

The four-stage framework mirrors the methodology described in the paper (Section 4):

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Stage 1 · Geometric Preprocessing          (Paper §4.1, Notebooks 01–02)│
│  ─ Clean ALKIS 3D buildings, compute footprint area & volume             │
│  ─ Merge duplicate/overlapping polygons (POI-aware)                      │
│  ─ Supplement missing buildings with OSM footprints                      │
├──────────────────────────────────────────────────────────────────────────┤
│  Stage 2 · Semantic Enrichment              (Paper §4.2, Notebooks 03–05)│
│  ─ Extract & clean OSM POIs                                              │
│  ─ Spatial-join ALKIS function labels, OSM land-use, OSM building tags   │
│  ─ Attach POIs to buildings (intersection + 100 m nearest-neighbour)     │
│  ─ Aggregate to one record per building (gml_id)                         │
├──────────────────────────────────────────────────────────────────────────┤
│  Stage 3 · LLM-based Classification        (Paper §4.3, Notebooks 06–09) │
│  ─ Convert each building record to a compact natural-language sentence   │
│  ─ LLM assigns MiD activity labels + Bosserhof building-use class        │
│  ─ Checkpointed every 50 rows; failed rows retried automatically         │
├──────────────────────────────────────────────────────────────────────────┤
│  Stage 4 · Activity-Informed Disaggregation (Paper §4.4, Notebooks 10–11)│
│  ─ Spatially assign buildings to TAZs                                    │
│  ─ Redistribute zonal totals ∝ building volume × Bosserhof weight        │
│  ─ Hierarchical fallback (TAZ → neighbours → study area)                 │
│  ─ Percentile-based volume caps prevent unrealistic concentrations       │
└──────────────────────────────────────────────────────────────────────────┘
```

### Notebook Sequence

| # | Notebook | Stage | Description |
|---|---|---|---|
| 01 | `01_geometry_volume.ipynb` | Geometric | Clean ALKIS buildings, compute volumes, remove duplicates |
| 02 | `02_poi_extraction.ipynb` | Geometric | Extract POIs + building footprints from OSM PBF |
| 03 | `03_poi_cleaning.ipynb` | Semantic | Normalise names, merge address fields, build search tags |
| 04 | `04_building_enrichment.ipynb` | Semantic | Spatial-join GFK codes, ALKIS labels, OSM land-use |
| 05 | `05_poi_building_merge.ipynb` | Semantic | Attach POIs → buildings (intersection + 100 m fallback) |
| 06 | `06_llm_classification.ipynb` | LLM | Classify each building: MiD label + Bosserhof class |
| 07 | `07_llm_error_rerun.ipynb` | LLM | Retry rows that failed validation in step 06 |
| 08 | `08_attach_geometry.ipynb` | LLM | Re-join flat prediction parquet back to building geometries |
| 09 | `09_merge_results.ipynb` | LLM | Combine predictions from multiple runs (later run wins) |
| 10 | `10_redistribution.ipynb` | Disaggregation | Allocate zone-level targets to buildings |
| 11 | `11_final_results.ipynb` | Disaggregation | Aggregate to zone level, compare with targets, export |

Each step reads from and writes to `data/output/` so you can inspect intermediate results or resume from any point.

---

## Results

### Semantic Classification (Paper §5.2)

Manual validation on 123 buildings (sampled across spatial distribution, urban density, and activity diversity):

| Metric | Activity Labels | Building-Use Class |
|---|---|---|
| Validated buildings | 123 | 123 |
| Precision | 81.6 % | — |
| Recall | 83.2 % | — |
| **F1-score / Accuracy** | **82.4 %** | **81.3 %** |

### Activity Potential Distribution (Paper §5.1)

The pipeline correctly concentrates:
- **Worker activity** around major employment hubs (Volkswagen, Siemens, TU Braunschweig, municipal hospital)
- **Retail daily** along commercial corridors and supermarket clusters
- **Retail non-daily** in the central commercial core and large-format retail periphery

---

## Repository Structure

```
.
├── config.py                   ← All settings — the ONLY file to edit for a new region
├── llm_utils.py                ← Shared LLM helpers (prompt building, JSON parsing, validation)
├── requirements.txt
├── .env.example                ← Copy to .env and add your API token
├── CITATION.cff                ← Machine-readable citation (used by GitHub's "Cite this repository")
│
├── notebooks/                  ← Run in order 01 → 11
│   ├── 01_geometry_volume.ipynb
│   ├── 02_poi_extraction.ipynb
│   ├── 03_poi_cleaning.ipynb
│   ├── 04_building_enrichment.ipynb
│   ├── 05_poi_building_merge.ipynb
│   ├── 06_llm_classification.ipynb
│   ├── 07_llm_error_rerun.ipynb
│   ├── 08_attach_geometry.ipynb
│   ├── 09_merge_results.ipynb
│   ├── 10_redistribution.ipynb
│   └── 11_final_results.ipynb
│
├── scripts/
│   └── llm_smoke_test.py       ← Verify LLM output on ~10 buildings before a full run
│
├── data/
│   ├── input/                  ← Place your input files here (not tracked by git)
│   ├── output/                 ← Pipeline outputs (not tracked by git)
│   └── reference/              ← ALKIS codelists + Bosserhof mapping (shipped with repo)
│       ├── building_function_codelist.csv
│       ├── alkis_building_activity_map.xlsx
│       └── BuildingFunctionTypeAdV.xml
│
└── tests/
    ├── data/                   ← Synthetic + sampled fixtures for fast unit testing
    ├── conftest.py
    ├── create_test_data.py     ← Regenerate synthetic fixtures
    ├── create_llm_test_sample.py  ← Sample real rows for LLM mock tests (run after step 05)
    ├── test_01_geometry.py
    ├── test_03_poi_cleaning.py
    ├── test_05_poi_building_merge.py
    ├── test_06_llm_mock.py
    └── test_10_redistribution.py
```

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/your-org/capacity-calculation-pipeline.git
cd capacity-calculation-pipeline
```

### 2. Create a Python environment

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Install the osmium-tool CLI (for Notebook 02)

Notebook 02 calls `osmium extract` via subprocess to clip the PBF file. This is a **system package** separate from the Python `osmium` binding in `requirements.txt`.

| Platform | Command |
|---|---|
| Linux (Debian/Ubuntu) | `sudo apt install osmium-tool` |
| macOS | `brew install osmium-tool` |
| Windows | Use WSL2 (recommended) or download from [osmcode.org](https://osmcode.org/osmium-tool/) |

Verify: `osmium --version`

> **Note:** `geopandas` and `pyrosm` install cleanly on Linux via pip (they bundle their own GDAL/GEOS via pyogrio). If you encounter GDAL errors, run `sudo apt install libgdal-dev libgeos-dev` first.

### 5. Configure your API token

```bash
cp .env.example .env
# Edit .env: TU_KI_TOOLBOX_TOKEN=your_token_here
```

Steps 06 and 07 call the [TU Braunschweig KI-Toolbox](https://ki-toolbox.tu-braunschweig.de) LLM API. To use a different provider, replace `call_tu_llm()` in `llm_utils.py` — the rest of the pipeline (prompt building, JSON extraction, validation) is provider-agnostic.

---

## Input Data

Place files in `data/input/`:

| File | Format | Required columns / notes |
|---|---|---|
| `buildings.gpkg` | GeoPackage | `gml_id`, `measHeight` (m), `function` (ALKIS code). Optional: `Stadt`, `Strasse`, `HausNr`, `Name` |
| `region.pbf` | OSM PBF | Regional extract from [Geofabrik](https://download.geofabrik.de/) |
| `study_boundary.gpkg` | GeoPackage | Single polygon clipping the study area |
| `zone_targets.gpkg` | GeoPackage | TAZ polygons with activity-demand columns (see `ZONE_COLUMN_MAP` in `config.py`) |
| `landuse_residential.gpkg` | GeoPackage | Residential land-use polygons |
| `landuse_commercial.gpkg` | GeoPackage | Commercial land-use polygons |
| `landuse_industrial.gpkg` | GeoPackage | Industrial land-use polygons |
| `landuse_public.gpkg` | GeoPackage | Public land-use polygons |
| `landuse_sports.gpkg` | GeoPackage | Sports/recreation land-use polygons |
| `osm_buildings.gpkg` *(optional)* | GeoPackage | Pre-extracted OSM building footprints. If absent, Notebook 02 extracts them from the PBF automatically. |

The `data/reference/` folder ships with ALKIS function codelists and the Bosserhof building-use mapping — **do not modify** these for standard German cadastral data.

### Comparable datasets in other countries

| Country | Dataset | Notes |
|---|---|---|
| Switzerland | [swissBUILDINGS3D](https://www.swisstopo.admin.ch/en/landscape-model-swissbuildings3d-2-0) | 3D building geometries |
| Netherlands | [BAG register](https://data.overheid.nl/en/dataset/basisregistratie-adressen-en-gebouwen--bag-) | Address and building register |
| Germany (other states) | ALKIS (state land survey offices) | Replace ALKIS codelists in `data/reference/` if needed |

---

## Configuration

**All region-specific settings live in [`config.py`](config.py).** You should not need to edit any notebook.

Key settings to review when adapting to a new region:

```python
# Coordinate reference system
TARGET_CRS = "EPSG:25832"   # UTM Zone 32N — change for your region

# Map your zone file's column names to the 7 pipeline activity categories
ZONE_COLUMN_MAP = ("Workers", "School", "University", "Kindergarten", "Retail_Daily", "Retail_Non-Daily", "Leisure")      

# Volume thresholds
MIN_BUILDING_VOLUME_M3  = 1    # geometric artefact filter (Notebook 01)
MIN_CONDENSED_VOLUME_M3 = 30   # unusable space filter (Notebook 05)

# LLM settings
LLM_MODEL       = "gpt-oss-120b"
LLM_REASONING   = "high"   # "low" | "medium" | "high"
LLM_MAX_WORKERS = 4        # parallel API threads
LLM_CHUNK_SIZE  = 50       # rows per checkpoint flush
```

---

## Running the Pipeline

```bash
jupyter lab notebooks/
```

Run notebooks in order (01 → 11). Typical runtimes on the Greater Braunschweig dataset (~130 000 buildings):

| Stage | Notebooks | Typical runtime |
|---|---|---|
| Geometric preprocessing | 01–02 | ~15 min |
| Semantic enrichment | 03–05 | ~15 min |
| LLM classification | 06–07 | **Several hours** (checkpointed) |
| Post-processing & results | 08–11 | ~15 min |

### LLM checkpointing

Notebook 06 saves progress to `data/output/llm_predictions/predictions_checkpoint.parquet` after every chunk of 50 rows. Restart the notebook at any time — already-classified rows are skipped automatically.

### Smoke test before a full LLM run

Before running Notebook 06 on the full dataset, verify that the LLM is producing schema-valid output on a diverse sample:

```bash
python scripts/llm_smoke_test.py --n 10
```

This calls the real API on 10 buildings (schools, supermarkets, sparse buildings, offices, etc.) and checks that every response validates against the expected JSON schema.

---

## Activity Labels

The LLM assigns each building one or more **MiD activity labels**:

| Label | Description | Maps to activity category |
|---|---|---|
| `work` / `business` | Offices, workplaces | Workers |
| `school` | Schools (primary, secondary, vocational) | School |
| `university` | Higher education | University |
| `childcare` | Kindergartens, daycare | Kindergarten |
| `retail_daily` / `errands` | Supermarkets, bakeries, pharmacies | Retail_Daily |
| `retail_non_daily` | Clothing, furniture, electronics | Retail_Non-Daily |
| `leisure` / `sports` / `meetup` / `lessons` | Recreation, gyms, community spaces | Leisure |

It also assigns a **Bosserhof class** (e.g. `normal office`, `discount stores`, `schools`) used to look up a worker-density weight (workers per 100 m³) during redistribution.

---

## Running the Tests

The test suite covers all pipeline logic except the live LLM API. All 61 tests run in under one second:

```bash
pytest tests/ -v
```

| Test file | What it covers |
|---|---|
| `test_01_geometry.py` | Volume computation, deduplication, volume filtering |
| `test_03_poi_cleaning.py` | POI exclusion rules, address normalisation |
| `test_05_poi_building_merge.py` | Spatial join, nearest-neighbour fallback |
| `test_06_llm_mock.py` | Full LLM pipeline on real sampled rows with a mock API — zero API calls |
| `test_10_redistribution.py` | Zone-to-building redistribution, Bosserhof weight lookup |

`test_06_llm_mock.py` uses `tests/data/sample_condensed_buildings.parquet` — 24 rows sampled across 8 signal types (school, kindergarten, restaurant, supermarket, hospital, office, named-only, sparse). Regenerate the sample after running Notebook 05 on new data:

```bash
python tests/create_llm_test_sample.py
```

---

## Output Files

All outputs are written to `data/output/`:

| File | Produced by | Description |
|---|---|---|
| `01_building_volumes_filtered.gpkg` | Notebook 01 | Cleaned buildings with computed volumes |
| `03_osm_pois_modified.gpkg` | Notebook 03 | Normalised, deduplicated POIs |
| `04_enriched_building_volume_data.gpkg` | Notebook 04 | Buildings with all spatial-join attributes |
| `05_condensed_buildings_with_pois.gpkg` | Notebook 05 | One row per building with merged POI attributes — LLM input |
| `llm_predictions/predictions_checkpoint.parquet` | Notebook 06 | LLM predictions (resumable checkpoint) |
| `llm_predictions/prediction_errors.parquet` | Notebook 06 | Rows that failed validation |
| `09_llm_predictions_merged.gpkg` | Notebook 09 | Final merged predictions with geometry |
| `10_building_level_redistributed.gpkg` | Notebook 10 | Per-building allocated activity demand |
| `10_redistribution_validation.csv` | Notebook 10 | Zone-level accuracy check |
| `11_final_results.gpkg` | Notebook 11 | Final dataset: buildings + zones as two layers |

---

## Adapting to a New Region

1. Replace files in `data/input/` with your region's data (see [Input Data](#input-data) table).
2. In [`config.py`](config.py), update:
   - `TARGET_CRS` — coordinate reference system for your region
   - `ZONE_COLUMN_MAP` — map your zone file's columns to the 7 activity categories
   - File path constants if your input files have different names
3. If your region uses a different cadastral building system, update the ALKIS codelists in `data/reference/` accordingly.
4. Run notebooks 01–11 in order.

No notebook code needs to be edited.

---

## Citation

If you use this pipeline in your research, please cite:

```bibtex
@unpublished{patel2027deriving,
  title  = {Deriving Activities and Their Potentials at Building-Level Using Large Language Models},
  author = {Patel, Mayur and Bienzeisler, Lasse and Friedrich, Bernhard},
  note   = {Preprint. Submitted to Transportation Research Procedia,
            Euro Working Group on Transportation Annual Meeting 2026 (EWGT2026)},
  year   = {2026},
}
```

---

## Acknowledgements

This work is part of the **TRANSFORMPATHS** project, funded by the Federal Ministry of Research, Technology and Space (BMFTR) within the framework of "Research for Sustainability" (FONA), under grant number **01UV2574A**.

The authors thank:
- [Regionalverband Großraum Braunschweig](https://www.regionalverband-braunschweig.de/) for data provision
- The [Gauß-IT-Zentrum of TU Braunschweig](https://www.tu-braunschweig.de/gitz) for LLM infrastructure

---

## Contact

**Mayur Patel**
Institute of Transportation and Urban Engineering, TU Braunschweig
m.patel@tu-braunschweig.de · Tel.: +49-531-391-66809
