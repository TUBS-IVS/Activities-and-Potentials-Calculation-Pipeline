"""workers_headcount.py - Workers: realistic headcounts on top of the step-08 allocation.

The allocation of notebook 08 (section 6) shares each zone's VISUM Workers over the zone's units in proportion to occupied floor
x Bosserhof factor - one multiplier per zone. VISUM's Workers are a real headcount of jobs, so where a zone's total is many times
what its buildings show, every carrier is inflated alike (Peine 22 x 9.8: the Peiner Festsaele, whose operator has 34 staff
for two venues, held 1,095 under the allocation alone). Hence a rule on top of the allocation, for Workers only (config block
"STEP 08 - Workers: realistic headcounts"):

  * weight       the unit's realistic headcount ('face'): its Bosserhof value exp = O x f / 100, never above the published size of
                 its activity - the band's 'high', or its size rule where the unit's size is known (WORKERS_BANDS, WORKERS_SIZES);
  * upper limit  an establishment (a sub-type with a band) at most fixed_k x its face and never above the published maximum of its
                 type; an open-ended unit (office, administration, industry, hospital ...) at most elastic_k x exp (industrial_k for
                 industry, logistics, transport) and never above an institution maximum; a remainder unit (unmapped upper floors) of
                 a building whose own type is an establishment at most remainder_k x exp; a technical structure (below) at most
                 technical_k x its face; the units of a named institution together at most its published staff
                 (WORKERS_INSTITUTIONS), each by its share of their faces;
  * no lower limit;
  * zone fill    in every zone one level s: a_i = min(s x face_i, hi_i) with sum a = the zone's total after the allocation (what its
                 own units hold, i.e. after the zero / near-zero sharing);
  * spill        what a zone cannot hold goes to the units of the zones around it (ring 1, the touching zones, then rings 2
                 and 3; the notebook's rings) that hold less than their face, emptiest first, never above their face
                 ('level_face'); the over-full zones in the order of their surplus, the largest first; what no ring takes stays
                 on the zone's own open-ended units by weight ('forced'); the regional total stays exact. A zone whose total is
                 0 or near 0 takes part like any other: it sends what the sharing of section 6 gave it beyond what its units
                 can hold, and it receives spill;
  * no spill     two kinds of units take no spill and keep what their own zone's fill gives them (WORKERS_NO_SPILL): the
                 remainder units the remainder rule caps (the unmapped upper floors of a building whose own type is an
                 establishment) and the technical structures - units whose own texts read as a sewage plant, a biogas or
                 composting plant (a digester or fermenter outside a sewage plant), a cistern, a bunker, a greenhouse (not one
                 whose type names a garden centre or a shop), a silo or an animal shelter (technical_structures). A technical structure also holds at most its realistic headcount in its own
                 zone's fill (technical_k = 1): what its over-full zone can then no longer hold goes to the zones around it like
                 any other surplus.

Two further rules:
  * both ways    the food stores (knobs['size_rule_both_ways']: supermarket, discounter, large supermarket / hypermarket) take the
                 published size rule as their face in both directions - also above their Bosserhof value (a discounter at 0.9 per
                 100 m2 held about 10 Workers against about 18 published);
  * raise        the named institutions are raised to knobs['institution_floor_k'] x their published staff after the spill
                 (raise_institutions): the deficit comes from the units of their own zones, then of rings 1-3, that hold more
                 than their face, the fullest first, never below their face; their units then hold their published share of the
                 faces (the upper limit of each institution unit is that share, not the other caps).

The activity types (60) are read from the unit's own data in a fixed order of evidence (WORKERS_ACTIVITY_*): a remainder is a
remainder; an asked POI by its OSM use, else its step-07 type, name, class; a building unit by the head of its step-05 type,
its name, a specific Bosserhof class, the full type text, the class - with keyword tiers (a specific use noun beats a generic
noun beats a brand). A conference or seminar centre is an event venue, also in an office class; only the buildings of the two
company campuses on VW sites (company_campus_ids) are business services. The tables (activity types, bands, band
allocation) live in config.py. Pure functions of the notebook's tables: nothing is read or written here. The unit ids the tables name (WORKERS_INSTITUTIONS, WORKERS_SIZES known)
must all be Workers units and the company campuses buildings with a Workers unit, else apply() stops.

    res = workers_headcount.apply(units, uo, bld, pois, zones, NEIGHBOURS, zone_id_col=ZONE_ID_COL, knobs=WORKERS_HEADCOUNT,
                                  activity=dict(groups=WORKERS_ACTIVITY_GROUPS, keywords=WORKERS_ACTIVITY_KEYWORDS,
                                                poi_uses=WORKERS_ACTIVITY_POI_USES, shop_uses=WORKERS_ACTIVITY_SHOP_USES,
                                                classes=WORKERS_ACTIVITY_CLASSES, rules=WORKERS_ACTIVITY_RULES),
                                  bands=WORKERS_BANDS, subtypes=WORKERS_SUBTYPES, sizes=WORKERS_SIZES, institutions=WORKERS_INSTITUTIONS,
                                  no_spill=WORKERS_NO_SPILL)
    res['W']['after']   the new Workers value of every Workers row of `units` (index of `units`)
    workers_headcount.verify(res)       the rule's invariants (raises AssertionError)
    workers_headcount.report(res, zones) the diagnostics as numbers and tables
"""
import functools
import json
import re

import numpy as np
import pandas as pd

FIXED, ELASTIC = 'fixed', 'elastic'
SPILLS = ('level_face', 'level', 'weight')
TEXT_FIELDS = ('t', 'nm', 'site', 'llm', 'pu', 'bc')
CONDITIONS = ('O', 'kind', 'not_kind', 'poi_use', 'match', 'not', 'any')
BAND_FIELDS = {'name', 'typ', 'hi', 'mx', 'basis', 'size', 'est', 'status', 'src', 'year', 'url'}
FOOD_TYPES = ('supermarket', 'kiosk', 'discounter', 'large supermarket / hypermarket')
# the activity types the order of evidence itself names (they must be in WORKERS_ACTIVITY_GROUPS)
NAMED_TYPES = FOOD_TYPES + ('remainder', 'unknown', 'other shop', 'office', 'bank branch', 'small customer service', 'post office',
                            'warehouse / logistics / yard', 'doctor / dental / therapy practice', 'hospital', 'event venue / city hall',
                            'business services', 'restaurant', 'cafe', 'fast food', 'social facility',
                            'mixed-use residential with services', 'residential (no evidence)', 'hotel')


# --- 0. the Workers units and what the rules read ---------------------------------------------------------------------
def _brand(tags):
    """'brand operator' of a POI's OSM tags (a JSON text)"""
    try:
        j = json.loads(tags) if isinstance(tags, str) and tags.startswith('{') else {}
    except Exception:
        j = {}
    return ' '.join(str(j.get(k, '')) for k in ('brand', 'operator') if j.get(k))


def workers_table(units, uo, bld, pois, zones, zone_id_col='NO'):
    """One row per Workers row of `units` (same index) with what the activity types and bands read: the unit's O, f, floor family
    and unit rule (uo), its building's name, step-05 type and classes (bld), for a POI unit its asked POI (name, class, step-07
    type, OSM use, brand / operator; pois - a building unit whose id equals a POI's, e.g. an OSM building way that is also a
    dropped non-occupant POI, reads none of it) and its building's POI names, its zone number and its Bosserhof value
    exp = weight / 100"""
    w = units.loc[units['category'] == 'Workers', ['building_id', 'unit_id', 'kind', 'weight', 'zone_idx', 'assigned']].copy()
    if w['unit_id'].duplicated().any() or uo['unit_id'].duplicated().any():
        raise AssertionError('a Workers unit id occurs twice in units or uo')
    w = w.join(uo.set_index('unit_id')[['O', 'f', 'family', 'unit_rule']], on='unit_id')
    if w['O'].isna().any():
        raise AssertionError('a Workers unit without its row in uo')
    b = bld.set_index('building_id')
    w = w.join(b[['name', 'llm_type', 'bosserhof_class', 'class_06']], on='building_id')
    p = pois.set_index('poi_id')
    is_poi = w['kind'].eq('poi')
    for c, s in (('poi_name', 'name'), ('poi_class', 'poi_class'), ('poi_type', 'poi_type'), ('poi_use', 'poi_use')):
        w[c] = w['unit_id'].map(p[s]).where(is_poi)
    w['zone_no'] = w['zone_idx'].map(zones[zone_id_col])
    w['exp'] = w['weight'] / 100.0
    w['brand'] = w['unit_id'].map(p['tags']).where(is_poi).map(_brand).fillna('')
    w['poi_names_b'] = w['building_id'].map(b['poi_names']).fillna('')
    return w


