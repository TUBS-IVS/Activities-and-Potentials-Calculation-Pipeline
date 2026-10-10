"""Step 08: one storey where only the height says more (the user, 2026-10-08; item 2 of the audit of run 7).

The 08b rule counts one storey per 3.5 m of height, so a one-level shop of 5.25-8.75 m counts two or three storeys, and the floor
its occupants do not use becomes a Workers-only remainder - a phantom upper floor. These rules read the evidence that a building
has one storey and set it to one where the height alone gave it more (no OSM building:levels, no structure rule, no dwellings, no
own POI on an upper level) - a fuel-station canopy wherever OSM gives no levels:
  * osm_levels_1    a shop, restaurant or service building whose OSM outlines with building:levels all say exactly 1
  * low_shop        a shop or restaurant below 6.5 m, unless a practice, office, school, Kita or hotel sits in it, its type names
                    upper floors, flats or offices, or residential outlines cover it
  * box_evidence    a shop of 800 m2 or more with store words in its type, a box chain or a box shop tag in it, eaves up to
                    8.75 m (9 m from 1,500 m2)
  * box_low         a shop of 1,000 m2 or more with eaves below 7 m
  * hall_tag_code   a shop or restaurant (and any canopy roof or car wash) under an OSM barn, shed, greenhouse or roof outline,
                    or with an ALKIS farm, depot or car-wash function (a farm code is no evidence for a restaurant)
  * canopy          a fuel-station canopy
  * station_shop    a fuel-station building (ALKIS 2130) that is no canopy
  * sport_box       (sport_boxes, round 17) a sport hall or studio where only the height gave more - the industry
                    rule's model: FLOOR_SPORT_BOX
The decided single-level box rule reads the box words plural-safe (FLOOR_BOX_TYPE_PATTERN). A canopy with a station shop within
15 m (or on the list) gives that shop its labels and gets no unit itself, where the shop has a unit (canopy_units). The patterns
and lists are config.FLOOR_ONE_STOREY_RULES.
"""
import json
import re

import numpy as np
import pandas as pd
import pyogrio
import shapely

I = re.IGNORECASE


def _num(s):
    """OSM numbers as floats: '1' -> 1.0, '1,5' -> 1.5; anything else NaN"""
    return pd.to_numeric(s.astype(str).str.replace(',', '.'), errors='coerce')


def _tag(t, key):
    if not isinstance(t, str) or key not in t:
        return None
    try:
        d = json.loads(t)
    except ValueError:
        return None
    return d.get(key) if isinstance(d, dict) else None


# --- inputs ----------------------------------------------------------------------------------------------------------

def osm_pairs(osm_buildings_file, bld, *, roof_tags, min_overlap_m2=1.0):
    """Every OSM building outline of step 01 that overlaps a building by min_overlap_m2 or more: building_id, bld_id, building
    (the OSM tag), levels (building:levels as a number), roof_levels (roof:levels), inter_m2, a_alkis, a_osm, share_alkis (of the
    footprint), share_osm (of the outline) and iou. Also the share of each footprint the union of its roof_tags outlines covers
    (a canopy roof, a carport)."""
    ob = pyogrio.read_dataframe(osm_buildings_file, columns=['bld_id', 'building', 'building_levels', 'tags'])
    ob = ob[ob.geometry.notna()].to_crs(bld.crs).reset_index(drop=True)
    og = shapely.make_valid(ob.geometry.values)
    b = bld[bld.geometry.notna()]
    bg = shapely.make_valid(b.geometry.values)
    bi, oi = shapely.STRtree(og).query(bg, predicate='intersects')
    # the union of the roof outlines over each footprint (every roof outline that touches it)
    r = pd.DataFrame({'bi': bi, 'oi': oi})[np.isin(ob['building'].to_numpy()[oi], list(roof_tags))]
    cov = {}
    for k, g in r.groupby('bi'):
        u = shapely.union_all(og[g['oi'].to_numpy()])
        cov[b['building_id'].iat[k]] = shapely.area(shapely.intersection(bg[k], u)) / shapely.area(bg[k])
    inter = shapely.area(shapely.intersection(bg[bi], og[oi]))
    keep = inter >= min_overlap_m2
    bi, oi, inter = bi[keep], oi[keep], inter[keep]
    out = pd.DataFrame({'building_id': b['building_id'].to_numpy()[bi], 'bld_id': ob['bld_id'].to_numpy()[oi],
                        'building': ob['building'].to_numpy()[oi], 'levels': _num(ob['building_levels']).to_numpy()[oi],
                        'roof_levels': _num(ob['tags'].map(lambda t: _tag(t, 'roof:levels'))).to_numpy()[oi],
                        'inter_m2': inter, 'a_alkis': shapely.area(bg)[bi], 'a_osm': shapely.area(og)[oi]})
    out['share_alkis'] = out['inter_m2'] / out['a_alkis']
    out['share_osm'] = out['inter_m2'] / out['a_osm']
    out['iou'] = out['inter_m2'] / (out['a_alkis'] + out['a_osm'] - out['inter_m2'])
    return out, pd.Series(cov, dtype=float)


