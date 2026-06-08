# Building-Level Activity Capacity Pipeline

A geospatial pipeline that disaggregates zone-level travel demand — workers, school pupils, shoppers, leisure trips — down to individual buildings. It combines official 3D building footprints (ALKIS), OpenStreetMap, and an LLM classifier to produce a building-level capacity dataset ready for transport or land-use modelling.

Developed at the Institute for Transportation and Urban Engineering, TU Braunschweig, as part of a research project on activity-based demand modelling. The pipeline is generic: all region-specific settings live in a single `config.py` file.

---

## The Problem It Solves

Transport models typically work at zone level — a zone has *5,000 workers*, but not *which buildings those workers are in*. Redistributing demand to buildings requires knowing what activity each building hosts and how much capacity it has. Manually classifying hundreds of thousands of buildings is infeasible; coarse ALKIS codes are often too ambiguous.

This pipeline solves it by:
1. Enriching each building with OSM points-of-interest, landuse, and ALKIS metadata
2. Asking an LLM to classify each building into a standardised activity type and Bosserhof worker-density class
3. Redistributing zone targets to buildings proportionally to usable volume and building type

---

## Pipeline Steps

```
01  Geometry & Volume       Clean ALKIS buildings, compute volumes, remove duplicates
         ↓
02  POI Extraction          Extract POIs + building footprints from OSM PBF
         ↓
03  POI Cleaning            Normalise names, merge address fields, build search tags
         ↓
04  Building Enrichment     Spatial-join GFK codes, ALKIS labels, OSM landuse
         ↓
05  POI–Building Merge      Attach POIs → buildings (intersection + 100 m nearest-neighbour)
         ↓
06  LLM Classification      Classify each building: MiD activity label + Bosserhof class
         ↓
07  LLM Error Rerun         Retry rows that failed validation in step 06
         ↓
08  Attach Geometry         Re-join flat prediction parquet back to building geometries
         ↓
09  Merge Results           Combine predictions from multiple LLM runs (later run wins)
         ↓
10  Redistribution          Allocate zone-level targets to buildings via Bosserhof weights
         ↓
11  Final Results           Aggregate to zone level, compare with targets, export
```

Each step reads from and writes to `data/output/` so you can inspect intermediate results or resume from any point.

---

## Project Structure

```
capacity-pipeline-generic/
├── config.py                  ← All settings — the only file to edit for a new region
├── llm_utils.py               ← Shared LLM helpers (sentence building, JSON parsing, validation)
├── requirements.txt
├── .env.example               ← Copy to .env and add your API token
│
├── notebooks/                 ← Run in order: 01 → 11
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
│   └── llm_smoke_test.py      ← Run ~10 real buildings through the LLM to verify before full run
│
├── data/
│   ├── input/                 ← Place your input files here (not tracked by git)
│   ├── output/                ← Pipeline outputs written here (not tracked by git)
│   └── reference/             ← ALKIS codelists shipped with the repo
│
└── tests/
    ├── data/                  ← Small synthetic + sampled fixtures for fast testing
    ├── create_test_data.py    ← Regenerate synthetic test fixtures
    ├── create_llm_test_sample.py  ← Sample real rows for LLM mock tests (run after step 05)
    └── test_*.py
```

---

## Installation

```bash
# 1. Clone
git clone https://github.com/your-org/capacity-calculation-pipeline.git
cd capacity-calculation-pipeline/capacity-pipeline-generic

# 2. Create environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up API token
cp .env.example .env
# Edit .env: TU_KI_TOOLBOX_TOKEN=your_token_here
```

### Linux server setup

Notebook 02 calls the `osmium` CLI via subprocess to clip the PBF file. This is a **system package** separate from the Python `osmium` in `requirements.txt`:

```bash
sudo apt install osmium-tool
```

Verify it works:
```bash
osmium --version
```

`geopandas` and `pyrosm` should install cleanly on Linux via pip without additional system packages (they bundle their own GDAL/GEOS via pyogrio). If you hit GDAL errors, run `sudo apt install libgdal-dev libgeos-dev` first.

---

## Input Data

Place files in `data/input/`:

