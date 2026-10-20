"""Step 08: the labels of steps 06 and 07 reconciled by OSM use.

Step 06 labelled each building whole - a building with one POI was not asked again - and step 07 each POI of a shared building
on its own. Both used the same label definitions, yet they read the same kinds of place differently (fast food: retail_daily on
44 % of the one-POI buildings, on 6 % of the asked POIs). These rules set what such a place carries from its own OSM use and
data, and never re-run the model:
  * eating_places  an eating or drinking place carries leisure, not retail_daily / retail_non_daily      - before the units
  * pharmacies     a pharmacy carries retail_daily                                                        - before the units
  * fuel           a fuel station carries retail_daily, unless its data show it has no shop: then
                   errands instead                                                   - before the units and after the canopies
  * daily_shops    a beverage market, kiosk, newsagent, tobacco or lottery shop carries retail_daily
                   instead of retail_non_daily                                                            - before the units
  * venues         a leisure venue labelled sports (pool, ice rink, bowling, climbing ...) carries
                   leisure as well                                                                        - before the units
  * services       a service (the POI groups counter and personal_service) carries no retail_non_daily  - on the units
  * rest_sources   a rest label goes where an active asked POI of the building is its evident source
                   and step 07 labelled that POI otherwise (the POI's answer wins)                        - on the units
A building unit follows the use of its only POI; an asked POI its own. A dropped label's share goes to the unit's other labels
(the unit's label counts are recounted). The patterns and lists are config.LABEL_RULES.
"""
import json
import re

import numpy as np
import pandas as pd

I = re.IGNORECASE


def _s(x):
    return x if isinstance(x, str) else ''


def tags(s):
    """the OSM tags of a POI as a dict (the tags column holds JSON)"""
    try:
        t = json.loads(s) if isinstance(s, str) and s else {}
    except ValueError:
        return {}
    return t if isinstance(t, dict) else {}


def relabel(labels, catalogue, add=(), drop=()):
    """the labels with `add` added and `drop` dropped, in catalogue order"""
    have = (set(labels) | set(add)) - set(drop)
    return tuple(l for l in catalogue if l in have)


def sole_pois(bld, own06):
    """the POI of each one-POI building (as nb08-07 4.5 reads it), indexed by building_id"""
    one = bld.loc[bld['n_pois'] == 1, 'building_id']
    return own06[own06['building_id'].isin(one)].drop_duplicates('building_id').set_index('building_id')


def _log(rows):
    return pd.DataFrame(rows, columns=['rule', 'kind', 'unit_id', 'building_id', 'use', 'labels_before', 'labels_after', 'why'])


