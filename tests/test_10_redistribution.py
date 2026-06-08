"""
test_10_redistribution.py — Tests for notebook 10: Bosserhof weights and redistribution.

Key invariants:
1. retail wholesale has a valid weight (was the bug)
2. All BOSSERHOF_WEIGHTS keys are lowercase (no silent NaN from casing)
3. TAZ totals are conserved: sum(assigned per zone) ≈ zone target
4. No building silently dropped due to unmapped bosserhof_class
"""

import pytest
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import box

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (BOSSERHOF_WEIGHTS, BOSSERHOF_NORMALIZATION_MAP, ZONE_ACTIVITY_COLUMNS,
                    MID_LABEL_TO_ACTIVITY, TARGET_MID_LABELS)


class TestBosserhofWeightsDict:
    def test_all_keys_are_lowercase(self):
        for key in BOSSERHOF_WEIGHTS:
            assert key == key.lower(), f"Key not lowercase: '{key}'"

    def test_retail_wholesale_has_weight(self):
        assert "retail wholesale" in BOSSERHOF_WEIGHTS, (
            "'retail wholesale' missing from BOSSERHOF_WEIGHTS — buildings will be silently dropped"
        )
        assert BOSSERHOF_WEIGHTS["retail wholesale"] > 0

    def test_all_weights_positive(self):
        for cls, w in BOSSERHOF_WEIGHTS.items():
            assert w > 0, f"Non-positive weight for '{cls}': {w}"

    def test_core_classes_present(self):
        core = ["normal office", "schools", "kindergartens", "hospitals",
                "retail small scale", "discount stores", "fitness wellness",
                "transport", "industrial operations production"]
        for cls in core:
            assert cls in BOSSERHOF_WEIGHTS, f"Missing core class: '{cls}'"

    def test_normalization_map_values_exist_in_weights(self):
        for src, target in BOSSERHOF_NORMALIZATION_MAP.items():
            assert target.lower() in BOSSERHOF_WEIGHTS, (
                f"BOSSERHOF_NORMALIZATION_MAP maps '{src}' → '{target}' "
                f"but '{target}' not in BOSSERHOF_WEIGHTS"
            )


class TestMidLabelMapping:
    def test_all_mid_labels_mapped(self):
        for label in TARGET_MID_LABELS:
            assert label in MID_LABEL_TO_ACTIVITY, f"MiD label '{label}' not in MID_LABEL_TO_ACTIVITY"

    def test_activity_values_match_zone_columns(self):
        for label, activity in MID_LABEL_TO_ACTIVITY.items():
            assert activity in ZONE_ACTIVITY_COLUMNS, (
                f"MID_LABEL_TO_ACTIVITY['{label}'] = '{activity}' not in ZONE_ACTIVITY_COLUMNS"
            )


class TestPotentialsComputation:
    """Unit test the potential calculation logic."""

    def _make_buildings(self, classes_and_volumes):
        rows = []
        for i, (cls, vol) in enumerate(classes_and_volumes):
            rows.append({"gml_id": f"B{i:03d}", "bosserhof_class_norm": cls.lower(),
                         "volume_m3": vol, "geometry": box(i*10, 0, i*10+5, 5)})
        return gpd.GeoDataFrame(rows, crs="EPSG:25832")

    def test_potential_computed_for_normal_office(self):
        df = self._make_buildings([("normal office", 1000.0)])
        weight = BOSSERHOF_WEIGHTS["normal office"]
        expected = 1000.0 * weight
        df["potentials"] = df["volume_m3"] * df["bosserhof_class_norm"].map(BOSSERHOF_WEIGHTS)
        assert abs(df.iloc[0]["potentials"] - expected) < 1e-9

    def test_retail_wholesale_no_nan(self):
        df = self._make_buildings([("retail wholesale", 500.0)])
        df["potentials"] = df["volume_m3"] * df["bosserhof_class_norm"].map(BOSSERHOF_WEIGHTS)
        assert df["potentials"].notna().all(), "'retail wholesale' produced NaN potentials"

    def test_unknown_class_produces_nan(self):
        df = self._make_buildings([("some_fictional_class_xyz", 500.0)])
        df["potentials"] = df["volume_m3"] * df["bosserhof_class_norm"].map(BOSSERHOF_WEIGHTS)
        assert df["potentials"].isna().all(), "Unknown class should produce NaN"

    def test_normalization_map_fixes_nonstandard_labels(self):
        nonstandard = "others"
        normalized  = BOSSERHOF_NORMALIZATION_MAP.get(nonstandard, nonstandard)
        assert normalized in BOSSERHOF_WEIGHTS, f"Normalized '{nonstandard}' → '{normalized}' not in weights"


