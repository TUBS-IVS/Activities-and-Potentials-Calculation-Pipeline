"""
create_llm_test_sample.py — Sample diverse rows from the real condensed buildings
file and save as tests/data/sample_condensed_buildings.parquet.

Run once after NB05 produces a new condensed buildings file:
    python tests/create_llm_test_sample.py

The output is a small (24-row) fixture used by test_06_llm_mock.py so tests
run on realistic inputs without loading the full 500k-row dataset.
"""

import sys
from pathlib import Path
import pandas as pd
import geopandas as gpd

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CONDENSED_BUILDINGS_FILE

DATA_DIR = Path(__file__).parent / "data"
OUT_FILE = DATA_DIR / "sample_condensed_buildings.parquet"
ROWS_PER_BUCKET = 3

print(f"Loading {CONDENSED_BUILDINGS_FILE} ...")
df = gpd.read_file(CONDENSED_BUILDINGS_FILE)
df = df.drop(columns=["geometry"])
print(f"Loaded {len(df):,} rows")

buckets = {
    "school":       df[df["amenity"].astype(str).str.contains("school", na=False)],
    "kindergarten": df[df["amenity"].astype(str).str.contains("kindergarten", na=False)],
    "restaurant":   df[df["amenity"].astype(str).str.contains("restaurant", na=False)],
    "supermarket":  df[df["shop"].astype(str).str.contains("supermarket", na=False)],
    "hospital":     df[df["amenity"].astype(str).str.contains("hospital", na=False)],
    "office":       df[df["amenity"].astype(str).str.contains("office", na=False)],
    "named_only":   df[df["osm_names"].notna() & df["amenity"].isna() & df["shop"].isna()],
    "sparse":       df[df["amenity"].isna() & df["shop"].isna() & df["osm_names"].isna()],
}

rows = []
for bucket, bdf in buckets.items():
    n = min(ROWS_PER_BUCKET, len(bdf))
    sample = bdf.sample(n, random_state=42).copy()
    sample["_bucket"] = bucket
    rows.append(sample)
    print(f"  {bucket}: {n} rows sampled (pool size: {len(bdf):,})")

out = pd.concat(rows, ignore_index=True)
out.to_parquet(OUT_FILE, index=False)
print(f"\nSaved {len(out)} rows → {OUT_FILE}")