# ======================================================================================================== before the units
def eating_places(bld, pois, sole, cfg, *, unit_b, active_p, staff_pattern, staff_classes, catalogue):
    """An eating or drinking place carries leisure, not retail: a building unit whose only POI has one of the uses, an active
    asked POI of the gastronomy group with one of them. A building filed in another class than place_classes only loses the
    retail labels; shops with seating (shop_pattern) and buildings filed as stores keep theirs; staff canteens and Mensas keep
    theirs (staff catering, section 4.8 of notebook 08). Returns (new building labels, new POI labels, log)."""
    uses, drop, add = set(cfg['uses']), tuple(cfg['drop']), tuple(cfg['add'])
    place, store = set(cfg['place_classes']), set(cfg['store_classes'])
    staff, shop = re.compile(staff_pattern, I), re.compile(cfg['shop_pattern'], I)
    kiosk, kfood = re.compile(cfg['kiosk_pattern'], I), re.compile(cfg['kiosk_food_pattern'], I)
    is_shop = lambda t: bool(shop.search(t)) or (bool(kiosk.search(t)) and not kfood.search(t))   # a kiosk, not a food / snack kiosk
    nb, np_, log = {}, {}, []
    cls = bld.set_index('building_id')['bosserhof_class']
    for bid, L, c, typ in zip(bld['building_id'], bld['labels'], bld['bosserhof_class'], bld['llm_type']):
        if bid not in unit_b or bid not in sole.index or sole.at[bid, 'poi_use'] not in uses or not set(drop) & set(L):
            continue
        use, txt = sole.at[bid, 'poi_use'], f'{_s(typ)} | {_s(sole.at[bid, "name"])}'
        if staff.search(txt):
            log.append(('eating_places', 'building', bid, bid, use, L, L, 'kept: staff canteen or Mensa (staff catering, 4.8)'))
            continue
        if is_shop(txt) or c in store:
            log.append(('eating_places', 'building', bid, bid, use, L, L, 'kept: a shop with seating' if is_shop(txt) else 'kept: a store class'))
            continue
        how = 'swap' if c in place else 'drop'
        new = relabel(L, catalogue, add=add if how == 'swap' else (), drop=drop)
        if new != L:
            nb[bid] = new
            log.append(('eating_places', 'building', bid, bid, use, L, new,
                        'an eating place: leisure, not retail' if how == 'swap' else f'retail dropped only (class {c})'))
    p = pois[pois['poi_id'].isin(active_p) & pois['group'].eq('gastronomy') & pois['poi_use'].isin(uses)]
    for pid, bid, use, L, nm, pt in zip(p['poi_id'], p['building_id'], p['poi_use'], p['labels'], p['name'], p['poi_type']):
        if not set(drop) & set(L):
            continue
        txt = f'{_s(nm)} | {_s(pt)}'
        if staff.search(txt):
            log.append(('eating_places', 'poi', pid, bid, use, L, L, 'kept: staff canteen or Mensa (staff catering, 4.8)'))
            continue
        if is_shop(txt):
            log.append(('eating_places', 'poi', pid, bid, use, L, L, 'kept: a shop with seating'))
            continue
        if cls.get(bid) in staff_classes:
            log.append(('eating_places', 'poi', pid, bid, use, L, L, 'kept: in a works, depot or transport building (4.8)'))
            continue
        new = relabel(L, catalogue, add=add, drop=drop)
        if new != L:
            np_[pid] = new
            log.append(('eating_places', 'poi', pid, bid, use, L, new, 'an eating place: leisure, not retail'))
    return nb, np_, _log(log)


def _fuel_no_shop(t, texts, cfg):
    """a station whose data show no shop: an automat, a gas-only pump, a works / dealer / farm / airfield pump"""
    fy = {k for k, v in t.items() if k.startswith('fuel:') and v == 'yes'}
    pet = [k for k in t if k.startswith('fuel:octane') or k in ('fuel:e10', 'fuel:e5', 'fuel:e85')]
    diesel_only = bool(cfg.get('diesel_only') and (t.get('fuel:diesel') == 'yes' or t.get('fuel:HGV_diesel') == 'yes') and pet
                       and not any(t.get(k) == 'yes' for k in pet))       # a truck stop: diesel only
    return (any(t.get(k) in (v if isinstance(v, (tuple, list)) else (v,)) for k, v in cfg['no_shop_tags'].items())
            or diesel_only or 'fuel' in str(t.get('vending_machine', ''))
            or (bool(fy) and fy <= set(cfg['gas_only_fuels']) and not t.get('brand'))
            or bool(re.search(cfg['no_shop_pattern'], ' | '.join(x for x in [_s(t.get('brand'))] + list(texts) if x), I)))