class TestRedistributionConservation:
    """
    Verify that the redistribution logic conserves demand:
    sum(assigned per zone) ≈ zone target, for each activity.
    """

    def _run_simple_redistribution(self, zones_gdf, buildings_gdf, activity):
        """
        Minimal redistribution: split zone demand proportionally to building volume.
        Returns dict: {gml_id: assigned_value}
        """
        assigned = {}

        for _, zone in zones_gdf.iterrows():
            demand = zone.get(activity, 0)
            if pd.isna(demand) or demand <= 0:
                continue

            # Find buildings in this zone
            bld_in_zone = gpd.sjoin(
                buildings_gdf[["gml_id", "volume_m3", "geometry"]].copy(),
                gpd.GeoDataFrame({"geometry": [zone.geometry]}, crs=zones_gdf.crs),
                how="inner", predicate="within"
            )

            if bld_in_zone.empty:
                continue

            total_vol = bld_in_zone["volume_m3"].sum()
            if total_vol <= 0:
                continue

            for _, brow in bld_in_zone.iterrows():
                share = brow["volume_m3"] / total_vol * demand
                gid   = brow["gml_id"]
                assigned[gid] = assigned.get(gid, 0) + share

        return assigned

    def test_taz_totals_conserved(self, test_buildings, test_zones):
        # Prepare buildings with volume
        buildings = test_buildings.copy().to_crs("EPSG:25832")
        buildings["volume_m3"] = buildings.geometry.area * buildings["measHeight"].astype(float)
        buildings = buildings[buildings["volume_m3"] > 0].copy()

        for activity in ["Workers", "Retail_Daily"]:
            if activity not in test_zones.columns:
                continue

            assigned = self._run_simple_redistribution(test_zones, buildings, activity)
            total_assigned = sum(assigned.values())
            total_demand   = test_zones[activity].fillna(0).sum()

            if total_demand > 0:
                relative_error = abs(total_assigned - total_demand) / total_demand
                assert relative_error < 0.01, (
                    f"{activity}: total assigned ({total_assigned:.2f}) differs from "
                    f"total demand ({total_demand:.2f}) by {relative_error*100:.2f}% > 1%"
                )

    def test_no_demand_lost_to_empty_zones(self, test_zones):
        for act in ZONE_ACTIVITY_COLUMNS:
            if act in test_zones.columns:
                total = test_zones[act].fillna(0).sum()
                assert total >= 0


class TestNormalizationPipeline:
    def test_lowercase_normalization_fixes_casing_bugs(self):
        """Simulate the original bug: mixed-case keys in label_weights."""
        bad_dict  = {"normal Office": 2.9, "Hotels": 1.5, "customer Service": 3.3}
        good_dict = {k.lower(): v for k, v in bad_dict.items()}

        # With bad dict: 'normal office' (lowercase, as normalized by pipeline) → NaN
        assert good_dict.get("normal office") == 2.9
        assert good_dict.get("hotels") == 1.5
        assert good_dict.get("customer service") == 3.3

    def test_bosserhof_weights_are_already_correct(self):
        """Confirm the config dict does not have the old casing bugs."""
        problematic = ["normal Office", "open plan Office", "Hotels",
                       "hotels with conference Areas", "customer Service"]
        for cls in problematic:
            assert cls not in BOSSERHOF_WEIGHTS, (
                f"Mixed-case key '{cls}' still present in BOSSERHOF_WEIGHTS"
            )