| File | Format | Description |
|---|---|---|
| `buildings.gpkg` | GeoPackage | ALKIS 3D buildings. Required columns: `gml_id`, `measHeight` (m), `function` (ALKIS code). Optional: `Stadt`, `Strasse`, `HausNr`, `Name`. |
| `region.pbf` | OSM PBF | Regional extract from [Geofabrik](https://download.geofabrik.de/). Used to extract POIs and OSM building footprints. |
| `study_boundary.gpkg` | GeoPackage | Polygon clipping the study area. |
| `zone_targets.gpkg` | GeoPackage | Zone polygons with activity-demand columns (workers, pupils, etc.). |
| `landuse_*.gpkg` | GeoPackage | Residential, commercial, industrial, public, sports landuse polygons. |

The `data/reference/` folder ships with ALKIS function codelists and the Bosserhof building-use mapping and does not need to be changed for standard German data.

---

## Configuration

**All settings live in [`config.py`](config.py).** You should not need to edit any notebook.

Key settings to review for a new region:

```python
TARGET_CRS = "EPSG:25832"          # UTM Zone 32N — change for your region

# Map your zone file's column names to the 7 pipeline activity types
ZONE_COLUMN_MAP = {
    "Workers":          "SG_3_BE~17",
    "School":           ["SG_4_BS", "SG_4_GSCH", "SG_4_WFSCH"],
    "University":       "SG_4_HS",
    "Kindergarten":     "SG_4_KITA",
    "Retail_Daily":     "SG_5_EK_TB",
    "Retail_Non-Daily": "SG_5_EK~19",
    "Leisure":          "SG_6_FR~23",
}

MIN_BUILDING_VOLUME_M3  = 1        # minimum volume to keep (step 01)
MIN_CONDENSED_VOLUME_M3 = 30       # minimum volume before LLM input (step 05)

LLM_MODEL      = "gpt-oss-120b"   # model served by TU KI-Toolbox
LLM_REASONING  = "high"           # "low", "medium", or "high"
LLM_MAX_WORKERS = 4               # parallel API threads
```

### LLM API

Steps 06 and 07 call the [TU Braunschweig KI-Toolbox](https://ki-toolbox.tu-braunschweig.de) API. To use a different LLM provider, replace `call_tu_llm()` in `llm_utils.py` — the rest of the pipeline (sentence building, JSON extraction, validation) is provider-agnostic.

---

## Running the Pipeline

```bash
jupyter lab notebooks/
```

Run notebooks in order. Typical runtimes:

| Step | Notebook | Runtime |
|---|---|---|
| 01–05 | Geometry through merge | ~30 min total |
| 06 | LLM classification | **hours** (checkpointed every 50 rows) |
| 07 | Error rerun | varies |
| 08–11 | Finalisation | ~15 min total |

**LLM checkpointing:** Step 06 saves progress to `data/output/llm_predictions/predictions_checkpoint.parquet` after every chunk. Restart the notebook at any time — already-classified rows are skipped automatically.

**Before running step 06 on the full dataset**, verify the LLM is producing valid output on a small sample:

```bash
python scripts/llm_smoke_test.py --n 10
```

This calls the real API on 10 diverse buildings (schools, supermarkets, sparse buildings, etc.) and checks that every response validates against the expected schema.

---

## Activity Labels

The LLM assigns each building one or more **MiD activity labels**:

| Label | Description |
|---|---|
| `work` / `business` | Offices, workplaces |
| `school` | Schools (primary, secondary, vocational) |
| `university` | Higher education |
| `childcare` | Kindergartens, daycare |
| `retail_daily` / `errands` | Supermarkets, bakeries, pharmacies |
| `retail_non_daily` | Clothing, furniture, electronics |
| `leisure` / `sports` / `meetup` | Recreation, gyms, community spaces |
| `lessons` | Private tutoring, music schools |

It also assigns a **Bosserhof class** (e.g. `normal office`, `discount stores`, `schools`) used to look up a worker-density weight (workers per 100 m³) for the redistribution step.

---

## Running the Tests

The test suite covers all pipeline logic except the live LLM API:

```bash
pytest tests/ -v
```

| Test file | Covers |
|---|---|
| `test_01_geometry.py` | Volume computation, deduplication, volume filtering |
| `test_03_poi_cleaning.py` | POI exclusion rules, address normalisation |
| `test_05_poi_building_merge.py` | Spatial join, nearest-neighbour fallback |
| `test_06_llm_mock.py` | LLM pipeline on **real sampled rows** with a mock API — no API calls |
| `test_10_redistribution.py` | Zone-to-building redistribution, Bosserhof weight lookup |

`test_06_llm_mock.py` uses `tests/data/sample_condensed_buildings.parquet` — 24 rows sampled from the real condensed buildings file across 8 signal types (school, kindergarten, restaurant, supermarket, hospital, office, named-only, sparse). Regenerate it after running step 05 on new data:

```bash
python tests/create_llm_test_sample.py
```

All 61 tests run in under one second.

---

## Output Files

All outputs written to `data/output/`:

| File | Produced by | Description |
|---|---|---|
| `01_building_volumes_filtered.gpkg` | Step 01 | Cleaned buildings with computed volumes |
| `03_osm_pois_modified.gpkg` | Step 03 | Normalised, deduplicated POIs |
| `04_enriched_building_volume_data.gpkg` | Step 04 | Buildings with all spatial join attributes |
| `05_condensed_buildings_with_pois.gpkg` | Step 05 | One row per building with matched POI attributes — LLM input |
| `llm_predictions/` | Steps 06–07 | Checkpoint parquet, error log |
| `09_llm_predictions_merged.gpkg` | Step 09 | Final merged predictions with geometry |
| `10_building_level_redistributed.gpkg` | Step 10 | Per-building allocated activity demand |
| `10_redistribution_validation.csv` | Step 10 | Zone-level accuracy check |
| `11_final_results.gpkg` | Step 11 | Final dataset: buildings + zones as two layers |

---

## Adapting to a New Region

1. Replace files in `data/input/` with your region's data.
2. In `config.py`, update `TARGET_CRS`, `ZONE_COLUMN_MAP`, and file paths if your inputs have different names.
3. Run notebooks 01–11 in order.

No notebook code needs to be edited.

---

## Contact

Mayur Patel — m.patel@tu-braunschweig.de  
Institute for Transportation and Urban Engineering, TU Braunschweig
