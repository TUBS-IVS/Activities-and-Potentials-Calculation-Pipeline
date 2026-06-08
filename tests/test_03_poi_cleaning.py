"""
test_03_poi_cleaning.py — Tests for notebook 03: POI cleaning and consolidation.
"""

import numpy as np
import pandas as pd
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import EXCLUDE_AMENITIES, EXCLUDE_BUILDING_TYPES, ALLOWED_TOURISM_TYPES, ALLOWED_INFORMATION_TYPES


def merge_address(row):
    addr_cols = ["addr:housename", "addr:street", "addr:housenumber",
                 "addr:place", "addr:city", "addr:postcode"]
    parts = [
        str(row[c]).strip()
        for c in addr_cols
        if c in row.index and pd.notna(row[c]) and str(row[c]).strip() not in ("", "nan")
    ]
    return np.nan if not parts else ", ".join(parts)


class TestAddressMerge:
    def test_address_merged_when_components_present(self, test_pois):
        # p12 has addr:street, addr:housenumber, addr:city, addr:postcode
        p12 = test_pois[test_pois["id"] == "p12"].iloc[0]
        addr = merge_address(p12)
        assert pd.notna(addr)
        assert "Teststrasse" in addr
        assert "Braunschweig" in addr

    def test_address_nan_when_no_components(self, test_pois):
        p1 = test_pois[test_pois["id"] == "p1"].iloc[0]
        addr = merge_address(p1)
        assert pd.isna(addr) or addr == ""


class TestAmenityExclusion:
    def test_excluded_amenities_removed(self, test_pois):
        before = len(test_pois)
        clean  = test_pois[~test_pois["amenity"].isin(EXCLUDE_AMENITIES)].copy()
        # parking and bench should be removed
        assert clean[clean["amenity"] == "parking"].empty
        assert clean[clean["amenity"] == "bench"].empty

    def test_enterable_amenities_kept(self, test_pois):
        clean = test_pois[~test_pois["amenity"].isin(EXCLUDE_AMENITIES)].copy()
        assert not clean[clean["amenity"] == "school"].empty
        assert not clean[clean["amenity"] == "townhall"].empty
        assert not clean[clean["amenity"] == "restaurant"].empty


class TestTourismFilter:
    def test_allowed_tourism_kept(self, test_pois):
        clean = test_pois[
            test_pois["tourism"].isna() | test_pois["tourism"].isin(ALLOWED_TOURISM_TYPES)
        ]
        hotel_rows = clean[clean["tourism"] == "hotel"]
        assert len(hotel_rows) > 0

    def test_excluded_tourism_removed(self):
        import geopandas as gpd
        from shapely.geometry import Point
        fake = gpd.GeoDataFrame(
            [{"id": "x", "tourism": "information_board", "geometry": Point(0, 0)}],
            crs="EPSG:25832"
        )
        clean = fake[fake["tourism"].isna() | fake["tourism"].isin(ALLOWED_TOURISM_TYPES)]
        assert len(clean) == 0


class TestExcludeBuildings:
    def test_excluded_building_types_removed(self):
        import geopandas as gpd
        from shapely.geometry import Point
        fake = gpd.GeoDataFrame(
            [{"id": "a", "building": "shed",  "geometry": Point(0, 0)},
             {"id": "b", "building": "roof",  "geometry": Point(1, 1)},
             {"id": "c", "building": "yes",   "geometry": Point(2, 2)}],
            crs="EPSG:25832"
        )
        clean = fake[~fake["building"].isin(EXCLUDE_BUILDING_TYPES)]
        assert len(clean) == 1
        assert clean.iloc[0]["id"] == "c"
