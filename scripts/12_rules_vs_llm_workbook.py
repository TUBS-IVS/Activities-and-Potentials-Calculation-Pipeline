"""Step 12 for reading: every validated place with the human ground truth, the LLM's answer and the rules' answer side
by side - config.RULES_VS_LLM_WORKBOOK (data/output/12_rules_vs_llm_side_by_side.xlsx).

The places, the truth and the scoring are notebook 12's: FINAL's validation units on kept buildings (09_validation.gpkg,
layer units), the LLM's answers from FINAL's 06, the rules' from notebook 11 (the main run, own and site POIs), scored
with FINAL's lib/validation.py. Sheets:
  Summary         the scores and how to read them
  Building class  one row per place with a class in the truth
  Activities      one row per place with an activity truth
  Notes           definitions, the label maps, the class catalogue, the inputs
A place's check marks, 'Original answer' and 'Who is right' are Excel formulas over its text cells, and every score is a
formula over those, so they follow an edited cell and, in rows 3-4 of the place sheets, the filter. After writing, a
hidden Excel instance of its own recalculates and saves the file (so a viewer without a calculation engine shows the
values), and the stored values are checked against the Python scoring.

Run from the repository root:   python scripts/12_rules_vs_llm_workbook.py
The recalculation and check need Windows with Microsoft Excel and pywin32; elsewhere the file is written unchecked and
calculates when it is opened.
FINAL is only read: its GeoPackages are opened immutable and its modules are loaded without writing bytecode.
"""
import datetime
import hashlib
import importlib.util
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule, DataBarRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.hyperlink import Hyperlink
from openpyxl.worksheet.table import Table, TableStyleInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import *  # the RULES config: FINAL's paths, notebook 11's output, the bootstrap settings, the workbook path


def _load(name, path):
    """a module of the FINAL pipeline, by file path and under its own name, so it never shadows this config"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.dont_write_bytecode = True          # loading FINAL's modules must leave no __pycache__ in FINAL
FC = _load('final_config', FINAL_CONFIG_FILE)
V = _load('final_validation', FINAL_VALIDATION_LIB)

NM = FC.BOSSERHOF_NORMALIZATION_MAP
SIX = list(FC.VALIDATION_SCORED_CATEGORIES)
S6 = frozenset(SIX)
HEAD = V.class_headlines(FC.LLM_BOSSERHOF_SUBCATEGORIES, NM)
MAPS = {'old': FC.VALIDATION_OLD_LABEL_MERGE, 'final': FC.MID_LABEL_TO_ACTIVITY}
LABELS = list(FC.VALIDATION_OLD_LABEL_MERGE)            # the twelve MiD labels, in the merge's order
OWN_ROLES = ('point', 'footprint', 'unit')              # POIs placed on the building; 'site' = a campus or plant around it
FIRST = 7                                               # first data row of a place sheet
OUT = RULES_VS_LLM_WORKBOOK
TMP = OUT.with_name(OUT.stem + '.unverified.xlsx')        # written and checked first, renamed to OUT when the check passes


def _writable(path):
    """False while Excel has the workbook open (Excel locks it)"""
    if not path.exists():
        return True
    try:
        with open(path, 'r+b'):
            return True
    except PermissionError:
        return False


if not _writable(OUT):
    sys.exit(f'{OUT} is open in Excel: close it and run again')

# class key (after FINAL's norm_class) -> the catalogue's wording
SHOW = {}
for _h, _subs in FC.LLM_BOSSERHOF_SUBCATEGORIES.items():
    SHOW[V.norm_class(_h, NM)] = _h
    for _s in _subs:
        SHOW[V.norm_class(_s, NM)] = _s
SHOW['others industrial'] = 'others (industrial)'       # the catalogue's bare "others" under Industrial operations
assert len(set(SHOW.values())) == len(SHOW)
RANK = {k: i for i, k in enumerate(SHOW)}
LAYER = {'poi_tags': 'POI tags', 'alkis_code': 'ALKIS code', 'osm_fallback': 'OSM building / land use',
         'no_signal': 'no signal'}
EVIDENCE = {'poi_or_site': 'POI or site', 'tag_only': 'OSM tag only', 'name_only': 'name only',
            'class_only': 'cadastre class only'}
ROUTE = {'own call': 'own call', 'signature, own record': 'asked for its group',
         'signature, copied': 'copied from its group'}


# ── 1. the places, the truth and the two answers, as notebook 12 ─────────────────────────────────────────────────────
def _txt(x):
    """a text cell with runs of whitespace as one space, or None when missing or blank"""
    return ' '.join(x.split()) if isinstance(x, str) and x.strip() else None


def _set(text):
    """a set stored as 'a;b' text -> frozenset; a missing cell stays None (no truth); '' is the empty set"""
    return frozenset(s for s in text.split(';') if s) if isinstance(text, str) else None


def _key(c):
    """FINAL's norm_class; no class stays None (scored as a miss)"""
    return V.norm_class(c, NM) if isinstance(c, str) and c else None


def _obj(values, index):
    """object column that keeps None and frozensets as they are"""
    return pd.Series(list(values), index=index, dtype=object)


def _unique(items, fold=False):
    """the items that are not empty, without repeats, in order (fold: ignoring case)"""
    seen, out = set(), []
    for x in items:
        if not x:
            continue
        k = x.lower() if fold else x
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


units = pyogrio.read_dataframe(FINAL_VALIDATION_FILE, layer='units', IMMUTABLE='YES')
vrows = pyogrio.read_dataframe(FINAL_VALIDATION_FILE, layer='rows', read_geometry=False, IMMUTABLE='YES',
                               columns=['row', 'Status_B', 'Comment_B', 'Status_D', 'Comment_D'])
assert vrows['row'].is_unique
vrows = vrows.set_index('row')
b06 = pyogrio.read_dataframe(FINAL_CLASSIFIED_FILE, layer='buildings', read_geometry=False, IMMUTABLE='YES',
                             columns=['building_id', 'label_en', 'name', 'address', 'city', 'evidence', 'llm_type',
                                      'llm_labels', 'bosserhof_class', 'llm_confidence', 'llm_reason']
                             ).set_index('building_id')
pois = pyogrio.read_dataframe(FINAL_CLASSIFIED_FILE, layer='building_pois', read_geometry=False, IMMUTABLE='YES',
                              columns=['building_id', 'poi_id', 'poi_role', 'poi_use', 'name', 'parent_name',
                                       'share_in_building'])
rules = pd.read_parquet(RULES_ON_FINAL_FILE).set_index('building_id')
assert rules.index.is_unique and set(rules.index) == set(b06.index), 'the rules and the LLM did not answer the same buildings'

ev = units[units['kept']].copy()
assert ev['building_id'].is_unique and ev['building_id'].isin(b06.index).all(), 'a kept unit is missing from 06'
for _c in ('act_truth', 'cls_truth', 'old_set'):
    ev[_c] = _obj(map(_set, ev[_c]), ev.index)
ev['old_class'] = _obj((c if isinstance(c, str) and c else None for c in ev['old_class']), ev.index)
_bid = ev['building_id']
ev['k06'] = _obj((_key(c) for c in _bid.map(b06['bosserhof_class'])), ev.index)
ev['kr'] = _obj((_key(c) for c in _bid.map(rules['cls_sites'])), ev.index)
ev['lab06'] = _obj(_bid.map(b06['llm_labels']), ev.index)
ev['labr'] = _obj(_bid.map(rules['labels_sites']), ev.index)
ev['layer'] = _obj(_bid.map(rules['layer_sites']), ev.index)
assert all((s if isinstance(s, str) else None) == k for s, k in zip(ev['cls_06'], ev['k06'])), \
    "09_validation.gpkg is out of step with FINAL's 06 - re-run FINAL notebook 09 first"
_off = sorted({k for k in list(ev['k06']) + list(ev['kr']) if k is not None} - set(HEAD))
assert not _off, f'answers outside the catalogue after normalisation: {_off}'
ev['first_row'] = [min(int(r) for r in str(x).split(';')) for x in ev['rows']]

bh = ev[[isinstance(t, frozenset) and len(t) > 0 for t in ev['cls_truth']]].copy()      # Bosserhof: a class in the truth
ac = ev[[isinstance(t, frozenset) for t in ev['act_truth']]].copy()                      # activities: any truth
for a in ('06', 'r'):
    _hits = [V.class_hits(t, k, HEAD) for t, k in zip(bh['cls_truth'], bh[f'k{a}'])]
    bh[f'ex{a}'] = [h[0] for h in _hits]
    bh[f'hd{a}'] = [h[1] for h in _hits]
bh['orig'] = [o in t for o, t in zip(bh['old_class'], bh['cls_truth'])]
ac['t6'] = _obj((t & S6 for t in ac['act_truth']), ac.index)
for a in ('06', 'r'):
    for m, mp in MAPS.items():
        ac[f'p{a}_{m}'] = _obj((V.to_categories(s, mp) & S6 for s in ac[f'lab{a}']), ac.index)
ac['orig'] = [t == ((o or frozenset()) & S6) for t, o in zip(ac['t6'], ac['old_set'])]


# ── 2. the scores in Python: what the workbook's formulas must give ─────────────────────────────────────────────────
def mcnemar(x, y):
    """exact two-sided McNemar test for paired hits: (right only by x, right only by y, p) - notebook 12's"""
    x, y = np.asarray(x, bool), np.asarray(y, bool)
    b, c = int((x & ~y).sum()), int((~x & y).sum())
    n, k = b + c, min(b, c)
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n) if n else 1.0
    return b, c, p