def osm_features(pairs, *, role_min, outline_min_share, two_min_share, res_tags, res_min_share):
    """Per building (index building_id), from its OSM outline pairs:
      lvn_cov, lvn_wmean   the share of the footprint the outlines with building:levels cover (roof outlines left out), and their
                           area-weighted levels - outlines that are its twin, cover it or lie in it (IoU, share >= role_min)
      roof_lv              their area-weighted roof:levels (an attic)
      lv2                  an outline (no roof) with 2 levels or more covers two_min_share of the footprint or more
      all1, cov1, tp1      every outline with levels (no roof) over outline_min_share of the footprint or more says exactly 1;
                           the share those level-1 outlines cover; the share the level-1 twins or parts cover
      res_share            the share residential outlines cover (each res_min_share or more)
      cover_tag, cover_share   the outline that covers the most of the footprint, and how much"""
    p = pairs
    out = pd.DataFrame(index=pd.Index(sorted(p['building_id'].unique()), name='building_id'))
    role = (p['share_osm'] >= role_min) | (p['share_alkis'] >= role_min) | (p['iou'] >= role_min)
    q = p[role & p['levels'].notna() & (p['building'] != 'roof')]
    g = q.assign(lw=q['levels'] * q['inter_m2']).groupby('building_id')
    out['lvn_cov'] = (g['inter_m2'].sum() / g['a_alkis'].first()).clip(upper=1.0)
    out['lvn_wmean'] = g['lw'].sum() / g['inter_m2'].sum()
    q = p[role & p['roof_levels'].notna()]
    g = q.assign(rw=q['roof_levels'] * q['inter_m2']).groupby('building_id')
    out['roof_lv'] = g['rw'].sum() / g['inter_m2'].sum()
    out['lv2'] = out.index.isin(p.loc[(p['levels'] >= 2) & (p['share_alkis'] >= two_min_share) & (p['building'] != 'roof'), 'building_id'])
    q = p[p['levels'].notna() & (p['building'] != 'roof') & (p['share_alkis'] >= outline_min_share)]
    one = q['levels'] == 1
    out['all1'] = q.assign(one=one).groupby('building_id')['one'].all().reindex(out.index).fillna(False).astype(bool)
    out['cov1'] = q[one].groupby('building_id')['share_alkis'].sum().reindex(out.index).fillna(0.0)
    tp = one & ((q['iou'] >= role_min) | (q['share_osm'] >= role_min))
    out['tp1'] = q[tp].groupby('building_id')['share_alkis'].sum().reindex(out.index).fillna(0.0)
    q = p[p['building'].isin(list(res_tags)) & (p['share_alkis'] >= res_min_share)]
    out['res_share'] = q.groupby('building_id')['share_alkis'].sum().clip(upper=1.0).reindex(out.index).fillna(0.0)
    c = p.sort_values('share_alkis', ascending=False, kind='stable').drop_duplicates('building_id').set_index('building_id')
    out['cover_tag'] = c['building'].reindex(out.index)
    out['cover_share'] = c['share_alkis'].reindex(out.index)
    return out


