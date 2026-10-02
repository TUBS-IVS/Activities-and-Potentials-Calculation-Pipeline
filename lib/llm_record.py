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

import json
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
    key = r.get("poi_use_tag")                           # r is a Series or a dict
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


def _format_pois(pairs: pd.DataFrame, *, tag_fn=_tag, quote: bool = False, fallback: bool = False,
                 dedupe: bool = True) -> str:
    """'name (tag); name (tag); tag xN: n1; n2; n3; K unnamed' - ordered by share, grouped when a tag repeats.

    The defaults render the step-05 inside line. The POI records (step 07) pass `tag_fn=_poi_tag`,
    `quote=True` (names in quotes, as on the occupant line), `fallback=True` (an unnamed entry shows
    its brand or operator) and `dedupe=False` (two units of one chain are listed twice, so the
    count xN and the list agree)."""
    if pairs.empty:
        return ""
    p = pairs.copy()
    p["_share"] = p["share_in_building"].fillna(0.0)
    p["_tag"] = p.apply(tag_fn, axis=1)
    p = p.sort_values(["_share", "name"], ascending=[False, True], na_position="last")
    counts = p["_tag"].value_counts()

    def label(r):
        """The name part of an entry; None when the entry has none."""
        if not _missing(r["name"]):
            n = _name(r["name"])
            return _quote(n) if quote else n
        if fallback:
            for what in ("brand", "operator"):
                if not _missing(r.get(what)):
                    return f"unnamed, {what} {_quote(_name(r[what]))}"
        return None

    out, done = [], set()
    for _, r in p.iterrows():
        tag = r["_tag"]
        if counts[tag] >= GROUP_SAME_USE_FROM:
            if tag in done:
                continue
            done.add(tag)
            named = [l for _, x in p[p["_tag"] == tag].iterrows() if (l := label(x)) is not None]
            names = list(dict.fromkeys(named)) if dedupe else named      # two units of one chain: one name (step 05)
            unnamed = int(counts[tag]) - len(named)
            body = "; ".join(names)
            if unnamed:
                body = (body + "; " if body else "") + f"{unnamed} unnamed"
            out.append(f"{tag} x{int(counts[tag])}: {body}")
        else:
            l = label(r)
            out.append(f"{l} ({tag})" if l else f"unnamed ({tag})")
    return "; ".join(out)


def _format_sites(sites: pd.DataFrame, *, tag_fn=_tag, quote: bool = False) -> str:
    if sites.empty:
        return ""
    s = sites.sort_values("share_of_site", ascending=False, na_position="last")
    out = []
    for _, r in s.iterrows():
        tag = tag_fn(r)
        if _missing(r["name"]):
            out.append(f"unnamed ({tag})")
        else:
            n = _name(r["name"])
            out.append(f"{_quote(n) if quote else n} ({tag})")
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
    cad = _cadastre(row)
    if cad:
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

    place = _place(row)
    if place:
        lines.append("place: " + place)
    return "\n".join(lines)


def _cadastre(row) -> str:
    """'<class>, named "<name>"' on ALKIS rows; '' on OSM gap rows, which have no register entry."""
    if row.get("source") == "osm":
        return ""
    cad = _txt(row["label_en"])
    if not _missing(row.get("name")):
        cad += f", named {_quote(_txt(row['name']))}"
    return cad


def _place(row) -> str:
    """'<municipality> | footprint N m2 | height N m' - whatever of the three is there."""
    place = []
    if not _missing(row.get("city")):
        place.append(_CITY_SUFFIX.sub("", _txt(row["city"])))
    if not _missing(row.get("area_m2")):
        place.append(f"footprint {int(round(float(row['area_m2'])))} m2")
    if not _missing(row.get("height_top_max_m")):
        h = int(round(float(row["height_top_max_m"])))
        if h >= 1:
            place.append(f"height {h} m")
    return " | ".join(place)


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


# ------------------------------------------------------------------ step 07: one POI in one building
# The occupant comes first, then where it sits, then the building's own lines in the
# order of build_record, each prefixed "building" so that context cannot be mistaken
# for the thing to label. The same cleaning rules apply (key=value tags, whole metres,
# no thousands separators, no line breaks or semicolons in a name, city suffix dropped).
# What the stand-in dry run of 2026-09-30 (26 records, three cold readers each, two
# critics) changed against the first draft, all measured on the 22,633 records:
#   * a use that step 01 wrote as the key itself (the mapper gave only "yes"; 242 own
#     pairs: historic, office, shop, club ...) is written key=yes, not historic=historic;
#   * qualifying tags follow the tag after a comma (leisure=sports_centre after
#     sport=multi, social_facility=group_home after amenity=social_facility) - the
#     notebook joins them with `poi_qualifiers`;
#   * a POI that is the building's own OSM outline (poi_use_tag == building, 1,534 own
#     pairs, median area ratio 1.01 to the footprint; or poi_id == building_id, the 519
#     OSM gap buildings) is not a tenant: as the occupant its role is "the building
#     itself", as a neighbour it goes on the "building footprint" line, as a unit's
#     parent it makes the unit simply "inside the building";
#   * a snapped occupant says whether it is a point outside the building or an area
#     around or next to it (903 of the 2,004 snapped POIs are areas), with the distance;
#   * the parent named on the role line is not repeated among the neighbours; the
#     neighbours are written as on the occupant line (quoted names, brand or operator
#     for an unnamed entry) and listed as often as they occur, so a group's count and
#     its list agree.
# Every line of a POI record starts with one of these - notebook 07 checks it:
POI_LINE_PREFIXES = ("occupant: ", "role: ", "building also inside: ", "building footprint: ",
                     "building site: ", "building cadastre: ", "building place: ")