def _counts(frame, col):
    """per place: right, extra and missed categories (tp, fp, fn) over the six"""
    return np.array([[len(t & p), len(p - t), len(t - p)] for t, p in zip(frame['t6'], frame[col])]).reshape(-1, 3)


def _f1(c):
    return 2 * c[..., 0] / (2 * c[..., 0] + c[..., 1] + c[..., 2])


def micro(frame, col):
    tp, fp, fn = _counts(frame, col).sum(axis=0)
    return tp / (tp + fp), tp / (tp + fn), 2 * tp / (2 * tp + fp + fn)


def boot_diff(frame, col_x, col_y):
    """micro F1 of x minus y in points, a 95 % percentile interval and a two-sided p from a paired bootstrap -
    notebook 12's, with the same seed, resamples and order of the places"""
    cx, cy = _counts(frame, col_x), _counts(frame, col_y)
    rng = np.random.default_rng(RULES_VS_LLM_SEED)
    idx = rng.integers(0, len(frame), size=(RULES_VS_LLM_BOOTSTRAP, len(frame)))
    d = 100 * (_f1(cx[idx].sum(axis=1)) - _f1(cy[idx].sum(axis=1)))
    lo, hi = np.percentile(d, [2.5, 97.5])
    p = min(1.0, 2 * min((d <= 0).mean(), (d >= 0).mean()))
    return 100 * (_f1(cx.sum(axis=0)) - _f1(cy.sum(axis=0))), lo, hi, p


SUBSETS = (('all', None), ('accepted', True), ('rejected', False))
EXP_CLS = {}
for _name, _flag in SUBSETS:
    _f = bh if _flag is None else bh[bh['orig'] == _flag]
    _b, _c, _p = mcnemar(_f['ex06'], _f['exr'])
    _bh, _ch, _ph = mcnemar(_f['hd06'], _f['hdr'])
    EXP_CLS[_name] = {'n': len(_f), 'ex06': float(np.mean(_f['ex06'])), 'exr': float(np.mean(_f['exr'])),
                      'b': _b, 'c': _c, 'p': _p, 'hd06': float(np.mean(_f['hd06'])), 'hdr': float(np.mean(_f['hdr'])),
                      'bh': _bh, 'ch': _ch, 'ph': _ph}
EXP_ACT = {}
for _name, _flag, _m in (('all', None, 'old'), ('accepted', True, 'old'), ('rejected', False, 'old'),
                         ('all_final', None, 'final')):
    _f = ac if _flag is None else ac[ac['orig'] == _flag]
    _P0, _R0, _F0 = micro(_f, f'p06_{_m}')
    _P1, _R1, _F1 = micro(_f, f'pr_{_m}')
    EXP_ACT[_name] = {'n': len(_f), 'P06': _P0, 'R06': _R0, 'F06': _F0, 'Pr': _P1, 'Rr': _R1, 'Fr': _F1,
                      'diff': 100 * (_F0 - _F1),
                      'ex06': float(np.mean([t == p for t, p in zip(_f['t6'], _f[f'p06_{_m}'])])),
                      'exr': float(np.mean([t == p for t, p in zip(_f['t6'], _f[f'pr_{_m}'])]))}
# the same numbers through FINAL's own scoring functions
_s = V.class_scores(bh, 'cls_truth', 'k06', HEAD)
assert math.isclose(_s['exact_%'], 100 * EXP_CLS['all']['ex06']) and math.isclose(_s['headline_%'], 100 * EXP_CLS['all']['hd06'])
_d, _ = V.set_scores(ac['act_truth'], ac['p06_old'], SIX)
assert math.isclose(_d.set_index('category').loc['micro', 'f1'], EXP_ACT['all']['F06'])
BOOT = {m: boot_diff(ac, f'p06_{m}', f'pr_{m}') for m in MAPS}
POI_SHARE = (float(np.mean([x == 'poi_tags' for x in bh['layer']])), float((rules['layer_sites'] == 'poi_tags').mean()))


# ── 3. what a place's row shows ──────────────────────────────────────────────────────────────────────────────────────
def show_cls(k):
    return '(no class)' if k is None else SHOW.get(k, k)


def show_head(k):
    return '–' if k is None else SHOW.get(HEAD[k], HEAD[k])


def show_truth(ks):
    return ' | '.join(show_cls(k) for k in sorted(ks, key=lambda k: (RANK.get(k, len(RANK)), k)))


def show_truth_heads(ks):
    return ' | '.join(_unique(show_head(k) for k in sorted(ks, key=lambda k: (RANK.get(HEAD[k], len(RANK)), k))))


def show_cats(s):
    return ', '.join(c for c in SIX if c in s)


def show_act_truth(t):
    """a truth or the original answer in the six categories; 'work only' and 'no activity' where none of them"""
    if t is None:
        return '(none)'
    return show_cats(t & S6) if t & S6 else ('no activity' if not t else 'work only')


def show_pred(p6):
    return show_cats(p6) if p6 else '–'


def show_labels(labels):
    """the MiD labels without 'work' (both pipelines add it by rule; it is not scored), in a fixed order"""
    ls = {lab for lab in labels.split(';') if lab and lab != 'work'} if isinstance(labels, str) else set()
    ls = sorted(ls, key=lambda lab: (LABELS.index(lab) if lab in LABELS else len(LABELS), lab))
    return ', '.join(ls) if ls else '–'


def miss_extra(t6, p6):
    parts = []
    if t6 - p6:
        parts.append('missed ' + show_cats(t6 - p6))
    if p6 - t6:
        parts.append('extra ' + show_cats(p6 - t6))
    return ' · '.join(parts)


def _poi(r, site=False):
    name, use = _txt(r['name']), _txt(r['poi_use']) or 'POI'
    where = f', in {_txt(r["parent_name"])}' if r['poi_role'] == 'unit' and _txt(r['parent_name']) else ''
    text = f'{name} ({use}{where})' if name else f'({use}{where})'
    return f'site: {text}' if site else text


pois = pois[pois['building_id'].isin(set(ev['building_id']))].copy()
pois['own'] = pois['poi_role'].isin(OWN_ROLES)
pois['share'] = pd.to_numeric(pois['share_in_building'], errors='coerce').fillna(0.0)
pois = pois.sort_values(['building_id', 'own', 'share', 'name', 'poi_id'], ascending=[True, False, False, True, True],
                        na_position='last')
POIS = {}
for _b, _g in pois.groupby('building_id', sort=False):
    _recs = _g.to_dict('records')
    _own = [r for r in _recs if r['own']]
    _site = [r for r in _recs if not r['own']]
    POIS[_b] = (_unique([_poi(r) for r in _own] + [_poi(r, True) for r in _site]),
                _unique([_txt(r['name']) for r in _own], fold=True), _unique([_txt(r['name']) for r in _site], fold=True))
_ll = units.loc[ev.index].geometry.representative_point().to_crs(4326)
MAP = {b: f'https://www.google.com/maps/place/{y:.6f},{x:.6f}/@{y:.6f},{x:.6f},19z'
       for b, x, y in zip(ev['building_id'], _ll.x, _ll.y)}


def place_text(b):
    """the building's name or its POIs' names, else the site's, else the address"""
    _, names, sites = POIS.get(b, ([], [], []))
    names = _unique([_txt(b06.at[b, 'name'])] + names, fold=True)
    if names:
        return ' · '.join(names[:2]) + (f' (+{len(names) - 2} more)' if len(names) > 2 else '')
    if sites:
        return f'site: {sites[0]}'
    return _txt(b06.at[b, 'address']) or '(no name or address)'


def pois_text(b, limit=8):
    entries = POIS.get(b, ([], [], []))[0]
    if not entries:
        return '–'
    return '; '.join(entries[:limit]) + (f'; +{len(entries) - limit} more' if len(entries) > limit else '')


def verdict(rows_text, dim):
    """the validator's verdict and typed text on the original answer, per sheet row of the place"""
    status, comment = ('Status_D', 'Comment_D') if dim == 'class' else ('Status_B', 'Comment_B')
    rows = [int(r) for r in str(rows_text).split(';')]
    parts = []
    for r in rows:
        s, c = _txt(vrows.at[r, status]) or '–', _txt(vrows.at[r, comment])
        text = f'{s}: {c}' if c else s
        parts.append(f'row {r}: {text}' if len(rows) > 1 else text)
    return ' | '.join(parts), any(_txt(vrows.at[r, comment]) for r in rows)


def common(u):
    b = u['building_id']
    city = _txt(b06.at[b, 'city'])
    return {'place': place_text(b), 'city': re.sub(r'\s*,\s*(Stadt|Flecken)$', '', city) if city else '–', 'map': MAP[b],
            'alkis': _txt(b06.at[b, 'label_en']) or '–', 'address': _txt(b06.at[b, 'address']) or '–', 'bid': b,
            'rows': str(u['rows']).replace(';', ', '), 'pois': pois_text(b),
            'l_type': _txt(b06.at[b, 'llm_type']) or '–', 'l_conf': _txt(b06.at[b, 'llm_confidence']) or '–',
            'l_evid': EVIDENCE.get(b06.at[b, 'evidence'], _txt(b06.at[b, 'evidence']) or '–'),
            'l_route': ROUTE.get(u['route_copied'], _txt(u['route_copied']) or '–'),
            'reason': _txt(b06.at[b, 'llm_reason']) or '–', 'r_layer': LAYER.get(u['layer'], u['layer'] or '–'),
            'l_cls': show_cls(u['k06']), 'r_cls': show_cls(u['kr'])}


