# Running the pipeline

How to install, feed and run notebooks 01–08, what they write, and how to move the pipeline to another region.
For what the classifier does, see [classification.md](classification.md); for the accuracy checks, see
[validation.md](validation.md) and [rules-vs-llm.md](rules-vs-llm.md).

- [Notebook sequence](#notebook-sequence)
- [Why the run order is not numeric](#why-the-run-order-is-not-numeric)
- [Installation](#installation)
- [Input data](#input-data)
- [Configuration](#configuration)
- [Running and runtimes](#running-and-runtimes)
- [Output files](#output-files)
- [Running the tests](#running-the-tests)
- [Adapting to a new region](#adapting-to-a-new-region)

---

## Notebook sequence

> **Run order is 02 → 03 → 01 → 04 → 05 → 06 → 07 → 08, not numeric order.** Notebook 01 reads notebook 03's cleaned
> POIs to set `has_poi`, which gates the polygon merge. See [below](#why-the-run-order-is-not-numeric).

| Order | Notebook | Stage | Description |
|---|---|---|---|
| 1 | `02_poi_extraction.ipynb` | Geometric | Clip PBF to the study boundary; extract POIs + OSM building footprints |
| 2 | `03_poi_cleaning.ipynb` | Semantic | Normalise names, merge address fields, build search tags |
| 3 | `01_geometry_volume.ipynb` | Geometric | Clean ALKIS buildings, compute volumes, POI-aware polygon merge |
| 4 | `04_building_enrichment.ipynb` | Semantic | Spatial-join GFK codes, ALKIS labels, OSM land-use |
| 5 | `05_poi_building_merge.ipynb` | Semantic | Attach POIs → buildings (intersection + 100 m fallback) |
| 6 | `06_rule_based_classification.ipynb` | Classification | Classify every building: MiD label + Bosserhof class, via `rule_utils.py` |
| 7 | `07_redistribution.ipynb` | Disaggregation | Allocate zone-level targets to buildings |
| 8 | `08_final_results.ipynb` | Disaggregation | Aggregate to zone level, compare with targets, export |

Each step reads from and writes to `data/output/`, so you can inspect intermediate results or resume from any point.
Notebooks 09–12 are evaluation steps, independent of 01–08; see [validation.md](validation.md) and
[rules-vs-llm.md](rules-vs-llm.md).

## Why the run order is not numeric

Notebook 01 contains this branch:

```python
if OSM_POIS_MODIFIED_FILE.exists():        # written by notebook 03
    ...
    gdf['has_poi'] = gdf.index.isin(poi_poly_idx)
else:
    gdf['has_poi'] = False
    print('OSM POI file not found — running without POI flags (run nb 02+03 first for full results)')
```

`has_poi` then **blocks the union-find merge** — two touching polygons with the same ALKIS function are merged only if
neither carries a POI:

```python
if has_poi[i] or has_poi[j]:
    continue
```

So on a clean checkout, running 01 first takes the else branch, merges buildings that should have stayed separate, and
yields a **smaller, differently-indexed** building set. Because notebook 05 assigns `gml_id` from the positional row
index, every downstream id shifts too.

Measured on this dataset: the correct order (02 → 03 → 01 → …) produces **574,435** condensed buildings and reproduces
that count exactly across runs. A run that takes the else branch produces **567,961**. Both are internally consistent;
only the first is correct.

---

## Installation

### 1. Clone the repository

```bash
git clone -b Rules-based-pipeline https://github.com/TUBS-IVS/Activities-and-Potentials-Calculation-Pipeline.git
cd Activities-and-Potentials-Calculation-Pipeline
```

### 2. Create a Python environment (3.10+)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> `geopandas` and `pyrosm` install cleanly on Linux via pip (they bundle their own GDAL/GEOS via pyogrio). If you
> encounter GDAL errors, run `sudo apt install libgdal-dev libgeos-dev` first.

### 3. Install the osmium-tool CLI (for notebook 02)

Notebook 02 calls `osmium extract` via subprocess to clip the PBF file — a **system package**, not something
`pip install` provides.

| Platform | Command |
|---|---|
| Linux (Debian/Ubuntu) | `sudo apt install osmium-tool` |
| macOS | `brew install osmium-tool` |
| Windows / conda | `conda install -c conda-forge osmium-tool` |

Verify: `osmium --version`

### 4. Enable the notebook clean filter *(optional, recommended for contributors)*

The notebooks are committed **with their cell outputs** — they are the record of the run every figure in the
documentation comes from, so `nbstripout` is deliberately *not* used. The cost is that editors inject metadata: VS
Code's Data Wrangler extension writes a full column schema into every DataFrame output when a notebook is opened, and
the kernelspec gets rewritten to whatever kernel you happen to have selected. Both produce large spurious diffs.

`scripts/nb_clean_filter.py` strips exactly that metadata on the way into git while leaving every output, execution
count and error intact. `.gitattributes` already routes `*.ipynb` through it; git filter config is local to a clone, so
enable it once with:

```bash
git config filter.nbclean.clean "python scripts/nb_clean_filter.py"
git config filter.nbclean.smudge cat
```

Your working copy is never modified — only what git stores. Skipping this step breaks nothing: git ignores an undefined
filter, you just get noisier diffs.

---

## Input data

Place files in `data/input/` (none are distributed with the repository — see [Licence](../README.md#licence)):

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
| `landuse_osm.gpkg` | GeoPackage | OSM land-use polygons — supplies `osm_landuse_class`, read by classifier layer 3. **Optional but load-bearing:** notebook 04 guards it with `.exists()`, so a run without it succeeds while classification silently degrades. |
| `osm_buildings.gpkg` *(optional)* | GeoPackage | Pre-extracted OSM building footprints. If absent, notebook 02 extracts them from the PBF automatically. |

The `data/reference/` folder ships with the ALKIS function codelist (`building_function_codelist.csv`, code → German /
English label) and `alkis_building_activity_map.xlsx` (read by notebook 04 for context columns only; the classifier no
longer reads it). **Do not modify** these for standard German cadastral data.

### Comparable datasets in other countries

| Country | Dataset | Notes |
|---|---|---|
| Switzerland | [swissBUILDINGS3D](https://www.swisstopo.admin.ch/en/landscape-model-swissbuildings3d-2-0) | 3D building geometries |
| Netherlands | [BAG register](https://data.overheid.nl/en/dataset/basisregistratie-adressen-en-gebouwen--bag-) | Address and building register |
| Germany (other states) | ALKIS (state land survey offices) | Replace the ALKIS codelist in `data/reference/` if needed |

---

## Configuration

**All region-specific settings live in [`config.py`](../config.py).** You should not need to edit any notebook.

Key settings to review when adapting to a new region:

```python
# Coordinate reference system
TARGET_CRS = "EPSG:25832"   # UTM Zone 32N — change for your region

# Map your zone file's column names to the 7 pipeline activity categories
ZONE_COLUMN_MAP = {"Workers": "SG_3_BE~17", "School": [...], ...}

# Volume thresholds
MIN_BUILDING_VOLUME_M3  = 1    # geometric artefact filter (notebook 01)
MIN_CONDENSED_VOLUME_M3 = 30   # unusable space filter (notebook 05)
```

The classification rule tables themselves (`AMENITY_RULES`, `SHOP_RULES`, `ALKIS_RULES`, …) live in `rule_utils.py`;
the Bosserhof worker densities and the activity taxonomy in `config.py`. See
[Where the rules live](classification.md#where-the-rules-live).

---

## Running and runtimes

```bash
jupyter lab notebooks/
```

Run the notebooks in **dependency order — 02, 03, 01, 04, 05, 06, 07, 08**. Measured end-to-end on the Greater
Braunschweig dataset (4,878,052 raw polygons → 574,435 classified buildings), total **34.7 min**:

| Order | Notebook | Runtime | Output |
|---|---|---|---|
| 1 | 02 poi_extraction | 3.8 min | 68,315 POIs · 509,794 OSM buildings |
| 2 | 03 poi_cleaning | 0.4 min | 68,315 cleaned POIs |
| 3 | 01 geometry_volume | 15.1 min | 663,580 buildings (from 4,878,052 raw) |
| 4 | 04 building_enrichment | 4.8 min | 663,580 enriched |
| 5 | 05 poi_building_merge | 6.8 min | 574,435 condensed |
| 6 | 06 rule_based_classification | **0.7 min** | 282,017 classified (49.1 %) |
| 7 | 07 redistribution | 2.7 min | 880 zones · conservation error 1.5 × 10⁻¹¹ |
| 8 | 08 final_results | 0.2 min | 279,913 buildings matched to a zone |
| — | 09 + 10 validation | 0.3 min | 882 / 874 scored |

---

## Output files

All outputs are written to `data/output/` (≈1.96 GB total for this study area; git-ignored):

| File | Produced by | Size | Description |
|---|---|---|---|
| `area_of_study_clipped.pbf` | Notebook 02 | 58 MB | PBF clipped to the study boundary |
| `01_all_pois.gpkg` | Notebook 02 | 26 MB | All OSM POIs in the study area |
| `01_all_buildings_osm.gpkg` | Notebook 02 | 164 MB | OSM building footprints for ALKIS gap-filling |
| `03_osm_pois_modified.gpkg` | Notebook 03 | 17 MB | Normalised, deduplicated POIs |
| `01_building_volumes_filtered.gpkg` | Notebook 01 | 350 MB | Cleaned buildings with computed volumes |
| `04_enriched_building_volume_data.gpkg` | Notebook 04 | 446 MB | Buildings with all spatial-join attributes |
| `05_condensed_buildings_with_pois.gpkg` | Notebook 05 | 325 MB | One row per building with merged POI attributes — classifier input |
| `06_classified_buildings.gpkg` | Notebook 06 | 291 MB | Every building with `mid_label`, `bosserhof_class`, and which rule layer resolved it (282,017 of 574,435 classified — 49.1 %) |
| `07_building_level_redistributed.gpkg` | Notebook 07 | 133 MB | Per-building allocated activity demand |
| `07_redistribution_allocation_log.csv` | Notebook 07 | 13 MB | Per-allocation audit trail |
| `07_redistribution_validation.csv` | Notebook 07 | 0.1 MB | Zone-level conservation check |
| `08_final_results.gpkg` | Notebook 08 | 134 MB | Final dataset: buildings + zones as two layers |

The evaluation steps write `11_rules_on_final.parquet`, `12_rules_vs_llm_side_by_side.xlsx`, the
`13_new_validation/` folder and `13_new_validation_side_by_side.xlsx` here as well; see
[rules-vs-llm.md](rules-vs-llm.md).

---

## Running the tests

The test suite covers all pipeline logic and runs in about a second, without any input data:

```bash
pytest tests/ -v
```

**156 tests, all passing.**

| Test file | Tests | What it covers |
|---|---|---|
| `test_01_geometry.py` | 8 | Volume computation, deduplication, volume filtering |
| `test_03_poi_cleaning.py` | 7 | POI exclusion rules, address normalisation |
| `test_05_poi_building_merge.py` | 6 | Spatial join, nearest-neighbour fallback |
| `test_06_rule_based.py` | 120 | `classify_building()` on real sampled rows, a static self-check of every rule table, and regression tests pinning each deliberate decision — see [classification.md](classification.md#tests-that-hold-the-rules-in-place) |
| `test_07_redistribution.py` | 15 | Zone-to-building redistribution, Bosserhof weight lookup |

The fixtures in `tests/data/` are synthetic (regenerate with `python tests/create_test_data.py`) or sampled from real
classifier input (regenerate after running notebook 05 with `python tests/create_classifier_test_sample.py`).

---

## Adapting to a new region

1. Replace files in `data/input/` with your region's data (see [Input data](#input-data)).
2. In [`config.py`](../config.py), update:
   - `TARGET_CRS` — coordinate reference system for your region
   - `ZONE_COLUMN_MAP` — map your zone file's columns to the 7 activity categories
   - File path constants if your input files have different names
3. If your region uses a different cadastral building system, update the codelist in `data/reference/`, then add a row
   to `ALKIS_RULES` in `rule_utils.py` for each code that occurs. Codes absent from the table fall through to the OSM
   layer rather than being guessed, so an incomplete table degrades gracefully — see what the table covers with:

   ```bash
   python scripts/rule_smoke_test.py --alkis
   ```

4. Run the notebooks in dependency order: **02, 03, 01, 04, 05, 06, 07, 08**.

No notebook code needs to be edited.