# --- fuel stations -----------------------------------------------------------------------------------------------------

def _fuel_text(b, fuel_pattern):
    t = b['llm_type'].fillna('') + ' | ' + b['name'].fillna('').astype(str) + ' | ' + b['osm_twin_name'].fillna('').astype(str)
    return t.str.contains(fuel_pattern, flags=I, regex=True)


def canopies(b, fuel_poi_ids, roof_cover, *, station_function, fuel_pattern, wash_pattern, canopy_pattern, roof_min_cover):
    """The fuel-station canopies: a fuel-station building (ALKIS) under an OSM roof twin or roof outlines over roof_min_cover of it,
    a building typed as a canopy, or another building with a fuel word or fuel POI under a roof (no car wash)."""
    fs = b['function'].eq(station_function)
    twin = b['osm_twin_tag'].where(b['source'] == 'alkis', b['osm_building']).fillna('')
    rc = b['building_id'].map(roof_cover).fillna(0.0)
    fuel = _fuel_text(b, fuel_pattern) | b['building_id'].isin(fuel_poi_ids)
    wash = b['llm_type'].fillna('').str.contains(wash_pattern, flags=I, regex=True)
    roof = twin.eq('roof') | (rc >= roof_min_cover)
    typed = b['llm_type'].fillna('').str.contains(canopy_pattern, flags=I, regex=True)
    return (fs & twin.eq('roof')) | (fs & (rc >= roof_min_cover)) | typed | (~fs & fuel & roof & ~wash)


def station_pairs(b, canopy, *, fuel_poi_ids, shop_poi_ids, max_dist, station_function, not_shop_head, fuel_pattern, extra):
    """Each canopy's station shop: the nearest building within max_dist m that is no canopy, is a fuel-station building (ALKIS) or
    carries a fuel word or fuel POI, and whose type head names no workshop, car wash, office, flat or hall; ties go to the one with
    a fuel POI, then a shop POI, then the larger footprint. extra: canopy -> shop pairs the rule misses (a service area further
    away). Returns {canopy building_id: shop building_id}."""
    can, oth = b[canopy], b[~canopy]
    cg = shapely.make_valid(can.geometry.values)
    og = shapely.make_valid(oth.geometry.values)
    ci, oi = shapely.STRtree(og).query(cg, predicate='dwithin', distance=max_dist)
    n = pd.DataFrame({'canopy': can['building_id'].to_numpy()[ci], 'other': oth['building_id'].to_numpy()[oi],
                      'dist': shapely.distance(cg[ci], og[oi]), 'o': oi})
    n = n[n['dist'] <= max_dist]
    o = oth.iloc[n['o'].to_numpy()]
    nsh = o['head'].fillna('').str.contains(not_shop_head, flags=I, regex=True).to_numpy()
    fp = o['building_id'].isin(fuel_poi_ids).to_numpy()
    ok = (o['function'].eq(station_function).to_numpy() | fp | _fuel_text(o, fuel_pattern).to_numpy()) & ~nsh
    n = n.assign(fp=fp, sp=o['building_id'].isin(shop_poi_ids).to_numpy(), area=o['area_m2'].to_numpy())[ok]
    n = n.sort_values(['canopy', 'dist', 'fp', 'sp', 'area'], ascending=[True, True, False, False, False], kind='stable')
    pairs = dict(zip(*n.drop_duplicates('canopy')[['canopy', 'other']].T.to_numpy()))
    pairs.update(extra)
    return pairs


# --- the rules ---------------------------------------------------------------------------------------------------------