def _mark(exact, near):
    return '✓' if exact else ('≈' if near else '✗')


CLS_ROWS = []
for _i, (_, _u) in enumerate(bh.sort_values('first_row', kind='stable').iterrows(), 1):
    _r = common(_u)
    _v, _typed = verdict(_u['rows'], 'class')
    _r.update(n=_i, t_cls=show_truth(_u['cls_truth']), t_head=show_truth_heads(_u['cls_truth']),
              o_cls=SHOW.get(_u['old_class'], _u['old_class']) if _u['old_class'] else '(none)',
              l_head=show_head(_u['k06']), r_head=show_head(_u['kr']), verdict=_v)
    _r['_notes'] = {'l_cls': f"LLM's reason ({_r['l_conf']} confidence): {_r['reason']}"}
    if _typed:
        _r['_notes']['t_cls'] = f'Validator on the original class: {_v}'
    _lm, _rm = _mark(_u['ex06'], _u['hd06']), _mark(_u['exr'], _u['hdr'])
    _r['_expect'] = {'o_ok': 'matches' if _u['orig'] else 'differs', 'l_mark': _lm, 'r_mark': _rm,
                     't_head': _r['t_head'], 'l_head': _r['l_head'], 'r_head': _r['r_head'],
                     'who': ('both right' if _lm == _rm == '✓' else 'only LLM right' if _lm == '✓'
                             else 'only rules right' if _rm == '✓' else 'neither')}
    CLS_ROWS.append(_r)

ACT_ROWS = []
for _i, (_, _u) in enumerate(ac.sort_values('first_row', kind='stable').iterrows(), 1):
    _r = common(_u)
    _v, _typed = verdict(_u['rows'], 'act')
    _t6 = _u['t6']
    _r.update(n=_i, t_act=show_act_truth(_u['act_truth']), o_act=show_act_truth(_u['old_set']),
              l_lab=show_labels(_u['lab06']), l_act=show_pred(_u['p06_old']), l_miss=miss_extra(_t6, _u['p06_old']),
              r_lab=show_labels(_u['labr']), r_act=show_pred(_u['pr_old']), r_miss=miss_extra(_t6, _u['pr_old']),
              l_actf=show_pred(_u['p06_final']), r_actf=show_pred(_u['pr_final']), verdict=_v)
    _r['_notes'] = {'l_lab': f"LLM's reason ({_r['l_conf']} confidence): {_r['reason']}"}
    if _typed:
        _r['_notes']['t_act'] = f'Validator on the original activities: {_v}'
    _exp = {'o_ok': 'matches' if _u['orig'] else 'differs'}
    _err = {}
    for a, side in (('06', 'l'), ('r', 'r')):
        for m, sfx in (('old', ''), ('final', 'f')):
            p6 = _u[f'p{a}_{m}']
            tp, fp, fn = len(_t6 & p6), len(p6 - _t6), len(_t6 - p6)
            _exp.update({f'{side}tp{sfx}': tp, f'{side}fp{sfx}': fp, f'{side}fn{sfx}': fn})
            if m == 'old':
                _exp[f'{side}_mark'] = '✓' if fp + fn == 0 else ('≈' if tp else '✗')
                _err[side] = fp + fn
    _exp['who'] = ('both right' if _err['l'] == _err['r'] == 0 else 'only LLM right' if _err['l'] == 0
                   else 'only rules right' if _err['r'] == 0 else 'LLM closer' if _err['l'] < _err['r']
                   else 'rules closer' if _err['r'] < _err['l'] else 'equally off')
    _r['_expect'] = _exp
    ACT_ROWS.append(_r)

# the text cells the formulas compare must stand for the keys one to one
_shown = {}
for _k in {k for s in bh['cls_truth'] for k in s} | set(bh['k06']) | set(bh['kr']) | set(bh['old_class']):
    _shown.setdefault(show_cls(_k), set()).add(_k)
assert all(len(v) == 1 for v in _shown.values()), 'two class keys look the same in the workbook'
_used = {k for s in bh['cls_truth'] for k in s} | {k for k in list(bh['k06']) + list(bh['kr']) if k is not None}
assert _used <= set(SHOW), f'classes outside the catalogue: {sorted(_used - set(SHOW))}'
HEADS = [SHOW[V.norm_class(h, NM)] for h in FC.LLM_BOSSERHOF_SUBCATEGORIES]      # the eight main groups as shown

# ── 4. the workbook ──────────────────────────────────────────────────────────────────────────────────────────────────
ARIAL = 'Arial'


def font(size=10, bold=False, italic=False, color='000000', underline=None):
    return Font(name=ARIAL, size=size, bold=bold, italic=italic, color=color, underline=underline)


def fill(rgb):
    return PatternFill(fill_type='solid', start_color=rgb, end_color=rgb)


BLOCKS = {          # title, dark, light
    'place':   ('PLACE', '595959', 'E7E6E6'),
    'truth':   ('HUMAN GROUND TRUTH', '5B3A8E', 'E6DEF0'),
    'llm':     ('LLM PIPELINE (FINAL)', '2F5597', 'DCE6F2'),
    'rules':   ('RULE-BASED PIPELINE (rule_utils.py)', 'C55A11', 'FBE3D3'),
    'cmp':     ('COMPARISON', '1F6F6F', 'D5EBE7'),
    'details': ('DETAILS', '7F7F7F', 'EDEDED'),
    'helpers': ('HELPER COLUMNS FOR THE SCORES', 'A6A6A6', 'F2F2F2'),
}
MARKS = (('✓', 'C6EFCE', '006100'), ('≈', 'FFEB9C', '9C5700'), ('✗', 'FFC7CE', '9C0006'))
WHO = (('both right', 'C6EFCE', '006100'), ('only LLM right', 'BDD7EE', '1F3864'),
       ('only rules right', 'F8CBAD', '843C0C'), ('neither', 'FFC7CE', '9C0006'),
       ('LLM closer', 'DDEBF7', '1F3864'), ('rules closer', 'FCE4D6', '843C0C'), ('equally off', 'EDEDED', '404040'))
CENTER = Alignment(horizontal='center', vertical='center')
LEFT = Alignment(horizontal='left', vertical='center')
EDGE = Side(style='thin', color='A6A6A6')
CATS = '{' + ','.join(f'"{c}"' for c in SIX) + '}'          # the six categories as an array constant
CATC = f'Lists!$A$2:$A${len(SHOW) + 1}'                     # the catalogue on the hidden sheet Lists: class as shown,
CATG = f'Lists!$B$2:$B${len(SHOW) + 1}'                     # and its main group

