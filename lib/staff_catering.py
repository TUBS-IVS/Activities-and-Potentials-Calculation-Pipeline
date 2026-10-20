"""Step 08: staff catering - works canteens, staff cafes and snack bars on company sites, school and university Mensas and
hospital cafeterias carry none of retail_daily / retail_non_daily / leisure (notebook 08 section 4.8): their guests are the staff, pupils and students counted as Workers, School or University.

staff_catering(...) finds the units whose OWN data say they are staff catering:
  words  a POI unit's name or step-07 type, a building unit's type head, name, OSM-twin name or only POI's name, or an OSM
         amenity=canteen name a canteen, cafeteria, Mensa or staff restaurant (STAFF_CATERING_RULES['words']);
  site   an eating-use POI (or a one-POI building of an eating use) on a company site: in a building filed in a works class, or on a
         factory / works site, or on an industrial site named after a company (not an estate: Gewerbegebiet ... hold public fast food);
  never  a shop (its group is a retail group), a POI in a store-class building (a cafeteria in a shopping centre or furniture store
         is public), an allotment-garden canteen, a pizzeria, a theatre canteen or a factory-outlet cafe (public by name or type).
Each hit gets a kind: hospital, school, university or works (by its words, the building's class, ALKIS function and OSM tag).
rest_catering(...) finds the rest units whose building is staff catering by its type head or name, or holds an active staff-catering
POI unit (the rest label's evident source); only retail_daily and leisure can come from catering. The patterns and lists are
config.STAFF_CATERING_RULES.
staff_shops(...) finds the staff shops and kiosks inside a plant (STAFF_CATERING_RULES['shops']): notebook 08
treats them as staff catering.
"""
import re

import numpy as np
import pandas as pd

I = re.IGNORECASE


def _s(x):
    return x if isinstance(x, str) else ''


def company_site(pairs06, cfg):
    """building_id -> the company site it lies on (a factory / works site, or an industrial site named after a company)"""
    est = re.compile(cfg['estate_pattern'], I)
    st = pairs06[pairs06['how'].eq('site')]
    m = st['poi_use'].isin(cfg['company_site_uses']) | (st['poi_use'].isin(cfg['named_site_uses']) & st['name'].fillna('').str.strip().ne('')
                                                         & ~st['name'].fillna('').str.contains(est))
    return st[m].groupby('building_id').apply(lambda d: '; '.join(f'{u}:{n}' for u, n in zip(d['poi_use'], d['name'].fillna('')))).to_dict()


def staff_catering(uo, bld, pois, sole, poi_attrs, cfg, *, eating_uses, store_classes, head_split, pairs06=None):
    """the active units that are staff catering by their own data: DataFrame unit_id, building_id, kind, how, where, evidence"""
    words, public = re.compile(cfg['words'], I), re.compile(cfg['public'], I)
    csite = company_site(pairs06, cfg) if pairs06 is not None else {}
    b = bld.set_index('building_id')
    p = pois.set_index('poi_id')
    am = poi_attrs.set_index('poi_id')['amenity']
    head = b['llm_type'].fillna('').str.split(head_split, n=1, regex=True).str[0]
    act = uo[uo['no_unit_reason'].eq('') | (uo['restored'] if 'restored' in uo.columns else False)]
    rows = []
    for u, bid, kind in zip(act['unit_id'], act['building_id'], act['kind']):
        cls = b.at[bid, 'bosserhof_class']
        if kind == 'poi':
            g, use = p.at[u, 'group'], _s(p.at[u, 'poi_use'])
            txt = f"{_s(p.at[u, 'name'])} | {_s(p.at[u, 'poi_type'])}"
            if g in cfg['shop_groups'] or cls in store_classes or public.search(txt):
                continue
            if words.search(txt) or am.get(u) == 'canteen':
                rows.append((u, bid, kind, 'words', txt))
            elif (g == 'gastronomy' and use in eating_uses and (cls in cfg['works_classes'] or bid in csite)
                  and not public.search(_s(b.at[bid, 'llm_type']))):
                rows.append((u, bid, kind, 'site', txt + f' | {cls}' + (f' | site {csite[bid]}' if bid in csite else '')))
        elif kind == 'building':
            has = b.at[bid, 'n_pois'] == 1 and bid in sole.index
            sg, su, sn = (sole.at[bid, 'group'], _s(sole.at[bid, 'poi_use']), _s(sole.at[bid, 'name'])) if has else (None, '', '')
            txt = f"{head[bid]} | {_s(b.at[bid, 'name'])} | {_s(b.at[bid, 'osm_twin_name'])} | {sn}"
            if sg in cfg['shop_groups'] or cls in store_classes or public.search(txt + ' | ' + _s(b.at[bid, 'llm_type'])):
                continue
            if words.search(txt) or (has and am.get(sole.at[bid, 'poi_id']) == 'canteen'):
                rows.append((u, bid, kind, 'words', txt))
            elif has and sg == 'gastronomy' and su in eating_uses and (cls in cfg['works_classes'] or bid in csite):
                rows.append((u, bid, kind, 'site', txt + f' | {cls}' + (f' | site {csite[bid]}' if bid in csite else '')))
    out = pd.DataFrame(rows, columns=['unit_id', 'building_id', 'kind', 'how', 'evidence'])
    out['where'] = [where(bid, ev, b, cfg) for bid, ev in zip(out['building_id'], out['evidence'])]
    return out