def rules(b, N, why, base, upper, own, feats, canopy, *, R):
    """The buildings each rule sets to one storey, in the order they apply (a building takes the first): {tag: mask over b}.

    b: bld (building_id, bosserhof_class, code, area_m2, height_eaves_m, mean_height_m, llm_type, name, poi_names, RC); N, why: the
    storeys and rule tags after the structure rules; base: the 08b storeys (storeys, storeys_source, height_used_m); upper: ids of
    the buildings with an own POI above level 0; own: the own POIs of step 06 with group, name, brand and shop; feats: osm_features;
    canopy: the canopies."""
    S, REST, SERV = set(R['shop_classes']), set(R['restaurant_classes']), set(R['service_classes'])
    cls, A, code = b['bosserhof_class'], b['area_m2'], b['code']
    h = base['height_used_m']
    e = b['height_eaves_m'].where(b['height_eaves_m'].gt(0), b['mean_height_m'])
    bid = b['building_id']
    f = feats.reindex(bid.to_numpy())
    f.index = b.index
    lv2 = f['lv2'].fillna(False).astype(bool)
    # only the height gave it more than one storey: no OSM levels or hall, no structure rule, no dwellings, no own POI upstairs
    pool = base['storeys_source'].eq('height') & why.eq('') & (N >= 2) & ~b['RC'].astype(bool) & ~bid.isin(upper)
    g = own.groupby('building_id')['group'].agg(set)
    groups = bid.map(g).map(lambda s: s if isinstance(s, set) else set())
    typ = b['llm_type'].fillna('')
    storeyed = typ.str.lower().str.contains(R['storeyed_pattern'], regex=True)
    res = f['res_share'].fillna(0.0) >= R['res_outline_min_share']
    M = {'canopy': canopy.astype(bool)}
    # osm_levels_1: every OSM outline with levels says 1; a service building (its own unit halves) also needs its own outline,
    # no attic and a low height
    osm1 = ((f['lvn_cov'].fillna(0.0) >= R['osm_min_cover']) & (f['lvn_wmean'] < 1.5) & ~lv2 & f['all1'].fillna(False).astype(bool)
            & (f['cov1'].fillna(0.0) >= R['osm_min_cover']))
    serv_ok = ((f['tp1'].fillna(0.0) >= R['osm_min_cover']) & ~(f['roof_lv'].fillna(0.0) >= 1) & (h < R['osm_service_max_height_m']))
    M['osm_levels_1'] = pool & cls.isin(S | REST | SERV) & osm1 & (~cls.isin(SERV) | serv_ok)
    # low_shop
    up = groups.map(lambda s: bool(s & set(R['upstairs_groups'])))
    M['low_shop'] = pool & (h < R['low_max_height_m']) & ~lv2 & cls.isin(S | REST) & ~up & ~storeyed & ~res
    # box_evidence, box_low: shops only
    ow = own.assign(brand=own['brand'].fillna(''), shop=own['shop'].fillna(''))
    o_names = ow.groupby('building_id')['name'].agg(lambda s: ' | '.join(sorted({x for x in s.dropna().astype(str) if x})))
    o_brands = ow.groupby('building_id')['brand'].agg(lambda s: ' | '.join(sorted({x for x in s if x})))
    names = (bid.map(o_names).fillna('') + ' | ' + bid.map(o_brands).fillna('') + ' | ' + b['name'].fillna('').astype(str) + ' | '
             + b['poi_names'].fillna('').astype(str))
    chain = names.str.contains(R['box_chain_pattern'], flags=I, regex=True) & ~names.str.contains(R['box_chain_exclude'], flags=I, regex=True)
    tags = bid.map(ow.groupby('building_id')['shop'].agg(set)).map(lambda s: s if isinstance(s, set) else set())
    shop_tag = tags.map(lambda s: bool(s & set(R['box_shop_tags'])))
    evid = typ.str.contains(R['box_type_pattern'], flags=I, regex=True) | chain | shop_tag
    shp = pool & cls.isin(S) & ~groups.map(lambda s: bool(s & set(R['box_upper_groups']))) & ~lv2
    tier = pd.Series(False, index=b.index)
    lo = np.inf
    for m2, eav in sorted(R['box_evidence_tiers'], reverse=True):      # (from m2, eaves at most) - each tier up to the next one
        tier |= (A >= m2) & (A < lo) & (e <= eav)
        lo = m2
    M['box_evidence'] = shp & evid & tier
    M['box_low'] = shp & (A >= R['box_low'][0]) & (e < R['box_low'][1])
    # hall_tag_code: halls filed as shops or restaurants (and canopy roofs and car washes in any class)
    tenant = groups.map(lambda s: bool(s & set(R['hall_tenant_groups'])))
    lo_r, hi_r = R['hall_res_codes']
    res_ev = (code.between(lo_r, hi_r) & ~((A > R['hall_res_keep'][0]) & (base['storeys'] <= R['hall_res_keep'][1]))) | res
    hg = pool & cls.isin(S | REST | SERV) & N.between(2, R['hall_max_storeys']) & ~lv2 & ~tenant & ~storeyed & ~res_ev
    cover = f['cover_share'].fillna(0.0) >= R['hall_min_cover']
    hall_tag = f['cover_tag'].isin(R['hall_tags']) & cover
    hall_code = code.isin(R['hall_codes'])
    roof = f['cover_tag'].isin(R['hall_roof_tags']) & cover
    M['hall_tag_code'] = hg & (hall_tag | (hall_code & ~cls.isin(REST))) & (cls.isin(S | REST) | roof | code.eq(R['hall_wash_code']))
    # station_shop
    M['station_shop'] = pool & code.eq(R['station_code']) & ~canopy.astype(bool) & ~lv2
    return {k: v.fillna(False).astype(bool) for k, v in M.items()}