# --- 1. the activity types (WORKERS_ACTIVITY_*): order of evidence and keyword tiers ----------------------------------
class _Activity:
    """the compiled activity-type rules"""

    def __init__(self, groups, keywords, poi_uses, shop_uses, classes, rules):
        self.groups, self.poi_uses, self.shop_uses, self.classes, self.r = groups, poi_uses, set(shop_uses), classes, rules
        self.rx = [(t, tier, re.compile(p)) for t, tier, p in keywords]
        self.order = {}
        for i, (t, tier, _) in enumerate(keywords):
            self.order.setdefault((t, tier), i)
        self.head_split = re.compile(rules['head_split'])
        self.grammar = re.compile(rules['grammar_school'])
        self.prefer = {k: set(v) for k, v in rules['prefer_classes'].items()}
        self.inst = set(rules['prefer_types'])
        self.c = {k: re.compile(rules[k]) for k in ('canteen', 'on_premises', 'residential', 'mixed', 'business', 'discount_chain',
                                                     'hyper_chain', 'full_range', 'food_text', 'post_logistics', 'bank_office',
                                                     'conference_centre', 'greenhouse_shop')}
        self.campus = set(rules['company_campus_ids'])
        self.hits = functools.lru_cache(maxsize=None)(self._hits)     # many units share a type text: scan each text once
        used = ({t for t, _, _ in keywords} | {v for v in poi_uses.values() if v is not None} | set(classes.values())
                | set(rules['canteen_of_class'].values()) | set(rules['prefer_types']) | {t for v in rules['prefer_classes'].values() for t in v}
                | set(NAMED_TYPES))
        if used - set(groups):
            raise ValueError(f'activity types without a group in WORKERS_ACTIVITY_GROUPS: {sorted(used - set(groups))}')

    def norm(self, s):
        """lower case; the German school word 'Gymnasium' (capital G or in a compound) becomes 'grammarschool' first"""
        if not isinstance(s, str) or not s:
            return ''
        return self.grammar.sub('grammarschool', s).lower()

    def _hits(self, text):
        """every keyword hit (start, end, tier, order, type, matched); a hit inside a longer hit of any type is dropped"""
        out = []
        for t, tier, rx in self.rx:
            for m in rx.finditer(text):
                if m.end() > m.start():
                    out.append((m.start(), m.end(), tier, self.order[(t, tier)], t, m.group(0)))
        return tuple(h for h in out if not any((o[0] <= h[0] and h[1] <= o[1]) and (o[1] - o[0]) > (h[1] - h[0]) for o in out))

    def best(self, text, max_tier=3, prefer=None):
        """(type, matched, tier) of the first hit of the best tier present; a hit of the type the Bosserhof class stands for wins
        within that tier where the hits are generic (tier 2 or 3) or the class is an institution's"""
        if not text:
            return None, None, None
        hs = [h for h in self.hits(text) if h[2] <= max_tier]
        if not hs:
            return None, None, None
        tmin = min(h[2] for h in hs)
        top = [x for x in hs if x[2] == tmin]
        if prefer:
            pr = {prefer} if isinstance(prefer, str) else set(prefer)
            if (tmin >= 2 or pr & self.inst) and any(x[4] in pr for x in top):
                top = [x for x in top if x[4] in pr]
        h = min(top, key=lambda x: (x[0], -(x[1] - x[0]), x[3]))
        return h[4], h[5], h[2]

    def head(self, s):
        return self.head_split.split(s, maxsplit=1)[0].strip() if s else ''

    def food(self, t, rule, name_txt, all_txt, O, cls):
        """discounter / supermarket / large supermarket by chain, class and size"""
        c = self.c
        if c['discount_chain'].search(name_txt):
            return 'discounter', rule + '; discount chain'
        if c['hyper_chain'].search(name_txt) or (cls == self.r['hypermarket_class'] and t != 'kiosk'):
            return 'large supermarket / hypermarket', rule + '; hypermarket chain or class'
        if t == 'supermarket' and O >= self.r['large_food_min_m2'] and c['full_range'].search(all_txt):
            return 'large supermarket / hypermarket', rule + f"; full-range supermarket with O >= {self.r['large_food_min_m2']} m2"
        if t == 'discounter' and not c['discount_chain'].search(all_txt) and not c['food_text'].search(all_txt):
            return 'other shop', rule + '; non-food discount'
        return t, rule

    def too_big(self, t, rule, O, cls, txt, bid):
        """fixed types too big for one establishment of the kind, or standing in an institution (bid: the unit's building)"""
        tb = self.r['too_big_m2']
        if t == 'bank branch' and O > tb['bank branch']:
            return 'office', rule + f"; bank building > {tb['bank branch']} m2: office"
        if t == 'small customer service' and O > tb['small customer service']:
            return 'office', rule + f"; > {tb['small customer service']} m2: office"
        if t == 'post office' and self.c['post_logistics'].search(txt):
            return 'warehouse / logistics / yard', rule + '; post logistics'
        if t == 'post office' and O > tb['post office']:
            return 'office', rule + f"; post building > {tb['post office']} m2: office"
        if t == 'doctor / dental / therapy practice' and cls == self.r['hospital_class']:
            return 'hospital', rule + '; in a hospital building'
        if t == 'event venue / city hall' and cls in self.r['office_classes']:
            if bid in self.campus:
                return 'business services', rule + '; a company campus on a VW site (company_campus_ids)'
            if self.c['conference_centre'].search(txt):
                return t, rule + '; conference / seminar centre: an event venue in an office class too'
            return 'business services', rule + '; conference / fair centre of an office class'
        if t in ('restaurant', 'cafe', 'fast food') and self.c['canteen'].search(txt) and cls in self.r['canteen_of_class']:
            return self.r['canteen_of_class'][cls], rule + f'; canteen of a {cls} building'
        return t, rule

    def row(self, r):
        """-> (activity type, the rule that decided)"""
        kind = r['kind']
        if kind == 'remainder':
            return 'remainder', 'kind remainder'
        cls = r['bosserhof_class'] if isinstance(r['bosserhof_class'], str) else ''
        L, N = self.norm(r['llm_type']), self.norm(r['name'])
        O = float(r['O'])
        if kind == 'poi':
            use = r['poi_use'] if isinstance(r['poi_use'], str) else ''
            PT, PN, BR = self.norm(r['poi_type']), self.norm(r['poi_name']), self.norm(r['brand'])
            pcls = r['poi_class'] if isinstance(r['poi_class'], str) else ''
            t = self.poi_uses.get(use, 'other shop' if use in self.shop_uses else None)
            rule = f'poi_use {use}'
            if t is None:
                pref = self.prefer.get(pcls, self.classes.get(pcls))
                for src, txt, mt in (('poi_type head', self.head(PT), 3), ('poi_name', PN, 2), ('poi_type', PT, 1),
                                     ('poi_use text', self.norm(use.replace('_', ' ')), 2)):
                    t, m, _ = self.best(txt, mt, pref)
                    if t:
                        rule = f"{src} '{m}'"
                        break
            if t is None and use == 'social_facility':
                t, rule = 'social facility', 'poi_use social_facility'
            if t is None and pcls:
                t, rule = self.classes.get(pcls), f'poi_class {pcls}'
            if t is None:
                t, rule = 'unknown', 'poi: nothing matched'
            if t in FOOD_TYPES:
                t, rule = self.food(t, rule, ' '.join([PN, BR]) if t != 'kiosk' else PN, ' '.join([PN, BR, PT]), O, pcls)
            return self.too_big(t, rule, O, pcls, ' '.join([PT, PN]), r['building_id'])
        # building units
        rule_u = r['unit_rule'] if isinstance(r['unit_rule'], str) else ''
        H = self.head(L)
        pref = self.prefer.get(cls, self.classes.get(cls))
        t, m, _ = self.best(H, 3, pref)
        src = 'llm_type head'
        if t is None:
            t, m, _ = self.best(N, 2, pref)
            src = 'building name'
        if t is None and cls in self.r['specific_classes']:
            t, m, src = self.classes[cls], cls, 'specific class'
        if t is None:
            t, m, _ = self.best(L, 1, pref)
            src = 'llm_type'
        c = self.c
        resid_rule = rule_u.startswith(self.r['no_evidence_rule']) or self.r['plain_home_rule'] in rule_u
        if c['mixed'].search(L) and c['residential'].search(L) and c['business'].search(L) and (
                t is None or src != 'llm_type head' or c['mixed'].search(H)):
            return 'mixed-use residential with services', f'mixed residential text ({src} gave {t})'
        if resid_rule:
            if self.r['labels_kept_rule'] in rule_u or (c['mixed'].search(L) and c['business'].search(L)):
                return 'mixed-use residential with services', 'no-evidence residential with business sign'
            if t is None or c['residential'].search(H) or src != 'llm_type head':
                return 'residential (no evidence)', f'unit rule: {rule_u[:40]}'
        if t is None and c['residential'].search(L) and not c['business'].search(L):
            return 'residential (no evidence)', 'residential type text'
        if t is None:
            t, m, src = self.classes.get(cls, 'unknown'), cls, 'class fallback'
        rule = f"{src} '{m}'"
        if t in FOOD_TYPES:
            t, rule = self.food(t, rule, ' '.join([N, H]), ' '.join([N, L, self.norm(r['poi_names_b'])]), O, cls)
        # a fixed use on industrial premises in an industrial class: the building is part of the works
        if self.groups.get(t) == FIXED and cls in self.r['industrial_classes'] and (c['on_premises'].search(L)
                                                                                      or O > self.r['works_min_m2']):
            t, rule = self.classes[cls], rule + f'; on industrial premises ({cls})'
        if t == 'office' and O <= self.r['bank_office_max_m2'] and c['bank_office'].search(L):
            t, rule = 'bank branch', rule + f"; bank office <= {self.r['bank_office_max_m2']} m2"
        if t == 'agriculture' and c['greenhouse_shop'].search(L):      # a greenhouse that sells: the garden centre
            t, rule = 'garden centre', rule + '; a greenhouse whose type names a garden centre or a shop'
        return self.too_big(t, rule, O, cls, L, r['building_id'])