def pharmacies_fuel(bld, pois, sole, cfg_ph, cfg_fu, *, unit_b, active_p, paired_canopies, head_split, wash_pattern, catalogue,
                    head):
    """A pharmacy carries retail_daily; a fuel station too, unless its data show no shop: then it carries errands, here for a
    paired canopy (which passes its labels to its station shop in 4.7) and after the canopy pass for the station units
    (fuel_no_shop). A building typed as a car wash is left alone. Returns (new building labels, new POI labels, the no-shop
    building and POI sets, log)."""
    ph, fu = set(cfg_ph['uses']), set(cfg_fu['uses'])
    rd, alt = tuple(cfg_ph['add']), tuple(cfg_fu['no_shop_add'])
    b = bld.set_index('building_id')
    bt, bn = b['llm_type'].to_dict(), b['name'].to_dict()
    su = sole['poi_use'].reindex(list(unit_b)).dropna()
    ph_b, fu_b = set(su.index[su.isin(ph)]), set(su.index[su.isin(fu)])
    pa = pois[pois['poi_id'].isin(active_p)]
    ph_p, fu_p = set(pa.loc[pa['poi_use'].isin(ph), 'poi_id']), set(pa.loc[pa['poi_use'].isin(fu), 'poi_id'])
    wash_b = set(bld.loc[head(bld['llm_type'], head_split).str.contains(wash_pattern, case=False, regex=True), 'building_id'])
    shop_t = re.compile(cfg_fu['shop_type_pattern'], I)
    site = re.compile(cfg_fu['site_pattern'], I)
    ns_b = {x for x in fu_b if _fuel_no_shop(tags(sole.at[x, 'tags']), (_s(sole.at[x, 'name']), _s(bt.get(x)), _s(bn.get(x))), cfg_fu)
            and not shop_t.search(_s(bt.get(x)))}
    pq = pa.set_index('poi_id')
    ns_p = set()
    for x in fu_p:
        bty = _s(bt.get(pq.at[x, 'building_id']))
        if (_fuel_no_shop(tags(pq.at[x, 'tags']), (_s(pq.at[x, 'name']), _s(pq.at[x, 'poi_type']), bty if site.search(bty) else ''), cfg_fu)
                and not shop_t.search(_s(pq.at[x, 'poi_type']))):
            ns_p.add(x)
    bset, pset, cdrop = ph_b | (fu_b - ns_b - wash_b), ph_p | (fu_p - ns_p), ns_b & set(paired_canopies)
    nb, np_, log = {}, {}, []
    for bid, L in zip(bld['building_id'], bld['labels']):
        if bid in bset and not set(rd) <= set(L):
            nb[bid] = relabel(L, catalogue, add=rd)
            log.append(('pharmacies' if bid in ph_b else 'fuel', 'building', bid, bid, su.get(bid), L, nb[bid],
                        'a pharmacy: retail_daily' if bid in ph_b else 'a fuel station with a shop: retail_daily'))
        elif bid in cdrop and set(rd) & set(L):
            nb[bid] = relabel(L, catalogue, add=alt, drop=rd)
            log.append(('fuel', 'building', bid, bid, su.get(bid), L, nb[bid], 'a canopy of a station without a shop: errands'))
    for pid, bid, use, L in zip(pa['poi_id'], pa['building_id'], pa['poi_use'], pa['labels']):
        if pid in pset and not set(rd) <= set(L):
            np_[pid] = relabel(L, catalogue, add=rd)
            log.append(('pharmacies' if use in ph else 'fuel', 'poi', pid, bid, use, L, np_[pid],
                        'a pharmacy: retail_daily' if use in ph else 'a fuel station with a shop: retail_daily'))
    for x in sorted(fu_b & wash_b):
        log.append(('fuel', 'building', x, x, 'fuel', b.at[x, 'labels'], b.at[x, 'labels'], 'kept: typed as a car wash'))
    return nb, np_, ns_b, ns_p, _log(log)


def daily_shops(bld, pois, sole, cfg, *, unit_b, active_p, catalogue):
    """A beverage market, kiosk, newsagent, tobacco or lottery shop (or a liquor shop named as a beverage market) carries
    retail_daily instead of retail_non_daily; producers' own shops, souvenir / tourist / pool kiosks, e-cigarette shops and
    shops in a factory outlet centre keep their labels. Returns (new building labels, new POI labels, log)."""
    uses, named = set(cfg['uses']), set(cfg['named_uses'])
    nm_rx, ex_rx = re.compile(cfg['name_pattern'], I), re.compile(cfg['exclude_pattern'], I)
    exc, add, drop = set(cfg['exclude_classes']), tuple(cfg['add']), tuple(cfg['drop'])
    cls = bld.set_index('building_id')['bosserhof_class']
    hit = lambda u, n: u in uses or (u in named and bool(nm_rx.search(_s(n))))
    nb, np_, log = {}, {}, []
    for bid, L, c, n, t in zip(bld['building_id'], bld['labels'], bld['bosserhof_class'], bld['name'], bld['llm_type']):
        if bid not in unit_b or bid not in sole.index or not hit(sole.at[bid, 'poi_use'], sole.at[bid, 'name']):
            continue
        use = sole.at[bid, 'poi_use']
        if ex_rx.search(' '.join(x for x in (_s(sole.at[bid, 'name']), _s(n), _s(t)) if x)) or c in exc:
            if set(drop) & set(L):
                log.append(('daily_shops', 'building', bid, bid, use, L, L, 'kept: a producer, souvenir / pool kiosk, e-cigarette or outlet shop'))
            continue
        if set(drop) & set(L):
            nb[bid] = relabel(L, catalogue, add=add, drop=drop)
            log.append(('daily_shops', 'building', bid, bid, use, L, nb[bid], 'a shop of daily goods: retail_daily, not retail_non_daily'))
    pa = pois[pois['poi_id'].isin(active_p)]
    for pid, bid, use, L, n, t in zip(pa['poi_id'], pa['building_id'], pa['poi_use'], pa['labels'], pa['name'], pa['poi_type']):
        if not hit(use, n):
            continue
        if ex_rx.search(' '.join(x for x in (_s(n), _s(t)) if x)) or cls.get(bid) in exc:
            if set(drop) & set(L):
                log.append(('daily_shops', 'poi', pid, bid, use, L, L, 'kept: a producer, souvenir / pool kiosk, e-cigarette or outlet shop'))
            continue
        if set(drop) & set(L):
            np_[pid] = relabel(L, catalogue, add=add, drop=drop)
            log.append(('daily_shops', 'poi', pid, bid, use, L, np_[pid], 'a shop of daily goods: retail_daily, not retail_non_daily'))
    return nb, np_, _log(log)


