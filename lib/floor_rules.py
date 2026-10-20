"""floor_rules.py — the occupied floor area of every unit of step 08.

Step 08 weights every unit by the floor area it occupies: Workers by that area times the Bosserhof
factor, the other zone categories by the area split over the unit's labels. The rules that decide
the area live here: the storeys of a building (the height rule with its halls, and the structure
rules on top of it), whether a building has dwellings (the residential context), the POI groups and
POI-level classes, the floor family of every occupant, the sharing of a building between its
occupants, and the sets of places the single-category rules apply to. The decisions behind them and
their numbers are documented with the settings in config.py (STEP 08).

Every function is pure: it takes DataFrames and config values and returns new columns or frames; the
notebook reads the files, shows each step and checks it.
"""

import re

import numpy as np
import pandas as pd

ALL = np.inf                       # every storey: a rule or family without a storey cap

# the storeys a floor family may take (claim-capped sharing); ALL takes what the others leave
FAMILY_STOREYS = {'GROUND': 1.0, 'ONE': 1.0, 'LOW2': 2.0, 'CAP2': 2.0, 'CAP3': 3.0, 'ALL': ALL}
# the share of a family's floor that lies on the ground floor (the shared ground-floor budget)
FAMILY_GROUND_SHARE = {'GROUND': 1.0, 'LOW2': 0.5, 'CAP3': 1.0 / 3.0}


# --- text helpers ------------------------------------------------------------------------------------

def head(types, split_pattern):
    """The head of each step-05 type: the text before the first split word, comma or bracket, so that
    the words describe the building and not something in it."""
    return types.fillna('').str.split(split_pattern, n=1, regex=True).str[0]


def parse_levels(value):
    """The floors an OSM `level` tag names, as a sorted tuple, or None.

    '0' -> (0,), '0;1' -> (0, 1), '1,_2' -> (1, 2), '0-1' -> (0, 1); a tag that is no floor number
    ('g', 'Keller') -> None."""
    if not isinstance(value, str):
        return None
    s = value.strip().replace('_', '').replace(' ', '')
    if not s:
        return None
    out = set()
    for part in re.split(r'[;,]', s):
        if not part:
            continue
        m = re.fullmatch(r'(-?\d+(?:\.\d+)?)\.?', part)
        if m:
            out.add(float(m.group(1)))
            continue
        m = re.fullmatch(r'(-?\d+)-(-?\d+)', part)
        if m and int(m.group(1)) <= int(m.group(2)) <= int(m.group(1)) + 10:
            out.update(float(x) for x in range(int(m.group(1)), int(m.group(2)) + 1))
            continue
        return None
    return tuple(sorted(out)) or None


def tag_value(tags, key):
    """One OSM key from the JSON text of the remaining tags (step 01's `tags` column)."""
    return tags.fillna('').str.extract('"' + re.escape(key) + r'"\s*:\s*"([^"]*)"')[0]


# --- storeys -----------------------------------------------------------------------------------------

def base_storeys(b, *, storey_height, hall_classes, head_split, hall_pattern, hall_exclude):
    """The base storeys of every building (the height rule).

    b: area_m2, volume_3d_m3, height_eaves_m (NaN where none), osm_levels (a whole number or NaN),
    llm_type, bosserhof_class. h = the eaves height capped at the mean height (volume / footprint),
    the mean height where no eaves height exists; storeys = max(1, round(h / storey_height)); a hall
    (its class is a hall class or the head of its type has a hall word, never with an exclusion
    word) is one storey; OSM building:levels overrides both."""
    hmean = b['volume_3d_m3'] / b['area_m2']
    eav = b['height_eaves_m']
    has_e = eav.gt(0)
    h = pd.Series(np.where(has_e, np.fmin(eav, hmean), hmean), index=b.index)
    hd = head(b['llm_type'], head_split)
    by_cls = b['bosserhof_class'].isin(hall_classes)
    by_type = hd.str.contains(hall_pattern, case=False, regex=True)
    excl = hd.str.contains(hall_exclude, case=False, regex=True)
    hall = np.select([by_cls & by_type & ~excl, by_cls & ~excl, by_type & ~excl], ['class+type', 'class', 'type'], default='')
    osm = b['osm_levels'].notna()
    st = np.maximum(1.0, np.floor(h / storey_height + 0.5))
    return pd.DataFrame({
        'height_used_m': h,
        'height_source': np.select([has_e & (eav <= hmean), has_e], ['eaves', 'mean (eaves above it)'], default='mean (no eaves)'),
        'height_storeys': st,
        'hall': hall,
        'osm': osm,
        'storeys': np.where(osm, b['osm_levels'], np.where(hall != '', 1.0, st)).astype(float),
        'storeys_source': np.select([osm, hall != ''], ['osm levels', 'hall'], default='height'),
    }, index=b.index)