def activity_types(W, groups, keywords, poi_uses, shop_uses, classes, rules, act=None):
    """atype, atype_rule, agroup per unit; building_atype = the unit's building read as a building unit (a POI or remainder unit
    read with its building's name and type; for a remainder the type of the building whose upper floors it is). act: the
    compiled rules (_Activity) where the caller has them already"""
    A = act if act is not None else _Activity(groups, keywords, poi_uses, shop_uses, classes, rules)

    def run(df):
        if not len(df):
            return pd.DataFrame({'atype': pd.Series(dtype=object), 'atype_rule': pd.Series(dtype=object)}, index=df.index)
        out = pd.DataFrame([A.row(r) for r in df.to_dict('records')], index=df.index, columns=['atype', 'atype_rule'])
        return out
    cl = run(W)
    cl['agroup'] = cl['atype'].map(groups)
    if cl['agroup'].isna().any():
        raise ValueError(f"activity types without a group: {sorted(cl.loc[cl['agroup'].isna(), 'atype'].unique())}")
    xb = W[W['kind'] != 'building'].copy()
    xb['kind'] = 'building'
    cb = run(xb)
    cl['building_atype'] = cl['atype'].where(W['kind'] == 'building', cb['atype'].reindex(W.index))
    return cl


# --- 2. sub-types, sizes, the realistic headcount (face), the published maximum (cap_hi) ------------------------------
def _num(v):
    m = re.match(r'\s*(\d+(?:[.,]\d+)?)', str(v))
    return float(m.group(1).replace(',', '.')) if m else np.nan


def _tags(t):
    if isinstance(t, dict):
        return t
    try:
        return json.loads(t)
    except Exception:
        return {}


def size_inputs(pois, bld):
    """per asked POI: its own outline area and its OSM rooms / beds / capacity / screen / stars; per building: its footprint"""
    P = pd.DataFrame(pois.drop(columns='geometry', errors='ignore'))
    tg = P['tags'].map(_tags)
    poi = pd.DataFrame({
        'own_area': np.where(P['geom_kind'].eq('area'), P['poi_area_m2'].astype(float), np.nan),
        'rooms': tg.map(lambda g: _num(g.get('rooms')) if 'rooms' in g else np.nan).to_numpy(float),
        'beds': tg.map(lambda g: _num(g.get('beds')) if 'beds' in g else np.nan).to_numpy(float),
        'capacity': tg.map(lambda g: _num(g.get('capacity')) if 'capacity' in g else np.nan).to_numpy(float),
        'screens': tg.map(lambda g: _num(g.get('screen')) if 'screen' in g else np.nan).to_numpy(float),
        'stars': tg.map(lambda g: _num(g.get('stars')) if 'stars' in g else np.nan).to_numpy(float),
    }, index=P['poi_id'].values)
    poi.loc[poi['own_area'] <= 0, 'own_area'] = np.nan
    B = pd.DataFrame(bld.drop(columns='geometry', errors='ignore'))
    return dict(poi=poi, bld=pd.DataFrame({'footprint': B['area_m2'].astype(float).values}, index=B['building_id'].values))


def _pattern(p):
    return '|'.join(p) if isinstance(p, (tuple, list)) else p


def _cond(cond, ctx, kind):
    """a sub-type rule's condition: every key must hold; 'any' holds where one of its conditions does"""
    ok = np.ones(len(kind), bool)
    for k, v in cond.items():
        if k == 'O':
            op, x = v
            O = ctx['O'].to_numpy(float)
            ok &= {'<': O < x, '<=': O <= x, '>': O > x, '>=': O >= x}[op]
        elif k == 'kind':
            ok &= (kind == v)
        elif k == 'not_kind':
            ok &= (kind != v)
        elif k == 'poi_use':
            ok &= ctx['pu'].isin(list(v)).to_numpy()
        elif k == 'match':
            ok &= ctx[v[0]].str.contains(v[1], regex=True).to_numpy()
        elif k == 'not':
            ok &= ~ctx[v[0]].str.contains(v[1], regex=True).to_numpy()
        elif k == 'any':
            a = np.zeros(len(kind), bool)
            for c in v:
                a |= _cond(c, ctx, kind)
            ok &= a
        else:
            raise ValueError(f'unknown condition {k!r}')
    return ok


def assign_subtypes(W, at, subtypes):
    """the sub-type (band key) of every unit: the first rule of its activity type that matches, else the type's default; then the
    fixed retail / craft units that are really production or storage, and the single-firm POIs of business-services buildings"""
    poi = W['kind'].eq('poi')
    t_poi = (W['poi_use'].fillna('') + ' | ' + W['poi_name'].fillna('') + ' | ' + W['poi_type'].fillna(''))
    t_bld = (W['name'].fillna('') + ' | ' + W['llm_type'].fillna(''))
    ctx = dict(t=t_poi.where(poi, t_bld).str.lower(), nm=W['poi_name'].fillna('').where(poi, W['name'].fillna('')).str.lower(),
               site=(W['name'].fillna('') + ' | ' + W['llm_type'].fillna('')).str.lower(), llm=W['llm_type'].fillna('').str.lower(),
               pu=W['poi_use'].fillna('').str.lower(), O=W['O'].astype(float), bc=W['bosserhof_class'].fillna('').str.lower())
    kind = W['kind'].to_numpy()
    atype = at['atype']
    sub = pd.Series(None, index=W.index, dtype=object)
    for a in atype.unique():
        m = (atype == a).to_numpy()
        for key, pat, cond, field in subtypes['rules'].get(a, []):
            mm = m & sub.isna().to_numpy()
            if not mm.any():
                break
            if pat is not None:
                mm &= ctx[field].str.contains(_pattern(pat), case=False, regex=True).to_numpy()
            if cond is not None:
                mm &= _cond(cond, ctx, kind)
            sub[mm] = key
        sub[m & sub.isna().to_numpy()] = subtypes['default'][a]
    wk = subtypes['works']
    works = (atype.isin(list(wk['types'])) & (ctx['O'] > wk['min_m2'])
             & (ctx['t'].str.contains(wk['text'], case=False, regex=True) | ctx['bc'].str.contains(wk['classes'], case=False, regex=True)))
    sub[works] = 'works_part'
    bp = subtypes['business_poi']
    for key, pat in bp['subtypes']:
        sub[(atype == bp['type']) & W['kind'].eq('poi') & ctx['pu'].str.contains(pat, regex=True)] = key
    return sub


def _sizes(W, at, sub, aux, bands, sizes):
    """size values per unit (NaN where unknown): the store's own gross area and sales area, rooms, beds, places, pupils, seats,
    screens, stars, and where a size comes from (the POI's own outline and OSM tags only for a POI unit)"""
    poi = aux['poi'].reindex(W['unit_id'].values)
    poi.loc[~W['kind'].eq('poi').to_numpy(), :] = np.nan
    bld = aux['bld'].reindex(W['building_id'].values)
    O = W['O'].astype(float).to_numpy()
    out = pd.DataFrame(index=W.index)
    own = poi['own_area'].to_numpy(float)
    foot = bld['footprint'].to_numpy(float)
    fmt = sub.map(lambda k: (bands[k]['size'] or {}).get('fmt_max', np.nan)).to_numpy(float)
    gfa = np.fmin(O, np.where(np.isfinite(own), own, np.inf))       # a food store's own gross area, never the whole building
    gfa = np.fmin(gfa, np.where(np.isfinite(foot) & (foot > 0), foot, np.inf))
    gfa = np.fmin(gfa, np.where(np.isfinite(fmt), fmt, np.inf))
    out['store_gfa_m2'] = gfa
    out['sales_m2'] = sizes['sales_share'] * gfa
    for c in ['rooms', 'beds', 'screens', 'stars']:
        out[c] = poi[c].to_numpy(float)
    cap = poi['capacity'].to_numpy(float)
    out['places'] = np.where(at['atype'].isin(list(sizes['places_types'])).to_numpy(), cap, np.nan)
    out['pupils'] = np.where(at['atype'].isin(list(sizes['pupils_types'])).to_numpy(), cap, np.nan)
    out['seats'] = np.nan
    out['size_src'] = ''
    uid = W['unit_id'].to_numpy()
    for u, kv in sizes['known'].items():
        for i in np.flatnonzero(uid == u):
            for k, v in kv.items():
                if k != 'src':
                    out.iat[i, out.columns.get_loc(k)] = v
            out.iat[i, out.columns.get_loc('size_src')] = kv['src']
    osm = (np.isfinite(out['rooms'].to_numpy()) | np.isfinite(out['beds'].to_numpy()) | np.isfinite(out['places'].to_numpy())
           | np.isfinite(out['pupils'].to_numpy()) | np.isfinite(out['screens'].to_numpy()))
    out.loc[osm & (out['size_src'] == ''), 'size_src'] = 'OSM capacity tag of the POI'
    return out


def norm_class(c):
    """a Bosserhof class as the FGSV tables key it (lower case, letters only; the industrial 'others')"""
    c = re.sub(r'[^a-z]+', ' ', str(c).lower()).strip()
    return {'others': 'others industrial'}.get(c, c)


