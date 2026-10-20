"""Step 08: who carries School, University and Kindergarten.

The education labels come from the model (steps 05 and 07). These rules correct them from evidence already in the data - names,
ALKIS functions, the OSM tags of POIs, sites and building outlines, the model's type text - and never re-run the model:
  * label_fixes   real schools typed after a tenant or labelled lessons get the school label; vocational schools labelled
                  university become School (vocational)                                   - before the units are built
  * drops         units whose own data name another use, non-teaching campus parts and places without any evidence lose
                  the label; the unit keeps its k_red, so the dropped share stays empty     - on the units, next to the
                                                                                             Workers-0 rules
  * no_join       School places in a zone with a School total of 0 known only from the cadastre or a bare OSM school
                  outline, with no school POI or site nearby, join no neighbour and take no fallback - in the allocation
  * kita_weights  the Kita part of a school, Kita polygons and squeezed Kita POIs weigh their own size - in the weights
  * type_fixes    school types from OSM isced / grades tags, vocational campuses and a short Oskar-Kaemmer list
The patterns and lists are config.EDU_CARRIER_RULES. All texts are matched folded: lower case, umlauts as ae / oe / ue, ss.
"""
import json
import re
import unicodedata

import numpy as np
import pandas as pd
import pyogrio
import shapely

I = re.IGNORECASE
EDU_LABELS = {'School': 'school', 'University': 'university', 'Kindergarten': 'childcare'}


def fold(s):
    """lower case, umlauts as ae / oe / ue, ss for sharp s, accents stripped"""
    if not isinstance(s, str):
        return ''
    for a, b in (('ä', 'ae'), ('ö', 'oe'), ('ü', 'ue'), ('Ä', 'ae'), ('Ö', 'oe'), ('Ü', 'ue'), ('ß', 'ss')):
        s = s.replace(a, b)
    s = unicodedata.normalize('NFKD', s)
    return ''.join(ch for ch in s if not unicodedata.combining(ch)).lower()


def _join(texts):
    return ' | '.join(fold(x) for x in texts if isinstance(x, str) and x.strip())


def _tags(t):
    if not isinstance(t, str) or not t.strip():
        return {}
    try:
        d = json.loads(t)
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


# --- inputs ----------------------------------------------------------------------------------------------------------

def outlines(osm_buildings_file, bld, *, building_values, amenity_values):
    """The OSM building outlines that tell a use (school, university, kindergarten, church, fire station, ruins ...) or carry an
    old_name or a Mensa name, with the share of each building's footprint they cover: building_id, bld_id, building, amenity,
    name, old_name, ruins (the outline is a ruin / abandoned / disused), cover."""
    vb = ', '.join(f"'{v}'" for v in sorted(building_values))
    va = ', '.join(f"'{v}'" for v in sorted(amenity_values))
    where = (f"building IN ({vb}) OR amenity IN ({va}) OR tags LIKE '%old_name%' OR tags LIKE '%abandoned%' OR tags LIKE '%disused%' "
             "OR tags LIKE '%ruins%' OR name LIKE '%ensa%' OR name LIKE '%antine%' OR name LIKE '%peisesaal%'")
    ob = pyogrio.read_dataframe(osm_buildings_file, where=where, columns=['bld_id', 'building', 'name', 'amenity', 'tags'])
    cols = ['building_id', 'bld_id', 'building', 'amenity', 'name', 'old_name', 'ruins', 'cover']
    if ob.empty:
        return pd.DataFrame(columns=cols)
    ob = ob.to_crs(bld.crs)
    t = ob['tags'].map(_tags)
    ob['old_name'] = t.map(lambda d: d.get('old_name'))
    ob['ruins'] = (ob['building'].isin(['ruins', 'abandoned', 'disused'])
                   | t.map(lambda d: str(d.get('ruins', '')).lower() in ('yes', 'true', '1') or 'abandoned:building' in d
                           or 'disused:building' in d))
    bg = bld[['building_id', 'geometry']].reset_index(drop=True)
    bi, oi = ob.sindex.query(bg.geometry.values, predicate='intersects')
    if not len(bi):
        return pd.DataFrame(columns=cols)
    bgeo = shapely.make_valid(bg.geometry.values[bi])
    ogeo = shapely.make_valid(ob.geometry.values[oi])
    inter = shapely.area(shapely.intersection(bgeo, ogeo))
    out = pd.DataFrame({'building_id': bg['building_id'].to_numpy()[bi], 'bld_id': ob['bld_id'].to_numpy()[oi],
                        'building': ob['building'].to_numpy()[oi], 'amenity': ob['amenity'].to_numpy()[oi],
                        'name': ob['name'].to_numpy()[oi], 'old_name': ob['old_name'].to_numpy()[oi], 'ruins': ob['ruins'].to_numpy()[oi],
                        'cover': inter / shapely.area(bgeo)})
    return out[out['cover'] > 1e-6].reset_index(drop=True)


def poi_geometries(all_pois_file, crs):
    """The geometry of every POI of step 01 - its point or polygon (step 07 keeps a point per POI)."""
    g = pyogrio.read_dataframe(all_pois_file, layer='pois', columns=['poi_id', 'poi_use', 'amenity', 'geom_kind', 'name'])
    g = g.to_crs(crs)
    g['geometry'] = shapely.make_valid(g.geometry.values)
    return g.set_index('poi_id')


