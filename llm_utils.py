"""
llm_utils.py — Shared helpers for LLM building classification.

Imported by:
  - notebooks/06_llm_classification.ipynb
  - notebooks/07_llm_error_rerun.ipynb
  - tests/test_06_llm_mock.py
  - llm_smoke_test.py

Edit here; nowhere else.
"""

import json
import re
import pandas as pd


def is_missing(x):
    if x is None: return True
    if isinstance(x, float) and pd.isna(x): return True
    if isinstance(x, str) and x.strip().lower() in ("", "none", "nan", "null"): return True
    if isinstance(x, (list, tuple, set, dict)) and len(x) == 0: return True
    return False


def format_value(x):
    if is_missing(x): return None
    if isinstance(x, (list, tuple, set)):
        vals = [format_value(v) for v in x if not is_missing(v)]
        return "; ".join(v for v in vals if v) or None
    return str(x).strip()


def row_to_llm_input(row):
    precise_fields = [("osm_names", "name"), ("amenity", "amenity"), ("building", "building"),
                      ("shop", "shop"), ("tourism", "tourism"), ("information", "information"),
                      ("website", "website"), ("email", "email")]
    general_fields = [("label_en", "building_label"), ("osm_building_type", "osm_building_type"),
                      ("osm_landuse_class", "osm_landuse_class"), ("osm_landuse_name", "osm_landuse_name"),
                      ("gfk_class", "gfk_class"), ("ALKIS_Landuse_info", "alkis_landuse"),
                      ("tags_search", "tags"), ("additional_information", "additional_info")]

    def collect(fields):
        bits = []
        for col, label in fields:
            val = format_value(row.get(col))
            if val: bits.append(f"{label}={val}")
        return bits

    sections = []
    p = collect(precise_fields)
    g = collect(general_fields)
    if p: sections.append("precise_known_info: " + " | ".join(p))
    if g: sections.append("general_building_context: " + " | ".join(g))
    return "\n".join(sections)


def extract_first_json(text):
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m: raise ValueError("No JSON object found")
    return json.loads(m.group(0))


def validate(obj, valid_labels):
    for key in ("interpreted_type", "mid_labels", "bosserhof_class", "reason"):
        if key not in obj: raise ValueError(f"Missing key: {key}")
    if not isinstance(obj["mid_labels"], list): raise ValueError("mid_labels must be a list")
    for lab in obj["mid_labels"]:
        if lab not in valid_labels: raise ValueError(f"Invalid label: {lab}")
    bc = obj["bosserhof_class"]
    if bc not in (None, []) and not (isinstance(bc, str) and bc.strip()):
        raise ValueError("bosserhof_class must be a non-empty string or null")