def headcount_bands(W, at, bands, subtypes, sizes, aux, both_ways=()):
    """per unit: face (the realistic headcount), cap_hi (the largest plausible headcount), sub, agroup_eff ('fixed' where an
    establishment band applies) and the band values. face = min(exp, X): X is the size-rule value (bounded by the type max) where
    the type has a size rule and the unit's size is known, else the type's 'high'; an open-ended unit keeps face = exp. An
    establishment of an activity type in both_ways with a size rule and a known size takes X itself, above exp too. cap_hi:
    the type max, size-scaled where a size rule applies (min(max, max(high, rate_hi x size))); an open-ended institution
    min(institution max, density x O) with the density never below the FGSV upper density of the unit's class; never below face"""
    sub = assign_subtypes(W, at, subtypes)
    sz = _sizes(W, at, sub, aux, bands, sizes)
    sub[(at['atype'] == 'hotel') & (sz['stars'].to_numpy() >= sizes['luxury_min_stars'])] = sizes['luxury_hotel']
    cv = sizes['convenience']      # a full-range 'supermarket' whose own store is under the convenience size is a convenience store
    sub[(sub == cv['from']) & (sz['sales_m2'] < cv['max_sales_m2']) & ~W['unit_id'].isin(list(sizes['known']))] = cv['to']
    sz = _sizes(W, at, sub, aux, bands, sizes)

    n = len(W)
    exp = W['exp'].to_numpy(float)
    O = W['O'].astype(float).to_numpy()
    cls_hi = W['bosserhof_class'].map(norm_class).map(sizes['fgsv_high']).astype(float).to_numpy()
    subs = sub.to_numpy()
    typ, hi, mx = (np.full(n, np.nan) for _ in range(3))
    est = np.zeros(n, bool)
    ref, cap_size, size_val = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    size_var, how = np.full(n, '', dtype=object), np.full(n, '', dtype=object)
    for k in pd.unique(subs):
        e = bands[k]
        ii = np.flatnonzero(subs == k)
        for arr, key in ((typ, 'typ'), (hi, 'hi'), (mx, 'mx')):
            arr[ii] = np.nan if e[key] is None else e[key]
        est[ii] = e['est']
        how[ii] = "band 'high'" if e['est'] else 'exp (open-ended)'
        s = e['size']
        if not s:
            continue
        for i in ii:
            val, rate, rate_hi, var = np.nan, np.nan, np.nan, ''
            v = s['var']
            if v == 'sales_m2':
                val, var, rate, rate_hi = sz['sales_m2'].iat[i], 'sales_m2', s['rate'] / 100, s['rate_hi'] / 100
            elif v == 'O':
                val, var, rate, rate_hi = O[i], 'O_m2', s['rate'] / 100, s['rate_hi'] / 100
            elif v == 'rooms_or_O':
                if np.isfinite(sz['rooms'].iat[i]) and sz['rooms'].iat[i] >= 3:
                    val, var, rate, rate_hi = sz['rooms'].iat[i], 'rooms', s['rate_room'], s['rate_room_hi']
                elif 'rate_bed' in s and np.isfinite(sz['beds'].iat[i]):
                    val, var, rate, rate_hi = sz['beds'].iat[i], 'beds', s['rate_bed'], s['rate_bed_hi']
                else:
                    val, var, rate, rate_hi = O[i], 'O_m2', s['rate'] / 100, s['rate_hi'] / 100
            elif v in ('places_or_O', 'pupils_or_O'):
                item = 'places' if v == 'places_or_O' else 'pupils'
                if np.isfinite(sz[item].iat[i]) and sz[item].iat[i] > 0:
                    val, var, rate, rate_hi = sz[item].iat[i], item, s['rate_item'], s['rate_item_hi']
                else:
                    val, var, rate, rate_hi = O[i], 'O_m2', s['rate'] / 100, s['rate_hi'] / 100
            elif v in ('seats', 'screens'):
                if np.isfinite(sz[v].iat[i]):
                    val, var, rate, rate_hi = sz[v].iat[i], v, s['rate_item'], s['rate_item_hi']
            if var and np.isfinite(val):
                if not e['est'] and var == 'O_m2' and np.isfinite(cls_hi[i]):
                    rate_hi = max(rate_hi, cls_hi[i] / 100)      # an open-ended institution: never below the FGSV upper density of its class
                size_var[i], size_val[i] = var, val
                ref[i], cap_size[i] = rate * val, rate_hi * val
                how[i] = f"size rule {rate * (100 if var.endswith('m2') else 1):g} {'per 100 m2 ' if var.endswith('m2') else 'x '}{var}"
    has_size = np.isfinite(ref)
    mxf = np.where(np.isfinite(mx), mx, np.inf)
    hif = np.where(np.isfinite(hi), hi, 0.0)
    X = np.where(est, np.where(has_size, np.fmin(ref, mxf), hif), np.inf)       # what the realistic headcount is bounded by
    face = np.fmin(exp, np.maximum(X, 0.0))
    bw = est & has_size & at['atype'].isin(list(both_ways)).to_numpy()      # the size rule both ways
    face = np.where(bw, np.maximum(X, 0.0), face)
    how = np.where(bw, how + ' (both ways)', how)
    cap = np.where(est, np.where(has_size, np.fmin(mxf, np.fmax(hif, cap_size)), mxf), np.where(has_size, np.fmin(mxf, cap_size), mxf))
    cap = np.fmax(np.where(np.isfinite(cap), cap, np.inf), face)
    return pd.DataFrame({'sub': subs, 'face': face, 'cap_hi': cap, 'agroup_eff': np.where(est, FIXED, ELASTIC), 'x': X, 'how': how,
                         'size_var': size_var, 'size_val': size_val, 'typ': typ, 'hi_pub': hi, 'mx': mx,
                         'size_src': sz['size_src'].to_numpy()}, index=W.index)


# --- 3. the band of every unit: weight and upper limit (WORKERS_HEADCOUNT, WORKERS_INSTITUTIONS) ----------------------
def unit_bands(U, knobs, institutions, groups, technical=None):
    """w = face; lo = 0; hi = the upper limits of the rule, for the zone-owned units U (with the columns of
    headcount_bands and activity_types). technical: the technical structures among U (one flag per unit; technical_structures),
    at most knobs['technical_k'] x their face (None: no limit of their own)"""
    exp = U['exp'].to_numpy(float)
    face = U['face'].to_numpy(float)
    cap = U['cap_hi'].to_numpy(float)
    fixed = (U['agroup_eff'] == FIXED).to_numpy()
    lo = np.zeros(len(U))
    hi = np.empty(len(U))
    hi[fixed] = np.minimum(cap[fixed], knobs['fixed_k'] * face[fixed])
    ke = np.full(len(U), float(knobs['elastic_k']))
    ke[U['atype'].isin(list(knobs['industrial_types'])).to_numpy()] = float(knobs['industrial_k'])
    hi[~fixed] = np.minimum(ke[~fixed] * exp[~fixed], cap[~fixed])
    hi = np.maximum(hi, lo)
    # the unmapped upper floors of a building whose own type is an establishment
    rem = (U['kind'] == 'remainder').to_numpy() & ~U['building_atype'].map(groups).eq(ELASTIC).to_numpy()
    hi = np.where(rem, np.minimum(hi, knobs['remainder_k'] * exp), hi)
    # the technical structures (WORKERS_NO_SPILL): at most technical_k x their realistic headcount
    tk = knobs['technical_k']
    tech = np.zeros(len(U), bool) if technical is None or tk is None else np.asarray(technical, bool)
    if len(tech) != len(U):
        raise ValueError('technical must hold one flag per unit')
    if tech.any():
        hi = np.where(tech, np.minimum(hi, tk * face), hi)
    # the named institutions: their units together at most the published staff, each at most its share of their faces; where
    # they are raised to their published staff (institution_floor_k) that share is the upper limit itself - the
    # published staff is a real headcount, so the other caps do not hold it down
    pos = pd.Series(np.arange(len(U)), index=U['unit_id'].to_numpy())
    raise_k = knobs.get('institution_floor_k')
    inst_rows, missing = {}, {}
    for name, e in institutions.items():
        ids = [u for u in e['unit_ids'] if u in pos.index]
        missing[name] = [u for u in e['unit_ids'] if u not in pos.index]
        ii = pos[ids].to_numpy(int) if ids else np.array([], int)
        inst_rows[name] = ii
        fs = face[ii].sum() if len(ii) else 0.0
        if fs > 0:
            share = face[ii] * e['published'] / fs
            hi[ii] = share if raise_k else np.minimum(hi[ii], share)
    hi = np.maximum(hi, lo)
    return dict(w=face.copy(), lo=lo, hi=hi, fixed=fixed, elastic=~fixed, remainder_capped=rem, technical_capped=tech,
                inst_rows=inst_rows, inst_missing=missing)


