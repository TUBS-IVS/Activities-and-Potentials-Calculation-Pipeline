"""
create_test_data.py — Generate synthetic test GeoPackages for the pipeline test suite.

Run once:
    python tests/create_test_data.py

Creates:
    tests/data/test_buildings.gpkg   — 20 synthetic ALKIS-like buildings
    tests/data/test_boundary.gpkg    — study area polygon enclosing all test buildings
    tests/data/test_pois.gpkg        — 15 synthetic OSM POIs
    tests/data/test_zones.gpkg       — 3 TAZ zones with known activity totals
"""

from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import box, Point, Polygon

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

CRS = "EPSG:25832"

# Origin point for test data (Braunschweig area)
OX, OY = 648000, 5795000   # approx Braunschweig centre, UTM 32N

rng = np.random.default_rng(42)

# ──────────────────────────────────────────────
# 1. Test buildings (20 rows)
# ──────────────────────────────────────────────

def make_building(i, x, y, w, h, height_m, function_code, city, name=None):
    geom = box(x, y, x + w, y + h)
    return {
        "gml_id":      f"DENI{i:05d}",
        "measHeight":  float(height_m),
        "function":    function_code,
        "Stadt":       city,
        "Strasse":     f"Teststrasse",
        "HausNr":      str(i),
        "Name":        name,
        "geometry":    geom,
    }

buildings_data = [
    # Normal-sized offices / commercial
    make_building(1,  OX+100,  OY+100,  30, 20, 12.0, "2010", "Braunschweig", "City Hall"),
    make_building(2,  OX+200,  OY+100,  25, 20, 9.0,  "2010", "Braunschweig", "Office A"),
    make_building(3,  OX+300,  OY+100,  40, 30, 15.0, "2010", "Braunschweig", None),
    # Residential (large)
    make_building(4,  OX+100,  OY+200,  20, 15, 8.0,  "1010", "Braunschweig", None),
    make_building(5,  OX+200,  OY+200,  20, 15, 8.0,  "1010", "Braunschweig", None),
    make_building(6,  OX+300,  OY+200,  20, 15, 8.0,  "1020", "Wolfsburg",    None),
    # Retail
    make_building(7,  OX+100,  OY+300,  50, 30, 6.0,  "3010", "Braunschweig", "Supermarkt Nord"),
    make_building(8,  OX+200,  OY+300,  60, 40, 4.0,  "3010", "Wolfsburg",    "Kaufhaus"),
    # School / education
    make_building(9,  OX+400,  OY+100,  50, 40, 10.0, "2350", "Braunschweig", "Gymnasium"),
    make_building(10, OX+400,  OY+200,  40, 30, 8.0,  "2420", "Braunschweig", "Kindergarten"),
    # Industrial
    make_building(11, OX+500,  OY+100,  80, 60, 8.0,  "3900", "Peine",        "Werk A"),
    make_building(12, OX+500,  OY+200,  70, 50, 7.0,  "3900", "Peine",        None),
    # Small / tiny (will be filtered by MIN_BUILDING_VOLUME_M3)
    make_building(13, OX+600,  OY+100,   2,  2, 2.0,  "1010", "Braunschweig", None),  # vol=8 m³ → passes ≥1
    make_building(14, OX+650,  OY+100,   1,  1, 0.5,  "1010", "Braunschweig", None),  # vol=0.5 m³ → filtered
    # Hospital / public
    make_building(15, OX+100,  OY+400,  60, 50, 20.0, "2160", "Braunschweig", "Klinikum"),
    # Leisure / sports
    make_building(16, OX+200,  OY+400,  40, 40, 12.0, "5130", "Wolfsburg",    "Sporthalle"),
    # Restaurant
    make_building(17, OX+300,  OY+400,  20, 15, 4.5,  "3040", "Braunschweig", "Restaurant Mitte"),
    # Duplicate gml_id (same building, different polygon — should be deduplicated, keep largest)
    make_building(18, OX+700,  OY+100,  15, 10, 6.0,  "2010", "Braunschweig", None),
    {**make_building(18, OX+700,  OY+100,  20, 15, 6.0,  "2010", "Braunschweig", None),
     "gml_id": "DENI00018"},  # larger polygon of same building
    # OSM-only building (no ALKIS gml_id — will be filled in nb05)
    make_building(19, OX+750,  OY+100,  25, 20, 5.0,  "2010", "Salzgitter",   "Neubau"),
    make_building(20, OX+800,  OY+100,  30, 25, 9.0,  "3010", "Peine",        "Einkaufszentrum"),
]

gdf_buildings = gpd.GeoDataFrame(buildings_data, crs=CRS)
gdf_buildings.to_file(DATA_DIR / "test_buildings.gpkg", driver="GPKG")
print(f"Saved {len(gdf_buildings)} buildings → test_buildings.gpkg")

# ──────────────────────────────────────────────
# 2. Study boundary (encloses all buildings + margin)
# ──────────────────────────────────────────────

minx = gdf_buildings.geometry.bounds["minx"].min() - 200
miny = gdf_buildings.geometry.bounds["miny"].min() - 200
maxx = gdf_buildings.geometry.bounds["maxx"].max() + 200
maxy = gdf_buildings.geometry.bounds["maxy"].max() + 200

