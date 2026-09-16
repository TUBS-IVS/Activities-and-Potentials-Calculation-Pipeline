"""The per-building record the LLM reads (step 05.2).

One building, one record, one call. The record is a compact labelled block, not
prose and not JSON: the format the previous pipeline validated at 78.5 % on the
annotated set, with four changes decided 2026-09-14:

  * each POI's name is paired with its OSM tag ("Star Tankstelle (amenity=fuel)")
    - the building row's `poi_uses` / `poi_names` lists are NOT aligned (a
    building can carry 4 uses and 3 names), so the pairs come from the
    `building_pois` layer, ordered by share;
  * every line names its SOURCE (inside / site / cadastre / osm footprint /
    land / place) instead of a confidence level - the system prompt says how
    much each source weighs, and a cadastre name stays distinguishable from a
    mapper's;
  * empty fields are omitted, absence is the information;
  * numbers are rounded to whole metres and square metres.

Nothing is capped: every POI name is kept. Where many POIs share one tag
(a snake farm with 20 `tourism=attraction` points) they are grouped under that
tag so the record stays readable without losing a name.

The dry run of 2026-09-14 (30 cold runs on 10 real records) found what the
renderer, not the prompt, had hidden from the model, and this module fixes it:
  * the tag is written key=value, not the bare value - `multi` (sport=multi,
    150 POIs), `it` (office=it, 81), `car` (shop=car, 232), `apartment`
    (tourism=apartment, 179), `works` (man_made=works, 250) mean nothing alone;
    the key comes from the `poi_use_tag` column the notebook joins from the
    step 01 POI layer;
  * the area has no thousands separator - a German reader takes "24,395 m2"
    for a decimal;
  * OSM gap-fill rows get no cadastre line - their label is a placeholder, and
    the prompt says an absent line means the source has nothing to say;
  * names lose line breaks and semicolons, which broke a record into unlabelled
    lines or one entry into two;
  * a multi-value tag keeps its semicolons unspaced ("shop=gift;tobacco") so
    it cannot mimic the entry separator;
  * the municipality loses its legal-form suffix (", Stadt", ", Flecken");
  * a height that rounds to zero is left out.

Only the 15 columns config.LLM_INPUT_COLS marks "llm" are read here; the
model-only columns never enter the text. Keep this module free of any call
logic - it must stay importable for the validation that reproduces what the
model saw.
"""
from __future__ import annotations

import math
import re

import pandas as pd

# POIs sharing one tag are grouped from this many onwards: "tourism=attraction x20: a; b; c"
GROUP_SAME_USE_FROM = 3

# every line of a record starts with one of these - the notebook checks it, so a
# stray line break inside a value can never reach the model as an unlabelled line
LINE_PREFIXES = ("inside: ", "site: ", "cadastre: ", "osm footprint: ", "land: ", "place: ")

_CITY_SUFFIX = re.compile(r",\s*(Stadt|Flecken)$")