def technical_structures(U, words, A, exceptions=None):
    """per unit the first group of `words` (WORKERS_NO_SPILL 'technical': group -> regex) that its own texts read as, '' where
    none. Its own texts: a building or remainder unit its building's step-05 type and name, an asked POI its step-07 type and its
    name. A group's words count in the head of the type; in the whole type where that head names nothing the activity types know
    (a bare 'building', 'part' ...: the order of evidence of the activity types, A: the compiled activity rules); and in the name
    only where the whole type carries a word of the same group too or the head names nothing (a factory whose ALKIS
    name is 'Silos' is no silo, a cistern typed 'storage facility (cistern)' is one). exceptions (WORKERS_NO_SPILL
    'technical_except': group -> regex): a unit whose whole type matches is not of that group (a greenhouse whose type
    names a garden centre or a shop is the garden centre or the shop)"""
    exc = exceptions or {}
    rx = [(k, re.compile(p), re.compile(exc[k]) if k in exc else None) for k, p in words.items()]
    isp = U['kind'].eq('poi').to_numpy()
    typ = np.where(isp, U['poi_type'].fillna('').to_numpy(object), U['llm_type'].fillna('').to_numpy(object))
    nam = np.where(isp, U['poi_name'].fillna('').to_numpy(object), U['name'].fillna('').to_numpy(object))
    seen, out = {}, []
    for t, n in zip(typ, nam):
        if (t, n) not in seen:
            tt, nn = A.norm(t), A.norm(n)
            h = A.head(tt)
            blank = A.best(h, 3)[0] is None              # the head names nothing the activity types know
            g = ''
            for k, r, x in rx:
                in_type = r.search(tt) is not None
                if ((r.search(h) or (blank and in_type) or ((in_type or blank) and r.search(nn)))
                        and not (x is not None and x.search(tt))):
                    g = k
                    break
            seen[(t, n)] = g
        out.append(seen[(t, n)])
    return pd.Series(out, index=U.index, dtype=object)


# --- 4. the zone fill and the spill (exact band solve) ----------------------------------------------------------------
def band_solve(w, lo, hi, T):
    """a = clip(s x w, lo, hi) with sum a = T. Returns (a, s, surplus, mode); mode 'floors_scaled' (T <= sum lo: a = lo x T / sum lo),
    'full' (T >= sum hi: a = hi, surplus = T - sum hi) or 'band'. Exact: a piecewise-linear sweep over the breakpoints lo/w, hi/w;
    a unit without weight stays at its lower limit"""
    w = np.asarray(w, float)
    lo = np.asarray(lo, float)
    hi = np.asarray(hi, float)
    if not (lo <= hi + 1e-9).all():
        raise AssertionError('lo > hi')
    pos = w > 0
    hi = np.where(pos, hi, lo)
    slo = lo.sum()
    shi = hi.sum()
    if T <= slo + 1e-12:
        if slo > 0:
            return lo * (max(T, 0.0) / slo), 0.0, 0.0, 'floors_scaled'
        return np.zeros_like(w), 0.0, 0.0, 'floors_scaled'
    if T >= shi - 1e-12:
        return hi.copy(), np.inf, max(T - shi, 0.0), 'full'
    s_lo = lo[pos] / w[pos]
    s_hi = hi[pos] / w[pos]
    ev_s = np.concatenate([s_lo, s_hi])
    ev_ds = np.concatenate([w[pos], -w[pos]])
    ev_dc = np.concatenate([-lo[pos], hi[pos]])
    fin = np.isfinite(ev_s)
    ev_s, ev_ds, ev_dc = ev_s[fin], ev_ds[fin], ev_dc[fin]
    o = np.argsort(ev_s, kind='mergesort')
    ev_s = ev_s[o]
    slope = np.cumsum(ev_ds[o])
    const = slo + np.cumsum(ev_dc[o])
    g = const + slope * ev_s
    j = int(np.searchsorted(g, T, side='left'))
    if j == 0:
        s = ev_s[0]
    else:
        sl = slope[j - 1]
        s = (T - const[j - 1]) / sl if sl > 0 else ev_s[j - 1]
    a = np.clip(s * w, lo, hi)
    a[~pos] = lo[~pos]
    r = T - a.sum()                     # exactness: the float residual onto the free units
    free = pos & (a > lo + 1e-12) & (a < hi - 1e-12)
    if abs(r) > 0 and free.any():
        a[free] += r * w[free] / w[free].sum()
    return a, float(s), 0.0, 'band'


def fill_and_spill(zone, w, lo, hi, elastic, T, neighbours, max_ring=3, spill='level_face', no_spill=None):
    """the zone fill, the spill to the rings of touching zones, the forced remainder. zone: the zone of every unit; T: zone -> its
    total; neighbours: zone -> the zones that touch it; no_spill: the units that take no spill from other zones (they keep their
    zone's fill). Returns a dict: assigned, filled (after the zone fill), the zone levels and modes, the surplus per zone, what the
    rings took, the flows (from, to, ring, W), what was forced back, what found no place"""
    if spill not in SPILLS:
        raise ValueError(f'spill must be one of {SPILLS}')
    w, lo, hi = (np.asarray(x, float) for x in (w, lo, hi))
    ns = np.zeros(len(w), bool) if no_spill is None else np.asarray(no_spill, bool)
    if len(ns) != len(w):
        raise ValueError('no_spill must hold one flag per unit')
    idx = pd.Series(np.arange(len(zone))).groupby(np.asarray(zone)).indices
    a = np.zeros(len(w))
    s_z, mode, surplus = {}, {}, {}
    for z, ii in idx.items():
        ai, s, sur, md = band_solve(w[ii], lo[ii], hi[ii], float(T[z]))
        a[ii] = ai
        s_z[z], mode[z] = s, md
        if sur > 1e-9:
            surplus[z] = sur
    filled = a.copy()
    surplus0 = dict(surplus)
    flows, to_ring = [], {}
    for z in sorted(surplus, key=lambda q: -surplus[q]):     # the largest surplus first
        S = surplus[z]
        seen, frontier, got = {z}, {z}, 0.0
        for r in range(1, max_ring + 1):
            if S <= 1e-9:
                break
            nxt = set()
            for q in frontier:
                nxt |= set(neighbours.get(q, ()))
            nxt -= seen
            seen |= nxt
            frontier = nxt
            if not nxt:
                break
            zs = [q for q in sorted(nxt) if q in idx]
            if not zs:
                continue
            jj = np.concatenate([idx[q] for q in zs])
            nsj = ns[jj]                 # the units that take no spill keep what they hold
            room = np.where(nsj, 0.0, np.maximum(hi[jj] - a[jj], 0.0))
            if room.sum() <= 1e-12:
                continue
            if spill == 'weight':        # each unit of the ring min(room, t x w), one t for the ring
                add, _, rest, _ = band_solve(w[jj], np.zeros(len(jj)), room, S)
            elif spill == 'level':       # the emptiest units first, up to their upper limit
                new, _, rest, _ = band_solve(w[jj], a[jj], np.where(nsj, a[jj], np.maximum(hi[jj], a[jj])), a[jj].sum() + S)
                add = new - a[jj]
            else:                        # 'level_face': the emptiest first, never above the unit's own weight (its realistic headcount)
                top = np.where(nsj, a[jj], np.maximum(a[jj], np.minimum(hi[jj], w[jj])))
                if (top - a[jj]).sum() <= 1e-12:
                    continue
                new, _, rest, _ = band_solve(w[jj], a[jj], top, a[jj].sum() + S)
                add = new - a[jj]
            add = np.maximum(add, 0.0)
            a[jj] += add
            off = 0
            for q in zs:
                k = len(idx[q])
                v = add[off:off + k].sum()
                if v > 1e-9:
                    flows.append((z, q, r, float(v)))
                off += k
            got += S - rest
            S = rest
        to_ring[z] = got
        surplus[z] = S
    forced, unplaced = {}, {}
    forced_units = np.zeros(len(w), bool)
    for z, S in surplus.items():
        if S <= 1e-9:
            continue
        ii = idx[z]
        e = ii[elastic[ii] & (w[ii] > 0)]
        if len(e) == 0:
            e = ii[w[ii] > 0]
        if len(e) == 0:
            unplaced[z] = S
            continue
        a[e] += S * w[e] / w[e].sum()
        forced[z] = S
        forced_units[e] = True
    return dict(assigned=a, filled=filled, s_z=s_z, mode=mode, surplus0=surplus0, to_ring=to_ring, flows=flows, forced=forced,
                forced_units=forced_units, unplaced=unplaced)


def raise_institutions(a, w, hi, zone, inst_rows, published, neighbours, floor_k=1.0, max_ring=3):
    """raise every named institution that holds less than floor_k x its published staff. The
    deficit comes from the units of the institution's own zones (ring 0), then of rings 1 to max_ring, that hold more than their
    face w - the fullest first (one level per ring: clip(s x w, w, a)), never below their face; the units of the institutions are
    never taken from. The institution's units then take what was found up to their upper limit hi (their published share of the
    faces), the emptiest first. The largest deficit first. Returns (a, rows, flows): rows per raised institution (published,
    before, after, found, short, per ring), flows (zone, institution, ring, W)."""
    a = np.asarray(a, float).copy()
    w, hi = np.asarray(w, float), np.asarray(hi, float)
    zone = np.asarray(zone)
    idx = pd.Series(np.arange(len(zone))).groupby(zone).indices
    inst_all = np.zeros(len(a), bool)
    for ii in inst_rows.values():
        inst_all[ii] = True
    deficit = {n: floor_k * published[n] - a[ii].sum() for n, ii in inst_rows.items() if len(ii)}
    rows, flows = [], []
    for name in sorted(deficit, key=lambda n: -deficit[n]):
        ii = inst_rows[name]
        before = a[ii].sum()
        D = min(floor_k * published[name], hi[ii].sum()) - before
        if D <= 1e-6:
            continue
        z0 = set(zone[ii])
        seen, frontier, got, per_ring = set(z0), set(z0), 0.0, {}
        for ring in range(0, max_ring + 1):
            if D - got <= 1e-9:
                break
            if ring:
                nxt = set()
                for q in frontier:
                    nxt |= set(neighbours.get(q, ()))
                nxt -= seen
                seen |= nxt
                frontier = nxt
                if not nxt:
                    break
                zs = nxt
            else:
                zs = z0
            zs = [q for q in sorted(zs) if q in idx]
            if not zs:
                continue
            jj = np.concatenate([idx[q] for q in zs])
            jj = jj[~inst_all[jj]]
            lo_d = np.minimum(a[jj], w[jj])
            give = (a[jj] - lo_d).sum()
            if give <= 1e-9:
                continue
            take = min(give, D - got)
            new, _, _, _ = band_solve(w[jj], lo_d, a[jj].copy(), a[jj].sum() - take)
            d = a[jj] - new
            a[jj] = new
            got += take
            per_ring[ring] = per_ring.get(ring, 0.0) + take
            off = 0
            for q in zs:
                k = int((~inst_all[idx[q]]).sum())
                v = d[off:off + k].sum()
                if v > 1e-9:
                    flows.append((q, name, ring, float(v)))
                off += k
        new, _, rest, _ = band_solve(w[ii], a[ii].copy(), np.maximum(hi[ii], a[ii]), before + got)
        a[ii] = new
        rows.append(dict(institution=name, published=float(published[name]), before=float(before), after=float(a[ii].sum()),
                         found=float(got), short=float(floor_k * published[name] - a[ii].sum()),
                         rings=' · '.join(f'ring {q} {v:,.0f}' for q, v in per_ring.items())))
    return a, rows, flows


