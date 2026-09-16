"""checks.py — contract assertions shared by every pipeline step.

Each step asserts what it expects on the way IN and what it guarantees on the
way OUT, so step n+1 can trust step n instead of re-discovering its quirks.

These live in one module rather than being pasted into each notebook on
purpose: duplicated notebook logic in this project has drifted before, and a
check that exists in three slightly different versions is not a check.
"""

from pathlib import Path


def require_file(path, what=""):
    """Fail early and legibly when an input is missing."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"missing input{' (' + what + ')' if what else ''}: {p}")
    size_mb = p.stat().st_size / 1e6
    print(f"  ok  {p.name} ({size_mb:,.1f} MB)")
    return p


def require_non_empty(gdf, name="frame"):
    if len(gdf) == 0:
        raise ValueError(f"{name} is empty")
    print(f"  ok  {name}: {len(gdf):,} rows")


def require_cols(gdf, cols, name="frame"):
    missing = [c for c in cols if c not in gdf.columns]
    if missing:
        raise KeyError(f"{name} is missing columns {missing}")
    print(f"  ok  {name}: has {cols}")


def require_crs(gdf, crs, name="frame"):
    if gdf.crs is None:
        raise ValueError(f"{name} has no CRS")
    if gdf.crs.to_string() != str(crs):
        raise ValueError(f"{name} is {gdf.crs.to_string()}, expected {crs}")
    print(f"  ok  {name}: CRS {crs}")


def require_unique(gdf, col, name="frame"):
    if col not in gdf.columns:
        raise KeyError(f"{name} has no column {col!r}")
    n_dup = int(gdf[col].duplicated().sum())
    if n_dup:
        raise ValueError(f"{name}.{col} has {n_dup:,} duplicate values")
    n_null = int(gdf[col].isna().sum())
    if n_null:
        raise ValueError(f"{name}.{col} has {n_null:,} nulls")
    print(f"  ok  {name}.{col}: unique and non-null ({len(gdf):,})")


def count_outside(gdf, boundary_geom, name="frame"):
    """Report how many rows fall outside the study boundary.

    Deliberately a REPORT, not an assertion. `osmium extract -s complete_ways`
    keeps whole ways that merely touch the polygon, so a small overhang is
    expected and correct. A large one means the wrong boundary or the wrong PBF.
    """
    outside = ~gdf.geometry.intersects(boundary_geom)
    n = int(outside.sum())
    pct = 100.0 * n / len(gdf) if len(gdf) else 0.0
    print(f"  ..  {name}: {n:,} of {len(gdf):,} rows outside boundary ({pct:.2f} %)")
    return gdf[outside]
