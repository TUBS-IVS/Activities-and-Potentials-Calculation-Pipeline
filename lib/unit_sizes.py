"""Step 08: the sizes of single tenants by format (round 16, 2026-10-09, on the user's behalf; a second look at item 9 of the audit
of run 7).
Notebook 08 section 4.5 sizes the POI units (4.4d: a point counts at least its group's median polygon, a mall's tenant points are
weighted by their group's median, a pharmacy at most the pharmacy cap, a big-box chain filed small up to the big-box cap). These
helpers refine those sizes where a format says more than a group (config UNIT_SIZE_FORMATS, each key absent = as in run 15):

  pharmacy_large  {'pattern', 'cap_m2'}       a named large pharmacy format (easyApotheke) keeps up to cap_m2 instead of the cap
  chain_caps      [(pattern, cap_m2), ...]     a chain filed as a small shop: at most its format's size (drugstores, pet stores,
                                               beverage stores, textile discounters); a chain word in no listed format keeps the
                                               big-box cap
  counters        {'uses', 'name_pattern', 'groups', 'kiosk_uses', 'mall'}
                                               counters and kiosks (kiosk, newsagent, tobacco, lottery, ticket, post-office uses,
                                               a 'Theke' name) count at least the median of the mapped kiosk polygons, not their
                                               group's median; in a mall ('mall': True) they weigh that median too
  mall_chains     [(pattern, m2, uses or None), ...]
                                               a mall tenant point whose name or brand is a listed chain weighs its published
                                               typical size, not its group's median, and counts at least that size (notebook
                                               08 uses the weight only in the malls of MALL_RETAIL_FLOOR, the minimum in every
                                               mall)
"""
import re

import numpy as np

_BRAND = re.compile(r'"brand"\s*:\s*"([^"]*)"')


def brand(tags):
    """the OSM brand of a POI from its tags text"""
    m = _BRAND.search(tags) if isinstance(tags, str) else None
    return m.group(1) if m else ''


def _texts(q):
    nm = q['name'].fillna('').astype(str).str.strip().tolist()
    br = [brand(t) for t in q['tags']] if 'tags' in q.columns else [''] * len(q)
    return nm, br


# --- a large pharmacy format --------------------------------------------------------------------------------------------------
def pharmacy_caps(q, cap, large):
    """the pharmacy cap of each POI row: cap, or large['cap_m2'] where the POI's name or brand names the large format"""
    out = np.full(len(q), float(cap))
    if not large:
        return out
    rx = re.compile(large['pattern'], re.IGNORECASE)
    nm, br = _texts(q)
    out[np.array([bool(rx.search(a) or rx.search(b_)) for a, b_ in zip(nm, br)], dtype=bool)] = float(large['cap_m2'])
    return out


def pharmacy_building_caps(sole, ph_buildings, cap, large):
    """building_id -> the pharmacy cap of the buildings whose only POI is a pharmacy (sole: one row per building)"""
    s = sole[sole['building_id'].isin(ph_buildings)]
    if 'tags' not in s.columns:
        s = s.assign(tags='')
    return dict(zip(s['building_id'], pharmacy_caps(s, cap, large)))


# --- chain caps by format ---------------------------------------------------------------------------------------------------------
def chain_cap(text, box_pattern, formats, default_cap):
    """the cap of a building filed as a small shop whose own data name a box chain: the largest cap of the formats its chain words
    belong to; a chain word in no listed format counts the default (the big-box cap)"""
    if not formats:
        return float(default_cap)
    words = [w.lower() for w in re.findall(box_pattern, text or '', flags=re.IGNORECASE)]
    if not words:
        return float(default_cap)
    caps = []
    for w in words:
        c = next((float(m2) for pat, m2 in formats if re.search(pat, w, flags=re.IGNORECASE)), None)
        caps.append(float(default_cap) if c is None else c)
    return max(caps)


# --- counters and kiosks ---------------------------------------------------------------------------------------------------------
def counter_mask(q, rule):
    """the POI rows that are counters or kiosks: a counter use, or a counter word in the name, in the rule's groups"""
    if not rule:
        return np.zeros(len(q), dtype=bool)
    g = q['group'].isin(rule['groups']).to_numpy()
    u = q['poi_use'].fillna('').astype(str).isin(rule['uses']).to_numpy()
    n = q['name'].fillna('').astype(str).str.contains(rule['name_pattern'], case=False, regex=True).to_numpy()
    return g & (u | n)


def kiosk_median(own06, rule):
    """the median of the mapped kiosk polygons (POI polygons of the kiosk uses); None without the rule"""
    if not rule:
        return None
    a = own06.loc[own06['geom_kind'].eq('area') & own06['poi_use'].isin(rule['kiosk_uses']) & own06['poi_area_m2'].gt(0), 'poi_area_m2']
    return float(a.median())


# --- mall tenants of a listed chain ----------------------------------------------------------------------------------------------
def chain_size(q, chains):
    """the published typical size of each POI row whose name or brand names a listed chain (NaN otherwise)"""
    out = np.full(len(q), np.nan)
    if not chains:
        return out
    nm, br = _texts(q)
    use = q['poi_use'].fillna('').astype(str).tolist()
    for i, (a, b_, u) in enumerate(zip(nm, br, use)):
        for pat, m2, uses in chains:
            if uses and u not in uses:
                continue
            if re.search(pat, a, flags=re.IGNORECASE) or re.search(pat, b_, flags=re.IGNORECASE):
                out[i] = float(m2)
                break
    return out


def point_min(q, base, counters, kiosk_m2, chains=None):
    """the point minimum of each POI row: base (its group's median polygon); a counter or kiosk the kiosk median; in a mall
    (chains given) a listed chain at least its published size"""
    out = np.asarray(base, dtype=float).copy()
    if chains:
        c = chain_size(q, chains)
        out = np.where(np.isnan(c), out, np.maximum(out, c))
    if counters and kiosk_m2:
        out[counter_mask(q, counters)] = float(kiosk_m2)
    return out


def mall_weights(q, base, chains, counters, kiosk_m2):
    """the weights of a mall's tenant points: a listed chain its published size, a counter or kiosk the kiosk median (with the
    counter rule's 'mall' flag), every other point its group's median polygon (base)"""
    w = np.asarray(base, dtype=float).copy()
    if counters and counters.get('mall') and kiosk_m2:
        w[counter_mask(q, counters)] = float(kiosk_m2)
    c = chain_size(q, chains)
    return np.where(np.isnan(c), w, c)


def check_config(rules):
    """the keys of UNIT_SIZE_FORMATS compile and are positive"""
    pl = rules.get('pharmacy_large')
    if pl:
        re.compile(pl['pattern'])
        assert pl['cap_m2'] > 0
    for pat, m2 in rules.get('chain_caps') or ():
        re.compile(pat)
        assert m2 > 0, pat
    c = rules.get('counters')
    if c:
        re.compile(c['name_pattern'])
        assert set(c) >= {'uses', 'name_pattern', 'groups', 'kiosk_uses', 'mall'}
    for pat, m2, _uses in rules.get('mall_chains') or ():
        re.compile(pat)
        assert m2 > 0, pat