# --- 5. the whole rule, its checks, and the checks of the config ------------------------------------------------------
def check_config(knobs, groups, keywords, poi_uses, shop_uses, classes, rules, bands, subtypes, sizes, institutions, no_spill,
                 bosserhof_classes=None, fgsv_ranges=None):
    """the tables fit together: every regex compiles, every activity type has a group and a default sub-type, every sub-type a
    band with its fields, every institution a published total above 0 and units in no other institution, the no-spill table its
    three keys; the classes are in the Bosserhof catalogue and the FGSV highs agree with BOSSERHOF_FGSV_RANGES where both hold a
    class"""
    for k in ('fixed_k', 'elastic_k', 'industrial_k', 'remainder_k'):
        if not knobs[k] > 0:
            raise ValueError(f'WORKERS_HEADCOUNT {k} must be above 0')
    tk = knobs['technical_k']
    if tk is not None and not (isinstance(tk, (int, float)) and not isinstance(tk, bool) and tk > 0):
        raise ValueError('WORKERS_HEADCOUNT technical_k must be above 0 (or None: no limit of their own)')
    if knobs['spill'] not in SPILLS or not (isinstance(knobs['max_ring'], int) and knobs['max_ring'] >= 0):
        raise ValueError(f'WORKERS_HEADCOUNT: spill one of {SPILLS}, max_ring an int >= 0')
    fk = knobs.get('institution_floor_k')
    if fk is not None and not (isinstance(fk, (int, float)) and not isinstance(fk, bool) and 0 < fk <= 1):
        raise ValueError('WORKERS_HEADCOUNT institution_floor_k must lie in (0, 1] (or None: the institutions are not raised)')
    bw = knobs.get('size_rule_both_ways', ())
    if not isinstance(bw, tuple) or set(bw) - set(groups) or any(groups[t] != FIXED for t in bw):
        raise ValueError('WORKERS_HEADCOUNT size_rule_both_ways: a tuple of fixed activity types')
    _Activity(groups, keywords, poi_uses, shop_uses, classes, rules)          # compiles and checks the groups
    cc = rules['company_campus_ids']
    if not (isinstance(cc, tuple) and all(isinstance(u, str) and u for u in cc)):
        raise ValueError('WORKERS_ACTIVITY_RULES company_campus_ids: a tuple of building ids')
    if set(no_spill) != {'remainder_capped', 'technical', 'technical_except'} or not isinstance(no_spill['remainder_capped'], bool):
        raise ValueError('WORKERS_NO_SPILL: exactly remainder_capped (True / False), technical and technical_except ({group: regex})')
    for key in ('technical', 'technical_except'):
        if not (isinstance(no_spill[key], dict) and all(isinstance(k, str) and k and isinstance(p, str) and p
                                                        for k, p in no_spill[key].items())):
            raise ValueError(f'WORKERS_NO_SPILL {key}: {{group: regex}}, both texts')
        for p in no_spill[key].values():
            if re.compile(p).search(''):
                raise ValueError(f'WORKERS_NO_SPILL {key}: {p!r} matches an empty text')
    if set(no_spill['technical_except']) - set(no_spill['technical']):
        raise ValueError(f"WORKERS_NO_SPILL technical_except: groups that technical does not name: "
                         f"{sorted(set(no_spill['technical_except']) - set(no_spill['technical']))}")
    if set(groups.values()) != {FIXED, ELASTIC} or set(knobs['industrial_types']) - set(groups):
        raise ValueError('WORKERS_ACTIVITY_GROUPS: fixed / elastic only; WORKERS_HEADCOUNT industrial_types must be activity types')
    bad = [k for k, e in bands.items() if set(e) != BAND_FIELDS]
    if bad:
        raise ValueError(f'WORKERS_BANDS: entries without exactly the fields {sorted(BAND_FIELDS)}: {bad[:5]}')
    bad = [k for k, e in bands.items() if e['est'] and not (e['hi'] is not None and e['mx'] is not None and 0 <= e['hi'] <= e['mx']
                                                           and (e['typ'] is None or 0 <= e['typ'] <= e['mx']))]
    if bad:
        raise ValueError(f'WORKERS_BANDS: an establishment band needs 0 <= high <= max (and typical <= max): {bad}')
    used = ({k for rs in subtypes['rules'].values() for k, _, _, _ in rs} | set(subtypes['default'].values()) | {'works_part'}
            | {k for k, _ in subtypes['business_poi']['subtypes']} | {sizes['luxury_hotel'], sizes['convenience']['to'], sizes['convenience']['from']})
    if used - set(bands) or set(subtypes['default']) != set(groups) or set(subtypes['rules']) - set(groups):
        raise ValueError(f'WORKERS_SUBTYPES: sub-types without a band {sorted(used - set(bands))}, or a default per activity type missing')
    for rs in subtypes['rules'].values():
        for _, pat, cond, field in rs:
            if pat is not None:
                re.compile(_pattern(pat))
            if field not in TEXT_FIELDS:
                raise ValueError(f'WORKERS_SUBTYPES: unknown text field {field!r}')
            stack = [cond] if cond else []
            while stack:
                c = stack.pop()
                if set(c) - set(CONDITIONS):
                    raise ValueError(f'WORKERS_SUBTYPES: unknown condition {sorted(set(c) - set(CONDITIONS))}')
                for k in ('match', 'not'):
                    if k in c:
                        re.compile(c[k][1])
                        if c[k][0] not in TEXT_FIELDS:
                            raise ValueError(f'WORKERS_SUBTYPES: unknown text field {c[k][0]!r}')
                stack += list(c.get('any', []))
    for p in (subtypes['works']['text'], subtypes['works']['classes']):
        re.compile(p)
    if set(subtypes['works']['types']) - set(groups) or subtypes['business_poi']['type'] not in groups:
        raise ValueError('WORKERS_SUBTYPES: works / business_poi name an unknown activity type')
    if any('src' not in v for v in sizes['known'].values()) or set(sizes['places_types']) - set(groups) or set(sizes['pupils_types']) - set(groups):
        raise ValueError('WORKERS_SIZES: every known size needs its source; places / pupils types must be activity types')
    ids = [u for e in institutions.values() for u in e['unit_ids']]
    if len(ids) != len(set(ids)) or any(not e['published'] > 0 for e in institutions.values()):
        raise ValueError('WORKERS_INSTITUTIONS: a unit in two institutions, or a published total not above 0')
    if any(set(e) != {'published', 'basis', 'year', 'source', 'unit_ids'} for e in institutions.values()):
        raise ValueError('WORKERS_INSTITUTIONS: each entry needs exactly published, basis, year, source, unit_ids')
    if bosserhof_classes is not None:
        cl = set(classes) | set(rules['prefer_classes']) | set(rules['specific_classes']) | set(rules['industrial_classes']) \
            | set(rules['office_classes']) | set(rules['canteen_of_class']) | {rules['hypermarket_class'], rules['hospital_class']}
        if cl - set(bosserhof_classes):
            raise ValueError(f'WORKERS_ACTIVITY: class names outside the Bosserhof catalogue: {sorted(cl - set(bosserhof_classes))}')
    if fgsv_ranges is not None:
        off = {k: (v, fgsv_ranges[k][1]) for k, v in sizes['fgsv_high'].items() if k in fgsv_ranges and abs(fgsv_ranges[k][1] - v) > 1e-9}
        if off:
            raise ValueError(f'WORKERS_SIZES fgsv_high differs from the high end of BOSSERHOF_FGSV_RANGES: {off}')