class Ctx:
    """The evidence per building, POI and unit, from the tables notebook 08 holds."""

    def __init__(self, bld, pois, pairs06, own06, poi_attrs, outlines_, geoms, rules, *, head_split):
        self.R = rules
        self.rx = {k: re.compile(v, I) for k, v in rules.items() if isinstance(v, str)}
        self.B = bld.set_index('building_id', drop=False)
        self.P = pois.set_index('poi_id', drop=False)
        self.PA = poi_attrs.set_index('poi_id', drop=False)
        self.head_rx = re.compile(head_split, I)
        self.site = {b: g for b, g in pairs06[pairs06['how'] == 'site'].groupby('building_id')}
        self.own = {b: g for b, g in own06.groupby('building_id')}
        self.out = {b: g for b, g in outlines_.groupby('building_id')}
        self.G = geoms
        self.TG = {pid: _tags(t) for pid, t in self.PA['tags'].items()}
        self._empty = own06.iloc[0:0]

    # --- texts and tags -----------------------------------------------------------------------------------------
    def head(self, t):
        return self.head_rx.split(t, maxsplit=1)[0].strip() if isinstance(t, str) else ''

    def sites(self, bid):
        return self.site.get(bid, self._empty)

    def owns(self, bid):
        return self.own.get(bid, self._empty)

    def covers(self, bid, min_cover=0.0):
        o = self.out.get(bid)
        if o is None:
            return pd.DataFrame(columns=['building', 'amenity', 'name', 'old_name', 'ruins', 'cover'])
        return o[o['cover'] >= min_cover]

    def bnames(self, bid):
        r = self.B.loc[bid]
        return [x for x in (r['name'], r['osm_twin_name']) if isinstance(x, str) and x.strip()]

    def own_names(self, bid):
        return [x for x in self.owns(bid)['name'] if isinstance(x, str) and x.strip()]

    def site_names(self, bid):
        return [x for x in self.sites(bid)['name'] if isinstance(x, str) and x.strip()]

    def all_names(self, uid, bid, kind):
        """every name of the unit and its building: ALKIS, OSM twin, own POIs, sites, the step-04 POI names (and a POI unit's own)"""
        return (self.bnames(bid) + self.own_names(bid) + self.site_names(bid) + [self.B.at[bid, 'poi_names']]
                + ([self.P.at[uid, 'name']] if kind == 'poi' else []))

    def tag(self, pid, key):
        v = self.TG.get(pid, {}).get(key)
        if v is None and pid in self.PA.index and key in self.PA.columns:
            v = self.PA.at[pid, key]
        return v if isinstance(v, str) else None

    def use(self, pid):
        return self.PA.at[pid, 'poi_use'] if pid in self.PA.index else None

    def amenity(self, pid):
        return self.PA.at[pid, 'amenity'] if pid in self.PA.index else None

    def fun(self, bid):
        return str(self.B.at[bid, 'function'])

    def twin(self, bid, values):
        return self.B.at[bid, 'osm_twin_tag'] in values or self.B.at[bid, 'osm_building'] in values

    def outline_use(self, bid, values, min_cover=0.5):
        c = self.covers(bid, min_cover)
        return bool((c['building'].isin(values) | c['amenity'].isin(values)).any())

    def feats(self, uid, bid, kind):
        """the unit's own POIs: the POI itself for a POI unit, the building's own POIs otherwise"""
        return [uid] if kind == 'poi' else list(self.owns(bid)['poi_id'])

    # --- geometry --------------------------------------------------------------------------------------------------
    def near_school(self, bid, dist, *, general_only=True):
        """a school POI or site within `dist` m of the building; general_only: not one whose name names a vocational school only"""
        key = '_school_general' if general_only else '_school_all'
        if not hasattr(self, key):
            sg = self.G[self.G['amenity'].eq('school') | (self.G['amenity'].eq('college') & (not general_only))]
            ad, tw = self.rx['adult_education'], self.rx['school_type_word']
            sg = sg[[not (ad.search(fold(n)) and not tw.search(fold(n))) for n in sg['name'].fillna('')]]    # not adult education
            if general_only:
                voc, gen, hp = self.rx['vocational_word'], self.rx['school_general_word'], self.rx['vocational_school_name']
                sg = sg[[not ((voc.search(fold(n)) or hp.search(fold(n))) and not gen.search(fold(n))) for n in sg['name'].fillna('')]]
            setattr(self, key, sg.geometry.values)
        geoms = getattr(self, key)
        return bool(len(geoms)) and bool((shapely.distance(self.B.at[bid, 'geometry'], geoms) <= dist).any())

    def kind(self, pid):
        """'area' or 'point' (step 01)"""
        return self.PA.at[pid, 'geom_kind'] if pid in self.PA.index else None

    def pgeom(self, pid):
        """the geometry of a POI (step 01: its point or polygon; None if it has none)"""
        g = self.G.at[pid, 'geometry'] if pid in self.G.index else None
        return None if g is None or g.is_empty else g

    def poly_area(self, pid):
        if self.kind(pid) == 'area':
            g = self.pgeom(pid)
            return float(shapely.area(g)) if g is not None else float(self.PA.at[pid, 'area_m2'])
        return 0.0

    def mensa_cover(self, bid):
        """the share of the footprint the building's own POI outlines named like a Mensa cover (None: there is none)"""
        o = self.owns(bid)
        rx = self.rx['mensa_outline_name']
        ps = [p for p, n in zip(o['poi_id'], o['name']) if isinstance(n, str) and rx.search(fold(n)) and self.kind(p) == 'area'
              and self.pgeom(p) is not None]
        if not ps:
            return None
        fp = self.B.at[bid, 'geometry']
        u = shapely.union_all([self.pgeom(p) for p in ps])
        return float(shapely.area(shapely.intersection(u, fp)) / shapely.area(fp))


