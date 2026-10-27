# Input data

Apart from the two reference tables of step 04 and two small files of the rule classifier (an older copy of the
codelist and a 30-building test sample; see
[Data included for the rule classifier](#data-included-for-the-rule-classifier)), no data is distributed with this
repository. The pipeline expects the inputs in `data/input/`
(`config.INPUT_DIR`; set the environment variable `CAPACITY_INPUT_DIR` to use another folder) and the two reference
tables in `data/reference/` (`config.REFERENCE_DIR`). The versions below are the ones used for the paper; newer
releases exist and give different numbers.

| Input | Config name | Read by | Access |
|---|---|---|---|
| OpenStreetMap extract | `OSM_PBF_FILE` | step 01 | open (ODbL) |
| LoD2 tile index and tiles | `LOD2_TILE_INDEX_FILE`, `LOD2_CACHE_DIR` | step 02 | open (CC BY 4.0) |
| ALKIS land use | `ALKIS_LANDUSE_FILE` | step 04 | open (CC BY 4.0) |
| Study-area polygon | `STUDY_BOUNDARY_FILE` | steps 01, 02 | any polygon of the study area |
| Building-function codelist | `BUILDING_FUNCTION_CODELIST_FILE` | step 04 | included in `data/reference/` |
| ALKIS activity map | `ALKIS_ACTIVITY_MAP_FILE` | step 04 | included in `data/reference/` |
| Zone totals | `ZONE_TARGETS_FILE`, `ZONE_LAYER`, `ZONE_COLUMN_MAP` | step 08 | restricted (local authority), not included |

## OpenStreetMap

- **File:** `data/input/niedersachsen-260910.osm.pbf` (505 MB), the Geofabrik extract of Lower Saxony with data up
  to 2026-09-10T20:21Z (header `osmosis_replication_timestamp`), downloaded 2026-09-11.
- **Source:** <https://download.geofabrik.de/europe/germany/niedersachsen.html>. The page always serves the newest
  data. To rebuild the same input, use an extract of that date if Geofabrik's archive still holds one, or cut it
  from an OSM full-history file at 2026-09-10T20:21Z, and set `OSM_PBF_FILE` to the file name.
- **Role:** step 01 clips it to the study area with `osmium` and extracts the activity-related POIs, every building
  footprint and the land use. Step 04 uses the footprints to fill gaps in ALKIS and as a second description of each
  building.
- **Licence:** © OpenStreetMap contributors, [Open Database Licence (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/);
  see <https://www.openstreetmap.org/copyright>. Databases derived from it fall under the ODbL's share-alike terms.

## LoD2 3D building models of Lower Saxony (LGLN)

- **Files:** the tile index `data/input/lgln-opengeodata-lod2.geojson` (37,928 tiles; data currency
  (*Aktualität*) 2024-05-31 to 2024-08-30) and the tiles themselves, which step 02 downloads into
  `data/input/lod2_cache/` (3,620 tiles for the study area, 0.44 GB; downloaded 2026-09-08).
- **Source:** LGLN OpenGeoData, <https://opengeodata.lgln.niedersachsen.de/> (3D building models LoD1/LoD2); product
  description at
  <https://lgln-geodaten.niedersachsen.de/startseite/luftbilder_und_3d_produkte/3d_produkte/3d_gebaudemodelle/3d-gebaudemodelle-lod1-und-lod2-142891.html>.
- **Role:** step 02 merges the tiles into 4,891,343 surfaces; step 03 turns them into footprints with heights and
  a volume (869,316 ALKIS buildings). The volume is never a weight of the allocation: it gives the mean height
  (volume / footprint) and step 04's `share_of_site` (see [REDISTRIBUTION.md](REDISTRIBUTION.md#volume)). The LoD2
  tiles carry the ALKIS building id, function code and name, which is why the buildings are called ALKIS buildings
  throughout.
- **Licence:** open geodata of the LGLN, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Source note
  required by the LGLN terms (AGNB §7.2,
  <https://www.lgln.niedersachsen.de/AGNB/allgemeine-geschafts-und-nutzungsbedingungen-agnb-97401.html>):
  "© GeoBasis-DE/LGLN <year of download>, Daten geändert" (the last part where the data were changed).

## ALKIS land use (*Landnutzung*)

- **File:** `data/input/FS_LN_03_NI_260101.gpkg` (3.4 GB, statewide, 22 layers), reference date 2026-01-01. The LGLN
  cuts it once a year.
- **Source:** LGLN STAC catalogue, <https://alkis.stac.lgln.niedersachsen.de/collections/alkis-landnutzung>.
- **Role:** step 04 clips it to the region on every run and attaches the land use under each building; it decides
  undescribed buildings of generic classes on residential or agricultural land.
- **Licence:** CC BY 4.0 (stated in the STAC collection), with the same LGLN source note as above.

## Study-area polygon

- **File:** `data/input/regionalverband_area.gpkg`, one layer of 9 polygons in EPSG:25832: the eight districts and
  district-free cities of the Regionalverband Großraum Braunschweig and the Volkswagen plant (`VW-Werk`) as its own
  polygon.
- **Role:** steps 01 and 02 clip the OSM extract and select the LoD2 tiles with it. Any polygon layer of a study area
  in Lower Saxony works in its place.

## Reference tables (step 04)

Step 04 needs two small lookup tables, keyed on the ALKIS building-function code (e.g. `31001_2000`): one gives each
code its German and English name, the other the activities a building of that code may serve. Step 04 attaches both
to every building; the names go into the LLM's record and the activity list is kept for comparison. Without them
step 04 stops with a "missing input" error. Both are included in [`data/reference/`](data/reference/).

- **`building_function_codelist_de_en.csv`** — columns `function`, `label_de`, `label_en`; 301 codes. The German
  labels are those of the AdV codelist *AX_Gebaeudefunktion*, published in the GDI-DE registry
  (<https://registry.gdi-de.org/codelist/de.adv-online.gid/AX_Gebaeudefunktion>); the English labels are a
  translation.
- **`alkis_building_activity_map.csv`** — columns `gfk_class`, `gfk_name`, `gfk_code`, `activities`; 280 codes, each
  with the activities a building of that code may serve (`;`-separated). Prepared by the authors.

## Data included for the rule classifier

- **[`rules/reference/building_function_codelist.csv`](rules/reference/building_function_codelist.csv)** — an older
  copy of `building_function_codelist_de_en.csv` with the same columns and codes. Three English labels differ:
  `31001_3031` (Schloss) is "Lock" there and "Castle" in the pipeline's table, and `31001_2213` and `53009_2090`
  (Schöpfwerk) are "Creation" there and "Drainage pumping station" in the pipeline's table. Only the rule
  classifier's smoke test (`rules/rule_smoke_test.py`) reads it, to display the German labels; no rule reads it.
- **[`rules/tests/data/sample_condensed_buildings.parquet`](rules/tests/data/sample_condensed_buildings.parquet)** —
  30 buildings of the region, sampled from the condensed building table of the original pipeline the rules were
  written against, as input rows for `rules/tests/test_rule_utils.py`. Its 21 columns hold LGLN data (ALKIS building
  id, function code, volume, address, ALKIS land use), OSM data (names, tags, land use, and the `email` and
  `website` contact tags of businesses), the labels of the two reference tables and the sampling group. It is
  derived from OpenStreetMap (© OpenStreetMap contributors, ODbL 1.0) and LGLN data (© GeoBasis-DE/LGLN, Daten
  geändert, CC BY 4.0) and keeps their terms; the MIT licence of the code does not cover it.

## Zone totals (step 08)

- **File:** `data/input/zone_targets.gpkg`, layer `regionbsstructuredata_zone` (`ZONE_LAYER`): 880 traffic zones
  with the structure data of the region's VISUM travel demand model, zone id `NO` (`ZONE_ID_COL`).
- **Columns used** (`ZONE_COLUMN_MAP`): Workers `SG_3_BE~17`; School `SG_4_BS + SG_4_GSCH + SG_4_WFSCH` (vocational,
  primary and secondary pupils); University `SG_4_HS`; Kindergarten `SG_4_KITA`; Retail_Daily `SG_5_EK_TB`;
  Retail_Non-Daily `SG_5_EK~19`; Leisure `SG_6_FR~23`. Missing values count as 0. Step 08 also reads the zone name
  `NAME` (for its printouts and the `zones` layer of the output), the district `RO_LANDK~1` (`ZONE_DISTRICT_COL`) and
  three Workers sector columns (`WORKER_SECTOR_COLUMNS`); the district and the sectors serve a check and a diagnostic
  only, not the allocation.
- **Another zone model:** these names fit this layer only. Set in `config.py`:
  - `ZONE_TARGETS_FILE` and `ZONE_LAYER`: the file and its layer of zone polygons;
  - `ZONE_ID_COL`: a unique, whole-number zone id;
  - `ZONE_COLUMN_MAP`: the column, or list of columns summed, for each of the seven categories;
  - `SCHOOL_TYPE_COLUMNS`: exactly the School columns of `ZONE_COLUMN_MAP`, one per school type; the types are
    `primary`, `secondary` and `vocational` (names the code matches in `lib/floor_rules.py`), and where a model lacks
    one, `SCHOOL_TYPE_DEFAULT` and `SCHOOL_TYPE_ALKIS` may name only the types kept;
  - `WORKER_SECTOR_COLUMNS`: the Workers sector columns, which must add up to the Workers total in every zone
    (`WORKER_SECTOR_CLASSES` assigns the building classes to the sectors), and `ZONE_DISTRICT_COL`: the district of
    each zone;
  - `FLOOR_OSM_HALL_LEVELS`: its `zones` entry is the zone id of the Volkswagen plant in this model.

  The layer must also have a column `NAME` (a fixed name in notebook 08) and be in EPSG:25832 (`TARGET_CRS`). Step 08
  stops at its input check if a column is missing, the ids are not unique, the CRS differs, a total is negative, or
  the school types or the Workers sectors do not add up to their totals.
- **Source and access:** supplied by the Regionalverband Großraum Braunschweig
  (<https://www.regionalverband-braunschweig.de/>). Not public and not redistributable without their permission.
- **Role:** step 08 reads it on every run; without it step 08 stops at its input check and writes nothing.
- **Use with lawful access:** place the file at `data/input/zone_targets.gpkg` (`ZONE_TARGETS_FILE` in `config.py`); the
  layer, id and column names above must match. Do not publish the file or values derived from it.

## Derived data

The step outputs in `data/output/` are not distributed. Those of steps 01–07 and `rules/` derive from the open
inputs (ODbL, CC BY 4.0) and the LLM. All outputs of step 08 derive from the restricted zone totals, so they fall
under the same restriction. The `zones` layer holds the totals themselves (`target_<category>`), and the building
values reveal many of them: summing `assigned_<category>` by zone comes within 1 % of the zone's total in 42 %
(Workers), 63 % (School), 20 % (University), 45 % (Kindergarten), 83 % (Retail_Daily), 75 % (Retail_Non-Daily) and
62 % (Leisure) of the zones with a total; the rest differ where the rules move amounts between zones
([REDISTRIBUTION.md](REDISTRIBUTION.md), section 2). The regional totals are kept exactly, and a building that is the
only carrier in its zone can show that zone's total directly. Column names write `_` for the `-` of Retail_Non-Daily
(`assigned_Retail_Non_Daily`, `target_Retail_Non_Daily`).