boundary = gpd.GeoDataFrame({"geometry": [box(minx, miny, maxx, maxy)]}, crs=CRS)
boundary.to_file(DATA_DIR / "test_boundary.gpkg", driver="GPKG")
print(f"Saved study boundary → test_boundary.gpkg")

# ──────────────────────────────────────────────
# 3. Test POIs (15 rows — various types)
# ──────────────────────────────────────────────

pois_data = [
    # Essential daily POIs (inside buildings 1 and 7)
    {"id": "p1", "name": "Bäckerei Müller",  "shop": "bakery",      "amenity": None,        "geometry": Point(OX+115, OY+110)},
    {"id": "p2", "name": "REWE Supermarkt",  "shop": "supermarket", "amenity": None,        "geometry": Point(OX+120, OY+315)},
    {"id": "p3", "name": "Apotheke",         "shop": "chemist",     "amenity": None,        "geometry": Point(OX+205, OY+110)},
    # Amenity POIs
    {"id": "p4", "name": "Rathaus",          "shop": None,          "amenity": "townhall",  "geometry": Point(OX+115, OY+115)},
    {"id": "p5", "name": "Gymnasium",        "shop": None,          "amenity": "school",    "geometry": Point(OX+425, OY+130)},
    {"id": "p6", "name": "Kita Sonnenschein","shop": None,          "amenity": "kindergarten","geometry": Point(OX+420, OY+215)},
    {"id": "p7", "name": "Restaurant Mitte", "shop": None,          "amenity": "restaurant","geometry": Point(OX+310, OY+408)},
    # Non-enterable POIs (should be excluded by EXCLUDE_AMENITIES)
    {"id": "p8", "name": None,               "shop": None,          "amenity": "parking",   "geometry": Point(OX+550, OY+150)},
    {"id": "p9", "name": None,               "shop": None,          "amenity": "bench",     "geometry": Point(OX+560, OY+155)},
    # Tourism
    {"id": "p10","name": "Hotel Zentrum",    "shop": None,          "amenity": None,
     "tourism": "hotel",                                                                     "geometry": Point(OX+205, OY+315)},
    # Near (within 100m) but not inside a building
    {"id": "p11","name": "Kiosk",            "shop": "kiosk",       "amenity": None,        "geometry": Point(OX+99,  OY+110)},
    # POI with address data
    {"id": "p12","name": "Büro ABC",         "shop": None,          "amenity": "office",
     "addr:street": "Teststrasse", "addr:housenumber": "3",
     "addr:city": "Braunschweig", "addr:postcode": "38100",                                 "geometry": Point(OX+315, OY+115)},
    {"id": "p13","name": "Sportzentrum",     "shop": None,          "amenity": "sports_centre","geometry": Point(OX+220, OY+415)},
    {"id": "p14","name": "Klinikum",         "shop": None,          "amenity": "hospital",  "geometry": Point(OX+130, OY+425)},
    {"id": "p15","name": "Kaufhaus GmbH",    "shop": "department_store","amenity": None,    "geometry": Point(OX+230, OY+320)},
]

# Ensure all POIs have all expected columns
poi_cols = ["id","name","shop","amenity","tourism","addr:street","addr:housenumber",
            "addr:city","addr:postcode","geometry"]
rows = []
for p in pois_data:
    row = {c: p.get(c, None) for c in poi_cols}
    rows.append(row)

gdf_pois = gpd.GeoDataFrame(rows, crs=CRS)
gdf_pois.to_file(DATA_DIR / "test_pois.gpkg", driver="GPKG")
print(f"Saved {len(gdf_pois)} POIs → test_pois.gpkg")

# ──────────────────────────────────────────────
# 4. Zone targets (3 TAZ zones with known activity totals)
# ──────────────────────────────────────────────

# Zone A: western part of study area
# Zone B: central part
# Zone C: eastern part

zone_bounds = [
    (minx,       miny, OX+350, maxy),   # Zone A (west)
    (OX+350,     miny, OX+600, maxy),   # Zone B (central)
    (OX+600,     miny, maxx,   maxy),   # Zone C (east)
]

zone_rows = []
zone_targets = [
    # Zone A: city centre
    {"Workers": 500.0, "School": 300.0, "University": 100.0, "Kindergarten": 80.0,
     "Retail_Daily": 200.0, "Retail_Non-Daily": 150.0, "Leisure": 120.0},
    # Zone B: mixed
    {"Workers": 800.0, "School": 150.0, "University": 50.0,  "Kindergarten": 60.0,
     "Retail_Daily": 350.0, "Retail_Non-Daily": 200.0, "Leisure": 180.0},
    # Zone C: industrial
    {"Workers": 1200.0,"School": 50.0,  "University": 20.0,  "Kindergarten": 30.0,
     "Retail_Daily": 100.0, "Retail_Non-Daily": 80.0,  "Leisure": 60.0},
]

for i, (b, t) in enumerate(zip(zone_bounds, zone_targets)):
    row = {"zone_id": i, "zone_name": f"Zone_{chr(65+i)}", "geometry": box(*b)}
    row.update(t)
    zone_rows.append(row)

gdf_zones = gpd.GeoDataFrame(zone_rows, crs=CRS)
gdf_zones.to_file(DATA_DIR / "test_zones.gpkg", layer="zone_targets", driver="GPKG")
print(f"Saved {len(gdf_zones)} zones → test_zones.gpkg")

print("\nAll test data created successfully.")
