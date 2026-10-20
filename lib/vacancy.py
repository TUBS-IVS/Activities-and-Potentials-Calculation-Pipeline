"""vacancy.py — which buildings and POIs show a clear sign that nobody is there.

Step 08 gives such a place no unit at all, so it gets no part of any zone target. The signs and
the decisions behind them are documented with the VACANCY_* settings in config.py (STEP 08). The
OSM signs of non-use are read as the tags say them - a building under works or gone, a lifecycle
prefix without an active tag, opening_hours closed, a past end_date, a permanent note, shop=no
(osm_signs; VACANCY_OSM_SIGNS).
"""

import datetime
import json
import re

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio

# the step-01 POI columns that are no OSM tags (tag_dict reads every other column as a tag)
POI_NOT_TAGS = ('poi_id', 'osm_type', 'osm_id', 'poi_use', 'poi_use_tag', 'poi_role', 'geom_kind', 'area_m2', 'n_osm_bld',
                'poi_parent_id', 'split_area_m2', 'rescued_by', 'tags')
BUILDING_NOT_TAGS = ('bld_id', 'osm_type', 'osm_id', 'tags', 'geometry')
# the SQL prefilter of the OSM building polygons for the signs of osm_signs (each sign needs one of these words)
_SIGN_WORDS = ('was:', 'demolished:', 'razed:', 'removed:', 'destroyed:', 'end_date', 'opening_hours', 'geschlossen', 'leer',
               'closed')


def text_vacant(texts, text_pattern, partial_pattern):
    """True where a model type describes the place itself as vacant (and not merely partly)."""
    vt, vp = re.compile(text_pattern, re.I), re.compile(partial_pattern, re.I)
    return texts.map(lambda s: isinstance(s, str) and bool(vt.search(s)) and not vp.search(s)).astype(bool)


def tag_dict(row, cols):
    """The OSM tags of a step-01 row: its tag columns (addr_x -> addr:x, building_x -> building:x) and the JSON of the
    remaining tags."""
    d = {}
    for c in cols:
        v = row.get(c)
        if v is None or (isinstance(v, float) and v != v) or str(v) == '':
            continue
        d[('addr:' + c[5:]) if c.startswith('addr_') else ('building:' + c[9:]) if c.startswith('building_') else c] = str(v)
    t = row.get('tags')
    if isinstance(t, str) and t:
        try:
            d.update({k: str(v) for k, v in json.loads(t).items()})
        except ValueError:
            pass
    return d


def _date(v):
    """An OSM date ('2026-03-31', '2025-12', '2019', '~2019', 'before 2010') as a date (a missing month: December; a missing
    day, or one after the 28th: the 28th); else None."""
    m = re.match(r'^\s*(?:~|before\s+|c\.\s*)?(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?', str(v))
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2) or 12), min(int(m.group(3) or 28), 28))
    except ValueError:
        return None