def apply(units, uo, bld, pois, zones, neighbours, *, zone_id_col, knobs, activity, bands, subtypes, sizes, institutions,
          no_spill=None):
    """the rule on the Workers rows of `units` (nothing is changed in place). Returns a dict: W (every Workers row with its
    activity type, sub-type, face, cap_hi, hi, why it takes no spill, before, after), U (the zone-owned rows, the solver's order),
    the bands, the no-spill flags of U, the solver's result, the zone totals before (T) and after (Az). no_spill: WORKERS_NO_SPILL
    (None: every unit takes spill and no technical structure is capped)"""
    W = workers_table(units, uo, bld, pois, zones, zone_id_col)
    # the ids the tables list must be Workers units, as notebook 08 requires of its other lists: a re-run of steps 04-07 that
    # renames or drops one would otherwise silently lift an institution's limit or a published size
    ids = set(W['unit_id'])
    miss_i = {n: [u for u in e['unit_ids'] if u not in ids] for n, e in institutions.items()}
    miss_i = {n: v for n, v in miss_i.items() if v}
    if miss_i:
        raise AssertionError(f'WORKERS_INSTITUTIONS: unit id(s) not among the Workers units: {miss_i}')
    miss_k = sorted(set(sizes['known']) - ids)
    if miss_k:
        raise AssertionError(f"WORKERS_SIZES 'known': unit id(s) not among the Workers units: {miss_k}")
    rr = activity['rules']
    miss_c = sorted(set(rr['company_campus_ids']) - set(W['building_id']))
    if miss_c:
        raise AssertionError(f'WORKERS_ACTIVITY_RULES company_campus_ids: building id(s) without a Workers unit: {miss_c}')
    for k in ('no_evidence_rule', 'plain_home_rule', 'labels_kept_rule'):     # the unit rules the activity types read must exist
        if not W['unit_rule'].fillna('').str.contains(rr[k], regex=False).any():
            raise AssertionError(f'WORKERS_ACTIVITY_RULES {k}: no Workers unit rule contains {rr[k]!r} - did notebook 08 reword it?')
    A = _Activity(**activity)
    at = activity_types(W, **activity, act=A)
    F = headcount_bands(W, at, bands, subtypes, sizes, size_inputs(pois, bld), both_ways=knobs.get('size_rule_both_ways', ()))
    W = pd.concat([W, at, F], axis=1)
    own = W['zone_idx'].notna().to_numpy()
    if (W.loc[~own, 'assigned'] != 0).any():
        raise AssertionError('a Workers unit in no zone held Workers before the rule')
    U = W[own].copy()
    U['zone_idx'] = U['zone_idx'].astype(int)
    # who takes no spill (WORKERS_NO_SPILL): the technical structures - which also hold at most technical_k x their realistic
    # headcount - and the remainder units the remainder rule caps
    if no_spill is None:
        ns_tech = pd.Series('', index=U.index, dtype=object)
    else:
        ns_tech = technical_structures(U, no_spill['technical'], A, no_spill['technical_except'])
    B = unit_bands(U, knobs, institutions, activity['groups'], technical=ns_tech.ne('').to_numpy())
    if no_spill is None:
        ns_rem = np.zeros(len(U), bool)
    else:
        ns_rem = np.asarray(B['remainder_capped'], bool) & bool(no_spill['remainder_capped'])
    ns = ns_rem | ns_tech.ne('').to_numpy()
    T = U.groupby('zone_idx')['assigned'].sum()
    res = fill_and_spill(U['zone_idx'].to_numpy(), B['w'], B['lo'], B['hi'], B['elastic'], T, neighbours,
                         max_ring=knobs['max_ring'], spill=knobs['spill'], no_spill=ns)
    res['spilled'] = res['assigned'].copy()
    res['raised'], res['raise_flows'] = [], []
    if knobs.get('institution_floor_k'):         # the named institutions raised to their published staff
        res['assigned'], res['raised'], res['raise_flows'] = raise_institutions(
            res['assigned'], B['w'], B['hi'], U['zone_idx'].to_numpy(), B['inst_rows'],
            {n: e['published'] for n, e in institutions.items()}, neighbours, floor_k=knobs['institution_floor_k'],
            max_ring=knobs['max_ring'])
    W['before'] = W['assigned']
    W['after'] = 0.0
    W.loc[U.index, 'after'] = res['assigned']
    W['hi'] = np.nan
    W.loc[U.index, 'hi'] = B['hi']
    W['no_spill'] = ''
    W.loc[U.index, 'no_spill'] = np.where(ns_rem, 'remainder of an establishment building',
                                          np.where(ns_tech.ne(''), 'technical: ' + ns_tech.astype(str), ''))
    Az = W.loc[U.index, 'after'].groupby(U['zone_idx']).sum()
    return dict(W=W, U=U, bands=B, no_spill=ns, res=res, T=T, Az=Az.reindex(T.index, fill_value=0.0), knobs=knobs,
                institutions=institutions)


def verify(r, tol=1e-6):
    """the rule's invariants on the result of apply(); raises AssertionError. Returns a short text for the notebook"""
    W, U, B, res, T = r['W'], r['U'], r['bands'], r['res'], r['T']
    a, f, w, hi = res['assigned'], res['filled'], B['w'], B['hi']
    if not np.isfinite(W['after']).all() or (W['after'] < 0).any():
        raise AssertionError('a negative or non-finite Workers value')
    if abs(W['after'].sum() - W['before'].sum()) > tol:
        raise AssertionError(f"the Workers total moved: {W['before'].sum():,.6f} -> {W['after'].sum():,.6f}")
    if W.loc[W['zone_idx'].isna(), 'after'].any():
        raise AssertionError('a Workers unit in no zone received Workers')
    zone = U['zone_idx'].to_numpy()
    Fz = pd.Series(f).groupby(zone).sum()
    Hz = pd.Series(np.where(w > 0, hi, 0.0)).groupby(zone).sum()
    if not np.allclose(Fz.reindex(T.index).to_numpy(), np.minimum(T.to_numpy(), Hz.reindex(T.index).to_numpy()), rtol=0, atol=tol):
        raise AssertionError('a zone does not hold min(its total, the sum of its upper limits) after the zone fill')
    if (f > hi + tol).any():
        raise AssertionError('a unit above its upper limit after the zone fill')
    # the zone fill gives every unit min(s x face, hi) with one s per zone
    for z, ii in pd.Series(np.arange(len(zone))).groupby(zone).indices.items():
        s = res['s_z'][z]
        if res['mode'][z] == 'band' and not np.allclose(f[ii], np.minimum(s * w[ii], hi[ii]), rtol=1e-9, atol=1e-6):
            raise AssertionError(f'zone {z}: the fill is not min(s x face, hi)')
    # the raise of the named institutions after the spill - it only takes from units above their face, never below it,
    # and never from an institution; an institution only gains
    a_s = res.get('spilled', a)
    inst = np.zeros(len(a), bool)
    for ii in B['inst_rows'].values():
        inst[ii] = True
    if abs(a.sum() - a_s.sum()) > tol:
        raise AssertionError('the raise of the institutions moved the Workers total')
    if (a[~inst] < np.minimum(a_s[~inst], w[~inst]) - tol).any() or (a[~inst] > a_s[~inst] + tol).any():
        raise AssertionError('the raise took a unit below its realistic headcount, or gave Workers to a unit of no institution')
    if (a[inst] < a_s[inst] - tol).any():
        raise AssertionError('the raise took Workers from an institution')
    kf = r['knobs'].get('institution_floor_k')
    n_raised, n_short = len(res.get('raised', [])), sum(1 for q in res.get('raised', []) if q['short'] > 0.5)
    a = a_s                                              # the checks of the fill and the spill read the result of the spill
    add = a - f
    if (add < -tol).any():
        raise AssertionError('the spill took Workers from a unit')
    sp = (add > tol) & ~res['forced_units']
    if (a[sp] > np.maximum(f[sp], np.minimum(hi[sp], w[sp])) + tol).any() and r['knobs']['spill'] == 'level_face':
        raise AssertionError('a unit received spill above its realistic headcount')
    ns = r['no_spill']
    if (sp & ns).any():
        raise AssertionError(f'{int((sp & ns).sum())} unit(s) of WORKERS_NO_SPILL received spill')
    tc = np.asarray(B['technical_capped'], bool)        # the technical structures: at most technical_k x their face
    tk = r['knobs']['technical_k']
    if tc.any() and (tc & ~res['forced_units'] & (a > tk * w + tol)).any():
        raise AssertionError(f"{int((tc & ~res['forced_units'] & (a > tk * w + tol)).sum())} technical structure(s) above {tk:g} x "
                             "their realistic headcount")
    sent = pd.Series(0.0, index=T.index)
    for src, _, _, v in res['flows']:
        sent[src] += v
    for z, S0 in res['surplus0'].items():
        if abs(sent.get(z, 0.0) + res['forced'].get(z, 0.0) + res['unplaced'].get(z, 0.0) - S0) > tol * max(1.0, S0):
            raise AssertionError(f'zone {z}: what it sent, forced and could not place differs from its surplus')
    if res['unplaced']:
        raise AssertionError(f"{len(res['unplaced'])} zone(s) could not place {sum(res['unplaced'].values()):,.1f} Workers")
    fz = set(res['forced'])
    a = res['assigned']                                  # the final values: after the raise
    for name, ii in B['inst_rows'].items():
        pub = r['institutions'][name]['published']
        if len(ii) and a[ii].sum() > pub + tol and not set(zone[ii]) & fz:
            raise AssertionError(f'{name}: {a[ii].sum():,.1f} Workers above its published {pub:,.0f}')
        if kf and len(ii) and a[ii].sum() < min(kf * pub, hi[ii].sum()) - 0.5 \
                and not any(q['institution'] == name and q['short'] > 0 for q in res['raised']):
            raise AssertionError(f'{name}: below {kf:g} x its published staff without a reported shortfall')
    unforced = ~res['forced_units']
    if (a[unforced] > np.maximum(hi[unforced], f[unforced]) + tol).any():
        raise AssertionError('a unit above its upper limit that was not forced')
    return (f"the Workers total holds ({W['after'].sum():,.2f}); every zone holds min(its total, the sum of its upper limits) after the "
            "fill, at one level per zone; the spill only lifts units below their realistic headcount, never above it"
            + (f", and none of the {int(ns.sum()):,} units of WORKERS_NO_SPILL" if ns.any() else '')
            + (f"; the {int(tc.sum()):,} technical structures hold at most {'their' if tk == 1 else f'{tk:g} x their'} realistic "
               "headcount" if tc.any() else '')
            + "; what an over-full zone sends equals its surplus; no unit is above its upper limit"
            + (f" (except the {int(res['forced_units'].sum())} unit(s) of the {len(fz)} zone(s) whose surplus no ring could take)" if fz else '')
            + '; no named institution above its published staff'
            + (f"; the raise lifted {n_raised} institution(s) to {kf:g} x their published staff ({n_short} short), taking only from "
               "units above their realistic headcount and never below it" if kf else ''))