def sport_boxes(b, N, why, base, upper, own, feats, *, R):
    """Sport halls and studios that count more than one storey from the height alone (round 17; the user, 2026-10-09: "Sports
    halls shouldn't be counted as two floors - apply industry-like correction to them"; R = config.FLOOR_SPORT_BOX): the mask of
    the buildings that count one storey.

    The candidates: only the height gave 2+ storeys (no OSM levels, no structure rule, no dwellings, no own POI upstairs) and the eaves
    (the mean height where none) are at most R['max_eaves_m']. A sport building - a sport class whose own data name a sport use:
    sport words in the head of its type, an own sport POI, an ALKIS sport function or an OSM sport outline - counts one storey as a
    hall activity (riding, shooting, pool, ice, tennis, climbing, bowling, indoor play, a sports hall ...) from R['min_m2'] (riding
    stables and shooting ranges at any size), as a studio (fitness, yoga, dance, martial arts) or a generic sports centre from
    R['min_m2'] where the height gave two storeys; unless another non-sport occupant, a mixed-use, shop or office type, a school,
    hotel, care home or hospital, a storeyed sport use (administration, academy, boarding, clinic, community centre ...: the
    industry rule's storeyed company uses), a type naming floors or OSM outlines averaging R['osm_min_levels'] levels say floors.
    Clubhouses below R['club_max_m2'], boathouses, golf club houses and stadium buildings keep their storeys (the industry rule's
    canteens). A candidate sport building whose own OSM outlines all say one level counts one storey too, whatever its kind
    (R['osm_one']).

    b: bld (building_id, bosserhof_class, code, osm_tag, area_m2, height_eaves_m, mean_height_m, llm_type, head, name,
    osm_twin_name, poi_names, RC); N, why: the storeys and rule tags after the structure rules; base: the 08b storeys; upper: ids of
    the buildings with an own POI above level 0; own: the own POIs of step 06 (building_id, poi_use, name, group, leisure, tags);
    feats: osm_features."""
    bid = b['building_id']
    T = b['llm_type'].fillna('').astype(str)
    H = b['head'].fillna('').astype(str)
    names = (b['name'].fillna('').astype(str) + ' | ' + b['osm_twin_name'].fillna('').astype(str) + ' | '
             + b['poi_names'].fillna('').astype(str))
    e = b['height_eaves_m'].where(b['height_eaves_m'].gt(0), b['mean_height_m'])
    f = feats.reindex(bid.to_numpy())
    f.index = b.index
    o = own[['building_id', 'poi_use', 'name', 'group', 'leisure', 'tags']].copy()
    o['sport'] = o['tags'].fillna('').str.extract(r'"sport"\s*:\s*"([^"]*)"')[0]
    uses = (o['poi_use'].fillna('').astype(str) + ';' + o['leisure'].fillna('').astype(str) + ';'
            + o['sport'].fillna('').astype(str)).str.lower().map(lambda s: {x.strip() for x in re.split(r'[;,]', s) if x.strip()})

    def has(key):                               # a POI with one of the uses R[key]
        return uses.map(lambda s: bool(s & set(R[key])))

    def ids(m):                                 # the buildings of the POIs m
        return bid.isin(set(o.loc[m, 'building_id']))

    def txt(s, key):
        return s.str.contains(R[key], flags=I, regex=True)

    club_poi = (o['group'].isin(R['club_poi_groups']) & ~o['poi_use'].isin(R['club_not_uses'])
                & o['name'].fillna('').str.contains(R['club_name_pattern'], flags=I, regex=True))
    sport_poi = (~o['group'].isin(R['not_sport_poi_groups']) & (o['group'].eq('sport') | has('sport_uses'))) | club_poi
    school_poi = o['group'].isin(R['school_poi_groups']) & ~o['name'].fillna('').str.contains(R['not_school_pattern'], flags=I, regex=True)
    # the sport building: a sport class and the building's own data name a sport use
    sport = b['bosserhof_class'].isin(R['classes']) & (txt(H, 'type_pattern') | ids(sport_poi) | b['code'].isin(R['codes'])
                                                        | b['osm_tag'].isin(R['osm_tags']))
    # the kind: a hall activity from min_m2 (riding and shooting at any size); a studio or a generic type from min_m2 where the
    # height gave low_max_storeys; clubhouses below club_max_m2 and the keep kinds keep their storeys
    club = txt(H + ' | ' + names, 'club_pattern') & (b['area_m2'] < R['club_max_m2'])
    keep = txt(T + ' | ' + names, 'keep_pattern')
    act = txt(T, 'activity_pattern') | ids(sport_poi & has('activity_uses'))
    any_size = txt(T, 'any_size_pattern') | ids(sport_poi & has('any_size_uses'))
    studio = (txt(T, 'studio_pattern') | ids(sport_poi & has('studio_uses'))) & ~act
    size = (b['area_m2'] >= R['min_m2']) | (any_size & act)
    low = N <= R['low_max_storeys']
    kind = (act & size) | (studio & bool(R['studios']) & size & low) | (~act & ~studio & size & low)
    kind &= ~club & ~keep
    if R.get('clubs'):
        kind |= club & ~keep & low
    # what keeps the storeys (the industry rule's storeyed company uses)
    floors_osm = (f['lvn_cov'].fillna(0.0) >= R['osm_min_cover']) & (f['lvn_wmean'].fillna(0.0) >= R['osm_min_levels'])
    storeyed = (ids(~sport_poi & ~o['group'].isin(R['no_occupant_groups'])) | txt(T, 'mixed_pattern')
                | b['bosserhof_class'].isin(R['school_classes']) | ids(school_poi)
                | (txt(H, 'school_pattern') & ~txt(H, 'not_school_pattern'))
                | b['bosserhof_class'].isin(R['hotel_classes']) | ids(o['group'].isin(R['hotel_poi_groups']))
                | txt(T, 'storeyed_pattern') | txt(names, 'storeyed_name_pattern') | txt(T, 'floors_pattern') | floors_osm)
    cand = (base['storeys_source'].eq('height') & why.eq('') & (N >= 2) & ~b['RC'].astype(bool) & ~bid.isin(upper)
            & (e <= R['max_eaves_m']))
    # the building's own OSM outlines all say one level (no roof levels): the evidence of osm_levels_1
    osm1 = (bool(R['osm_one']) & (f['lvn_cov'].fillna(0.0) >= R['osm_min_cover']) & (f['lvn_wmean'] < 1.5)
            & f['all1'].fillna(False).astype(bool) & (f['cov1'].fillna(0.0) >= R['osm_min_cover'])
            & ~(f['roof_lv'].fillna(0.0) >= 1) & ~f['lv2'].fillna(False).astype(bool))
    return (cand & sport & ((kind & ~storeyed) | osm1)).fillna(False).astype(bool)