def reclassify(b, pairs, *, mall_class, hyper_class, outlet_class, hyper_pattern, hyper_max_pairs, outlet_pattern, outlet_uses,
               outlet_exclude):
    """The shopping centres that are a hypermarket or a factory outlet centre.

    pairs: every building-POI pair of step 06, site rows included (building_id, poi_use, name,
    parent_name). A shopping centre is an outlet when a POI name or parent name matches
    outlet_pattern or a POI's use is one of outlet_uses (the ids in outlet_exclude excepted), and a
    hypermarket when it is no outlet, has fewer than hyper_max_pairs pairs and a POI or parent name
    matches hyper_pattern. Returns the class per building and the two masks."""
    txt = (pairs['name'].fillna('') + ' | ' + pairs['parent_name'].fillna('')).str.lower()
    outlet_b = set(pairs.loc[txt.str.contains(outlet_pattern, regex=True) | pairs['poi_use'].isin(outlet_uses), 'building_id'])
    full_b = set(pairs.loc[txt.str.contains(hyper_pattern, regex=True), 'building_id'])
    n_pairs = b['building_id'].map(pairs.groupby('building_id').size()).fillna(0)
    mall = b['bosserhof_class'].eq(mall_class)
    outlet_any = mall & b['building_id'].isin(outlet_b)
    hyper = mall & ~outlet_any & (n_pairs < hyper_max_pairs) & b['building_id'].isin(full_b)
    outlet = outlet_any & ~b['building_id'].isin(outlet_exclude)
    cls = b['bosserhof_class'].where(~hyper, hyper_class).where(~outlet, outlet_class)
    return cls, hyper, outlet


def type_flags(heads, types, patterns, full_type_keys):
    """One boolean column per pattern: matched in the head of the type, or in the whole type for the
    keys in full_type_keys."""
    return pd.DataFrame({k: (types.fillna('') if k in full_type_keys else heads).str.contains(p, case=False, regex=True)
                         for k, p in patterns.items()}, index=heads.index)


def residential_context(b, storeys, *, res_range, res_codes, res_type, office_whole, res_twins, house_twins, nonres_twins,
                        house_min_storeys, box_min_m2, box_max_storeys, nonres_range, kita_class):
    """Whether a building has dwellings (the residential context, RC).

    b: code (the ALKIS function number or NaN), source, osm_twin_tag, osm_building, llm_type, head,
    area_m2, bosserhof_class; storeys: the base storeys. RC = (an ALKIS residential code, unless the
    head names a whole office building, the OSM twin is a specific non-residential building, or it
    is a low box that neither type nor twin confirms) or an OSM residential twin or a residential
    noun in the type. A house twin never makes an explicit non-residential code residential, and a
    Kita counts as residential only when its type names dwellings. Returns the parts and RC."""
    code = b['code']
    tag = b['osm_twin_tag'].where(b['source'] == 'alkis', b['osm_building']).fillna('')
    alk_res = code.between(*res_range) | code.isin(res_codes)
    type_res = b['llm_type'].fillna('').str.contains(res_type, case=False, regex=True)
    twin_res = tag.isin(res_twins) | (tag.isin(house_twins) & (storeys >= house_min_storeys))
    twin_non = tag.isin(nonres_twins) & ~type_res
    office = b['head'].str.contains(office_whole, case=False, regex=True)
    box_quirk = alk_res & ~type_res & ~twin_res & (b['area_m2'] > box_min_m2) & (storeys <= box_max_storeys)
    rc0 = (alk_res & ~office & ~twin_non & ~box_quirk) | twin_res | type_res
    house_on_nonres = code.between(*nonres_range) & ~alk_res & tag.isin(house_twins) & ~type_res
    kita = b['bosserhof_class'].eq(kita_class)
    rc = (rc0 & ~house_on_nonres).where(~kita, type_res)
    return pd.DataFrame({'osm_tag': tag, 'alk_res': alk_res, 'type_res': type_res, 'twin_res': twin_res, 'twin_non': twin_non,
                         'office_whole': office, 'box_quirk': box_quirk, 'house_on_nonres': house_on_nonres & rc0,
                         'kita_by_type': kita & (rc != (rc0 & ~house_on_nonres)), 'RC': rc.astype(bool)}, index=b.index)