def _missing(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    if isinstance(v, str) and not v.strip():
        return True
    return v is pd.NA


def _txt(v) -> str:
    """Trimmed, with every run of whitespace (line breaks included) collapsed to one space."""
    return " ".join(str(v).split())


def _name(v) -> str:
    """A POI name for the inside/site line: ';' is the entry separator, so it cannot stay in a name."""
    return _txt(v).replace(";", ",")


def _quote(name: str) -> str:
    return '"' + name.replace('"', "'") + '"'


def _tag(r) -> str:
    """The POI's OSM tag as key=value ('shop=car'); the bare value when the key is not there."""
    use = _txt(r["poi_use"]).replace("; ", ";")          # a multi-value tag stays one token
    key = r["poi_use_tag"] if "poi_use_tag" in r.index else None
    return f"{_txt(key)}={use}" if not _missing(key) else use


def evidence_group(row) -> str:
    """Which of the four evidence groups a building falls in (for routing and QA)."""
    if not _missing(row.get("poi_uses")) or not _missing(row.get("site_uses")):
        return "poi_or_site"
    if not _missing(row.get("name")) or not _missing(row.get("osm_twin_name")):
        return "name_only"
    tag = row.get("osm_twin_tag") if not _missing(row.get("osm_twin_tag")) else row.get("osm_building")
    if not _missing(tag) and _txt(tag).lower() != "yes":
        return "tag_only"
    return "class_only"


def _format_pois(pairs: pd.DataFrame) -> str:
    """'name (tag); name (tag); tag xN: n1; n2; n3; K unnamed' - ordered by share, grouped when a tag repeats."""
    if pairs.empty:
        return ""
    p = pairs.copy()
    p["_share"] = p["share_in_building"].fillna(0.0)
    p["_tag"] = p.apply(_tag, axis=1)
    p = p.sort_values(["_share", "name"], ascending=[False, True], na_position="last")
    counts = p["_tag"].value_counts()
    out, done = [], set()
    for _, r in p.iterrows():
        tag = r["_tag"]
        name = None if _missing(r["name"]) else _name(r["name"])
        if counts[tag] >= GROUP_SAME_USE_FROM:
            if tag in done:
                continue
            done.add(tag)
            named = [_name(n) for n in p.loc[p["_tag"] == tag, "name"] if not _missing(n)]
            names = list(dict.fromkeys(named))            # two units of one chain: one name
            unnamed = int(counts[tag]) - len(named)
            body = "; ".join(names)
            if unnamed:
                body = (body + "; " if body else "") + f"{unnamed} unnamed"
            out.append(f"{tag} x{int(counts[tag])}: {body}")
        else:
            out.append(f"{name} ({tag})" if name else f"unnamed ({tag})")
    return "; ".join(out)


def _format_sites(sites: pd.DataFrame) -> str:
    if sites.empty:
        return ""
    s = sites.sort_values("share_of_site", ascending=False, na_position="last")
    out = []
    for _, r in s.iterrows():
        tag = _tag(r)
        out.append(f"{_name(r['name'])} ({tag})" if not _missing(r["name"]) else f"unnamed ({tag})")
    return "; ".join(out)


def build_record(row, pairs: pd.DataFrame) -> str:
    """Render one building. `row` is its buildings-layer row, `pairs` its rows of the
    building_pois layer (may be empty). Lines with nothing to say are left out."""
    # No id line: one building per call, the answer is joined by position, and the
    # id would only be a token string the model might try to read something into.
    lines = []

    own = pairs[pairs["poi_role"] != "site"] if len(pairs) else pairs
    sites = pairs[pairs["poi_role"] == "site"] if len(pairs) else pairs
    inside = _format_pois(own)
    if inside:
        lines.append(f"inside: {inside}")
    site = _format_sites(sites)
    if site:
        lines.append(f"site: {site}")

    # the cadastre: class and, on ALKIS rows, its own name. An OSM gap-fill row has
    # no register entry - its label_en is a placeholder - so it gets no line at all.
    if row.get("source") != "osm":
        cad = _txt(row["label_en"])
        if not _missing(row.get("name")):
            cad += f", named {_quote(_txt(row['name']))}"
        lines.append(f"cadastre: {cad}")

    # the OSM footprint: the twin's tag on ALKIS rows, the row's own tag on OSM rows
    tag = row.get("osm_twin_tag")
    if _missing(tag):
        tag = row.get("osm_building")
    osm_name = row.get("osm_twin_name")
    if row.get("source") == "osm" and not _missing(row.get("name")):
        osm_name = row.get("name")                       # an OSM gap row's name IS the footprint's name
    bits = []
    if not _missing(tag):
        bits.append(_txt(tag).lower())
    if not _missing(osm_name):
        bits.append(f"named {_quote(_txt(osm_name))}")
    if bits:
        lines.append("osm footprint: " + ", ".join(bits))

    land = []
    if not _missing(row.get("alkis_landuse")):
        l = _txt(row["alkis_landuse"])
        if not _missing(row.get("alkis_landuse_detail")):
            l += f", {_txt(row['alkis_landuse_detail'])}"
        land.append(l)
    if not _missing(row.get("osm_landuse")):
        land.append(f"osm: {_txt(row['osm_landuse'])}")
    if land:
        lines.append("land: " + " | ".join(land))

    place = []
    if not _missing(row.get("city")):
        place.append(_CITY_SUFFIX.sub("", _txt(row["city"])))
    if not _missing(row.get("area_m2")):
        place.append(f"footprint {int(round(float(row['area_m2'])))} m2")
    if not _missing(row.get("height_top_max_m")):
        h = int(round(float(row["height_top_max_m"])))
        if h >= 1:
            place.append(f"height {h} m")
    if place:
        lines.append("place: " + " | ".join(place))
    return "\n".join(lines)


def build_records(buildings: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    """All buildings -> DataFrame[building_id, evidence, record, n_chars], same order as `buildings`.
    `pairs` should carry `poi_use_tag` (the OSM key) next to `poi_use`; without it the bare value is written."""
    by_bld = {k: g for k, g in pairs.groupby("building_id", sort=False)}
    empty = pairs.iloc[0:0]
    recs, groups = [], []
    for row in buildings.to_dict("records"):
        recs.append(build_record(row, by_bld.get(row["building_id"], empty)))
        groups.append(evidence_group(row))
    return pd.DataFrame({
        "building_id": buildings["building_id"].to_numpy(),
        "evidence": groups,
        "record": recs,
        "n_chars": [len(r) for r in recs],
    })