# --- D2: the right label --------------------------------------------------------------------------------------------

def label_fixes(ctx, bld, pois):
    """Real schools get the school label (R1, R3), vocational schools labelled university become School (R2, R4).
    Returns {building_id: new labels}, {poi_id: new labels}, {building_id or poi_id: forced school types}, and the log."""
    R, rx = ctx.R, ctx.rx
    alk_school, uses_u = set(R['school_alkis']), set(R['univ_uses'])
    bl, pl, forced, log = {}, {}, {}, []
    zoned = bld['zone_idx'].notna() if 'zone_idx' in bld.columns else pd.Series(True, index=bld.index)
    for bid, labels, z in zip(bld['building_id'], bld['labels'], zoned):
        L = set(labels)
        fa = float(ctx.B.at[bid, 'floor_area_m2']) if 'floor_area_m2' in ctx.B.columns else np.inf
        names = ctx.bnames(bid) + ctx.own_names(bid) + ctx.site_names(bid)
        # R1: a school typed after a tenant (its Mensa, its Kita) or labelled lessons: ALKIS school, school evidence, at least the floor
        if (z and ctx.fun(bid) in alk_school and 'school' not in L and 'university' not in L and fa >= R['add_school_min_floor_m2']):
            ev = [w for w, ok in (('OSM school outline', ctx.twin(bid, ('school',))),
                                  ('school site', ctx.sites(bid)['poi_use'].eq('school').any()),
                                  ('school name', any(rx['school_name'].search(fold(n)) for n in names))) if ok]
            if ev and not rx['replaced_use'].search(_join(names + [ctx.B.at[bid, 'llm_type']])):
                bl[bid] = tuple(labels) + ('school',)
                log.append(('R1', bid, '', 'school added', f"{', '.join(ev)}; {fa:,.0f} m2; {ctx.B.at[bid, 'llm_type']}"[:150]))
                continue
        # R3: a school labelled lessons only
        if (z and 'lessons' in L and 'school' not in L and 'university' not in L and ctx.twin(bid, ('school',))
                and re.search(r'school|schul', fold(ctx.B.at[bid, 'llm_type']))
                and not rx['lessons_not_school'].search(_join(ctx.bnames(bid) + ctx.own_names(bid) + [ctx.B.at[bid, 'llm_type']]))
                and not rx['replaced_use'].search(_join(ctx.bnames(bid) + ctx.own_names(bid) + [ctx.B.at[bid, 'llm_type']]))):
            bl[bid] = tuple(labels) + ('school',)
            log.append(('R3', bid, '', 'school added', str(ctx.B.at[bid, 'llm_type'])[:150]))
            continue
        # R2 / R4 on a building's university label (its building or rest unit)
        if 'university' in L:
            hit = _vocational_univ(ctx, bid, None)
            if hit:
                bl[bid] = tuple('school' if l == 'university' else l for l in labels)
                forced[bid] = ('vocational',)
                log.append((hit[0], bid, '', 'university -> school (vocational)', hit[1]))
    for pid, bid, labels in zip(pois['poi_id'], pois['building_id'], pois['labels']):
        if 'university' in labels:
            hit = _vocational_univ(ctx, bid, pid)
            if hit:
                pl[pid] = tuple('school' if l == 'university' else l for l in labels)
                forced[pid] = ('vocational',)
                log.append((hit[0], bid, pid, 'university -> school (vocational)', hit[1]))
    # a fixed POI fixes its building's label too where no other POI of the building still carries university - else a rest unit
    # would bring University back
    bl0 = dict(zip(bld['building_id'], bld['labels']))
    for bid, g in pois[pois['poi_id'].isin(list(pl))].groupby('building_id'):
        L = bl.get(bid, bl0[bid])
        others = pois[(pois['building_id'] == bid) & ~pois['poi_id'].isin(list(pl))]['labels']
        if 'university' in L and not any('university' in t for t in others):
            bl[bid] = tuple('school' if l == 'university' else l for l in L)
            forced[bid] = ('vocational',)
            log.append(('R2', bid, '', 'university -> school (vocational), after its POI', ', '.join(g['poi_id'])))
    return bl, pl, forced, pd.DataFrame(log, columns=['rule', 'building_id', 'poi_id', 'change', 'evidence'])