def structure_storeys(b, f, base, rc, upper, *, codes, hall_classes, craft_classes, industry_classes, sport_classes,
                      ikea_classes, brand_unhall_classes, furniture_class, box_classes, mall_class, hall_word, hall_site, town_hall,
                      location_split, canteen_max, cinema_max, ikea_pattern, ikea_exclude, ikea_storeys, furniture_min_eaves,
                      furniture_min_m2, furniture_max, furniture_exclude_type, furniture_exclude_name, box_min_m2, box_max_eaves,
                      box_type, mall_box_max_eaves, hyper):
    """The storeys after the structure rules. Rules apply in order where OSM building:levels is not
    mapped (parking also where it is); a later rule overrides an earlier one.

    b: building_id, bosserhof_class (after the reclassification), code, area_m2, height_eaves_m,
    mean_height_m, name, poi_names, llm_type, head, osm_tag; f: type flags (type_flags); base:
    base_storeys; rc: the residential context; upper: ids of the buildings with an own POI on a level
    of 1 or more; hyper: the reclassified hypermarkets. A hall word before the office word counts
    only before the first location word and not as a site qualifier (hall_site: 'factory site',
    'factory premises'); a brand word un-halls a small shop only where the hall word of its type also
    stands in its name or a POI name (Jacques' Wein-Depot, Games Workshop). Returns (storeys, the
    rule tags, and the derived building flags worship / fire / sport_hall / parking)."""
    cls, code, hd = b['bosserhof_class'], b['code'], b['head']
    N = base['storeys'].copy()
    st = base['height_storeys']
    osm = base['osm']
    hall08 = base['hall'] != ''
    why = pd.Series('', index=b.index)
    eaves = b['height_eaves_m'].where(b['height_eaves_m'].gt(0), b['mean_height_m'])
    pre = hd.str.split(location_split, n=1, regex=True).str[0].str.replace(hall_site, ' ', case=False, regex=True)
    hall_word_pre = pre.str.contains(hall_word, case=False, regex=True) & ~pre.str.contains(town_hall, case=False, regex=True)
    names = b['name'].fillna('') + ' ' + b['poi_names'].fillna('').astype(str)
    brand = pd.Series([any(re.search(r'\b' + re.escape(w) + r'\b', n, flags=re.IGNORECASE) for w in re.findall(hall_word, h, flags=re.IGNORECASE))
                       for h, n in zip(hd, names)], index=b.index, dtype=bool)
    worship = (code.isin(codes['worship']) | f['worship']) & ~f['worship_excl']
    fire = (code.isin(codes['fire']) | f['fire']) & ~f['fire_prof'] & ~f['office_any']
    sport_hall = (code.isin(codes['sports_hall']) | f['sports_hall'] | f['pool']
                  | (f['gym_word'] & (cls.isin(sport_classes) | f['gym_sport'])))
    parking = code.isin(codes['parking']) | b['osm_tag'].eq('parking') | f['parking']
    tower = f['tower'] & ~f['tower_excl']
    cinema = f['cinema'] & ~f['museum']
    ikea = (names + ' ' + b['llm_type'].fillna('')).str.contains(ikea_pattern, case=False, regex=True)

    def setn(mask, val, tag, osm_ok=False):
        m = mask & (~osm | osm_ok)
        if not m.any():
            return
        N[m] = val if np.isscalar(val) else np.asarray(val, dtype=float)[m.to_numpy()]
        why[m] = why[m].where(why[m] == '', why[m] + '+') + tag

    setn(hyper, 1.0, 'hypermarket')
    setn(cls.isin(hall_classes) & ~hall08 & f['res_head'] & ~f['office_any'], 1.0, 'hall_residential')
    setn(~hall08 & (cls.isin(hall_classes) | hd.str.contains(hall_word, case=False, regex=True)) & f['office_any']
         & hall_word_pre & ~f['town_hall'], 1.0, 'hall_before_office')
    setn(cls.isin(craft_classes) & (N > 1), 1.0, 'crafts')
    co = cls.isin(industry_classes) & hall08
    setn(co & f['storeyed_co'], st, 'storeyed_company_use')
    setn(co & f['canteen'] & ~f['storeyed_co'], np.minimum(st, canteen_max), 'canteen')
    setn(worship & (N > 1), 1.0, 'worship')
    setn(fire & (N > 1), 1.0, 'fire_station')
    setn(sport_hall & (N > 1), 1.0, 'sports_hall')
    setn((f['hangar'] | f['auditorium']) & (N > 1), 1.0, 'hangar_auditorium')
    setn(tower & (N > 1), 1.0, 'tower')
    setn(parking & (N > 1), 1.0, 'parking', osm_ok=True)
    setn(cinema & (N > cinema_max), float(cinema_max), 'cinema')
    setn(f['factory_outlet'] & hall08, st, 'outlet_not_hall')
    setn(cls.isin(brand_unhall_classes) & (base['hall'] == 'type') & brand, st, 'brand_not_hall')
    setn(ikea & cls.isin(ikea_classes) & ~b['llm_type'].fillna('').str.contains(ikea_exclude, case=False, regex=True),
         float(ikea_storeys), 'ikea')
    furn = (cls.eq(furniture_class) & (b['height_eaves_m'] >= furniture_min_eaves) & (b['area_m2'] >= furniture_min_m2)
            & ~b['llm_type'].fillna('').str.contains(furniture_exclude_type, case=False, regex=True)
            & ~b['name'].fillna('').str.contains(furniture_exclude_name, case=False, regex=True))
    setn(furn, np.minimum(st, furniture_max), 'furniture_house')
    box = (cls.isin(box_classes) & ~rc & (b['area_m2'] >= box_min_m2) & (N >= 2) & b['llm_type'].fillna('').str.contains(box_type, case=False, regex=True)
           & ~b['building_id'].isin(upper) & (eaves <= box_max_eaves))
    mall_box = cls.eq(mall_class) & (eaves < mall_box_max_eaves) & ~b['building_id'].isin(upper) & (N >= 2)
    setn(box, 1.0, 'single_level_box')
    setn(mall_box & ~box, 1.0, 'single_level_mall')
    flags = pd.DataFrame({'worship': worship, 'fire': fire, 'sport_hall': sport_hall, 'parking': parking, 'tower': tower,
                          'cinema': cinema, 'ikea': ikea, 'furniture_house': furn, 'box': box, 'mall_box': mall_box & ~box,
                          'hall_word_pre': hall_word_pre}, index=b.index)
    return N, why, flags