# key, header, width, block, kind
CLS_COLS = [
    ('n', 'No.', 5, 'place', 'int'), ('place', 'Place', 34, 'place', 'text'), ('city', 'City', 15, 'place', 'text'),
    ('map', 'Map', 6, 'place', 'link'), ('alkis', 'ALKIS building use', 30, 'place', 'text'),
    ('t_cls', 'Accepted class(es)', 36, 'truth', 'text'), ('t_head', 'Main group', 30, 'truth', 'text'),
    ('o_cls', "Original pipeline's class", 28, 'truth', 'grey'), ('o_ok', 'Original answer', 11, 'truth', 'orig'),
    ('l_type', "LLM's description", 34, 'llm', 'text'), ('l_cls', 'LLM class', 32, 'llm', 'text'),
    ('l_mark', 'LLM ✓', 7, 'llm', 'mark'),
    ('r_layer', 'Rules decided by', 14, 'rules', 'text'), ('r_cls', 'Rules class', 32, 'rules', 'text'),
    ('r_mark', 'Rules ✓', 7, 'rules', 'mark'),
    ('who', 'Who is right', 23, 'cmp', 'who'),
    ('l_head', 'LLM main group', 30, 'details', 'text'), ('r_head', 'Rules main group', 30, 'details', 'text'),
    ('l_conf', 'LLM confidence', 11, 'details', 'text'), ('l_evid', 'LLM evidence', 18, 'details', 'text'),
    ('l_route', 'LLM call', 20, 'details', 'text'), ('address', 'Address', 24, 'details', 'text'),
    ('bid', 'Building ID', 19, 'details', 'text'), ('rows', 'Sample row', 10, 'details', 'text'),
    ('verdict', "Validator's verdict", 32, 'details', 'text'), ('pois', 'POIs on the building (site: = around it)', 50, 'details', 'text'),
    ('reason', "LLM's reason", 80, 'details', 'text'),
    ('h_lex', 'LLM exact (1/0)', 9, 'helpers', 'helper'), ('h_lhd', 'LLM main group (1/0)', 9, 'helpers', 'helper'),
    ('h_rex', 'Rules exact (1/0)', 9, 'helpers', 'helper'), ('h_rhd', 'Rules main group (1/0)', 9, 'helpers', 'helper'),
    ('h_orig', 'Truth = original (1/0)', 9, 'helpers', 'helper'),
    ('h_lonly', 'Only LLM exact (1/0)', 9, 'helpers', 'helper'),
    ('h_ronly', 'Only rules exact (1/0)', 9, 'helpers', 'helper'),
    ('h_lonlyhd', 'Only LLM main group (1/0)', 9, 'helpers', 'helper'),
    ('h_ronlyhd', 'Only rules main group (1/0)', 9, 'helpers', 'helper'),
]
ACT_COLS = [
    ('n', 'No.', 5, 'place', 'int'), ('place', 'Place', 34, 'place', 'text'), ('city', 'City', 15, 'place', 'text'),
    ('map', 'Map', 6, 'place', 'link'), ('alkis', 'ALKIS building use', 30, 'place', 'text'),
    ('t_act', 'Activities (truth)', 32, 'truth', 'text'),
    ('o_act', "Original pipeline's activities", 30, 'truth', 'grey'), ('o_ok', 'Original answer', 11, 'truth', 'orig'),
    ('l_lab', 'LLM labels (MiD)', 30, 'llm', 'text'), ('l_act', 'LLM activities', 30, 'llm', 'text'),
    ('l_mark', 'LLM ✓', 7, 'llm', 'mark'), ('l_miss', 'LLM missed / extra', 34, 'llm', 'text'),
    ('r_layer', 'Rules decided by', 14, 'rules', 'text'), ('r_lab', 'Rules labels (MiD)', 30, 'rules', 'text'),
    ('r_act', 'Rules activities', 30, 'rules', 'text'), ('r_mark', 'Rules ✓', 7, 'rules', 'mark'),
    ('r_miss', 'Rules missed / extra', 34, 'rules', 'text'),
    ('who', 'Who is closer', 24, 'cmp', 'who'),
    ('l_type', "LLM's description", 32, 'details', 'text'), ('l_cls', 'LLM class', 26, 'details', 'text'),
    ('r_cls', 'Rules class', 26, 'details', 'text'),
    ('l_actf', 'LLM activities (FINAL map)', 24, 'details', 'text'),
    ('r_actf', 'Rules activities (FINAL map)', 24, 'details', 'text'),
    ('address', 'Address', 24, 'details', 'text'), ('bid', 'Building ID', 19, 'details', 'text'),
    ('rows', 'Sample row', 10, 'details', 'text'),
    ('verdict', "Validator's verdict", 32, 'details', 'text'), ('pois', 'POIs on the building (site: = around it)', 50, 'details', 'text'),
    ('reason', "LLM's reason", 80, 'details', 'text'),
] + [(f'{s}{x}{f}', f'{who} {what}{fname} (n)', 9, 'helpers', 'helper')
     for f, fname in (('', ''), ('f', ', FINAL map'))
     for s, who in (('l', 'LLM'), ('r', 'Rules'))
     for x, what in (('tp', 'right'), ('fp', 'extra'), ('fn', 'missed'))] + [
    ('h_orig', 'Truth = original (1/0)', 9, 'helpers', 'helper'),
    ('h_lex', 'LLM exact set (1/0)', 9, 'helpers', 'helper'), ('h_rex', 'Rules exact set (1/0)', 9, 'helpers', 'helper'),
    ('h_lfewer', 'LLM fewer errors (1/0)', 9, 'helpers', 'helper'),
    ('h_rfewer', 'Rules fewer errors (1/0)', 9, 'helpers', 'helper'),
]


def _found(needle, hay):
    """Excel: is the text of cell `needle` one of the ' | '-separated entries of cell `hay` (any case)"""
    return f'ISNUMBER(SEARCH(" | "&{needle}&" | "," | "&{hay}&" | "))'


def _in_group(hay, group):
    """Excel: does any entry of cell `hay` (' | '-separated) lie in main group `group` (a cell or a quoted text)"""
    return f'SUMPRODUCT(ISNUMBER(SEARCH(" | "&{CATC}&" | "," | "&{hay}&" | "))*({CATG}={group}))>0'


def cls_formulas(L, r):
    c = {k: f'{v}{r}' for k, v in L.items()}
    groups = []
    for h in HEADS:
        groups.append(f'IF({_in_group(c["t_cls"], chr(34) + h + chr(34))}," | {h}","")')
    return {
        't_head': f'=MID({"&".join(groups)},4,999)',
        'l_head': f'=IFERROR(INDEX({CATG},MATCH({c["l_cls"]},{CATC},0)),"–")',
        'r_head': f'=IFERROR(INDEX({CATG},MATCH({c["r_cls"]},{CATC},0)),"–")',
        'o_ok': f'=IF({_found(c["o_cls"], c["t_cls"])},"matches","differs")',
        'l_mark': f'=IF({_found(c["l_cls"], c["t_cls"])},"✓",IF({_in_group(c["t_cls"], c["l_head"])},"≈","✗"))',
        'r_mark': f'=IF({_found(c["r_cls"], c["t_cls"])},"✓",IF({_in_group(c["t_cls"], c["r_head"])},"≈","✗"))',
        'who': (f'=IF({c["l_mark"]}="✓",IF({c["r_mark"]}="✓","both right","only LLM right"),'
                f'IF({c["r_mark"]}="✓","only rules right","neither"))'),
        'h_lex': f'=IF({c["l_mark"]}="✓",1,0)', 'h_lhd': f'=IF({c["l_mark"]}="✗",0,1)',
        'h_rex': f'=IF({c["r_mark"]}="✓",1,0)', 'h_rhd': f'=IF({c["r_mark"]}="✗",0,1)',
        'h_orig': f'=IF({c["o_ok"]}="matches",1,0)',
        'h_lonly': f'={c["h_lex"]}*(1-{c["h_rex"]})', 'h_ronly': f'=(1-{c["h_lex"]})*{c["h_rex"]}',
        'h_lonlyhd': f'={c["h_lhd"]}*(1-{c["h_rhd"]})', 'h_ronlyhd': f'=(1-{c["h_lhd"]})*{c["h_rhd"]}',
    }


def act_formulas(L, r):
    c = {k: f'{v}{r}' for k, v in L.items()}
    t = f'ISNUMBER(SEARCH({CATS},${L["t_act"]}{r}))'
    out = {'o_ok': (f'=IF(SUMPRODUCT(ABS({t}-ISNUMBER(SEARCH({CATS},{c["o_act"]}))))=0,'
                    f'"matches","differs")')}
    for side, col in (('l', 'l_act'), ('r', 'r_act'), ('lf', 'l_actf'), ('rf', 'r_actf')):
        s, f = side[0], side[1:]
        p = f'ISNUMBER(SEARCH({CATS},{c[col]}))'
        out[f'{s}tp{f}'] = f'=SUMPRODUCT({t}*{p})'
        out[f'{s}fp{f}'] = f'=SUMPRODUCT((1-{t})*{p})'
        out[f'{s}fn{f}'] = f'=SUMPRODUCT({t}*(1-{p}))'
    el, er = f'({c["lfp"]}+{c["lfn"]})', f'({c["rfp"]}+{c["rfn"]})'
    out['l_mark'] = f'=IF({el}=0,"✓",IF({c["ltp"]}>0,"≈","✗"))'
    out['r_mark'] = f'=IF({er}=0,"✓",IF({c["rtp"]}>0,"≈","✗"))'
    out['who'] = (f'=IF(AND({el}=0,{er}=0),"both right",IF({el}=0,"only LLM right",IF({er}=0,"only rules right",'
                  f'IF({el}<{er},"LLM closer",IF({er}<{el},"rules closer","equally off")))))')
    out['h_orig'] = f'=IF({c["o_ok"]}="matches",1,0)'
    out['h_lex'] = f'=IF({c["l_mark"]}="✓",1,0)'
    out['h_rex'] = f'=IF({c["r_mark"]}="✓",1,0)'
    out['h_lfewer'] = f'=IF({el}<{er},1,0)'
    out['h_rfewer'] = f'=IF({er}<{el},1,0)'
    return out


def _clean(v):
    """text safe for a cell: no control characters, never read as a formula"""
    if isinstance(v, str):
        v = ILLEGAL_CHARACTERS_RE.sub('', v)
        if v[:1] == '=':
            v = ' ' + v
    return v


def _spans(cols):
    """(block, first column index, last column index) for each run of columns of one block"""
    out = []
    for i, c in enumerate(cols, 1):
        if out and out[-1][0] == c[3]:
            out[-1][2] = i
        else:
            out.append([c[3], i, i])
    return out