def venues(bld, pois, sole, poi_attrs, cfg, *, unit_b, shared_b, active_p, cover, evidence_b, head_split, head, catalogue):
    """A leisure venue labelled sports but not leisure (nor school, university or childcare) gets leisure where its own data
    name it: an asked POI by its OSM values, name or type head (its building's name and type head can only exclude it); a
    building unit by its only POI's OSM values and name, its own names, type head or ALKIS function - not a building without
    evidence (no POI, no name, no site other than a landuse area: its type is the model's reading of the cadastre, which still
    lists a pool demolished in 2018); a shared building (for its rest unit) by its own data, where none of its asked POIs
    (counted as for the rest units) carries sports or leisure. Never a school, therapy, hotel, club, fitness or private pool, nor
    a private or closed POI. Returns (new building labels, new POI labels, log)."""
    rx = {k: (set(v['uses']), re.compile(v['names'], I), re.compile(v['types'], I)) for k, v in cfg['classes'].items()}
    ex = re.compile(cfg['exclude_pattern'], I)
    exc = {k: re.compile(v, I) for k, v in cfg['class_exclude_patterns'].items()}
    closed = re.compile(cfg['closed_tag_pattern'])
    alk = {k: set(v) for k, v in cfg['alkis_functions'].items()}
    no = set(cfg['never_with'])
    add = tuple(cfg['add'])
    sp = re.compile(r'"sport"\s*:\s*"([^"]*)"')
    pa = poi_attrs.set_index('poi_id')

    def osm(pid):                                # the OSM values of one POI: use, leisure, amenity, the first sport value
        if not isinstance(pid, str) or pid not in pa.index:
            return set()
        r = pa.loc[pid]
        m = sp.search(_s(r['tags']))
        s1 = m.group(1).split(';')[0].strip().lower() if m else ''
        return {_s(r['poi_use']).lower(), _s(r['leisure']).lower(), _s(r['amenity']).lower(), s1} - {''}

    def is_closed(pid):
        m = closed.search(_s(pa['tags'].get(pid))) if isinstance(pid, str) and pid in pa.index else None
        return m.group(0) if m else ''

    def match(o, names, hd, a='', ctx='', strict=True):
        txt = ' | '.join(x for x in list(names) + [hd, ctx] if x)
        m = ex.search(txt)
        if m and strict:
            k0, e0 = match(o, names, hd, a, ctx, strict=False)
            return '', (f'excluded ({k0}, {e0}) by: {m.group(0)}' if k0 else '')
        for k, (us, rn, rt) in rx.items():
            if strict and k in exc and exc[k].search(txt):
                continue
            if o & us:
                return k, 'OSM ' + ','.join(sorted(o & us))
            for n in names:
                if n and rn.search(n):
                    return k, 'name ' + n
            if hd and rt.search(hd):
                return k, 'type ' + hd
            if a and a in alk.get(k, set()):
                return k, 'ALKIS ' + a
        return '', ''

    want = lambda t: 'sports' in t and not set(add) & set(t) and not no & set(t)
    head_b = dict(zip(bld['building_id'], head(bld['llm_type'], head_split).str.strip()))
    name_b = dict(zip(bld['building_id'], bld['name'].fillna('').astype(str) + ' | ' + bld['osm_twin_name'].fillna('').astype(str)))
    nb, np_, log = {}, {}, []
    p = pois[pois['poi_id'].isin(active_p) & pois['labels'].map(want)]
    hp = head(p['poi_type'], head_split).str.strip()
    for pid, bid, L, n, hd in zip(p['poi_id'], p['building_id'], p['labels'], p['name'], hp):
        k, e = match(osm(pid), [_s(n)], _s(hd), ctx=name_b.get(bid, '') + ' | ' + _s(head_b.get(bid)))
        x = is_closed(pid)
        if k and x:
            k, e = '', f'excluded ({k}, {e}) by OSM tag: {x}'
        if k:
            np_[pid] = relabel(L, catalogue, add=add)
            log.append(('venues', 'poi', pid, bid, k, L, np_[pid], e))
        elif e:
            log.append(('venues', 'poi', pid, bid, '', L, L, e))
    for bid, L, n, tn, f in zip(bld['building_id'], bld['labels'], bld['name'], bld['osm_twin_name'], bld['function']):
        sh = bid in shared_b
        if not (sh or bid in unit_b) or not want(L):
            continue
        has = (not sh) and bid in sole.index
        names = [_s(n), _s(tn)] + ([_s(sole.at[bid, 'name'])] if has else [])
        k, e = match(osm(sole.at[bid, 'poi_id']) if has else set(), names, _s(head_b.get(bid)), _s(f))
        x = is_closed(sole.at[bid, 'poi_id']) if has else ''
        c = ({'sports'} | set(add)) & cover.get(bid, set()) if sh else set()
        if k and x:
            k, e = '', f'excluded ({k}, {e}) by the OSM tag of its only POI: {x}'
        if k and not sh and bid not in evidence_b:
            k, e = '', f'excluded ({k}, {e}): a building without a POI, a name or a site'
        if k and c:
            k, e = '', f'skipped ({k}, {e}): its asked POIs carry ' + '+'.join(sorted(c))
        if k:
            nb[bid] = relabel(L, catalogue, add=add)
            log.append(('venues', 'rest' if sh else 'building', bid, bid, k, L, nb[bid], e))
        elif e:
            log.append(('venues', 'rest' if sh else 'building', bid, bid, '', L, L, e))
    return nb, np_, _log(log)