def retail_storeys(b, base, N, why, *, classes, storey_height):
    """Department stores and shopping centres count storeys of storey_height instead of 3.5 m
    where OSM building:levels is not mapped; never more than the storeys they come with."""
    n45 = np.maximum(1.0, np.floor(base['height_used_m'] / storey_height + 0.5))
    m = b['bosserhof_class'].isin(classes) & ~base['osm'] & (n45 < N)
    N, why = N.copy(), why.copy()
    N[m] = n45[m]
    why[m] = why[m].where(why[m] == '', why[m] + '+') + 'retail_storey'
    return N, why


def mall_storeys(b, N, why, rc, flags, own_levels, *, mall_class, outlet_class, level_min, level_max, min_pois, mall_max,
                 small_max, small_m2, outlet_max):
    """The storeys of malls and outlet centres: a shopping centre takes the
    distinct whole levels from level_min to level_max mapped on at least min_pois of its own POIs,
    otherwise at most mall_max storeys, at most small_max in a parking building or with dwellings on
    a footprint of at most small_m2; an outlet centre at most outlet_max.

    own_levels: building_id and the leading whole number of each own POI's level tag."""
    lv = own_levels[own_levels['level'].between(level_min, level_max)]
    t = lv.groupby('building_id')['level'].agg(['size', 'nunique'])
    mapped = t.loc[t['size'] >= min_pois, 'nunique']
    N, why = N.copy(), why.copy()
    mall = b['bosserhof_class'].eq(mall_class)
    has = mall & b['building_id'].isin(mapped.index)
    small = mall & ~has & (flags['parking'] | (rc & (b['area_m2'] <= small_m2)))
    rest = mall & ~has & ~small
    out = b['bosserhof_class'].eq(outlet_class)
    new = N.copy()
    new[has] = b.loc[has, 'building_id'].map(mapped).astype(float)
    new[small] = np.minimum(N[small], small_max)
    new[rest] = np.minimum(N[rest], mall_max)
    new[out] = np.minimum(N[out], outlet_max)
    for m, tag in ((has, 'mall_mapped_levels'), (small, 'mall_small'), (rest, 'mall_cap'), (out, 'outlet_cap')):
        ch = m & (new != N)
        why[ch] = why[ch].where(why[ch] == '', why[ch] + '+') + tag
    return new, why


# --- POI groups and classes ------------------------------------------------------------------------------

def poi_groups(df, groups, key_fallback):
    """The use group of every POI: its poi_use in a group's use list, else the OSM key its use came
    from (poi_use_tag), else the first OSM key column it carries; 'unmapped' if none.

    df: poi_use, poi_use_tag and the key columns of key_fallback."""
    use2group = {u: g for g, uses in groups.items() for u in uses}
    g = df['poi_use'].fillna('').str.strip().map(use2group)
    g = g.fillna(df['poi_use_tag'].map(key_fallback))
    for key, grp in key_fallback.items():
        g = g.where(g.notna(), np.where(df[key].notna(), grp, None))
    return g.fillna('unmapped')


def poi_classes(df, group, *, group_class, class_by_use, food_class, discount_class, discount_pattern, hyper_class, hyper_pattern):
    """The Bosserhof class of every POI on its own (a step-05 class name), or None where the group
    carries no class information (generic, unmapped, vacant and the uses without a refinement).

    df: poi_use, name; group: poi_groups. class_by_use: (group, uses, class) refinements, the last
    matching one wins; uses None means every POI of the group not refined before."""
    u = df['poi_use'].fillna('')
    cls = group.map(group_class).astype(object)
    for g, uses, c in class_by_use:
        m = group.eq(g) & (u.isin(uses) if uses is not None else cls.isna())
        cls[m] = c
    fs = group.eq('food_store')
    name = df['name'].fillna('').str.lower()
    cls[fs] = food_class
    cls[fs & name.str.contains(discount_pattern, regex=True)] = discount_class
    cls[fs & name.str.contains(hyper_pattern, regex=True)] = hyper_class
    return cls.where(cls.notna(), None)


