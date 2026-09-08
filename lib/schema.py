"""schema.py — reduce a pyrosm frame to a workable schema without losing data.

`pyrosm` promotes every OSM tag it recognises to its own column, which gives a
frame with ~100 columns of which a handful are populated and the rest hold two
or three values each. That is unusable downstream and expensive to carry.

The reduction here is deliberately **lossless**: a dropped tag column is folded
into the `tags` JSON string rather than deleted, so a step three notebooks later
can still recover `capacity:beds` without re-parsing the PBF. Only OSM edit
metadata (version, changeset, ...) is dropped outright, because it describes the
edit and not the thing.

Kept in one module rather than pasted into each notebook because both the POI
and the building layer need it, and a fold that exists in two slightly different
versions would put the same tag in a column in one layer and in `tags` in the
other.
"""

import json

import pandas as pd


def fold_tags(gdf, keep, meta=(), tags_col="tags"):
    """Fold every non-kept tag column into `tags_col`.

    Parameters
    ----------
    gdf : GeoDataFrame
    keep : list of column names to retain as real fields. Missing names are
        ignored, so one list can serve regions where a tag never occurs.
    meta : column names to drop WITHOUT folding (OSM edit metadata).
    tags_col : the existing JSON-string column to fold into. Created if absent.

    Returns
    -------
    (GeoDataFrame, folded_column_names)
        The frame is a copy; `tags_col` holds a JSON string or None.
    """
    out = gdf.copy()
    if tags_col not in out.columns:
        out[tags_col] = None

    protected = set(keep) | set(meta) | {tags_col, out.geometry.name}
    folded = [c for c in out.columns if c not in protected]

    def _fold(row):
        raw = row[tags_col]
        merged = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
        for c in folded:
            v = row[c]
            if pd.notna(v) and str(v) != "":
                # setdefault: a value already in `tags` is the authoritative one,
                # since pyrosm only promotes a tag it did not also leave there.
                merged.setdefault(c, str(v))
        return json.dumps(merged, ensure_ascii=False, sort_keys=True) if merged else None

    if folded:
        out[tags_col] = out.apply(_fold, axis=1)
    return out, folded


def osm_key(gdf, name="osm_key"):
    """Add a stable unique key.

    A node and a way can share an OSM id, so `id` alone is not a key - there is
    such a collision in this region's POIs. `osm_type` + `id` is.
    """
    out = gdf.copy()
    out[name] = out["osm_type"].astype(str) + "/" + out["id"].astype(str)
    return out


def tidy_names(gdf):
    """Rename `addr:street` -> `addr_street`.

    A colon is legal in a GeoPackage column name but needs quoting in SQL and in
    QGIS expressions, which makes every downstream filter fragile.
    """
    return gdf.rename(columns={c: c.replace(":", "_") for c in gdf.columns})


def assert_no_empty_columns(gdf, name="frame"):
    """Fail if a column was kept but holds nothing after filtering.

    A column that survives the keep-list but is entirely null is either a
    filtering mistake or a stale entry in the list. Either way the schema claims
    something the data does not have.
    """
    dead = [
        c for c in gdf.columns
        if c != gdf.geometry.name and gdf[c].notna().sum() == 0
    ]
    if dead:
        raise AssertionError(f"{name}: columns kept but empty: {dead}")
    print(f"  ok  {name}: {len(gdf.columns)} columns, none empty")