def no_reopen(bld, cover0, cover1, shared_b, catalogue):
    """A building label that its asked POIs carried before the rules and no longer carry after them is not brought back as a
    rest unit: it leaves the building's labels too (the rule took it off its source). Returns (new building labels, log)."""
    nb, log = {}, []
    for bid, L in zip(bld['building_id'], bld['labels']):
        if bid in shared_b:
            gone = {l for l in L if l != 'work' and l in cover0.get(bid, set()) and l not in cover1.get(bid, set())}
            if gone:
                nb[bid] = relabel(L, catalogue, drop=gone)
                log.append(('no_reopen', 'rest', bid, bid, None, L, nb[bid], 'its asked POIs no longer carry ' + '+'.join(sorted(gone))))
    return nb, _log(log)


# ======================================================================================================== on the units
def services(uo, pois, sole, n_pois, cfg, *, active_p):
    """A service carries no retail_non_daily: a POI unit whose own POI, a building unit whose only POI, is in the groups
    (phone shops, post counters and the listed shops that also sell goods aside); and the rest unit of a building whose
    active asked POIs are all such services. Returns the mask of the units that lose the label."""
    groups, keep_u, keep_i = set(cfg['groups']), set(cfg['keep_uses']), set(cfg['keep_poi_ids'])
    lab = cfg['drop'][0]
    svc = lambda g, u, p: g in groups and u not in keep_u and p not in keep_i
    pq = pois.set_index('poi_id')
    psvc = pd.Series([svc(g, u, p) for p, g, u in zip(pq.index, pq['group'], pq['poi_use'])], index=pq.index)
    ssvc = pd.Series([svc(g, u, p) for p, g, u in zip(sole['poi_id'], sole['group'], sole['poi_use'])], index=sole.index)
    act = pois[pois['poi_id'].isin(active_p)]
    allsvc = act['poi_id'].map(psvc).groupby(act['building_id']).all()
    has = uo['labels'].map(lambda t: lab in t) & uo['no_unit_reason'].eq('')
    return has & ((uo['kind'].eq('poi') & uo['unit_id'].map(psvc).fillna(False).astype(bool))
                  | (uo['kind'].eq('building') & uo['building_id'].map(n_pois).eq(1)
                     & uo['building_id'].map(ssvc).fillna(False).astype(bool))
                  | (uo['kind'].eq('rest') & uo['building_id'].map(allsvc).fillna(False).astype(bool)))