def chain_names(names, chains):
    """The multi-level chain each name belongs to ('' for none)."""
    out = pd.Series('', index=names.index)
    for chain, pat in chains.items():
        out[(out == '') & names.fillna('').str.contains(pat, case=False, regex=True)] = chain
    return out


# --- occupied floor area ---------------------------------------------------------------------------------

def sole_storeys(r, group, use, levels, chain, *, class_storeys, group_storeys, street_classes, level_classes, level_groups,
                 counter_all_uses, home_storeys):
    """The storeys a sole occupant takes (ALL = every storey), with the rule that set them (the
    caller adds the storeys).

    r: the building (attributes cls, RC, N, office_whole, public_office, small_school, small_unit,
    studio, sport_hall, parking, alk_res, box_quirk, pure_home, n_pois, small_attraction); group / use /
    levels / chain: the building's only POI, or None. class_storeys and group_storeys map a class or
    a group to (storeys with dwellings, storeys without, condition); None = every storey; the
    condition, where given, must hold or the occupant takes every storey."""
    def cond(name):
        return {None: True, 'not_office_building': not r.office_whole, 'public_office': r.public_office,
                'small_school': r.small_school, 'small_unit': r.small_unit, 'small_unit_upstairs': r.small_unit and r.N >= 2,
                'studio': (r.studio or group == 'sport') and not r.sport_hall,
                'dwelling_by_code': r.alk_res and not r.box_quirk,
                'holiday_flat': group == 'holiday_flat' and r.alk_res and not r.box_quirk,
                'small_attraction': r.small_attraction}[name]
    failed = {'not_office_building': 'a whole office building', 'public_office': 'no parish, social or counselling office',
              'small_school': 'no small school', 'small_unit': 'no small unit', 'small_unit_upstairs': 'no small unit upstairs',
              'studio': 'no studio', 'dwelling_by_code': 'no residential ALKIS code',
              'holiday_flat': 'no holiday flat with a residential ALKIS code', 'small_attraction': 'no small attraction'}

    def pick(rule, key):
        with_d, without_d, c = rule
        if not cond(c):
            return ALL, f'{key}, {failed[c]}'
        dwell = r.RC or (r.parking and key in ('sport', 'fitness / wellness'))
        if c == 'dwelling_by_code' or c == 'holiday_flat':
            dwell = True                                   # the rule reads the ALKIS code, not the residential context
        v = with_d if dwell else without_d
        return (ALL if v is None else float(v)), f'{key} ({"with" if dwell else "without"} dwellings)'

    def level_adjust(n, why):
        if levels is not None and len(levels) >= 2:
            return float(len(levels)), f'level tag {";".join(f"{x:g}" for x in levels)}'
        if levels is not None and levels[0] >= 1:
            return 1.0, f'level tag {levels[0]:g}'
        if chain and not r.RC:
            return 2.0, f'multi-level chain {chain}'
        return n, why

    if r.pure_home and r.n_pois == 0 and r.cls in home_storeys:
        return float(home_storeys[r.cls]), 'plain home'
    if r.cls in street_classes and isinstance(group, str) and group in group_storeys:
        if group == 'counter' and use in counter_all_uses:
            n, why = pick((1, None, None), 'counter (bank, insurance, agency)')
            return n, why
        n, why = pick(group_storeys[group], group)
        if group in level_groups:
            n, why = level_adjust(n, why)
        return n, why
    if r.cls in class_storeys:
        n, why = pick(class_storeys[r.cls], r.cls)
        if r.cls in level_classes:
            n, why = level_adjust(n, why)
        return n, why
    return ALL, f'{r.cls} (no storey rule)'


def poi_family(q, br, *, group_family, mall_classes, mall_unit_groups, bigbox_classes, culture_all_uses, cinema_use, chain_groups,
               anchor_groups):
    """The floor family of an asked POI in a shared building, with the rule that set it.

    q: the POI (attributes group, poi_use, how, levels, chain); br: its building (cls, RC, alk_res,
    box_quirk, worship). group_family maps a group to (family with dwellings, family without)."""
    g, RC, cls = q.group, bool(br.RC), br.cls
    if cls in mall_classes and (q.how == 'unit' or g in mall_unit_groups):
        return 'ALL', 'mall unit'
    with_d, without_d = group_family.get(g, group_family['unmapped'])
    fam, why = (with_d if RC else without_d), f'{g} ({"with" if RC else "without"} dwellings)'
    if g == 'holiday_flat':
        fam, why = (with_d if (br.alk_res and not br.box_quirk) else without_d), 'holiday_flat (by the ALKIS code)'
    if g in anchor_groups and cls in bigbox_classes:
        fam, why = 'ALL', f'{g} anchor in its own big-box building'
    if g == 'culture':
        if q.poi_use in culture_all_uses:
            fam, why = 'ALL', f'culture ({q.poi_use})'
        elif q.poi_use == cinema_use:
            fam, why = 'CAP2', 'culture (cinema)'
    if g == 'worship' and br.worship:
        fam, why = 'ALL', 'worship in a worship building'
    if g in chain_groups and q.chain and not RC and fam == 'GROUND':
        fam, why = 'LOW2', f'multi-level chain {q.chain}'
    lv = q.levels
    if lv is not None and len(lv) >= 2 and fam in ('GROUND', 'ONE', 'LOW2'):
        up = min(lv) >= 1
        fam = 'CAP2' if (up and len(lv) == 2) else ('LOW2' if len(lv) == 2 else 'CAP3')
        why += f'; level tag {";".join(f"{x:g}" for x in lv)}'
    elif lv is not None and len(lv) == 1 and lv[0] >= 1 and fam in ('GROUND', 'LOW2'):
        fam = 'ONE'
        why += f'; level tag {lv[0]:g}'
    return fam, why


