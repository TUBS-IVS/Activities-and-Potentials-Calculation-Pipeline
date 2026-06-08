"""
test_01_geometry.py — Tests for notebook 01: geometry cleaning and volume calculation.
"""

import numpy as np
import pandas as pd
import geopandas as gpd
import pytest
from shapely.geometry import box

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MIN_BUILDING_VOLUME_M3, TARGET_CRS


def compute_volumes(buildings: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    df = buildings.copy()
    df["area_m2"]   = df.geometry.area
    df["volume_m3"] = df["area_m2"] * df["measHeight"].astype(float)
    return df


def deduplicate_by_gml_id(buildings: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return (
        buildings
        .loc[buildings.groupby("gml_id")["area_m2"].idxmax()]
        .reset_index(drop=True)
    )


class TestVolumeCalculation:
    def test_area_computed(self, test_buildings):
        df = compute_volumes(test_buildings)
        assert "area_m2" in df.columns
        assert (df["area_m2"] > 0).all()

    def test_volume_computed(self, test_buildings):
        df = compute_volumes(test_buildings)
        assert "volume_m3" in df.columns
        assert (df["volume_m3"] >= 0).all()

    def test_volume_equals_area_times_height(self, test_buildings):
        df = compute_volumes(test_buildings)
        expected = df["area_m2"] * df["measHeight"].astype(float)
        pd.testing.assert_series_equal(df["volume_m3"], expected, check_names=False)


class TestVolumeFilter:
    def test_below_min_volume_excluded(self, test_buildings):
        df = compute_volumes(test_buildings)
        df_filtered = df[df["volume_m3"] >= MIN_BUILDING_VOLUME_M3]
        # The 0.5m³ building (gml_id DENI00014, measHeight=0.5, 1×1 footprint) must be gone
        tiny = df[df["volume_m3"] < MIN_BUILDING_VOLUME_M3]
        assert len(tiny) > 0, "Test data must contain at least one sub-threshold building"
        assert not any(gid in df_filtered["gml_id"].values for gid in tiny["gml_id"])

    def test_all_remaining_volumes_valid(self, test_buildings):
        df = compute_volumes(test_buildings)
        df_filtered = df[df["volume_m3"] >= MIN_BUILDING_VOLUME_M3]
        assert (df_filtered["volume_m3"] >= MIN_BUILDING_VOLUME_M3).all()


class TestDeduplication:
    def test_no_duplicate_gml_ids(self, test_buildings):
        df = compute_volumes(test_buildings)
        df_filtered = df[df["volume_m3"] >= MIN_BUILDING_VOLUME_M3]
        df_dedup    = deduplicate_by_gml_id(df_filtered)
        assert df_dedup["gml_id"].nunique() == len(df_dedup), "Duplicate gml_ids after deduplication"

    def test_keeps_largest_polygon(self, test_buildings):
        """For gml_id DENI00018 there are two polygons — the 20×15 one should win over 15×10."""
        df = compute_volumes(test_buildings)
        dupes = df[df["gml_id"] == "DENI00018"]
        if len(dupes) >= 2:
            df_dedup = deduplicate_by_gml_id(df)
            kept = df_dedup[df_dedup["gml_id"] == "DENI00018"]
            assert len(kept) == 1
            assert kept.iloc[0]["area_m2"] == dupes["area_m2"].max()


class TestCRS:
    def test_crs_is_target(self, test_buildings):
        assert test_buildings.crs.to_epsg() == int(TARGET_CRS.split(":")[-1])