def _vocational_univ(ctx, bid, pid):
    """R2: ALKIS vocational school or a vocational word in the unit's own names / type, no university, Akademie or
    Berufsfoerderungswerk; R4: ALKIS university code, but an OSM school outline and a school site and no university POI or name"""
    rx = ctx.rx
    if pid is not None:
        names, typ = [ctx.P.at[pid, 'name']], ctx.P.at[pid, 'poi_type']
    else:
        names, typ = ctx.bnames(bid) + ctx.own_names(bid), ctx.B.at[bid, 'llm_type']
    txt = _join(names + [typ])
    if ((ctx.fun(bid) == '31001_3022' or rx['vocational_word'].search(txt))
            and not rx['not_vocational'].search(_join(names)) and not rx['not_vocational_type'].search(fold(typ))):
        return 'R2', txt[:150]
    if (pid is None and ctx.fun(bid) == '31001_3023' and ctx.twin(bid, ('school',)) and ctx.sites(bid)['poi_use'].eq('school').any()
            and not ctx.owns(bid)['poi_use'].isin(ctx.R['univ_uses']).any()
            and not rx['univ_word'].search(_join(ctx.bnames(bid) + ctx.own_names(bid)))):
        return 'R4', 'sites: ' + '; '.join(ctx.site_names(bid))[:140]
    return None


# --- D1 / D3: drops -------------------------------------------------------------------------------------------------

def drops(ctx, uo, fixed=frozenset()):
    """The units that lose an education label: one row per unit and label with the rule and its evidence. fixed: (unit_id, label)
    pairs a label fix gave - never dropped."""
    rows = []
    for c, lab in EDU_LABELS.items():
        sel = uo[uo['labels'].map(lambda t, lab=lab: lab in t).astype(bool)]
        for uid, bid, kind in zip(sel['unit_id'], sel['building_id'], sel['kind']):
            if (uid, lab) in fixed:
                continue
            hit = {'School': _drop_school, 'University': _drop_univ, 'Kindergarten': _drop_kita}[c](ctx, uid, bid, kind)
            if hit:
                rows.append((uid, bid, kind, lab, c, hit[0], hit[1][:160]))
    return pd.DataFrame(rows, columns=['unit_id', 'building_id', 'kind', 'label', 'category', 'rule', 'evidence'])


def _drop_school(ctx, uid, bid, kind):
    R, rx = ctx.R, ctx.rx
    alk = ctx.fun(bid) in set(R['school_alkis'])
    feats = ctx.feats(uid, bid, kind)
    s = ctx.sites(bid)
    # S-N (D3) first: a non-teaching part of a school site
    if kind == 'poi':
        names, typ = [ctx.P.at[uid, 'name']], ctx.P.at[uid, 'poi_type']
    else:
        names, typ = ctx.bnames(bid), ctx.B.at[bid, 'llm_type']
    h = re.split(R['school_head_tail'], ctx.head(typ), maxsplit=1, flags=I)[0]
    fn = [fold(x) for x in names if isinstance(x, str)]
    what = None
    if any(rx['school_mensa_name'].search(x) for x in fn) or rx['school_mensa_head'].search(fold(h)):
        what = 'mensa'
    if any(rx['school_board_name'].search(x) for x in fn) or rx['school_other_head'].search(fold(h)):
        what = what or 'boarding / office / technical'
    if what and not rx['school_teaching_head'].search(fold(h)):
        mc = ctx.mensa_cover(bid) if (what == 'mensa' and kind != 'poi') else None
        if not (mc is not None and mc < R['mensa_min_cover']):
            return 'S-N', f"{what}: {' / '.join(fn)} | {h}"
    # S-C1: a former school
    why = []
    allf = list(s['poi_id']) + feats
    for pid in allf:
        if (ctx.tag(pid, 'abandoned') or '').lower() in ('yes', 'true', '1') or (ctx.tag(pid, 'disused') or '').lower() in ('yes', 'true', '1'):
            why.append(f'{pid} abandoned / disused')
        on = ctx.tag(pid, 'old_name')
        if on and 'schul' in fold(on) and ctx.use(pid) != 'school':
            why.append(f'old_name {on}')
    for x in ctx.covers(bid, 0.5).itertuples(index=False):
        if x.ruins:
            why.append(f'OSM outline {x.building}')
        if isinstance(x.old_name, str) and 'schul' in fold(x.old_name) and x.building != 'school' and x.amenity != 'school':
            why.append(f'OSM old_name {x.old_name}')
    nm = ctx.bnames(bid) + ctx.own_names(bid) + ctx.site_names(bid) + ([ctx.P.at[uid, 'name']] if kind == 'poi' else [])
    if not alk and any(rx['former_school_name'].search(fold(n)) for n in nm if isinstance(n, str)):
        why.append('an "Alte Schule" name')
    if why:
        return 'S-C1', '; '.join(why)
    # S-C2: a village or community house
    if not alk and (rx['village_house'].search(fold(ctx.B.at[bid, 'name'])) or rx['village_house'].search(fold(ctx.head(ctx.B.at[bid, 'llm_type'])))):
        o = ctx.owns(bid)
        if not any(u_ == 'school' and rx['school_type_word'].search(fold(n)) for u_, n in zip(o['poi_use'], o['name']) if isinstance(n, str)):
            return 'S-C2', f"{ctx.B.at[bid, 'name']} | {ctx.head(ctx.B.at[bid, 'llm_type'])}"
    # S-C3: adult or out-of-school education
    if kind == 'poi':
        nm0 = ctx.P.at[uid, 'name']
        de = [nm0] + ([] if rx['school_type_word'].search(fold(nm0)) else [ctx.B.at[bid, 'name']] + ctx.site_names(bid))
        en = [ctx.head(ctx.P.at[uid, 'poi_type'])]
    else:
        de, en = [ctx.B.at[bid, 'name'], ctx.B.at[bid, 'osm_twin_name']], [ctx.head(ctx.B.at[bid, 'llm_type'])]
    own_school = any(ctx.amenity(p) == 'school' for p in feats)
    if not own_school:                          # the adult name may sit on a sibling POI, the operator or the type's tail
        de = de + ctx.own_names(bid) + [ctx.tag(p, 'operator') for p in ctx.feats(uid, bid, 'building')]
        en = en + [ctx.P.at[uid, 'poi_type'] if kind == 'poi' else ctx.B.at[bid, 'llm_type']]
    jde, jen = _join(de), _join(en)
    m = rx['adult_education'].search(jde) or rx['adult_education'].search(jen)
    tagged = any(ctx.amenity(p) == 'prep_school' or ctx.tag(p, 'school:type') == 'artwork' for p in feats)
    if tagged or (m and not rx['school_type_word'].search(jde) and not rx['school_type_word_en'].search(jen)
                  and not rx['adult_education_keep'].search(jde)):
        return 'S-C3', f"{m.group(0) if m else 'tagged prep school / art'} | {jde[:70]} | {jen[:60]}"
    # S-C4: a Kita building
    hk = fold(ctx.head(ctx.B.at[bid, 'llm_type']))
    if not alk and rx['kita_type_en'].search(hk) and not rx['school_any'].search(hk):
        return 'S-C4', hk
    # S-C6: another occupant on a school site
    if kind != 'poi' and not alk:
        o = ctx.owns(bid)
        if len(o) and s['poi_use'].eq('school').any():
            ok_uses = set(R['other_occupant_ok_uses'])
            occupied = any(u_ in ok_uses or g_ in ('school', 'sport') or ctx.tag(p, 'historic')
                           or (p in ctx.PA.index and ctx.PA.at[p, 'poi_use_tag'] == 'historic') or 'hall' in str(u_)
                           for p, u_, g_ in zip(o['poi_id'], o['poi_use'], o['group'] if 'group' in o.columns else [''] * len(o)))
            h6 = re.split(R['type_tail'], ctx.head(ctx.B.at[bid, 'llm_type']), maxsplit=1, flags=I)[0]
            if not occupied and not rx['school_any'].search(fold(h6)):
                return 'S-C6', f"own POIs {list(o['poi_use'])} | {h6}"
    # S-C5: no school evidence at all, and no school nearby
    if not alk and not _school_evidence(ctx, uid, bid, kind) and not ctx.near_school(bid, R['near_school_m']):
        return 'S-C5', f"no school POI, site, tag, name or ALKIS function; {ctx.B.at[bid, 'llm_type']}"
    return None