def share_floor(A, N, s, fams, point, slot, cap_m2):
    """The occupied floor of every occupant of one shared building (claim-capped sharing).

    A: footprint; N: storeys; s: the shares, re-split so that they sum to 1 over the asked POIs and
    the vacant slots; fams: the floor family of each; point: True for a POI mapped as a point (not a
    unit) that is no anchor; slot: True for an occupant that gives no unit (a vacant, holiday-flat or
    dormitory place: it keeps its floor, never takes the rest); cap_m2: the point size cap of each.

    Each occupant claims min(s x floor area, its family's storeys x A); a point is capped at its size
    first; the ground-floor units together (GROUND, half of LOW2, a third of
    CAP3) then get at most A; the main occupants - ALL units that are no point and no slot - take what
    the others leave, by their shares. A point is never a main occupant, so the floor its cap frees goes
    to the main occupants - with none, it stays free. Returns the occupied floor of each and the floor
    nobody occupies."""
    FA = A * N
    s = np.asarray(s, dtype=float)
    fams = np.asarray(fams, dtype=object)
    point = np.asarray(point, dtype=bool)
    slot = np.asarray(slot, dtype=bool)
    cap = np.array([FAMILY_STOREYS[f] for f in fams]) * A
    occ = np.minimum(FA * s, cap)
    occ = np.where(point, np.minimum(occ, cap_m2), occ)
    gshare = np.array([FAMILY_GROUND_SHARE.get(f, 0.0) for f in fams])
    ground = (occ * gshare).sum()
    if ground > A:
        occ = np.where(gshare > 0, occ * A / ground, occ)
    main = (fams == 'ALL') & ~point & ~slot
    if main.any():
        occ[main] = max(FA - occ[~main].sum(), 0.0) * s[main] / s[main].sum()
    return occ, max(FA - occ.sum(), 0.0)


def ground_use(occ, fams):
    """The part of one footprint the ground-floor units of a building use."""
    return float(sum(o * FAMILY_GROUND_SHARE.get(f, 0.0) for o, f in zip(occ, fams)))


# --- the single-category rules ----------------------------------------------------------------------------

def church_ids(b, *, codes):
    """The churches: ALKIS church / chapel / place-of-worship codes."""
    return set(b.loc[b['code'].isin(codes), 'building_id'])


def volunteer_fire_ids(b, *, station, exclude, exclude_head, volunteer, city_ags):
    """The volunteer fire stations: a fire-station head that is no professional, works or FTZ station
    (exclude, read in the whole type and the name: 'Fire station (Feuerwehrtechnische Zentrale)') and
    no former station now used otherwise, office or museum (exclude_head, read in the head and the
    name: 'Volunteer fire station with municipal office' stays); inside the independent cities
    (city_ags) the head must also say volunteer."""
    hd, nm = b['head'], b['name'].fillna('')
    st = (hd.str.contains(station, case=False, regex=True)
          & ~(b['llm_type'].fillna('') + ' ' + nm).str.contains(exclude, case=False, regex=True)
          & ~(hd + ' ' + nm).str.contains(exclude_head, case=False, regex=True))
    city = b['ags'].fillna('').astype(str).str[:5].isin(city_ags)
    return set(b.loc[st & (~city | hd.str.contains(volunteer, case=False, regex=True)), 'building_id'])


def sports_hall_ids(b, *, codes, type_pattern, classes, keep_pattern, keep_ids):
    """The sports halls and clubhouses run without staff: ALKIS sports codes or a sports-hall head, in
    the club-type classes, without the staffed venues (keep_pattern, keep_ids)."""
    hd = b['head']
    m = ((b['code'].isin(codes) | hd.str.contains(type_pattern, case=False, regex=True)) & b['bosserhof_class'].isin(classes)
         & ~(hd + ' ' + b['name'].fillna('')).str.contains(keep_pattern, case=False, regex=True) & ~b['building_id'].isin(keep_ids))
    return set(b.loc[m, 'building_id'])