def rest_sources(uo, bld, sole, pois, pairs06, cfg, *, active_p, non_occupant_p):
    """The POI's answer wins: a Retail_Daily, Retail_Non-Daily or Leisure rest label goes when an active asked POI of the same
    building is its evident source - step 06 gives that label to at least min_rate of the one-POI buildings of that POI's use
    (of its group where the use has fewer than min_n such buildings) - and step 07 labelled that POI without it. It stays when a
    dropped non-occupant POI carries it (kind B) or when the building's own data name its kind (C: a site, an OSM outline tag, an
    ALKIS function or a name); a label with no source stays too (D, keep all). Returns (the (unit_id, label) drops, the table
    of all such rest labels, the source rates by use and by group)."""
    scope, rate, min_n = tuple(cfg['labels']), float(cfg['min_rate']), int(cfg['min_n'])
    s = sole[['poi_use', 'group']].copy()
    ml = bld.set_index('building_id')['mid_labels']
    s['lab'] = [set(str(x).split(';')) for x in s.index.map(ml)]

    def tab(key):
        g = s.groupby(key)
        t = pd.DataFrame({'n': g.size()})
        for l in scope:
            t[l] = g['lab'].apply(lambda x: float(np.mean([l in q for q in x])))
        return t
    tu, tg = tab('poi_use'), tab('group')

    def r(use, group, l):
        if isinstance(use, str) and use in tu.index and tu.at[use, 'n'] >= min_n:
            return float(tu.at[use, l])
        if isinstance(group, str) and group in tg.index and tg.at[group, 'n'] >= min_n:
            return float(tg.at[group, l])
        return 0.0
    own = {l: (set(v['sites']), set(v['tags']), set(v['codes']), re.compile(v['names'], I)) for l, v in cfg['own_evidence'].items()}
    sites = {k: list(zip(d['poi_use'].fillna(''), d['name'].fillna(''))) for k, d in pairs06[pairs06['how'].eq('site')].groupby('building_id')}
    b = bld.set_index('building_id')

    def own_ev(bid, l):
        si, tg_, co, nm = own[l]
        x, ev = b.loc[bid], []
        if str(x['function']) in co:
            ev.append(f'ALKIS {x["function"]}')
        if str(x['osm_twin_tag']) in tg_:
            ev.append(f'OSM outline {x["osm_twin_tag"]}')
        for u_, n_ in sites.get(bid, []):
            if u_ in si:
                ev.append(f'site {n_ or "-"} ({u_})')
        for t_ in [x['name'], x['osm_twin_name']] + [n_ for _, n_ in sites.get(bid, [])]:
            if isinstance(t_, str) and t_ and nm.search(t_):
                ev.append(f'name "{t_}"')
        return '; '.join(dict.fromkeys(ev))
    act = pois[pois['poi_id'].isin(active_p)]
    actg = {k: d for k, d in act.groupby('building_id')}
    nonocc = pois[pois['poi_id'].isin(non_occupant_p)].groupby('building_id')['labels'].agg(lambda x: set().union(*x)).to_dict()
    rows = []
    for uid, bid, L, O in uo.loc[uo['kind'].eq('rest') & uo['no_unit_reason'].eq(''), ['unit_id', 'building_id', 'labels', 'O']].itertuples(index=False):
        for l in L:
            if l not in scope:
                continue
            src = []
            if l in nonocc.get(bid, set()):
                k, ev = 'B', 'a non-occupant POI carries it'
            else:
                ev = own_ev(bid, l)
                if ev:
                    k = 'C'
                else:
                    q = actg.get(bid, act.iloc[0:0])
                    src = [(p.poi_id, p.poi_use, p.group, _s(p.name), r(p.poi_use, p.group, l))
                           for p in q.itertuples(index=False) if r(p.poi_use, p.group, l) >= rate]
                    k = 'A' if src else 'D'
            rows.append((uid, bid, l, k, ev, src, float(O)))
    t = pd.DataFrame(rows, columns=['unit_id', 'building_id', 'label', 'kind', 'evidence', 'sources', 'O'])
    drops = set(zip(t.loc[t['kind'].eq('A'), 'unit_id'], t.loc[t['kind'].eq('A'), 'label']))
    return drops, t, tu, tg