def where(bid, ev, b, cfg):
    """hospital / school / university / works: by the words, then the building's class, ALKIS function and OSM tag"""
    cls, fn, tag = b.at[bid, 'bosserhof_class'], _s(b.at[bid, 'function']), _s(b.at[bid, 'osm_tag'])
    txt = ev + ' | ' + _s(b.at[bid, 'llm_type']) + ' | ' + _s(b.at[bid, 'name'])
    if re.search(cfg['kind_hospital'], txt, I) or cls in cfg['hospital_classes'] or fn in cfg['hospital_functions'] or tag in cfg['hospital_tags']:
        return 'hospital'
    if re.search(cfg['kind_school'], txt, I) or cls in cfg['school_classes'] or fn in cfg['school_functions']:
        return 'school'
    if re.search(cfg['kind_university'], txt, I) or cls in cfg['university_classes'] or fn in cfg['university_functions']:
        return 'university'
    return 'works'


def rest_catering(uo, bld, sc, cfg, *, store_classes, head_split):
    """the active rest units carrying retail_daily or leisure whose building is staff catering by its type head (or name), or holds
    an active staff-catering POI unit (the label's evident source)"""
    words, public = re.compile(cfg['words'], I), re.compile(cfg['public'], I)
    b = bld.set_index('building_id')
    head = b['llm_type'].fillna('').str.split(head_split, n=1, regex=True).str[0]
    src = sc[sc['kind'].eq('poi')].groupby('building_id')['unit_id'].agg(list)
    act = uo[(uo['no_unit_reason'].eq('') | (uo['restored'] if 'restored' in uo.columns else False)) & uo['kind'].eq('rest')
             & uo['labels'].map(lambda t: bool(set(t) & set(cfg['rest_labels'])))]
    rows = []
    for u, bid in zip(act['unit_id'], act['building_id']):
        cls = b.at[bid, 'bosserhof_class']
        txt = f"{head[bid]} | {_s(b.at[bid, 'name'])}"
        if cls in store_classes or public.search(txt):
            continue
        if words.search(txt):
            rows.append((u, bid, 'rest', 'words', txt))
        elif bid in src.index:
            rows.append((u, bid, 'rest', 'source', 'its staff-catering POI(s): ' + ', '.join(src[bid])))
    out = pd.DataFrame(rows, columns=['unit_id', 'building_id', 'kind', 'how', 'evidence'])
    out['where'] = [where(bid, ev, b, cfg) for bid, ev in zip(out['building_id'], out['evidence'])]
    return out


def staff_shops(uo, bld, pois, sole, cfg, *, store_classes, head_split, pairs06):
    """the active units that are staff shops by their own data: DataFrame unit_id, building_id, kind, how ('shop'),
    evidence, where - a POI unit of a shop group (cfg['shops']['groups']), a one-POI building unit whose POI is of such a group, or
    a building unit without a POI whose type head names a kiosk or a shop; in a building filed in a works class AND on a company
    site with a name (company_site on the named site rows); never in a store-class building, never public by its own words
    (cfg['public'] and cfg['shops']['public'] in its names, types or the building's type)"""
    scfg = cfg['shops']
    public = re.compile(cfg['public'] + '|' + scfg['public'], I)
    headp = re.compile(scfg['head_pattern'], I)
    works = set(cfg['works_classes'])
    site = company_site(pairs06[pairs06['name'].fillna('').str.strip().ne('')], cfg)
    b = bld.set_index('building_id')
    p = pois.set_index('poi_id')
    head = b['llm_type'].fillna('').str.split(head_split, n=1, regex=True).str[0]
    act = uo[uo['no_unit_reason'].eq('') | (uo['restored'] if 'restored' in uo.columns else False)]
    rows = []
    for u, bid, kind in zip(act['unit_id'], act['building_id'], act['kind']):
        cls = b.at[bid, 'bosserhof_class']
        if cls in store_classes or not (cls in works and bid in site):
            continue
        if kind == 'poi':
            ok = p.at[u, 'group'] in scfg['groups']
            txt = f"{_s(p.at[u, 'name'])} | {_s(p.at[u, 'poi_type'])}"
        elif kind == 'building':
            has = b.at[bid, 'n_pois'] == 1 and bid in sole.index
            txt = f"{head[bid]} | {_s(b.at[bid, 'name'])} | {_s(b.at[bid, 'osm_twin_name'])}" + (f" | {_s(sole.at[bid, 'name'])}" if has else '')
            ok = (sole.at[bid, 'group'] in scfg['groups']) if has else (b.at[bid, 'n_pois'] == 0 and bool(headp.search(head[bid])))
        else:
            continue
        if not ok or public.search(txt + ' | ' + _s(b.at[bid, 'llm_type'])):
            continue
        rows.append((u, bid, kind, 'shop', txt + f' | {cls} | site {site[bid]}'))
    out = pd.DataFrame(rows, columns=['unit_id', 'building_id', 'kind', 'how', 'evidence'])
    out['where'] = [where(bid, ev, b, cfg) for bid, ev in zip(out['building_id'], out['evidence'])]
    return out