def no_evidence_ids(b, *, function_prefix, classes):
    """The no-evidence buildings: residential-coded buildings of an office / services / small retail /
    customer services class with no POI, no site and no name (empty or '-')."""
    name_empty = b['name'].isna() | b['name'].fillna('').str.strip().isin(['', '-'])
    m = (b['function'].fillna('').str.startswith(function_prefix) & b['bosserhof_class'].isin(classes)
         & b['n_pois'].eq(0) & b['n_sites'].eq(0) & name_empty)
    return set(b.loc[m, 'building_id'])


def holiday_flat_ids(b, pairs, *, hotel_class, function_prefix, uses):
    """The holiday flats: hotels with a residential ALKIS code whose POIs (site rows included)
    are only holiday flats and chalets."""
    u = pairs.dropna(subset=['poi_use']).groupby('building_id')['poi_use'].agg(lambda s: frozenset(x for x in s if str(x).strip()))
    only = b['building_id'].map(u).map(lambda s: isinstance(s, frozenset) and len(s) > 0 and s <= set(uses))
    m = b['bosserhof_class'].eq(hotel_class) & b['function'].fillna('').str.startswith(function_prefix) & only
    return set(b.loc[m, 'building_id'])


def non_occupants(q, *, tags, info_staffed, keep_keys):
    """The asked POIs that are amenity features, not occupants: a tag of the non-occupant table, and no
    other occupant tag (keep_keys: shop, office, craft, healthcare beyond the table); tourism=information
    unless information=office or the step-07 type names a staffed place.

    q: amenity, leisure, shop, tourism, information, poi_type and the keep_keys columns."""
    hit = pd.Series(False, index=q.index)
    for key, values in tags.items():
        hit |= q[key].isin(values)
    other = pd.Series(False, index=q.index)
    for key in keep_keys:
        other |= q[key].notna() & ~q[key].isin(tags.get(key, ()))
    info = q['tourism'].eq('information') & ~q['information'].eq('office') & ~q['poi_type'].fillna('').str.contains(info_staffed, case=False, regex=True)
    return (hit & ~other) | (info & ~other & ~q['amenity'].notna())


def point_size_caps(pairs, footprints, *, groups, quantile, outline_share):
    """The size cap of each group: the quantile of the own POI polygons that are not the building
    outline (polygon area below outline_share of the footprint). pairs: group, geom_kind, poi_area_m2,
    building_id (site rows left out); footprints: area per building_id. Returns n and the cap per group."""
    p = pairs[pairs['group'].isin(groups) & pairs['geom_kind'].eq('area') & pairs['poi_area_m2'].gt(0)].copy()
    p = p[p['poi_area_m2'] / p['building_id'].map(footprints) < outline_share]
    return p.groupby('group')['poi_area_m2'].agg(n='size', cap=lambda s: s.quantile(quantile)).reindex(groups)


def point_size_cap_all(pairs, footprints, *, quantile, outline_share):
    """The default size cap: the quantile of the own POI polygons of every group that are not the
    building outline (as point_size_caps). Returns (n, cap)."""
    p = pairs[pairs['geom_kind'].eq('area') & pairs['poi_area_m2'].gt(0)]
    p = p[p['poi_area_m2'] / p['building_id'].map(footprints) < outline_share]
    return len(p), float(p['poi_area_m2'].quantile(quantile))


# --- the five labels without a zone total: visitor rates -------------------------------------------------

def sport_use_rate(use, sport_uses):
    """The sports rate id of a POI use (fitness, pool, entertainment, tennis, riding, shooting, dance,
    hall), or None."""
    for rid, uses in sport_uses.items():
        if use in uses:
            return rid
    return None