def fuel_no_shop(uo, ns_b, ns_p, rd='retail_daily'):
    """After the canopy pass: the units of a fuel station without a shop that carry retail_daily (their own, or passed on by a
    canopy). Returns the mask."""
    return (uo['no_unit_reason'].eq('') & uo['labels'].map(lambda t: rd in t)
            & ((uo['kind'].eq('poi') & uo['unit_id'].isin(ns_p)) | (uo['kind'].eq('building') & uo['building_id'].isin(ns_b))))


def drop_on_units(uo, mask, labels, rule, red_labels, catalogue, add=(), per_unit=None, reason=''):
    """Take `labels` (or per_unit[unit_id]) off the masked units and put `add` on, mark the rule, and recount their label counts:
    a dropped label's share goes to the unit's other labels; the counts move by the change only, so a
    share the education rules keep empty stays empty. A unit left without labels gets no unit (`reason`)."""
    for i in uo.index[mask]:
        old = uo.at[i, 'labels']
        new = relabel(old, catalogue, add=add, drop=per_unit[uo.at[i, 'unit_id']] if per_unit is not None else labels)
        gone, came = set(old) - set(new), set(new) - set(old)
        uo.at[i, 'labels'] = new
        uo.at[i, 'k_red'] = uo.at[i, 'k_red'] - sum(l in red_labels for l in gone) + sum(l in red_labels for l in came)
        uo.at[i, 'k_all'] = uo.at[i, 'k_all'] - sum(l != 'work' for l in gone) + sum(l != 'work' for l in came)
        uo.at[i, 'label_rule'] = '+'.join(x for x in (uo.at[i, 'label_rule'], rule) if x)
        if not new:
            uo.at[i, 'no_unit_reason'] = reason or f'{rule}: no label left'
    return uo


def check_config(cfg, catalogue):
    """LABEL_RULES: the seven rules with their keys; labels from the catalogue; no rule adds a label it drops."""
    need = {'eating_places': {'uses', 'drop', 'add', 'place_classes', 'store_classes', 'shop_pattern', 'kiosk_pattern', 'kiosk_food_pattern',
                              'staff_pattern'},
            'pharmacies': {'uses', 'add'},
            'fuel': {'uses', 'no_shop_add', 'no_shop_tags', 'gas_only_fuels', 'no_shop_pattern', 'site_pattern', 'shop_type_pattern'},
            'daily_shops': {'uses', 'named_uses', 'name_pattern', 'exclude_pattern', 'exclude_classes', 'add', 'drop'},
            'venues': {'classes', 'exclude_pattern', 'class_exclude_patterns', 'closed_tag_pattern', 'alkis_functions', 'never_with', 'add'},
            'services': {'groups', 'keep_uses', 'keep_poi_ids', 'drop'},
            'rest_sources': {'labels', 'min_rate', 'min_n', 'own_evidence'}}
    bad = [k for k in need if k not in cfg or not need[k] <= set(cfg[k])] + [k for k in cfg if k not in need]
    for k, v in cfg.items():
        for f in ('add', 'drop', 'no_shop_add', 'never_with', 'labels'):
            if f in v and not set(v[f]) <= set(catalogue):
                bad.append(f'{k}.{f}')
        if set(v.get('add', ())) & set(v.get('drop', ())):
            bad.append(f'{k}: adds a label it drops')
        for f in [f for f in v if f.endswith('pattern')]:
            re.compile(v[f])
    for k, v in cfg['venues']['classes'].items():
        re.compile(v['names']), re.compile(v['types'])
    if not 0 < float(cfg['rest_sources']['min_rate']) < 1:
        bad.append('rest_sources.min_rate')
    if bad:
        raise ValueError(f'LABEL_RULES: {bad}')