def _school_evidence(ctx, uid, bid, kind):
    """any school evidence other than the model's label: a school POI or site, an OSM school tag, a school name"""
    rx = ctx.rx
    feats = ctx.feats(uid, bid, kind) + list(ctx.sites(bid)['poi_id'])
    if any(ctx.use(p) in ('school', 'college') or ctx.amenity(p) in ('school', 'college') for p in feats):
        return True
    if ctx.twin(bid, ('school', 'college')) or ctx.outline_use(bid, ('school', 'college')):
        return True
    return any(rx['school_any'].search(fold(n)) for n in ctx.all_names(uid, bid, kind) if isinstance(n, str))


def _kita(ctx, uid, bid, kind):
    rx, ku, su = ctx.rx, set(ctx.R['kita_uses']), set(ctx.R['social_uses'])
    feats = ctx.feats(uid, bid, kind)
    names = _join([ctx.P.at[uid, 'name']] if kind == 'poi' else ctx.bnames(bid) + ctx.own_names(bid))
    s = ctx.sites(bid)
    tag = (any(ctx.amenity(p) in ku or ctx.use(p) in ku for p in feats)
           or (kind != 'poi' and (ctx.twin(bid, ('kindergarten',)) or ctx.outline_use(bid, ('kindergarten',)))))
    return dict(names=names, strong=bool(rx['kita_strong'].search(names)), tag=tag,
                social=any(ctx.amenity(p) == 'social_facility' or ctx.use(p) in su for p in feats),
                kita_site=bool(s['poi_use'].isin(ku).any()), social_site=bool(s['poi_use'].isin(su).any()),
                notword=rx['kita_not'].search(names))