def osm_signs(t, rules, polygon=False):
    """The OSM signs that the object with the tags t (a dict) is not in use, as 'key=value' texts ([] = none). rules is
    config.VACANCY_OSM_SIGNS; a primary tag (rules['active_keys']) is active unless its value is one of rules['inactive_values'].
      lifecycle  <prefix>:<use key>=* (disused:shop=..., was:amenity=..., abandoned:office=...) where the object has no active
                 primary tag - with one it records a former use of a place active today; <gone prefix>:building=*
                 (demolished:building=...) on the same terms; disused / abandoned:building only as =yes (a value naming a former
                 building type - train_station - is no sign)
      works      building=construction / demolished / razed / removed, whatever else the object carries - building=construction
                 only where it says what is built (construction=*) or was checked (check_date), with construction_needs_detail
      closed     opening_hours closed / off / no / geschlossen / temporarily closed (the whole value, also after Mo-Su, PH or
                 24/7: closed now), not on a workshop (craft: 'off' means no public hours)
      ended      an end_date before rules['end_date_before'] where the object has no active primary tag
      note       a name, note, description or fixme saying it for good ('dauerhaft geschlossen', 'Leerstand', 'steht leer' ...;
                 not on building outlines where note_on_polygons is False)
      shop_no    shop=no on an object without an active primary tag, not at a fuel station (there it means no shop)"""
    R = rules
    out = []
    lk = {k.lower(): v for k, v in t.items()}
    inactive = set(R['inactive_values'])
    active = [k for k in R['active_keys'] if lk.get(k) and str(lk[k]).strip().lower() not in inactive]
    for k, v in t.items():
        kl, vl = k.lower(), str(v).strip().lower()
        if ':' in kl:
            pre, base = kl.split(':', 1)
            if not active and ((pre in R['lifecycle_prefixes'] and base in R['lifecycle_keys'])
                               or (pre in R['gone_prefixes'] and base == 'building')
                               or (pre in R['building_yes_prefixes'] and base == 'building' and vl == 'yes')):
                out.append(f'{k}={v}')
    b = lk.get('building', '').strip().lower()
    if b in R['works_values'] and not (b == 'construction' and R['construction_needs_detail']
                                       and not (lk.get('construction') or lk.get('check_date'))):
        out.append(f'building={b}' + (f", construction={lk['construction']}" if lk.get('construction') else ''))
    oh = lk.get('opening_hours')
    if oh and re.match(R['opening_hours_pattern'], oh, re.I) and not (active and set(active) <= set(R['opening_hours_exempt_keys'])):
        out.append(f'opening_hours={oh}')
    ed = lk.get('end_date')
    if ed and not active:
        d = _date(ed)
        if d is not None and d < datetime.date.fromisoformat(R['end_date_before']):
            out.append(f'end_date={ed}')
    for k in (dict.fromkeys(x.lower() for x in R['note_keys']) if R.get('note_on_polygons', True) or not polygon else ()):
        v = lk.get(k)
        if v and re.search(R['note_pattern'], v, re.I) and not re.search(R['note_exclude_pattern'], v, re.I):
            out.append(f'{k}={v[:60]}')
    if R['shop_no'] and lk.get('shop', '').strip().lower() == 'no' and not active and lk.get('amenity', '').lower() != 'fuel':
        out.append('shop=no')
    return out


def poi_sign_texts(poi_file, rules):
    """Per poi_id of step 01 the signs of osm_signs, '; '-joined ('' = none); none for the OSM objects of rules['stale_ids']
    (a dated source says the place is in use)."""
    x = pyogrio.read_dataframe(poi_file, layer='pois', read_geometry=False)
    cols = [c for c in x.columns if c not in POI_NOT_TAGS]
    s = pd.Series(['; '.join(osm_signs(tag_dict(r, cols), rules)) for r in x.to_dict('records')], index=x['poi_id'].to_numpy())
    return s.where(~s.index.isin(list(rules.get('stale_ids', {}))), '')


def poi_signs(poi_attrs, uses, name_pattern, tag_pattern, texts=None):
    """Per poi_id the OSM sign of vacancy: 'tag', 'name' or ''.

    poi_attrs: the step-01 POIs with poi_id, poi_use, shop, office, name and tags (the JSON of
    the remaining OSM tags); texts: poi_sign_texts - a POI with such a sign reads 'tag' too."""
    a = poi_attrs
    tag = (a['poi_use'].isin(uses) | a['shop'].eq('vacant') | a['office'].eq('vacant')
           | a['tags'].fillna('').str.contains(tag_pattern, regex=True))
    name = a['name'].fillna('').str.contains(re.compile(name_pattern, re.I))
    out = pd.Series(np.select([tag, name], ['tag', 'name'], default=''), index=a['poi_id'].to_numpy())
    if texts is not None:
        out = out.where(out != '', texts.reindex(out.index).fillna('').map(lambda s: 'tag' if s else ''))
    return out


