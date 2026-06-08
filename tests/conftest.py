"""
conftest.py — Shared pytest fixtures for the capacity pipeline test suite.
"""

import sys
from pathlib import Path

import pytest
import geopandas as gpd
import pandas as pd

# Make the project root importable
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

TEST_DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def test_buildings():
    return gpd.read_file(TEST_DATA_DIR / "test_buildings.gpkg")


@pytest.fixture(scope="session")
def test_boundary():
    return gpd.read_file(TEST_DATA_DIR / "test_boundary.gpkg")


@pytest.fixture(scope="session")
def test_pois():
    return gpd.read_file(TEST_DATA_DIR / "test_pois.gpkg")


@pytest.fixture(scope="session")
def test_zones():
    return gpd.read_file(TEST_DATA_DIR / "test_zones.gpkg", layer="zone_targets")