def _drop_kita(ctx, uid, bid, kind):
    rx = ctx.rx
    k = _kita(ctx, uid, bid, kind)
    if k['social'] and not k['tag'] and not k['strong']:
        return 'K1', 'social facility | ' + k['names']
    if kind != 'poi' and not (k['strong'] or k['tag']) and not k['kita_site'] and k['social_site']:
        return 'K1s', 'social-facility site | ' + k['names']
    if k['notword'] and not k['strong'] and not (kind == 'poi' and ctx.amenity(uid) == 'kindergarten'):
        return 'K2', k['notword'].group(0) + ' | ' + k['names']
    if kind == 'building' and not k['strong'] and not k['tag'] and k['kita_site']:
        why = []
        if re.match(ctx.R['kita_other_use_alkis'], ctx.fun(bid)):
            why.append(ctx.fun(bid))
        ou = set(ctx.R['kita_other_use_osm'])
        if ctx.twin(bid, ou) or ctx.outline_use(bid, ou):
            why.append('OSM outline of another use')
        if rx['kita_other_use_name'].search(fold(ctx.B.at[bid, 'name'])):
            why.append(f"name {ctx.B.at[bid, 'name']}")
        if ctx.owns(bid)['poi_use'].eq('fire_station').any():
            why.append('a fire-station POI')
        if why:
            return 'K3', 'a Kita lot on another use: ' + '; '.join(why)
    if kind != 'poi':
        allnames = _join(ctx.bnames(bid) + ctx.own_names(bid) + ctx.site_names(bid))
        if rx['all_day_school'].search(allnames + ' | ' + fold(ctx.B.at[bid, 'llm_type'])) and not rx['kita_strong'].search(allnames):
            return 'K6', 'all-day school programme | ' + allnames
        if not (rx['kita_strong'].search(allnames) or k['tag'] or k['kita_site'] or k['social'] or k['social_site']
                or rx['kita_not'].search(allnames)):
            return 'K4', f"no Kita evidence | {ctx.B.at[bid, 'llm_type']}"
    return None


def _drop_univ(ctx, uid, bid, kind):
    R, rx = ctx.R, ctx.rx
    if uid in set(R['univ_keep_ids']):
        return None
    texts = [ctx.P.at[uid, 'name'], ctx.P.at[uid, 'poi_type']] if kind == 'poi' else ctx.bnames(bid) + ctx.own_names(bid) + [ctx.B.at[bid, 'llm_type']]
    t = _join(texts)
    m = rx['continuing_education'].search(t)
    if m:
        return 'U2', m.group(0) + ' | ' + t
    # U6 (D3): a non-teaching part of a campus
    names, h = ([ctx.P.at[uid, 'name']], ctx.head(ctx.P.at[uid, 'poi_type'])) if kind == 'poi' else (ctx.bnames(bid), ctx.head(ctx.B.at[bid, 'llm_type']))
    tt = _join(names) + ' | ' + fold(h)
    m = rx['univ_non_teaching'].search(tt)
    d = rx['dining'].search(tt)
    if (m or d) and not rx['univ_teaching_head'].search(tt):
        if m:
            return 'U6', m.group(0) + ' | ' + tt
        mc = ctx.mensa_cover(bid) if kind != 'poi' else None
        if not (mc is not None and mc < R['mensa_min_cover']):
            return 'U6', d.group(0) + ' | ' + tt
    alk_u = ctx.fun(bid) in set(R['univ_alkis'])
    outline = ctx.twin(bid, set(R['univ_uses'])) or ctx.outline_use(bid, set(R['univ_uses']))
    if kind == 'rest' and not alk_u and not outline:
        return 'U5', f"rest unit; {ctx.fun(bid)} {ctx.B.at[bid, 'name']}"
    if bid in set(R['univ_drop_ids']):
        return 'U9', 'list'
    # U9: a residential building on a campus site only (no POI, no name; the site tagged university and residential)
    if (ctx.fun(bid).startswith('31001_1') and not ctx.owns(bid).shape[0] and not ctx.bnames(bid)):
        sp = ctx.sites(bid)
        if len(sp) and all(ctx.use(p) in set(R['univ_uses']) and (ctx.tag(p, 'landuse') == 'residential') for p in sp['poi_id']):
            return 'U9', 'a residential building whose only university link is a campus site tagged landuse=residential'
    if not alk_u and not outline:
        o, s = ctx.owns(bid), ctx.sites(bid)
        if not (o['poi_use'].isin(R['univ_uses']).any() or s['poi_use'].isin(R['univ_uses']).any()
                or rx['univ_word'].search(_join(ctx.bnames(bid) + ctx.own_names(bid) + ctx.site_names(bid)))):
            return 'U4', f"no university evidence | {ctx.fun(bid)} | {ctx.B.at[bid, 'llm_type']}"
    return None


# --- no join ---------------------------------------------------------------------------------------------------------

def no_join(ctx, uo, zero_school_zones):
    """School units in zones whose School target is 0 whose only school evidence is the ALKIS function or a bare OSM school
    outline - no school POI or site of their own, no school name - and no school POI or site within the distance: they join no
    neighbour and take no ring fallback."""
    R, rx = ctx.R, ctx.rx
    rows = []
    sel = uo[uo['labels'].map(lambda t: 'school' in t).astype(bool) & uo['zone_idx'].isin(zero_school_zones)]
    for uid, bid, kind in zip(sel['unit_id'], sel['building_id'], sel['kind']):
        feats = ctx.feats(uid, bid, kind) + list(ctx.sites(bid)['poi_id'])
        if any(ctx.amenity(p) in ('school', 'college') for p in feats):       # an operating school POI or site
            continue
        if any(rx['school_any'].search(fold(n)) for n in ctx.all_names(uid, bid, kind) if isinstance(n, str)):
            continue
        if ctx.near_school(bid, R['near_school_m'], general_only=False):
            continue
        ev = ', '.join(w for w, ok in (('ALKIS ' + ctx.fun(bid), ctx.fun(bid) in set(R['school_alkis'])),
                                       ('OSM school outline', ctx.twin(bid, ('school',)) or ctx.outline_use(bid, ('school',)))) if ok)
        rows.append((uid, bid, kind, ev or 'the model\'s label only'))
    return pd.DataFrame(rows, columns=['unit_id', 'building_id', 'kind', 'evidence'])