# --- the units -----------------------------------------------------------------------------------------------------------

def canopy_units(uo, b, canopy_ids, pairs, no_unit, red_labels):
    """A canopy forms no remainder; a canopy with a station shop gives the shop's main unit its labels (its building unit, else its
    rest unit, else its largest POI unit; a building unit without POIs counts as a place with evidence when the canopy has a POI)
    and keeps no unit itself, nor does a canopy of the no_unit list. A shop without such a unit carries nothing: its canopies keep
    their units. Returns the units and the shops whose labels changed."""
    uo = uo.copy()
    ok = uo['no_unit_reason'].eq('')
    m = ok & uo['building_id'].isin(canopy_ids) & uo['kind'].eq('remainder')
    uo.loc[m, 'no_unit_reason'] = 'canopy: no remainder'
    nb = b.set_index('building_id')['n_pois']
    log, carried = [], set()
    for shop in sorted(set(pairs.values())):
        cans = sorted(c for c, s_ in pairs.items() if s_ == shop)
        cl = set()
        for c in cans:
            for L in uo.loc[ok & uo['building_id'].eq(c), 'labels']:
                cl |= set(L)
        cl.discard('work')
        had_poi = bool((nb.reindex(cans).fillna(0) > 0).any())
        su = uo[ok & uo['building_id'].eq(shop)]
        bu, ru, pu = (su[su['kind'].eq(k)] for k in ('building', 'rest', 'poi'))
        if not (len(bu) or len(ru) or len(pu)):
            continue                                    # no unit to carry them: the canopies keep theirs
        have = set().union(*su['labels'])
        if len(bu):
            i = bu.index[0]
            new = tuple(dict.fromkeys(list(uo.at[i, 'labels']) + sorted(cl - set(uo.at[i, 'labels']))))
        else:
            i = (ru if len(ru) else pu.sort_values('O', ascending=False)).index[0]
            new = tuple(dict.fromkeys(list(uo.at[i, 'labels']) + sorted(cl - have)))
        added = set(new) - set(uo.at[i, 'labels'])
        uo.at[i, 'k_red'] = int(uo.at[i, 'k_red']) + sum(l in red_labels for l in added)      # each added label takes its share
        uo.at[i, 'k_all'] = int(uo.at[i, 'k_all']) + sum(l != 'work' for l in added)
        flip = had_poi and uo.at[i, 'kind'] == 'building' and bool(uo.at[i, 'no_poi'])
        if added or flip:
            log.append((shop, ';'.join(cans), ';'.join(uo.at[i, 'labels']), ';'.join(new), flip))
        uo.at[i, 'labels'] = new
        if flip:
            uo.at[i, 'no_poi'] = False
        carried |= set(cans)
    m = ok & uo['building_id'].isin(carried) & uo['no_unit_reason'].eq('')
    uo.loc[m, 'no_unit_reason'] = 'canopy: the station shop carries it'
    uo.loc[m & uo['rule'].eq(''), 'rule'] = 'canopy_shop'
    m = ok & uo['building_id'].isin(set(no_unit) - set(pairs)) & uo['no_unit_reason'].eq('')
    uo.loc[m, 'no_unit_reason'] = 'canopy: no unit (list)'
    uo.loc[m & uo['rule'].eq(''), 'rule'] = 'canopy_no_unit'
    return uo, pd.DataFrame(log, columns=['shop', 'canopies', 'labels_before', 'labels_after', 'now_with_evidence'])
