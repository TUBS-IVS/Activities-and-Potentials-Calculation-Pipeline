"""Who gets asked (step 05.4).

One call per building wherever the record carries evidence of its own: a POI,
a site, a name, an activity tag. The class_only buildings carry nothing but a
register class, a footprint type, the land use and a size, and two such
buildings with the same class, land and size band are the same question; asking
it twice can only produce two answers. They are grouped into signatures and
each signature is asked once, on the record of its median-area member. The
answer is copied to every member in the assembly step and marked as copied.

The plan is a table with one row per building:
  route          'building' (its own call) or 'signature' (shares a call)
  signature      the signature string, NULL for route 'building'
  answered_by    the building whose record is sent - itself for route
                 'building', the representative for route 'signature'
  n_in_signature how many buildings share the answer (1 for route 'building')
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import LLM_SIGNATURE_AREA_BINS_M2, LLM_SIGNATURE_HEIGHT_BINS_M

PLAN_COLUMNS = ["building_id", "evidence", "route", "signature", "answered_by", "n_in_signature"]


def _band(values: pd.Series, edges, unit: str) -> pd.Series:
    """'<250 m2', '250-500 m2', ..., '>=2500 m2'; 'unknown' where the value is missing."""
    edges = list(edges)
    labels = [f"<{edges[0]} {unit}"] + [f"{a}-{b} {unit}" for a, b in zip(edges[:-1], edges[1:])] + [f">={edges[-1]} {unit}"]
    idx = np.digitize(values.fillna(-1).to_numpy(dtype=float), edges, right=False)
    out = pd.Series([labels[i] for i in idx], index=values.index, dtype="object")
    out[values.isna()] = f"unknown {unit}"
    return out


def build_plan(bld: pd.DataFrame, evidence: pd.DataFrame) -> pd.DataFrame:
    """bld: the buildings layer (label_en, osm_twin_tag, osm_building, alkis_landuse,
    alkis_landuse_detail, osm_landuse, area_m2, height_top_max_m); evidence: [building_id, evidence]."""
    df = bld[["building_id", "label_en", "osm_twin_tag", "osm_building", "alkis_landuse",
              "alkis_landuse_detail", "osm_landuse", "area_m2", "height_top_max_m"]].merge(
        evidence[["building_id", "evidence"]], on="building_id", how="inner", validate="one_to_one")
    if len(df) != len(bld):
        raise AssertionError(f"{len(bld) - len(df):,} buildings have no evidence group")

    plan = pd.DataFrame({
        "building_id": df["building_id"].to_numpy(),
        "evidence": df["evidence"].to_numpy(),
        "route": "building",
        "signature": pd.Series([None] * len(df), dtype="object"),
        "answered_by": df["building_id"].to_numpy(),
        "n_in_signature": 1,
    })

    co = df["evidence"] == "class_only"
    c = df[co]
    if len(c):
        tag = c["osm_twin_tag"].where(c["osm_twin_tag"].notna(), c["osm_building"]).fillna("-").astype(str).str.lower()
        parts = [
            c["label_en"].fillna("-").astype(str),
            "footprint " + tag,
            "land " + c["alkis_landuse"].fillna("-").astype(str),
            c["alkis_landuse_detail"].fillna("-").astype(str),
            "osm " + c["osm_landuse"].fillna("-").astype(str),
            _band(c["area_m2"], LLM_SIGNATURE_AREA_BINS_M2, "m2"),
            _band(c["height_top_max_m"], LLM_SIGNATURE_HEIGHT_BINS_M, "m"),
        ]
        sig = parts[0]
        for p in parts[1:]:
            sig = sig + " | " + p
        c = c.assign(signature=sig.to_numpy())
        # the representative: the member whose footprint is closest to the group's median
        med = c.groupby("signature")["area_m2"].transform("median")
        c = c.assign(_dist=(c["area_m2"] - med).abs()).sort_values(["signature", "_dist", "building_id"])
        rep = c.groupby("signature")["building_id"].first()
        size = c.groupby("signature").size()
        plan.loc[co.to_numpy(), "route"] = "signature"
        plan.loc[co.to_numpy(), "signature"] = c.set_index("building_id").loc[plan.loc[co.to_numpy(), "building_id"], "signature"].to_numpy()
        plan.loc[co.to_numpy(), "answered_by"] = plan.loc[co.to_numpy(), "signature"].map(rep).to_numpy()
        plan.loc[co.to_numpy(), "n_in_signature"] = plan.loc[co.to_numpy(), "signature"].map(size).astype(int).to_numpy()

    # contract
    if plan["building_id"].duplicated().any():
        raise AssertionError("a building appears twice in the plan")
    if not set(plan["answered_by"]).issubset(set(plan["building_id"])):
        raise AssertionError("a representative is not a building of the plan")
    own = plan["route"] == "building"
    if (plan.loc[own, "answered_by"] != plan.loc[own, "building_id"]).any():
        raise AssertionError("a building with its own call is answered by another building")
    if (plan.loc[~own, "n_in_signature"] < 1).any() or plan.loc[~own, "signature"].isna().any():
        raise AssertionError("a signature row without signature or size")
    return plan[PLAN_COLUMNS]