def polygon_signs(osm_buildings_file, bld, building_values, tag_pattern, rules=None):
    """Per building_id: the share of its footprint under OSM building polygons with a vacancy sign ('cover'), the share under
    polygons with a sign of building_values / tag_pattern alone ('cover_old': the basic signs without those of osm_signs,
    disused / abandoned:building only =yes), and the signs (e.g. 'abandoned=yes', 'building=construction,
    construction=civic').

    Reads only the candidate polygons of step 01's OSM buildings (an SQL prefilter), confirms them with the patterns and, with
    rules (VACANCY_OSM_SIGNS), osm_signs, and intersects them with the building footprints; the polygons of rules['stale_ids']
    give no sign."""
    vals = ', '.join(f"'{v}'" for v in sorted(set(building_values) | set(rules['works_values'] if rules else ())))
    words = ('disused', 'abandoned', 'vacant', 'ruins') + (_SIGN_WORDS if rules else ())
    where = ' OR '.join([f'lower(trim(building)) IN ({vals})', "shop = 'vacant'", "office = 'vacant'"]
                        + ([f"name LIKE '%{w}%'" for w in ('leer', 'geschlossen', 'closed')] + ["lower(trim(shop)) = 'no'"]
                           if rules else [])
                        + [f"tags LIKE '%{w}%'" for w in words])
    ob = pyogrio.read_dataframe(osm_buildings_file, where=where)
    if rules:
        ob = ob[~ob['bld_id'].isin(list(rules.get('stale_ids', {})))]
    cols = [c for c in ob.columns if c not in BUILDING_NOT_TAGS]
    pat = re.compile(tag_pattern)
    old, new = [], []
    for r in ob.drop(columns='geometry').to_dict('records'):
        t = r.get('tags') if isinstance(r.get('tags'), str) else ''
        o = [f"building={r['building']}"] if r['building'] in building_values else []
        o += ['='.join(re.findall(r'"([^"]+)"', m.group(0))) for m in pat.finditer(t)]   # "abandoned": "yes" -> abandoned=yes
        o += [f'{k}=vacant' for k in ('shop', 'office') if r.get(k) == 'vacant']
        old.append(', '.join(dict.fromkeys(o)))
        new.append(', '.join(dict.fromkeys(s for s in osm_signs(tag_dict(r, cols), rules, polygon=True) if s not in o)) if rules else '')
    ob['old'], ob['new'] = old, new
    ob = ob[(ob['old'] != '') | (ob['new'] != '')].to_crs(bld.crs)
    empty = pd.DataFrame({'cover': pd.Series(dtype=float), 'cover_old': pd.Series(dtype=float), 'signs': pd.Series(dtype=str)})
    if ob.empty:
        return empty
    hit = gpd.overlay(ob[['bld_id', 'old', 'new', 'geometry']], bld[['building_id', 'geometry']].reset_index(drop=True),
                      how='intersection', keep_geom_type=True)
    if hit.empty:
        return empty
    hit['a'] = hit.area
    hit['a_old'] = hit['a'].where(hit['old'] != '', 0.0)
    hit['signs'] = [', '.join(x for x in (o, n) if x) for o, n in zip(hit['old'], hit['new'])]
    foot = pd.Series(bld.geometry.area.to_numpy(), index=bld['building_id'].to_numpy())
    out = hit.groupby('building_id').agg(a=('a', 'sum'), a_old=('a_old', 'sum'),
                                         signs=('signs', lambda s: ', '.join(dict.fromkeys(', '.join(s).split(', ')))))
    out['cover'] = (out['a'] / out.index.map(foot)).clip(upper=1.0)
    out['cover_old'] = (out['a_old'] / out.index.map(foot)).clip(upper=1.0)
    return out[['cover', 'cover_old', 'signs']]