def place_sheet(ws, cols, rows, formulas, title, subtitle, banner, table):
    """one row per place: title, live scores (rows 3-4), block band (5), header (6), the places (7 ...)"""
    L = {c[0]: get_column_letter(i) for i, c in enumerate(cols, 1)}
    last = FIRST + len(rows) - 1
    vis = max(i for i, c in enumerate(cols, 1) if c[3] == 'cmp')
    expect = {}
    ws.sheet_properties.tabColor = '5B3A8E'
    ws.cell(1, 1, title).font = font(14, bold=True, color='1F1F1F')
    ws.cell(2, 1, subtitle).font = font(9, italic=True, color='595959')
    ws.row_dimensions[1].height = 22
    for r in (1, 2):
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=vis)
        ws.cell(r, 1).alignment = LEFT
    # live scores: SUBTOTAL leaves out the rows a filter hides
    for row, k0, k1, value, fmt, block, want in banner(L, last):
        c0, c1 = cols.index(next(c for c in cols if c[0] == k0)) + 1, cols.index(next(c for c in cols if c[0] == k1)) + 1
        cell = ws.cell(row, c0, value)
        cell.number_format = fmt
        cell.font = font(10, bold=True, color=BLOCKS[block][1] if block != 'place' else '1F1F1F')
        cell.fill = fill(BLOCKS[block][2])
        cell.alignment = CENTER
        if c1 > c0:
            ws.merge_cells(start_row=row, start_column=c0, end_row=row, end_column=c1)
        if want is not None:
            expect[(ws.title, cell.coordinate)] = want
    for block, c0, c1 in _spans(cols):
        cell = ws.cell(5, c0, BLOCKS[block][0])
        cell.font = font(9, bold=True, color='FFFFFF')
        cell.fill = fill(BLOCKS[block][1])
        cell.alignment = CENTER
        if c1 > c0:
            ws.merge_cells(start_row=5, start_column=c0, end_row=5, end_column=c1)
    starts = {c0 for _, c0, _ in _spans(cols)}
    for i, (key, head, width, block, kind) in enumerate(cols, 1):
        cell = ws.cell(6, i, head)
        cell.font = font(9, bold=True, color='1F1F1F')
        cell.fill = fill(BLOCKS[block][2])
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = Border(left=EDGE if i in starts else None, bottom=Side(style='medium', color=BLOCKS[block][1]))
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.row_dimensions[5].height = 16
    ws.row_dimensions[6].height = 30
    styles = {'int': (font(9, color='7F7F7F'), CENTER), 'text': (font(10), LEFT),
              'grey': (font(10, italic=True, color='7F7F7F'), LEFT),
              'link': (font(10, color='0563C1', underline='single'), CENTER),
              'mark': (font(11, bold=True), CENTER), 'who': (font(10), CENTER),
              'orig': (font(9, color='595959'), CENTER), 'helper': (font(9, color='7F7F7F'), CENTER)}
    for j, rec in enumerate(rows):
        r = FIRST + j
        fx = formulas(L, r)
        for i, (key, head, width, block, kind) in enumerate(cols, 1):
            cell = ws.cell(r, i)
            if key in fx:
                cell.value = fx[key]
                if key in rec['_expect']:
                    expect[(ws.title, cell.coordinate)] = rec['_expect'][key]
            elif kind == 'link':
                cell.value = 'map'
                cell.hyperlink = rec['map']
            else:
                cell.value = _clean(rec[key])
            cell.font, cell.alignment = styles[kind]
            if i in starts:
                cell.border = Border(left=EDGE)
            note = rec['_notes'].get(key)
            if note:
                cell.comment = Comment(_clean(note), 'note', width=420, height=150)
    for key, kind in ((c[0], c[4]) for c in cols):
        rng = f'{L[key]}{FIRST}:{L[key]}{last}'
        if kind == 'mark':
            for text, bg, fg in MARKS:
                ws.conditional_formatting.add(rng, CellIsRule(operator='equal', formula=[f'"{text}"'], fill=fill(bg),
                                                              font=Font(color=fg, bold=True)))
        elif kind == 'who':
            for text, bg, fg in WHO:
                ws.conditional_formatting.add(rng, CellIsRule(operator='equal', formula=[f'"{text}"'], fill=fill(bg),
                                                              font=Font(color=fg)))
        elif kind == 'orig':
            ws.conditional_formatting.add(rng, CellIsRule(operator='equal', formula=['"differs"'], fill=fill('FFF2CC'),
                                                          font=Font(color='7F6000', bold=True)))
    tab = Table(displayName=table, ref=f'A6:{get_column_letter(len(cols))}{last}')
    tab.tableStyleInfo = TableStyleInfo(name='TableStyleLight1', showRowStripes=True, showColumnStripes=False)
    ws.add_table(tab)
    helpers = [L[c[0]] for c in cols if c[3] == 'helpers']
    ws.column_dimensions.group(helpers[0], helpers[-1], hidden=True, outline_level=1)
    ws.freeze_panes = f'C{FIRST}'
    ws.sheet_view.zoomScale = 90
    ws.page_setup.orientation = 'landscape'
    ws.print_title_rows = '5:6'
    return L, last, expect


def _sum(L, key, last):
    return f'SUBTOTAL(109,{L[key]}{FIRST}:{L[key]}{last})'


def cls_banner(L, last):
    shown = f'SUBTOTAL(103,$A${FIRST}:$A${last})'
    e = EXP_CLS['all']
    n = e['n']
    return [
        (3, 'n', 'place', f'={shown}', f'"Places shown: "0" of {n}"', 'place', n),
        (4, 'n', 'place', 'Rows 3-4 score the rows shown', '@', 'place', None),
        (3, 't_cls', 'o_ok', f'={_sum(L, "h_orig", last)}', '"original answer matches: "#,##0', 'truth',
         EXP_CLS['accepted']['n']),
        (4, 't_cls', 'o_ok', f'={shown}-{_sum(L, "h_orig", last)}', '"original answer differs: "#,##0', 'truth',
         EXP_CLS['rejected']['n']),
        (3, 'l_type', 'l_mark', f'=IFERROR({_sum(L, "h_lex", last)}/{shown},"")', '"exact class: "0.0%', 'llm', e['ex06']),
        (4, 'l_type', 'l_mark', f'=IFERROR({_sum(L, "h_lhd", last)}/{shown},"")', '"right main group: "0.0%', 'llm',
         e['hd06']),
        (3, 'r_layer', 'r_mark', f'=IFERROR({_sum(L, "h_rex", last)}/{shown},"")', '"exact class: "0.0%', 'rules',
         e['exr']),
        (4, 'r_layer', 'r_mark', f'=IFERROR({_sum(L, "h_rhd", last)}/{shown},"")', '"right main group: "0.0%', 'rules',
         e['hdr']),
        (3, 'who', 'who', f'={_sum(L, "h_lonly", last)}', '"only LLM right: "#,##0', 'cmp', e['b']),
        (4, 'who', 'who', f'={_sum(L, "h_ronly", last)}', '"only rules right: "#,##0', 'cmp', e['c']),
    ]


def act_banner(L, last):
    shown = f'SUBTOTAL(103,$A${FIRST}:$A${last})'
    e = EXP_ACT['all']
    n = e['n']

    def f1(s):
        tp, fp, fn = (_sum(L, f'{s}{x}', last) for x in ('tp', 'fp', 'fn'))
        return f'=IFERROR(2*{tp}/(2*{tp}+{fp}+{fn}),"")'

    def prec(s):
        return f'=IFERROR({_sum(L, f"{s}tp", last)}/({_sum(L, f"{s}tp", last)}+{_sum(L, f"{s}fp", last)}),"")'

    def rec(s):
        return f'=IFERROR({_sum(L, f"{s}tp", last)}/({_sum(L, f"{s}tp", last)}+{_sum(L, f"{s}fn", last)}),"")'

    lfew = int(sum(r['_expect']['who'] in ('only LLM right', 'LLM closer') for r in ACT_ROWS))
    rfew = int(sum(r['_expect']['who'] in ('only rules right', 'rules closer') for r in ACT_ROWS))
    return [
        (3, 'n', 'place', f'={shown}', f'"Places shown: "0" of {n}"', 'place', n),
        (4, 'n', 'place', 'Rows 3-4 score the rows shown', '@', 'place', None),
        (3, 't_act', 'o_ok', f'={_sum(L, "h_orig", last)}', '"original answer matches: "#,##0', 'truth',
         EXP_ACT['accepted']['n']),
        (4, 't_act', 'o_ok', f'={shown}-{_sum(L, "h_orig", last)}', '"original answer differs: "#,##0', 'truth',
         EXP_ACT['rejected']['n']),
        (3, 'l_lab', 'l_miss', f1('l'), '"F1: "0.0%', 'llm', e['F06']),
        (4, 'l_lab', 'l_act', prec('l'), '"precision: "0.0%', 'llm', e['P06']),
        (4, 'l_mark', 'l_miss', rec('l'), '"recall: "0.0%', 'llm', e['R06']),
        (3, 'r_layer', 'r_miss', f1('r'), '"F1: "0.0%', 'rules', e['Fr']),
        (4, 'r_layer', 'r_lab', prec('r'), '"precision: "0.0%', 'rules', e['Pr']),
        (4, 'r_act', 'r_miss', rec('r'), '"recall: "0.0%', 'rules', e['Rr']),
        (3, 'who', 'who', f'={_sum(L, "h_lfewer", last)}', '"LLM fewer errors: "#,##0', 'cmp', lfew),
        (4, 'who', 'who', f'={_sum(L, "h_rfewer", last)}', '"rules fewer errors: "#,##0', 'cmp', rfew),
    ]


wb = Workbook()
ws_sum = wb.active
ws_sum.title = 'Summary'
ws_cls = wb.create_sheet('Building class')
ws_act = wb.create_sheet('Activities')
ws_not = wb.create_sheet('Notes')
EXPECT = {}

_sub = ('One row per validated place.  ✓ an accepted class  ·  ≈ wrong class, right main group  ·  ✗ wrong or no class.  '
        'Filter with the ▼ buttons in row 6.  Hover over an LLM class to read the LLM\'s reason; details further right.')
LC, LAST_C, _e = place_sheet(ws_cls, CLS_COLS, CLS_ROWS, cls_formulas,
                             f'Building class: human ground truth, LLM and rules side by side ({len(CLS_ROWS):,} places)',
                             _sub, cls_banner, 'tblBuildingClass')
EXPECT.update(_e)
_sub = ('One row per validated place, in six categories (Workers left out).  ✓ the same set as the truth  ·  ≈ partly '
        'right  ·  ✗ nothing right.  Labels are mapped by the old merge.  Hover over the LLM labels to read its reason.')
LA, LAST_A, _e = place_sheet(ws_act, ACT_COLS, ACT_ROWS, act_formulas,
                             f'Activities: human ground truth, LLM and rules side by side ({len(ACT_ROWS):,} places)',
                             _sub, act_banner, 'tblActivities')