# --- 6. diagnostics ---------------------------------------------------------------------------------------------------
def wquantiles(m, wt, qs=(0.5, 0.9, 0.95, 0.99)):
    """weighted quantiles of m (weights wt), finite m and wt > 0 only"""
    m, wt = np.asarray(m, float), np.asarray(wt, float)
    ok = np.isfinite(m) & (wt > 0)
    m, wt = m[ok], wt[ok]
    o = np.argsort(m)
    m, wt = m[o], wt[o]
    cw = np.cumsum(wt) / wt.sum()
    return {q: float(m[min(np.searchsorted(cw, q), len(m) - 1)]) for q in qs}


def report(r, zones, zone_name_col='NAME'):
    """the diagnostics of the rule against the allocation it starts from: what moved between units, buildings and zones; the zones
    that changed; the units that take no spill; the units above the published maximum of their type and the establishments above
    fixed_k x their realistic headcount; the named institutions; the largest gainers; the largest zone-to-zone flows; the
    Workers-weighted multipliers"""
    W, U, res = r['W'], r['U'], r['res']
    k_f = r['knobs']['fixed_k']
    out = {}
    b, a = W['before'].to_numpy(float), W['after'].to_numpy(float)
    out['total_before'], out['total_after'] = float(b.sum()), float(a.sum())
    out['moved_units'] = float(np.abs(a - b).sum() / 2)
    db = (W['after'] - W['before']).groupby(W['building_id']).sum()
    out['moved_buildings'] = float(db.abs().sum() / 2)
    out['buildings_changed'] = int((db.abs() > 0.5).sum())
    zb = W.loc[U.index, 'before'].groupby(U['zone_idx']).sum()
    za = W.loc[U.index, 'after'].groupby(U['zone_idx']).sum()
    dz = za - zb
    out['moved_zones'] = float(dz.abs().sum() / 2)
    out['zones_changed'] = int((dz.abs() > 0.5).sum())
    out['zones_doubled'] = int(((za >= 2 * zb) & (dz > 5)).sum())
    out['zones_halved'] = int(((za <= 0.5 * zb) & (dz < -5)).sum())
    out['zones_with_units'] = int(len(zb))
    out['senders'], out['receivers'] = int((dz < -0.5).sum()), int((dz > 0.5).sum())
    fl = pd.DataFrame(res['flows'], columns=['src', 'dst', 'ring', 'W'])
    out['ring_split'] = fl.groupby('ring')['W'].sum().to_dict() if len(fl) else {}
    out['forced'] = float(sum(res['forced'].values()))
    out['forced_zones'] = [zones.at[z, zone_name_col] for z in res['forced']]
    out['unplaced'] = float(sum(res['unplaced'].values()))
    out['over_full_zones'] = len(res['surplus0'])
    out['surplus'] = float(sum(res['surplus0'].values()))
    # the units that take no spill (WORKERS_NO_SPILL): how many, what they hold before and after the rule, per reason
    nsr = W.loc[U.index, 'no_spill']
    out['no_spill'] = (W.loc[U.index][nsr.ne('')].groupby(nsr[nsr.ne('')]).agg(units=('unit_id', 'size'), before=('before', 'sum'),
                                                                              after=('after', 'sum'))
                       .sort_values('units', ascending=False, kind='mergesort'))
    # the technical structures above their realistic headcount (after the rule at most technical_k x it)
    tc = np.asarray(r['bands']['technical_capped'], bool)
    fu = U['face'].to_numpy(float)
    out['technical_capped'] = int(tc.sum())
    for tag in ('before', 'after'):
        v = W.loc[U.index, tag].to_numpy(float)
        ab = tc & (v > fu + 1e-6)
        out[f'technical_above_face_{tag}'] = int(ab.sum())
        out[f'W_technical_above_face_{tag}'] = float(np.where(ab, v - fu, 0.0).sum())
    # units above the published maximum of their type, establishments above fixed_k x their realistic headcount
    own = W['zone_idx'].notna()
    mx = W['mx'].to_numpy(float)
    fixed = (W['agroup_eff'] == FIXED).to_numpy() & own.to_numpy()
    face = W['face'].to_numpy(float)
    for tag, v in (('before', b), ('after', a)):
        above = np.isfinite(mx) & (v > mx + 0.5)
        out[f'above_max_{tag}'] = int(above.sum())
        out[f'W_above_max_{tag}'] = float(np.where(above, v - mx, 0.0).sum())
        est = fixed & (v > k_f * face + 0.5) & (v > 5)
        out[f'est_above_kf_{tag}'] = int(est.sum())
        out[f'W_est_above_kf_{tag}'] = float(np.where(est, v - k_f * face, 0.0).sum())
        out[f'establishments_W_{tag}'] = float(v[fixed].sum())
    # the named institutions
    rows = []
    by_id = W.set_index('unit_id')
    for name, e in r['institutions'].items():
        ids = [u for u in e['unit_ids'] if u in by_id.index]
        rows.append(dict(institution=name, published=float(e['published']), units=len(ids), before=float(by_id.loc[ids, 'before'].sum()),
                         after=float(by_id.loc[ids, 'after'].sum())))
    out['institutions'] = pd.DataFrame(rows)
    # the raise of the named institutions - per institution, what was found where, and the zones it came from
    out['raised'] = pd.DataFrame(res.get('raised', []), columns=['institution', 'published', 'before', 'after', 'found', 'short', 'rings'])
    rf = pd.DataFrame(res.get('raise_flows', []), columns=['zone', 'institution', 'ring', 'W'])
    out['raise_moved'] = float(rf['W'].sum())
    out['raise_zones'] = int(rf['zone'].nunique())
    a_s = np.asarray(res.get('spilled', res['assigned']), float)
    out['raise_donors'] = int((res['assigned'] < a_s - 1e-6).sum())
    # who gains most
    nm = W['poi_name'].where(W['kind'].eq('poi')).fillna(W['name']).fillna(W['llm_type'].fillna('').str[:60])
    zn = W['zone_idx'].map(zones[zone_name_col])
    G = pd.DataFrame({'unit': W['unit_id'], 'name': nm.str[:44], 'type': W['atype'].str[:26], 'zone': zn.fillna('').str[:24],
                      'face': W['face'], 'before': W['before'], 'after': W['after'], 'gain': W['after'] - W['before']})
    out['gainers'] = G.sort_values('gain', ascending=False)
    out['losers'] = G.sort_values('gain')
    # the largest zone-to-zone flows
    if len(fl):
        f2 = fl.groupby(['src', 'dst'], as_index=False).agg(ring=('ring', 'min'), W=('W', 'sum')).sort_values('W', ascending=False)
        f2['from'] = f2['src'].map(zones[zone_name_col])
        f2['to'] = f2['dst'].map(zones[zone_name_col])
        out['flows'] = f2[['from', 'to', 'ring', 'W']]
        out['flows_by_sender'] = (fl.groupby('src')['W'].sum().sort_values(ascending=False)
                                  .rename(index=zones[zone_name_col]).rename('W'))
    else:
        out['flows'] = pd.DataFrame(columns=['from', 'to', 'ring', 'W'])
        out['flows_by_sender'] = pd.Series(dtype=float)
    # the multipliers: Workers / Bosserhof value, weighted by Workers
    exp = W['exp'].to_numpy(float)
    m_b = np.where(exp > 0, b / np.where(exp > 0, exp, 1), np.nan)
    m_a = np.where(exp > 0, a / np.where(exp > 0, exp, 1), np.nan)
    qs = (0.5, 0.9, 0.95, 0.99)
    out['mult_before'] = wquantiles(m_b, b, qs)
    out['mult_after'] = wquantiles(m_a, a, qs)
    out['mult_max_before'] = float(np.nanmax(np.where(b > 1, m_b, np.nan)))
    out['mult_max_after'] = float(np.nanmax(np.where(a > 1, m_a, np.nan)))
    # per activity type
    out['types'] = (W.groupby('atype').agg(units=('unit_id', 'size'), before=('before', 'sum'), after=('after', 'sum'),
                                           max_before=('before', 'max'), max_after=('after', 'max'))
                    .assign(change=lambda d: d['after'] - d['before']).sort_values('change'))
    return out