# --- D4: Kita weights ------------------------------------------------------------------------------------------------

def kita_weights(ctx, uo, *, fam_storeys, kita_cap_m2, n_active, even_split=True):
    """W1 the Kita part of a school weighs at most the Kita's own polygons (else the childcare point cap) and gives the rest to
    School; W2 a Kita polygon weighs at most its area x the storeys of its floor family where the building's Kita polygons cover
    less than the threshold, and a Kita point within the merge distance of such a polygon is the same facility (no Kita weight);
    W3 a squeezed Kita POI - its building's only Kita carrier, keeping less than the share of its own extent - weighs that extent.
    Returns unit_id, rule, the new Kindergarten weight, the weight given to School, and the evidence. Only the Kita weight changes."""
    R = ctx.R
    ku = set(R['kita_uses'])
    is_kita = lambda p: ctx.use(p) in ku or ctx.amenity(p) in ku
    k = uo[uo['labels'].map(lambda t: 'childcare' in t).astype(bool)].copy()
    kk = k['k_red'].clip(lower=1) if even_split else pd.Series(1.0, index=k.index)       # the split of section 5
    k['w'] = k['O'] / kk
    k['kk'] = kk
    out = {}
    # W1
    for r in k.itertuples(index=False):
        L, bid = set(r.labels), r.building_id
        kp = [r.unit_id] if r.kind == 'poi' else [p for p in ctx.owns(bid)['poi_id'] if is_kita(p)]
        oper = ctx.sites(bid)['poi_use'].eq('school').any() or ctx.owns(bid)['poi_use'].eq('school').any()
        a_ = 'school' in L or 'university' in L
        b_ = r.kind == 'building' and ctx.fun(bid) in set(R['school_alkis']) and oper and len(kp) > 0
        if not (a_ or b_):
            continue
        ext = sum(ctx.poly_area(p) for p in kp) if any(ctx.poly_area(p) > 0 for p in kp) else kita_cap_m2
        if ext < r.w - 1e-9:
            out[r.unit_id] = ('W1', ext, (r.w - ext) if 'school' in L else 0.0, f"Kita part of a school: {r.w:,.1f} -> {ext:,.1f} m2")
    # W2
    kp_units = k[k['kind'].eq('poi')]
    for bid, g in kp_units.groupby('building_id'):
        polys = [p for p in g['unit_id'] if ctx.kind(p) == 'area' and ctx.pgeom(p) is not None]
        if not polys:
            continue
        fp = ctx.B.at[bid, 'geometry']
        cov = float(shapely.area(shapely.intersection(shapely.union_all([ctx.pgeom(p) for p in polys]), fp)) / shapely.area(fp))
        if cov >= R['kita_polygon_max_cover']:
            continue
        for r in g.itertuples(index=False):
            if r.unit_id in out:
                continue
            if r.unit_id in polys:
                cap = ctx.poly_area(r.unit_id) * fam_storeys(r.family, bid) / r.kk
                if cap < r.w - 1e-9:
                    out[r.unit_id] = ('W2', cap, 0.0, f"Kita polygon covering {cov:.0%} of the building: {r.w:,.1f} -> {cap:,.1f} m2")
            elif ctx.pgeom(r.unit_id) is not None:
                d = min(float(shapely.distance(ctx.pgeom(r.unit_id), ctx.pgeom(p))) for p in polys)
                if d <= R['kita_point_merge_m']:
                    out[r.unit_id] = ('W2', 0.0, 0.0, f"Kita point {d:,.1f} m from a Kita polygon of the building: the same facility")
    # W3
    n_k = k.groupby('building_id')['unit_id'].nunique()
    for r in kp_units.itertuples(index=False):
        if r.unit_id in out or n_k[r.building_id] != 1:
            continue
        bid = r.building_id
        if ctx.kind(r.unit_id) == 'area' and ctx.pgeom(r.unit_id) is not None:
            ext = float(shapely.area(shapely.intersection(ctx.pgeom(r.unit_id), ctx.B.at[bid, 'geometry'])))
        else:
            ext = min(R['kita_median_part_m2'], float(ctx.B.at[bid, 'floor_area_m2']) / max(n_active.get(bid, 1), 1),
                      float(ctx.B.at[bid, 'area_m2']))
        if r.O < R['kita_squeezed_share'] * ext:
            out[r.unit_id] = ('W3', ext / r.kk, 0.0, f"a squeezed Kita: {r.O:,.1f} m2 -> {ext:,.1f} m2")
    return pd.DataFrame([(u, *v) for u, v in out.items()], columns=['unit_id', 'rule', 'kita_weight', 'to_school', 'evidence'])


# --- D2: the right school types --------------------------------------------------------------------------------------

def _grades(g):
    out, nums = set(), []
    if not isinstance(g, str):
        return out
    for part in re.split(r'[;,]', g):
        m = re.fullmatch(r'\s*(\d+)\s*-\s*(\d+)\s*', part)
        if m:
            nums += list(range(int(m.group(1)), int(m.group(2)) + 1))
        elif re.fullmatch(r'\s*\d+\s*', part):
            nums.append(int(part))
    for n in nums:
        out.add('primary' if 1 <= n <= 4 else 'secondary' if 5 <= n <= 13 else None)
    return out - {None}