EXPECT.update(_e)


# ── the summary ──────────────────────────────────────────────────────────────────────────────────────────────────────
def R(sheet, L, key, last):
    return f"'{sheet}'!${L[key]}${FIRST}:${L[key]}${last}"


def cr(key):
    return R('Building class', LC, key, LAST_C)


def ar(key):
    return R('Activities', LA, key, LAST_A)


ws = ws_sum
ws.sheet_view.showGridLines = False
ws.sheet_properties.tabColor = '1F6F6F'
for _col, _w in zip('ABCDEFGHIJKLM', (2, 50, 9, 10, 10, 10, 10, 9, 10, 10, 10, 10, 9)):
    ws.column_dimensions[_col].width = _w
HEADF = font(9, bold=True, color='1F1F1F')
NOTE = font(9, italic=True, color='595959')


def put(cell, value, f=None, fmt=None, align=None, bg=None, want=None):
    c = ws[cell]
    c.value = value
    c.font = f or font(10)
    if fmt:
        c.number_format = fmt
    if align:
        c.alignment = align
    if bg:
        c.fill = fill(bg)
    if want is not None:
        EXPECT[('Summary', cell)] = want
    return c


def head(cells, text, block):
    first, last_ = cells.split(':') if ':' in cells else (cells, cells)
    c = put(first, text, font(9, bold=True, color='FFFFFF'), align=Alignment(horizontal='center', vertical='center',
                                                                              wrap_text=True), bg=BLOCKS[block][1])
    if first != last_:
        ws.merge_cells(cells)
    return c


def sub(cell, text, block):
    put(cell, text, HEADF, align=Alignment(horizontal='center', vertical='center', wrap_text=True), bg=BLOCKS[block][2])


put('B2', 'Rules vs LLM on the validated places', font(16, bold=True, color='1F1F1F'))
put('B3', 'Human ground truth · LLM pipeline (FINAL) · rule-based pipeline (rule_utils.py on FINAL\'s buildings, '
          'notebook 11). Same places, truth and scoring as notebook 12.',
    font(10, color='595959'))
put('B4', 'Sheets:', font(10, bold=True))
for _cell, _sheet, _text in (('C4', 'Building class', f'Building class ({len(CLS_ROWS):,} places) ▸'),
                             ('F4', 'Activities', f'Activities ({len(ACT_ROWS):,} places) ▸'),
                             ('I4', 'Notes', 'Notes ▸')):
    _c = put(_cell, _text, font(10, color='0563C1', underline='single'))
    _c.hyperlink = Hyperlink(ref=_cell, location=f"'{_sheet}'!A1", display=_text)

# building class
put('B6', 'Building class (Bosserhof)', font(12, bold=True, color='1F1F1F'))
head('C7:C8', 'Places', 'place')
head('D7:H7', 'Exact class', 'cmp')
head('I7:M7', 'Right main group', 'cmp')
for _c0 in ('D', 'I'):
    _cols = [get_column_letter(ws[f'{_c0}8'].column + k) for k in range(5)]
    for _col, _t, _b in zip(_cols, ('LLM', 'Rules', 'only LLM right', 'only rules right', 'p (paired test)'),
                            ('llm', 'rules', 'llm', 'rules', 'cmp')):
        sub(f'{_col}8', _t, _b)
ws.row_dimensions[8].height = 26
_labels = {'all': 'All places',
           'accepted': 'Truth matches the original answer',
           'rejected': 'Truth differs from the original answer'}
for _r, (_name, _flag) in zip((9, 10, 11), SUBSETS):
    e = EXP_CLS[_name]
    put(f'B{_r}', _labels[_name], font(10, bold=_name == 'all'))
    if _flag is None:
        _n = f'=COUNT({cr("h_lex")})'

        def S(k):
            return f'SUM({cr(k)})'
    else:
        _n = f'=SUM({cr("h_orig")})' if _flag else f'=COUNT({cr("h_orig")})-SUM({cr("h_orig")})'

        def S(k, _v=int(_flag)):
            return f'SUMIFS({cr(k)},{cr("h_orig")},{_v})'
    put(f'C{_r}', _n, fmt='#,##0', align=CENTER, want=e['n'])
    for _cols, (ex, rx, only_l, only_r, kl, kr_, kb, kc, kp) in (
            (('D', 'E', 'F', 'G', 'H'), ('h_lex', 'h_rex', 'h_lonly', 'h_ronly', 'ex06', 'exr', 'b', 'c', 'p')),
            (('I', 'J', 'K', 'L', 'M'), ('h_lhd', 'h_rhd', 'h_lonlyhd', 'h_ronlyhd', 'hd06', 'hdr', 'bh', 'ch', 'ph'))):
        put(f'{_cols[0]}{_r}', f'={S(ex)}/C{_r}', fmt='0.0%', align=CENTER, want=e[kl])
        put(f'{_cols[1]}{_r}', f'={S(rx)}/C{_r}', fmt='0.0%', align=CENTER, want=e[kr_])
        put(f'{_cols[2]}{_r}', f'={S(only_l)}', fmt='#,##0', align=CENTER, want=e[kb])
        put(f'{_cols[3]}{_r}', f'={S(only_r)}', fmt='#,##0', align=CENTER, want=e[kc])
        _b, _c = f'{_cols[2]}{_r}', f'{_cols[3]}{_r}'
        put(f'{_cols[4]}{_r}', f'=IF({_b}+{_c}=0,1,MIN(1,2*BINOMDIST(MIN({_b},{_c}),{_b}+{_c},0.5,TRUE)))',
            fmt='[<0.001]"< 0.001";[<0.01]0.0000;0.000', align=CENTER, want=e[kp])
for _rng, _col in (('D9:D11', '5B9BD5'), ('E9:E11', 'F4B183'), ('I9:I11', '5B9BD5'), ('J9:J11', 'F4B183')):
    ws.conditional_formatting.add(_rng, DataBarRule(start_type='num', start_value=0, end_type='num', end_value=1,
                                                    color=_col))
put('B12', 'Exact: the answer is one of the accepted classes. Main group: it lies in the same Bosserhof main group.', NOTE)
put('B13', 'p: exact two-sided McNemar test on the places only one of the two gets right (as notebook 12).', NOTE)

# activities
put('B15', 'Activities (six categories; Workers left out)', font(12, bold=True, color='1F1F1F'))
head('C16:C17', 'Places', 'place')
head('D16:F16', 'LLM', 'llm')
head('G16:I16', 'Rules', 'rules')
head('J16:J17', 'F1: LLM − rules (points)', 'cmp')
head('K16:L16', 'Exact set', 'cmp')
for _c, _t, _b in (('D', 'precision', 'llm'), ('E', 'recall', 'llm'), ('F', 'F1', 'llm'), ('G', 'precision', 'rules'),
                   ('H', 'recall', 'rules'), ('I', 'F1', 'rules'), ('K', 'LLM', 'llm'), ('L', 'Rules', 'rules')):
    sub(f'{_c}17', _t, _b)
ws.row_dimensions[17].height = 26
_alabels = {'all': 'All places (old merge: the main score here)',
            'accepted': 'Truth matches the original answer',
            'rejected': 'Truth differs from the original answer',
            'all_final': "All places, FINAL's map (as in notebook 09)"}
for _r, (_name, _flag, _m) in zip((18, 19, 20, 21), (('all', None, 'old'), ('accepted', True, 'old'),
                                                    ('rejected', False, 'old'), ('all_final', None, 'final'))):
    e = EXP_ACT[_name]
    _sf = '' if _m == 'old' else 'f'
    put(f'B{_r}', _alabels[_name], font(10, bold=_name in ('all', 'all_final')))
    if _flag is None:
        put(f'C{_r}', f'=COUNT({ar("h_orig")})', fmt='#,##0', align=CENTER, want=e['n'])

        def S(k):
            return f'SUM({ar(k)})'

        def X(s):
            return f'SUMPRODUCT(--(({ar(s + "fp" + _sf)}+{ar(s + "fn" + _sf)})=0))'
    else:
        _v = int(_flag)
        put(f'C{_r}', f'=SUM({ar("h_orig")})' if _flag else f'=COUNT({ar("h_orig")})-SUM({ar("h_orig")})',
            fmt='#,##0', align=CENTER, want=e['n'])

        def S(k, _v=_v):
            return f'SUMIFS({ar(k)},{ar("h_orig")},{_v})'

        def X(s, _v=_v):
            return f'SUMPRODUCT((({ar(s + "fp")}+{ar(s + "fn")})=0)*({ar("h_orig")}={_v}))'
    for _side, (cp, cr_, cf), (kp, kr2, kf) in (('l', ('D', 'E', 'F'), ('P06', 'R06', 'F06')),
                                               ('r', ('G', 'H', 'I'), ('Pr', 'Rr', 'Fr'))):
        tp, fp, fn = (S(f'{_side}{x}{_sf}') for x in ('tp', 'fp', 'fn'))
        put(f'{cp}{_r}', f'={tp}/({tp}+{fp})', fmt='0.0%', align=CENTER, want=e[kp])
        put(f'{cr_}{_r}', f'={tp}/({tp}+{fn})', fmt='0.0%', align=CENTER, want=e[kr2])
        put(f'{cf}{_r}', f'=2*{tp}/(2*{tp}+{fp}+{fn})', fmt='0.0%', align=CENTER, want=e[kf])
    put(f'J{_r}', f'=(F{_r}-I{_r})*100', fmt='+0.0;"−"0.0;0.0', align=CENTER, want=e['diff'])
    put(f'K{_r}', f'={X("l")}/C{_r}', fmt='0.0%', align=CENTER, want=e['ex06'])
    put(f'L{_r}', f'={X("r")}/C{_r}', fmt='0.0%', align=CENTER, want=e['exr'])