def visitor_rate_id(label, u, *, group_rates, class_rates, type_rates, default_rates, sport_uses, dance_uses, events_uses,
                    car_uses, gastro_class, hotel_classes, industry_class):
    """The rate id of one unit for one of the five labels without a zone total, and the tier that set
    it ('use', 'class', 'class (type words)', 'default' or 'zero: why').

    u: the unit (attributes group, use - its own POI's, or a building unit's only POI's, None for a
    rest unit or a building without a POI - cls, btype (the building's step-05 type), staff_only,
    leisure (the unit also carries leisure), co_school (its building carries school or university),
    plain_home, parking). The zero cases come first; then the POI's group and use, then the
    building's class (CMP: by the type words), then the label's default."""
    g = u.group if isinstance(u.group, str) else None
    use = u.use if isinstance(u.use, str) else ''
    c = u.cls
    if u.staff_only:
        return 'ZERO', 'zero: staff only'
    if label == 'business' and (g == 'hotel' or c in hotel_classes):
        return 'ZERO', 'zero: hotel'
    if label == 'errands':
        if u.parking:
            return 'E_PARKING', 'zero: parking'
        rid = group_rates['errands'].get(g)
        if g == 'small_retail':
            rid = 'E_COUNTER'
        elif g == 'big_box':
            rid = 'E_VEHICLE' if use in car_uses else 'E_COUNTER'
        elif g == 'community':
            rid = 'E_PRACTICE' if use == 'centre' else 'E_PUBOFF'
        elif g == 'culture' and use == 'library':
            rid = 'E_LIBRARY'
        if rid:
            return rid, 'use'
    if label == 'sports':
        if g in ('sport', 'unmapped', 'culture', 'small_school'):
            rid = sport_use_rate(use, sport_uses)
            if rid:
                return rid, 'use'
            if g == 'sport':
                return 'S_HALL', 'use'
        if g == 'community':
            return 'S_CLUB', 'use'
    if label == 'meetup':
        if u.plain_home:
            return 'ZERO', 'zero: plain home'
        if u.leisure and (g == 'gastronomy' or (g is None and c == gastro_class)):
            return 'ZERO', 'zero: also leisure'
        if g == 'culture' and use in events_uses:
            return 'M_EVENTS', 'use'
        rid = group_rates['meetup'].get(g)
        if rid:
            return rid, 'use'
    if label == 'lessons':
        if u.co_school:
            return 'ZERO', 'zero: school or university building'
        if g == 'industry' or c == industry_class:
            return 'ZERO', 'zero: company academy'
        if g == 'small_school':
            return ('L_DANCE' if use in dance_uses else 'L_SMALL'), 'use'
        if g in ('sport', 'unmapped'):
            rid = sport_use_rate(use, sport_uses)
            if rid:
                return rid, 'use'
            if g == 'sport':
                return 'S_HALL', 'use'
        rid = group_rates['lessons'].get(g)
        if rid:
            return rid, 'use'
    rid = class_rates[label].get(c)
    if rid == 'CMP':
        pats, fallback = type_rates[label]
        for pat, r in pats:
            if re.search(pat, u.btype or '', flags=re.IGNORECASE):
                return r, 'class (type words)'
        return fallback, 'class (type words)'
    if rid:
        return rid, 'class'
    return default_rates[label], 'default'


# --- School by type -----------------------------------------------------------------------------------

def compile_school_patterns(patterns, strip):
    """SCHOOL_TYPE_PATTERNS compiled: all without case except the secondary words of the model's English types."""
    rx = {k: re.compile(v) if k == 'secondary_type' else re.compile(v, re.IGNORECASE) for k, v in patterns.items()}
    rx['strip'] = re.compile(strip, re.IGNORECASE)
    return rx


def _school_hits(names, model_type, rx):
    """The school types that one set of texts names: German names and an English model type."""
    names = ' | '.join(x for x in names if isinstance(x, str) and x)
    model_type = model_type if isinstance(model_type, str) else ''
    both = f'{names} | {model_type}'
    hits = set()
    if rx['vocational'].search(both):
        hits.add('vocational')
    if rx['both'].search(both):
        hits |= {'primary', 'secondary'}
    if rx['primary'].search(both):
        hits.add('primary')
    if rx['secondary_name'].search(rx['strip'].sub(' ', names)) or rx['secondary_type'].search(rx['strip'].sub(' ', model_type)):
        hits.add('secondary')
    return hits


def school_types(own_names, own_type, building_names, building_type, alkis_function, *, rx, alkis_types, all_types, default_types):
    """The school types a place serves and where they come from: 'name' (a POI's own name or step-07 type), 'building' (its
    building's names - own, POI and site names - or step-05 type), 'ALKIS' (the building's function) or 'none' (the default)."""
    for hits, how in ((_school_hits(own_names, own_type, rx), 'name'), (_school_hits(building_names, building_type, rx), 'building')):
        if hits:
            return tuple(t for t in all_types if t in hits), how
    if alkis_function in alkis_types:
        return tuple(alkis_types[alkis_function]), 'ALKIS'
    return tuple(t for t in all_types if t in default_types), 'none'


def school_split(weight, types, pool, targets, all_types):
    """Each type's target of a pool over the pool's places of that type, in proportion to their weight; a pool without a place
    of a type gives that type to all its places, so the pool keeps its total. weight, types (tuples) and pool are aligned
    Series; targets has a row per pool and a column per type. Returns the value per place and type, and per place and type
    whether it came to all places that way."""
    got = pd.DataFrame(0.0, index=weight.index, columns=list(all_types))
    to_all = pd.DataFrame(False, index=weight.index, columns=list(all_types))
    p = pool.to_numpy()
    for t in all_types:
        T = pool.map(targets[t]).fillna(0.0).to_numpy(dtype=float)
        own = types.map(lambda s: t in s).to_numpy(dtype=bool)
        has = pd.Series(own, index=weight.index).groupby(p).transform('any').to_numpy(dtype=bool)
        elig = own | ~has
        w = np.where(elig, weight.to_numpy(dtype=float), 0.0)
        wsum = pd.Series(w, index=weight.index).groupby(p).transform('sum').to_numpy(dtype=float)
        got[t] = np.where((T > 0) & elig, w / np.where(wsum > 0, wsum, 1.0) * T, 0.0)
        to_all[t] = (T > 0) & ~has
    return got, to_all