def flag(bld, pois, own, poi_attrs, polygons, *, uses, name_pattern, poi_tag_pattern, text_pattern, partial_pattern, min_cover,
         texts=None, sites=None):
    """The vacancy of every building and asked POI.

    bld: buildings (building_id, llm_type); pois: the asked POIs (poi_id, building_id, poi_type);
    own: every building's own POIs (building_id, poi_id; site rows already left out);
    poi_attrs: the step-01 POIs (see poi_signs); polygons: the output of polygon_signs;
    texts: poi_sign_texts (the OSM signs of osm_signs); sites: the site pairs of step 06
    (building_id, poi_id, name) - a building that only such a sign leaves empty (all its own
    POIs vacant, at least one by such a sign, or an OSM polygon whose sign is one) keeps its units
    where it lies on the named site of an active occupant (a site POI that is no landuse area, has a
    name and no sign itself: the exception of GONE_BUILDINGS) and is listed for review.

    Returns (building vacancy, building evidence, POI vacancy, review). A vacancy is '' or its
    sources joined by '+': for a building 'osm' (all own POIs vacant), 'polygon', 'model'; for a
    POI 'tag' / 'name', 'model'. review lists the buildings under a vacancy-tagged polygon that
    keep their values because an active POI is inside, and those kept on a named site."""
    old_sign = poi_signs(poi_attrs, uses, name_pattern, poi_tag_pattern)
    new_txt = (texts.reindex(old_sign.index) if texts is not None else pd.Series('', index=old_sign.index)).fillna('')
    sign = old_sign.where(old_sign != '', new_txt.map(lambda s: 'tag' if s else ''))
    p_osm = pois['poi_id'].map(sign).fillna('')
    p_mod = text_vacant(pois['poi_type'], text_pattern, partial_pattern)
    poi_vac = pd.Series([('+'.join(x for x in (o, 'model' if m else '') if x)) for o, m in zip(p_osm, p_mod)], index=pois.index)

    o = own[['building_id', 'poi_id']].copy()
    o['vac'] = o['poi_id'].map(sign).fillna('').ne('') | o['poi_id'].isin(pois.loc[poi_vac != '', 'poi_id'])
    o['new'] = (o['poi_id'].map(old_sign).fillna('').eq('') & o['poi_id'].map(new_txt).fillna('').ne('')
                & ~o['poi_id'].isin(pois.loc[p_mod.to_numpy(), 'poi_id']))       # vacant only by a sign of osm_signs
    n_own = o.groupby('building_id').size()
    n_vac = o.groupby('building_id')['vac'].sum()
    n_new = o.groupby('building_id')['new'].sum()
    b = bld['building_id']
    all_vac = b.map(n_vac).fillna(0).gt(0) & b.map(n_vac).fillna(0).eq(b.map(n_own).fillna(0))
    active = b.map(n_own).fillna(0) - b.map(n_vac).fillna(0)
    cover = b.map(polygons['cover']).fillna(0.0)
    cover_old = b.map(polygons['cover_old']).fillna(0.0) if 'cover_old' in polygons.columns else cover
    under = cover >= min_cover
    on_site, site_name = pd.Series(False, index=b.index), pd.Series('', index=b.index)
    if sites is not None:                       # the named site of an active occupant: no landuse area, a name, no sign
        st = sites[['building_id', 'poi_id', 'name']].copy()
        st['tag'] = st['poi_id'].map(poi_attrs.set_index('poi_id')['poi_use_tag'])
        st = st[st['tag'].ne('landuse') & st['name'].fillna('').astype(str).str.strip().ne('') & st['poi_id'].map(sign).fillna('').eq('')]
        on_site = b.isin(set(st['building_id']))
        site_name = b.map(st.groupby('building_id')['name'].agg(lambda s: ' / '.join(sorted(set(s.astype(str)))))).fillna('')
    osm_new = all_vac & b.map(n_new).fillna(0).gt(0)
    poly_old = (cover_old >= min_cover) & active.eq(0)
    poly_new = under & ~poly_old & active.eq(0)
    keep_site = (osm_new | poly_new) & on_site & ~poly_old & ~(all_vac & ~osm_new)   # never a place the run-16 signs leave empty
    all_vac = all_vac & ~(osm_new & keep_site)
    poly = poly_old | (poly_new & ~keep_site)
    model = text_vacant(bld['llm_type'], text_pattern, partial_pattern)
    srcs = list(zip(all_vac, poly, model))
    vac = pd.Series(['+'.join(n for n, f in zip(('osm', 'polygon', 'model'), fl) if f) for fl in srcs], index=bld.index)

    names = o[o['vac']].assign(s=lambda d: d['poi_id'].map(new_txt).fillna('')).merge(poi_attrs[['poi_id', 'poi_use']], on='poi_id',
                                                                                     how='left')
    names = names.assign(t=[f'{u}: {s}' if s else str(u) for u, s in zip(names['poi_use'], names['s'])]) \
        .groupby('building_id')['t'].agg(lambda s: ', '.join(sorted(set(s))))
    ev = []
    for bid, a_, p_, m_, c_, t_ in zip(b, all_vac, poly, model, cover, bld['llm_type']):
        parts = []
        if a_:
            parts.append(f'all {int(n_own.get(bid, 0))} own POI(s) vacant ({names.get(bid, "")})')
        if p_:
            parts.append(f'OSM polygon {polygons.at[bid, "signs"]} over {100 * c_:.0f} %')
        if m_:
            parts.append(f'type: {t_}')
        ev.append('; '.join(parts))
    evidence = pd.Series(ev, index=bld.index)
    rv = (under & active.gt(0)) | keep_site
    review = pd.DataFrame({'building_id': b[rv], 'cover': cover[rv], 'active_pois': active[rv].astype(int)})
    review['signs'] = review['building_id'].map(polygons['signs']).fillna('') + [
        (f' | kept: on the site of {site_name[i]}' if keep_site[i] else '') + (f' | own POIs: {names.get(x, "")}' if osm_new[i] else '')
        for i, x in zip(review.index, review['building_id'])]
    return vac, evidence, poi_vac, review