def _isced(v):
    """the general types an isced:level value names, and whether it names level 3"""
    if not isinstance(v, str):
        return set(), False
    parts = [p.strip() for p in re.split(r'[;,]', v)]
    return {{'1': 'primary', '2': 'secondary'}[p] for p in parts if p in ('1', '2')}, '3' in parts


def type_fixes(ctx, sch, st, *, school_type_rx):
    """sch: the School units (unit_id, building_id, kind); st: {unit_id: (types, from)} as nb08-16 computed them. Returns
    {unit_id: (types, rule, evidence)}: T-isced (the OSM isced:level / grades of the unit's own school POI or its site name one general
    type), T-list (the Oskar-Kaemmer sites are vocational), then T-campus (a unit typed only by ALKIS or the default on a named
    vocational school site whose name-typed units are all vocational only)."""
    rx = ctx.rx
    new = {}
    cur = {u: tuple(t) for u, (t, _) in st.items()}
    frm = {u: f for u, (_, f) in st.items()}
    from_lib = school_type_rx
    for uid, bid, kind in sch[['unit_id', 'building_id', 'kind']].itertuples(index=False):
        if frm.get(uid) in ('name', 'label fix'):
            continue
        if kind == 'poi':
            own = [uid] if (ctx.use(uid) == 'school' or ctx.amenity(uid) == 'school') else []
            if from_lib(ctx.P.at[uid, 'name']):
                continue
        else:
            o = ctx.owns(bid)
            own = list(o.loc[o['poi_use'].eq('school'), 'poi_id'])
        found = None
        for pids in (own, list(ctx.sites(bid).loc[ctx.sites(bid)['poi_use'].eq('school'), 'poi_id'])):
            ts, gen, has3, why = set(), set(), False, []
            for p in pids:
                a, h3 = _isced(ctx.tag(p, 'isced:level'))
                b = _grades(ctx.tag(p, 'grades'))
                has3 |= h3
                gen |= a
                if a or b or h3:
                    why.append(f"{p}: isced {ctx.tag(p, 'isced:level')} grades {ctx.tag(p, 'grades')}")
                ts |= a | b
            if ts or has3:
                found = (ts, gen, has3, why)
                break
        if not found:
            continue
        ts, gen, has3, why = found
        if (has3 and not gen) or len(ts) != 1:     # upper secondary alone may be general or vocational: no reading
            continue
        t = tuple(ts)
        if t != cur.get(uid) and not (cur.get(uid) == ('vocational',) and t == ('secondary',)):
            new[uid] = (t, 'T-isced', '; '.join(why))
    for uid, bid, kind in sch[['unit_id', 'building_id', 'kind']].itertuples(index=False):
        names = ([ctx.P.at[uid, 'name']] if kind == 'poi' else ctx.bnames(bid) + ctx.own_names(bid)) + ctx.site_names(bid)
        if (any(rx['oskar_kaemmer'].search(fold(n)) for n in names if isinstance(n, str))
                and not any(rx['oskar_kaemmer_not_site'].search(fold(n)) for n in ctx.site_names(bid))):
            if cur.get(uid) != ('vocational',):
                new[uid] = (('vocational',), 'T-list', 'an Oskar-Kaemmer site')
    # T-campus on the types after the rules above
    cur2 = {u: (new[u][0] if u in new else cur.get(u, ())) for u in cur}
    frm2 = {u: ('name' if u in new else frm.get(u)) for u in frm}
    by_site = {}
    for uid, bid in sch[['unit_id', 'building_id']].itertuples(index=False):
        s = ctx.sites(bid)
        for pid, nm in zip(s['poi_id'], s['name']):
            if ctx.use(pid) == 'school' and isinstance(nm, str) and nm.strip():
                by_site.setdefault((pid, nm), []).append((uid, bid))
    for (pid, nm), us in by_site.items():
        gen = _isced(ctx.tag(pid, 'isced:level'))[0] or set()
        if gen or any(n <= 10 for n in _grade_numbers(ctx.tag(pid, 'grades'))):
            continue                                        # the site itself says it is a general school
        named = [u for u, _ in us if frm2.get(u) in ('name', 'building')]
        if not named or not all(cur2.get(u) == ('vocational',) for u in named):
            continue
        for uid, bid in us:
            if frm2.get(uid) not in ('ALKIS', 'none') or uid in new:
                continue
            if any('schul' in fold(n) and fold(n) != fold(nm) for n in ctx.bnames(bid)):
                continue
            if cur2.get(uid) != ('vocational',):
                new[uid] = (('vocational',), 'T-campus', f'on the vocational site {nm}')
    return new


def _grade_numbers(g):
    nums = []
    if not isinstance(g, str):
        return nums
    for part in re.split(r'[;,]', g):
        m = re.fullmatch(r'\s*(\d+)\s*-\s*(\d+)\s*', part)
        if m:
            nums += list(range(int(m.group(1)), int(m.group(2)) + 1))
        elif re.fullmatch(r'\s*\d+\s*', part):
            nums.append(int(part))
    return nums