for _rng, _col in (('F18:F21', '5B9BD5'), ('I18:I21', 'F4B183')):
    ws.conditional_formatting.add(_rng, DataBarRule(start_type='num', start_value=0, end_type='num', end_value=1,
                                                    color=_col))


def _p(p):
    return f'< {2 / RULES_VS_LLM_BOOTSTRAP:.3f}' if p == 0 else f'{p:.2g}'


_bo, _bf = BOOT['old'], BOOT['final']
_sig = [lo > 0 or hi < 0 for _, lo, hi, _ in (_bo, _bf)]
put('B22', f'Paired bootstrap of the F1 difference ({RULES_VS_LLM_BOOTSTRAP:,} resamples of the places, seed '
           f'{RULES_VS_LLM_SEED}, as notebook 12): old merge {_bo[0]:+.1f} points (95 % interval {_bo[1]:+.1f} .. '
           f'{_bo[2]:+.1f}, p {_p(_bo[3])});', NOTE)
put('B23', f"FINAL's map {_bf[0]:+.1f} points ({_bf[1]:+.1f} .. {_bf[2]:+.1f}, p {_p(_bf[3])}). "
           + ('Neither difference is significant.' if not any(_sig) else
              'Significant (an interval without 0): ' + ', '.join(n for n, s in zip(('old merge', "FINAL's map"), _sig)
                                                                  if s) + '.'), NOTE)
put('B24', "Old merge: the original pipeline's merge of the labels, which the validator judged (errands → Retail_Daily; "
           "sports, meetup, lessons → Leisure). FINAL's map: those feed no category.", NOTE)

# who is right
put('B26', 'Who is right, place by place', font(12, bold=True, color='1F1F1F'))
for _r0, _title, _sheet_rng, _cats, _rows in (
        (27, 'Building class (exact)', cr('who'), ('both right', 'only LLM right', 'only rules right', 'neither'),
         CLS_ROWS),
        (33, 'Activities (closer: fewer wrong categories)', ar('who'),
         ('both right', 'only LLM right', 'only rules right', 'LLM closer', 'rules closer', 'equally off'), ACT_ROWS)):
    put(f'B{_r0}', _title, HEADF, bg=BLOCKS['cmp'][2])
    sub(f'C{_r0}', 'places', 'cmp')
    sub(f'D{_r0}', 'share', 'cmp')
    for _k, _cat in enumerate(_cats, 1):
        _r = _r0 + _k
        _want = sum(rr['_expect']['who'] == _cat for rr in _rows)
        _bg, _fg = next((bg, fg) for t, bg, fg in WHO if t == _cat)
        put(f'B{_r}', _cat, font(10, color=_fg), bg=_bg)
        put(f'C{_r}', f'=COUNTIF({_sheet_rng},"{_cat}")', fmt='#,##0', align=CENTER, want=_want)
        put(f'D{_r}', f'=C{_r}/{len(_rows)}', fmt='0.0%', align=CENTER, want=_want / len(_rows))

# how to read
put('B41', 'How to read', font(12, bold=True, color='1F1F1F'))
_pt, _pr = POI_SHARE
_ncopy = sum(r['l_route'] == ROUTE['signature, copied'] for r in CLS_ROWS)
for _r, _line in enumerate((
        "• The truth is a human check of the ORIGINAL pipeline's LLM answers. Where it matches the original answer "
        '(mostly an OK), the truth is',
        "   that older LLM answer, so a model like the old one has an edge there. Where it differs, the places are "
        "exactly the old model's",
        '   mistakes, which tilts the other way. Neither split is neutral; only a blind sample could settle it.',
        f'• The sample is POI-heavy: POI tags decide the rules on {100 * _pt:.0f} % of these places but on '
        f'{100 * _pr:.0f} % of the {len(rules):,} buildings both pipelines classified.',
        f'• The LLM ran once (no repeated runs), so its run-to-run spread is not in these numbers; {_ncopy} class places '
        'carry an answer copied from a like building.',
        '• Marks and scores are formulas: change a class or an activities cell and they follow; filter a place sheet and '
        'its rows 3-4 follow.',
        '• Definitions, the label maps, the class catalogue and the inputs: sheet Notes.'), 42):
    put(f'B{_r}', _line, font(10))
put('B50', 'Colours', font(12, bold=True, color='1F1F1F'))
for _r, (_t, _bg, _fg, _text) in enumerate((
        ('✓', 'C6EFCE', '006100', 'right: an accepted class / the same six-category set as the truth'),
        ('≈', 'FFEB9C', '9C5700', 'close: the right main group / at least one right category'),
        ('✗', 'FFC7CE', '9C0006', 'wrong: another main group or no class / no right category'),
        ('LLM', BLOCKS['llm'][1], 'FFFFFF', 'the LLM pipeline (FINAL)'),
        ('Rules', BLOCKS['rules'][1], 'FFFFFF', 'the rule-based pipeline (rule_utils.py, notebook 11)'),
        ('Truth', BLOCKS['truth'][1], 'FFFFFF', 'the human ground truth')), 51):
    put(f'C{_r}', _t, font(10, bold=True, color=_fg), align=CENTER, bg=_bg)
    put(f'D{_r}', _text, font(10))
ws.freeze_panes = None

# ── the notes ────────────────────────────────────────────────────────────────────────────────────────────────────────
ws = ws_not
ws.sheet_view.showGridLines = False
ws.sheet_properties.tabColor = '7F7F7F'
for _col, _w in zip('ABCD', (2, 44, 60, 40)):
    ws.column_dimensions[_col].width = _w


def _sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()[:12]


def _git(folder, *args):
    return subprocess.run(['git', '-C', str(folder), *args], capture_output=True, text=True).stdout.strip()


_lines = [
    ('Notes', 'title'),
    ('The three answers', 'h'),
    ("Human ground truth: a validator checked 1,641 buildings of the ORIGINAL pipeline (sample_final.xlsx in FINAL's "
     'data/Manual_Validation).', ''),
    ("   FINAL's notebook 09 turned the verdicts into one truth per building. OK: the original answer is right. "
     'Deviation: the typed correction.', ''),
    ("   On an OK row, 'also X' / 'better X' adds X, so a place can have several accepted classes (separated by ' | '); "
     'any one is right.', ''),
    ('   Residential, garages, vacancy: no class and no activity. Such places are not in the Building class sheet; in '
     "Activities their truth is 'no activity'.", ''),
    ('   Unclear, and a Deviation with nothing typed, give no truth (left out); a class or set typed on an Unclear row '
     'is the truth.', ''),
    ("LLM pipeline: FINAL's step-05 answers as stored in step 06 (model requested: gpt-oss-120b; which model answered "
     'is not confirmed).', ''),
    ("   bosserhof_class and llm_labels, one answer per building. 'LLM call': own call, asked for its group, or "
     'copied from its group (same signature).', ''),
    ('Rule-based pipeline: rule_utils.py from branch rule-based-pipeline, unchanged, with its own weights, run on '
     "FINAL's buildings and POIs (notebook 11).", ''),
    ("   Main run: the building's own POIs and the site POIs around it. 'Rules decided by': POI tags, else the ALKIS "
     'code, else the OSM building / land use.', ''),
    ('Building class sheet', 'h'),
    ('✓ one of the accepted classes  ·  ≈ another class in the same main group (e.g. Services where the truth is '
     'normal office)  ·  ✗ another main group or no class.', ''),
    ("Main group: one of the 8 headlines of the Bosserhof catalogue (listed below). 'Others (industrial)' is its bare "
     "'others' under Industrial operations.", ''),
    ("'Original answer': matches = the truth contains the original pipeline's class; differs = it does not (mostly "
     'where the validator corrected it).', ''),
    ('Who is right: by exact class.', ''),
    ('Activities sheet', 'h'),
    ('Six categories: ' + ', '.join(SIX) + '. Workers is left out of every score here (notebook 09 shows it apart).',
     ''),
    ("Labels (MiD) are shown without 'work' (not scored); the LLM's are 06 llm_labels, its own labels before FINAL's "
     'work rule.', ''),
    ("The activities columns come from the labels by the old merge, which the validator judged; the DETAILS columns "
     "also show FINAL's map.", ''),
    ('✓ the same six-category set as the truth  ·  ≈ at least one right category, but something missed or extra  ·  '
     '✗ no right category.', ''),
    ("'no activity': nobody comes (e.g. residential). 'work only': only people who work there. '–': none of the six.",
     ''),
    ("'Original answer' compares the six categories, so a Deviation that only added or removed Workers counts as "
     "'matches'.", ''),
    ('Who is closer: fewer wrong categories (missed + extra).', ''),
    ('Scores', 'h'),
    ('Building class: the share of places with ✓ (exact), and with ✓ or ≈ (main group).', ''),
    ('Activities: micro precision, recall and F1 over the six categories, summed over the places.', ''),
    ('The Summary scores all places; rows 3-4 of a place sheet score the rows its filter shows.', ''),
    ("Marks, main groups and scores are formulas: change a class (catalogue wording; several separated by ' | ') or "
     'an activities cell and they follow.', ''),
    ("   The labels, 'missed / extra' and the other text columns are for reading only.", ''),
    ("Notebook 12 (RULES worktree) has the same numbers, the rules' second run (own POIs only) and the tables per "
     'rule layer.', ''),
]
_r = 2
for _text, _kind in _lines:
    if _kind == 'title':
        put_c = ws.cell(_r, 2, _text)
        put_c.font = font(16, bold=True, color='1F1F1F')
        _r += 2
        continue
    if _kind == 'h':
        _r += 1 if _r > 4 else 0
        ws.cell(_r, 2, _text).font = font(12, bold=True, color='1F1F1F')
    else:
        ws.cell(_r, 2, _text).font = font(10)
    _r += 1