def poi_qualifiers(pois: pd.DataFrame, keys, building_for) -> pd.Series:
    """One string per POI, 'leisure=sports_centre, building=sports_hall': the tags among `keys`
    that the POI carries besides its own use key, in the order of `keys`, read from the
    step-01 layer's columns where the key is a column, else from the folded `tags` JSON.
    `building` is shown only for a use key in `building_for` (for amenity, shop, office ...
    the POI's own building=* tag says nothing the use does not). '' where there is none."""
    tags = pois["tags"].map(lambda t: json.loads(t) if isinstance(t, str) and t.strip() else {})
    cols = set(pois.columns)
    out = []
    for (_, r), t in zip(pois.iterrows(), tags):
        main = _txt(r["poi_use_tag"]) if not _missing(r.get("poi_use_tag")) else ""
        parts = []
        for k in keys:
            if k == main or (k == "building" and main not in building_for):
                continue
            v = r[k] if k in cols else t.get(k)
            if not _missing(v):
                parts.append(f"{k}={_txt(v).replace('; ', ';')}")
        out.append(", ".join(parts))
    return pd.Series(out, index=pois.index, dtype="object")


def _poi_tag(r) -> str:
    """The tag of a POI record entry: 'key=value'; 'key=yes' where step 01 wrote the key as the
    use; the qualifiers after it, from the `qualifiers` column when the notebook joined it."""
    use = _txt(r["poi_use"]).replace("; ", ";")
    key = r.get("poi_use_tag")
    if _missing(key):
        tag = use
    elif _txt(key) == use:
        tag = f"{_txt(key)}=yes"
    else:
        tag = f"{_txt(key)}={use}"
    q = r.get("qualifiers")
    return f"{tag}, {_txt(q)}" if not _missing(q) else tag


def occupant_evidence(r) -> str:
    """What the occupant line carries: 'named', 'brand', 'operator' (an unnamed occupant shown
    with that tag) or 'unnamed'. Recorded next to every record for QA and the sample."""
    if not _missing(r.get("name")):
        return "named"
    for what in ("brand", "operator"):
        if not _missing(r.get(what)):
            return what
    return "unnamed"


def _occupant(r) -> str:
    """'"Name" (key=value, qualifiers)'; an unnamed occupant shows its brand or operator when the mapper gave one."""
    tag = _poi_tag(r)
    kind = occupant_evidence(r)
    if kind == "named":
        return f"{_quote(_name(r['name']))} ({tag})"
    if kind in ("brand", "operator"):
        return f"unnamed, {kind} {_quote(_name(r[kind]))} ({tag})"
    return f"unnamed ({tag})"


def _is_outline(r) -> bool:
    """A POI that is the building's own OSM outline: tagged building=*, or the gap building itself."""
    key_is_building = (not _missing(r.get("poi_use_tag"))) and _txt(r["poi_use_tag"]) == "building"
    is_the_building = (not _missing(r.get("building_id"))) and r["poi_id"] == r["building_id"]
    return key_is_building or is_the_building


def _role(r) -> str:
    """Where the occupant sits, from `how`, `geom_kind`, `snap_m` and the parent columns."""
    how = _txt(r["how"])
    outline = _is_outline(r)
    if outline and how != "snap":
        return "the building itself: the tag is the one on its OSM outline"
    if how == "unit":
        if _txt(r.get("parent_use_tag")) == "building" or (
                not _missing(r.get("parent_name")) and not _missing(r.get("name"))
                and _name(r["parent_name"]) == _name(r["name"])):
            return "inside the building"                    # the parent is the building's outline, or the occupant's own
        use = _txt(r["parent_use"]).replace("; ", ";") if not _missing(r.get("parent_use")) else "unknown"
        key = r.get("parent_use_tag")
        tag = f"{_txt(key)}={use}" if not _missing(key) else use
        if not _missing(r.get("parent_name")):
            return f"a unit inside {_quote(_name(r['parent_name']))} ({tag})"
        return f"a unit inside an unnamed {tag}"
    if how == "snap":
        kind = "an area" if _txt(r.get("geom_kind")) == "area" else "a point"
        d = r.get("snap_m")
        if _missing(d):
            dist = "some way"
        else:
            m = int(round(float(d)))
            dist = "under 1 m" if m < 1 else f"{m} m"
        if outline:
            return f"placed on the nearest building: the OSM outline of a building mapped {dist} from this one"
        if kind == "an area":
            return f"placed on the nearest building: an area mapped {dist} from it"
        return f"placed on the nearest building: a point mapped {dist} outside it"
    return "inside the building"