def note_table(r0, title, header, rows):
    ws.cell(r0, 2, title).font = font(12, bold=True, color='1F1F1F')
    for j, h in enumerate(header):
        c = ws.cell(r0 + 1, 2 + j, h)
        c.font = font(9, bold=True, color='FFFFFF')
        c.fill = fill('595959')
        c.alignment = LEFT
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            c = ws.cell(r0 + 2 + i, 2 + j, v)
            c.font = font(10)
            c.alignment = Alignment(vertical='top', wrap_text=True)
            c.border = Border(bottom=Side(style='thin', color='D9D9D9'))
    return r0 + 2 + len(rows) + 1


_r = note_table(_r + 1, 'The twelve MiD labels and their categories', ('MiD label', 'old merge (main score)', "FINAL's map"),
                [(lab, FC.VALIDATION_OLD_LABEL_MERGE.get(lab, '–'), FC.MID_LABEL_TO_ACTIVITY.get(lab, '– (no category)'))
                 for lab in LABELS])
_r = note_table(_r, 'The Bosserhof catalogue', ('Main group', 'Classes'),
                [(h, '; '.join(SHOW[V.norm_class(s, NM)] for s in subs) or '(a class of its own)')
                 for h, subs in FC.LLM_BOSSERHOF_SUBCATEGORIES.items()])
_inputs = [(FINAL_CLASSIFIED_FILE, "the LLM's answers (FINAL 06)"), (FINAL_VALIDATION_FILE, "the truth (FINAL 09, layer units)"),
           (FINAL_CONFIG_FILE, "FINAL's catalogue and label maps"), (FINAL_VALIDATION_LIB, "FINAL's scoring functions"),
           (RULES_ON_FINAL_FILE, "the rules' answers (notebook 11)"), (ROOT / 'rule_utils.py', 'the rule engine')]
def _rel(path):
    """a path as FINAL/... or RULES/..., without the user's folders"""
    for name, base in (('FINAL', FINAL_DIR), ('RULES', ROOT)):
        try:
            return f'{name}/{Path(path).resolve().relative_to(Path(base).resolve()).as_posix()}'
        except ValueError:
            pass
    return Path(path).name


def _pending(folder, *paths):
    """the paths git has not committed in `folder`"""
    out = subprocess.run(['git', '-C', str(folder), 'status', '--porcelain', '--', *paths], capture_output=True,
                         text=True).stdout
    return [line[3:] for line in out.splitlines() if line.strip()]


_r = note_table(_r, 'Inputs', ('What', 'sha256 (first 12)', 'File'),
                [(w, _sha(p), _rel(p)) for p, w in _inputs])
for _row in ws.iter_rows(min_row=_r - len(_inputs) - 1, max_row=_r - 1, min_col=2, max_col=4):
    for _c in _row:
        _c.alignment = Alignment(vertical='top', wrap_text=False)
_fin = _pending(FINAL_DIR, 'config.py', 'lib/validation.py', 'pipeline/09_validation.ipynb')
_rul = _pending(ROOT)
for _text in (f"FINAL at {_git(FINAL_DIR, 'rev-parse', '--short', 'HEAD')} on {_git(FINAL_DIR, 'branch', '--show-current')}"
              f"; not committed there: {', '.join(_fin) or 'nothing'}.",
              f"RULES at {_git(ROOT, 'rev-parse', '--short', 'HEAD')} on {_git(ROOT, 'branch', '--show-current')}"
              f"; not committed there: {', '.join(_rul) or 'nothing'}.",
              f'Built {datetime.date.today().isoformat()} by scripts/12_rules_vs_llm_workbook.py (RULES worktree).'):
    ws.cell(_r, 2, _text).font = NOTE
    _r += 1

ws = wb.create_sheet('Lists')            # the catalogue the main-group formulas look up
ws.sheet_state = 'hidden'
ws['A1'], ws['B1'] = 'Class', 'Main group'
for _i, _k in enumerate(SHOW, 2):
    ws.cell(_i, 1, SHOW[_k])
    ws.cell(_i, 2, SHOW[HEAD[_k]])

wb.properties.title = 'Rules vs LLM on the validated places'
wb.properties.creator = 'scripts/12_rules_vs_llm_workbook.py'
wb.active = 0
OUT.parent.mkdir(parents=True, exist_ok=True)
wb.save(TMP)
print(f'wrote {TMP.name}: {len(CLS_ROWS):,} class places, {len(ACT_ROWS):,} activity places')


# ── 5. let Excel calculate and save, then check what it stored ──────────────────────────────────────────────────────
def _alive(pid):
    out = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'], capture_output=True, text=True).stdout
    return str(pid) in out


def excel_recalculate(path):
    """a hidden Excel instance of our own calculates and saves the file; only that instance is ever stopped.
    False when Excel cannot be driven here (the file then calculates when it is opened)."""
    try:
        import pythoncom
        import win32com.client
        import win32process
    except ImportError:
        return False
    pythoncom.CoInitialize()
    xl = win32com.client.DispatchEx('Excel.Application')
    pid = win32process.GetWindowThreadProcessId(xl.Hwnd)[1]
    try:
        xl.Visible = False
        xl.DisplayAlerts = False
        book = xl.Workbooks.Open(str(path), 0, False)
        xl.CalculateFull()
        book.Worksheets('Notes').UsedRange.Rows.AutoFit()      # the wrapped catalogue rows
        book.Worksheets('Summary').Activate()
        book.Save()
        book.Close(False)
        book = None
    finally:
        try:
            xl.Quit()
        except Exception:
            pass
        xl = None
        pythoncom.CoUninitialize()
        for _ in range(40):
            if not _alive(pid):
                break
            time.sleep(0.25)
        else:
            subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True)
    return True


ERRORS = {'#VALUE!', '#NAME?', '#DIV/0!', '#N/A', '#REF!', '#NUM!', '#NULL!', '#CALC!', '#SPILL!'}


def check_stored(path):
    """every formula value Excel stored equals the Python scoring; nothing is an error; the parts survived the save"""
    stored = load_workbook(path, data_only=True)
    errs = [f'{s.title}!{c.coordinate}' for s in stored.worksheets for row in s.iter_rows() for c in row
            if isinstance(c.value, str) and c.value in ERRORS]
    assert not errs, f'formula errors: {errs[:10]}'
    bad = []
    for (sheet, coord), want in EXPECT.items():
        got = stored[sheet][coord].value
        if isinstance(want, (int, float, np.integer, np.floating)) and not isinstance(want, bool):
            ok = isinstance(got, (int, float)) and math.isclose(got, float(want), rel_tol=1e-9, abs_tol=1e-12)
        else:
            ok = got == want
        if not ok:
            bad.append((sheet, coord, got, want))
    assert not bad, f'{len(bad)} stored values differ from the Python scoring, e.g. {bad[:5]}'
    full = load_workbook(path)
    for name, n_rows in (('Building class', len(CLS_ROWS)), ('Activities', len(ACT_ROWS))):
        s = full[name]
        assert len(s.tables) == 1, f'{name}: the table did not survive'
        assert s.freeze_panes == f'C{FIRST}', f'{name}: frozen panes lost'
        n_notes = sum(c.comment is not None for row in s.iter_rows(min_row=FIRST) for c in row)
        n_links = sum(c.hyperlink is not None for row in s.iter_rows(min_row=FIRST) for c in row)
        assert n_notes >= n_rows and n_links == n_rows, f'{name}: notes {n_notes}, links {n_links}'
        assert len(s.conditional_formatting) > 0, f'{name}: conditional formats lost'
    return len(EXPECT)


if excel_recalculate(TMP):
    _n = check_stored(TMP)              # on a failure TMP stays (*.unverified.xlsx) and OUT is left as it was
    os.replace(TMP, OUT)
    print(f'Excel recalculated it; {_n:,} stored values equal the Python scoring -> {OUT}')
else:
    os.replace(TMP, OUT)
    print(f'Excel is not available here: {OUT} calculates when it is opened (stored values not checked)')

e, a = EXP_CLS, EXP_ACT
print(f"Bosserhof exact: LLM {100 * e['all']['ex06']:.1f} %, rules {100 * e['all']['exr']:.1f} % "
      f"(only LLM {e['all']['b']}, only rules {e['all']['c']}, p {e['all']['p']:.2g}); by main group "
      f"{100 * e['all']['hd06']:.1f} vs {100 * e['all']['hdr']:.1f} (p {e['all']['ph']:.2g})")
print(f"activities F1, old merge: LLM {100 * a['all']['F06']:.1f}, rules {100 * a['all']['Fr']:.1f} "
      f"(bootstrap {_bo[0]:+.1f}, {_bo[1]:+.1f} .. {_bo[2]:+.1f}); FINAL map {100 * a['all_final']['F06']:.1f} vs "
      f"{100 * a['all_final']['Fr']:.1f}")