def _format_outlines(outlines: pd.DataFrame) -> str:
    """'building=school, named "Realschule Calberlah"; building=yes' - the building's own OSM outline(s)."""
    if outlines.empty:
        return ""
    o = outlines.sort_values("share_in_building", ascending=False, na_position="last")
    out = []
    for _, r in o.iterrows():
        s = _poi_tag(r)
        if not _missing(r["name"]):
            s += f", named {_quote(_name(r['name']))}"
        out.append(s)
    return "; ".join(out)


def build_poi_record(pair_row, building_row, pairs: pd.DataFrame) -> str:
    """Render one POI in one building.

    pair_row:     its row of the building_pois layer, with `poi_use_tag` and, where the
                  notebook joined them, `qualifiers`, `brand`, `operator`, `geom_kind` and
                  `parent_use_tag`;
    building_row: its building's row of the step-06 buildings layer (label_en, name,
                  source, city, area_m2, height_top_max_m);
    pairs:        every building_pois row of that building, the occupant included or not
                  (it is removed here): the other own pairs become "building also inside",
                  the building's own OSM outline(s) "building footprint", the site rows
                  "building site"; the parent named on the role line is left out.
    No id line, as in build_record: the answer is joined by poi_id beside the record."""
    role = _role(pair_row)
    lines = [f"occupant: {_occupant(pair_row)}", f"role: {role}"]
    if len(pairs):
        own = pairs[(pairs["poi_role"] != "site") & (pairs["poi_id"] != pair_row["poi_id"])]
        is_outline = own.apply(_is_outline, axis=1).astype(bool) if len(own) else pd.Series([], dtype=bool)
        outlines = own[is_outline]
        others = own[~is_outline]
        if role.startswith("a unit inside ") and not _missing(pair_row.get("poi_parent_id")):
            others = others[others["poi_id"] != pair_row["poi_parent_id"]]      # named on the role line already
        sites = pairs[pairs["poi_role"] == "site"]
    else:
        outlines = others = sites = pairs
    inside = _format_pois(others, tag_fn=_poi_tag, quote=True, fallback=True, dedupe=False)
    if inside:
        lines.append(f"building also inside: {inside}")
    footprint = _format_outlines(outlines)
    if footprint:
        lines.append(f"building footprint: {footprint}")
    site = _format_sites(sites, tag_fn=_poi_tag, quote=True)
    if site:
        lines.append(f"building site: {site}")
    cad = _cadastre(building_row)
    if cad:
        lines.append(f"building cadastre: {cad}")
    place = _place(building_row)
    if place:
        lines.append(f"building place: {place}")
    return "\n".join(lines)


def build_poi_records(pairs: pd.DataFrame, buildings: pd.DataFrame, poi_ids=None) -> pd.DataFrame:
    """Every own pair (how != 'site') -> DataFrame[poi_id, building_id, how, evidence, record, n_chars],
    in the order of `pairs`; only the own pairs in `poi_ids` when that is given (the context of a
    record still comes from every pair of its building). `pairs` is the whole building_pois layer
    (site rows included, they render the site line) with `poi_use_tag`, `geom_kind`, `qualifiers`,
    `brand`, `operator` and `parent_use_tag`; `buildings` the step-06 buildings layer, one row per
    building_id."""
    for c in ("poi_id", "building_id", "poi_role", "how", "poi_use", "poi_use_tag", "name", "share_in_building"):
        if c not in pairs.columns:
            raise KeyError(f"pairs lack the column {c!r}")
    if buildings["building_id"].duplicated().any():
        raise ValueError("a building_id appears twice in the buildings frame")
    bld = buildings.set_index("building_id")
    own = pairs[pairs["how"] != "site"]
    if poi_ids is not None:
        own = own[own["poi_id"].isin(set(poi_ids))]
    missing = sorted(set(own["building_id"]) - set(bld.index))
    if missing:
        raise KeyError(f"{len(missing)} own pair(s) point at buildings not in the layer, e.g. {missing[:3]}")
    by_bld = {k: g for k, g in pairs.groupby("building_id", sort=False)}
    recs, kinds = [], []
    for _, r in own.iterrows():
        recs.append(build_poi_record(r, bld.loc[r["building_id"]], by_bld[r["building_id"]]))
        kinds.append(occupant_evidence(r))
    return pd.DataFrame({
        "poi_id": own["poi_id"].to_numpy(),
        "building_id": own["building_id"].to_numpy(),
        "how": own["how"].to_numpy(),
        "evidence": kinds,
        "record": recs,
        "n_chars": [len(x) for x in recs],
    })
