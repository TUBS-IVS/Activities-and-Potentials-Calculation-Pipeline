"""Step 13, part 3: the new truth and the scores against it.

Usage:  python scripts/13_new_validation_workbook.py [<review workflow output .json> ...]

Merges the blind judgments (blind.json) with the reviewers' final judgments into truth.json (data/output/
13_new_validation/), scores the LLM (FINAL 06: bosserhof_class, llm_labels) and the rules (notebook 11, main run)
against it, and writes config.NEW_VALIDATION_WORKBOOK in the layout of step 12's workbook:
  Summary         scores against the new truth, by the judge's confidence and per label; old truth against new; how
                  good the new truth is (60 places judged twice, what the review changed)
  Building class  one row per place the new truth gives a class
  Activities      one row per place: the eleven MiD labels besides work
  Notes           how the truth was made, the inputs
The new truth per place: the class judged best plus the classes also accepted; the labels required plus the labels
optional (an optional label is neither credited nor counted wrong). Marks, main groups and scores are Excel formulas
over the text cells, as in step 12; a hidden Excel instance of its own recalculates the file, every stored value is
checked against the Python scoring, and only then is the file renamed into place.
The recalculation and check need Windows with Microsoft Excel and pywin32; elsewhere the file is written unchecked and
calculates when it is opened. FINAL is only read (GeoPackages immutable, no bytecode written next to its modules).
"""
import datetime
import hashlib
import importlib.util
import json
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
from config import *  # the RULES config: FINAL's paths, notebook 11's output, the step-13 folder and workbook


def _load(name, path):
    """a module by file path and under its own name, so it never shadows this config"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.dont_write_bytecode = True          # loading FINAL's modules must leave no __pycache__ in FINAL
FC = _load('final_config', FINAL_CONFIG_FILE)
V = _load('final_validation', FINAL_VALIDATION_LIB)
REV = _load('new_validation_review', Path(__file__).resolve().parent / '13_new_validation_review.py')

NM = FC.BOSSERHOF_NORMALIZATION_MAP
HEAD = V.class_headlines(FC.LLM_BOSSERHOF_SUBCATEGORIES, NM)
SIX = list(FC.VALIDATION_SCORED_CATEGORIES)
S6 = frozenset(SIX)
LABELS = REV.LABELS                                     # the eleven MiD labels besides work
SHOW = REV.SHOW                                         # class key -> the catalogue's wording
RANK = {k: i for i, k in enumerate(SHOW)}
HEADS = [SHOW[V.norm_class(h, NM)] for h in FC.LLM_BOSSERHOF_SUBCATEGORIES]
DIR = NEW_VALIDATION_DIR
FIRST = 7
OUT = NEW_VALIDATION_WORKBOOK
TMP = OUT.with_name(OUT.stem + '.unverified.xlsx')
OWN_ROLES = ('point', 'footprint', 'unit')
LAYER = {'poi_tags': 'POI tags', 'alkis_code': 'ALKIS code', 'osm_fallback': 'OSM building / land use',
         'no_signal': 'no signal'}
ROUTE = {'own call': 'own call', 'signature, own record': 'asked for its group',
         'signature, copied': 'copied from its group'}


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


# ── 1. the truth: the blind judgment, or the reviewer's where the place was reviewed ───────────────────────────────
places = pd.read_csv(DIR / 'places.csv', dtype=str).fillna('')
prim = places[places['duplicate_of'] == ''].set_index('pid')
blind = json.loads((DIR / 'blind.json').read_text(encoding='utf-8'))
assert set(prim.index) <= set(blind), 'blind judgments are missing: run part 2 on every stage-1 output first'
SENT = set()
for _f in (DIR / 'review').glob('r*.md'):
    SENT |= set(re.findall(r'^### (P\d{4})$', _f.read_text(encoding='utf-8'), re.M))
_rev = REV.load_runs(sys.argv[1:])
_missing = sorted(SENT - set(_rev))
if _missing:
    print(f'NOTE: {len(_missing)} of {len(SENT)} places sent to review have no review answer; their blind judgment '
          'stands')
truth = {}
for _pid, _row in prim.iterrows():
    _t = dict(blind[_pid], reviewed=False, changes='')
    if _pid in _rev and _pid in SENT:
        _j = _rev[_pid]
        _m = REV.clean({**_j, 'pid': _pid, 'confidence': _t['confidence'], 'changed': _t['changed'], 'web': _t['web'],
                        'reason': _t['reason']})
        _m.update(reviewed=True, changes=(_j.get('changes') or '').strip(), notes=_t['notes'] + _m['notes'],
                  blind={k: _t[k] for k in ('no_activity', 'class_best', 'class_accept', 'labels_required',
                                            'labels_optional')})
        _t = _m
    _t['pid'] = _pid
    truth[_row['building_id']] = _t
(DIR / 'truth.json').write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding='utf-8')
RELIABILITY = json.loads((DIR / 'reliability.json').read_text(encoding='utf-8')) if (DIR / 'reliability.json').exists() \
    else None


# ── 2. the places, their context and the two answers ─────────────────────────────────────────────────────────────────
def _txt(x):
    return ' '.join(x.split()) if isinstance(x, str) and x.strip() else None


def _set(text):
    return frozenset(s for s in text.split(';') if s) if isinstance(text, str) else None


def _unique(items, fold=False):
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
units = units[units['building_id'].isin(truth)].set_index('building_id')
assert len(units) == len(truth)
vrows = pyogrio.read_dataframe(FINAL_VALIDATION_FILE, layer='rows', read_geometry=False, IMMUTABLE='YES',
                               columns=['row', 'Status_B', 'Comment_B', 'Status_D', 'Comment_D']).set_index('row')
b06 = pyogrio.read_dataframe(FINAL_CLASSIFIED_FILE, layer='buildings', read_geometry=False, IMMUTABLE='YES',
                             columns=['building_id', 'label_en', 'name', 'address', 'city', 'llm_type', 'llm_labels',
                                      'bosserhof_class', 'llm_confidence', 'llm_reason']).set_index('building_id')
pois = pyogrio.read_dataframe(FINAL_CLASSIFIED_FILE, layer='building_pois', read_geometry=False, IMMUTABLE='YES',
                              columns=['building_id', 'poi_id', 'poi_role', 'poi_use', 'name', 'parent_name',
                                       'share_in_building'])
rules = pd.read_parquet(RULES_ON_FINAL_FILE).set_index('building_id')


def labels_of(text):
    """the eleven labels besides work in a label list 'a;b', in a fixed order"""
    return sorted({lab for lab in str(text).split(';') if lab in LABELS}, key=LABELS.index) if isinstance(text, str) else []


ANS = {b: {'k06': REV.key_of(b06.at[b, 'bosserhof_class']), 'L06': labels_of(b06.at[b, 'llm_labels']),
           'kr': REV.key_of(rules.at[b, 'cls_sites']), 'Lr': labels_of(rules.at[b, 'labels_sites']),
           'layer': rules.at[b, 'layer_sites']} for b in truth}
_off = sorted({a[k] for a in ANS.values() for k in ('k06', 'kr') if a[k] is not None} - set(HEAD))
assert not _off, f'answers outside the catalogue: {_off}'
ORDER = sorted(truth, key=lambda b: min(int(r) for r in str(units.at[b, 'rows']).split(';')))
CLS_PLACES = [b for b in ORDER if not truth[b]['no_activity']]


# ── 3. the scores in Python: what the formulas must give ─────────────────────────────────────────────────────────────
def acc_of(t):
    return [t['class_best'], *t['class_accept']]


def cls_hit(t, k):
    acc = acc_of(t)
    return k in acc, k is not None and HEAD.get(k) in {HEAD[a] for a in acc}


def counts(t, pred):
    """tp, fp, fn over the eleven labels; an optional label is neither credited nor counted wrong"""
    req, opt = set(t['labels_required']), set(t['labels_optional'])
    p = set(pred) - opt
    return len(p & req), len(p - req), len(req - p)


def mcnemar(x, y):
    x, y = np.asarray(x, bool), np.asarray(y, bool)
    b, c = int((x & ~y).sum()), int((~x & y).sum())
    n, k = b + c, min(b, c)
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n) if n else 1.0
    return b, c, p


def _f1(c):
    return 2 * c[..., 0] / (2 * c[..., 0] + c[..., 1] + c[..., 2])


def boot_diff(cx, cy):
    """micro F1 of x minus y in points, a 95 % percentile interval and a two-sided p (paired bootstrap)"""
    rng = np.random.default_rng(RULES_VS_LLM_SEED)
    idx = rng.integers(0, len(cx), size=(RULES_VS_LLM_BOOTSTRAP, len(cx)))
    d = 100 * (_f1(cx[idx].sum(axis=1)) - _f1(cy[idx].sum(axis=1)))
    lo, hi = np.percentile(d, [2.5, 97.5])
    p = min(1.0, 2 * min((d <= 0).mean(), (d >= 0).mean()))
    return 100 * (_f1(cx.sum(axis=0)) - _f1(cy.sum(axis=0))), lo, hi, p


def _prf(tp, fp, fn):
    return (tp / (tp + fp) if tp + fp else None, tp / (tp + fn) if tp + fn else None,
            2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None)


SUBSETS = (('all', None), ('high', 'high'), ('medium', 'medium'), ('low', 'low'))
EXP_CLS, EXP_ACT = {}, {}
for _name, _conf in SUBSETS:
    _bs = [b for b in CLS_PLACES if _conf is None or truth[b]['confidence'] == _conf]
    _h06 = [cls_hit(truth[b], ANS[b]['k06']) for b in _bs]
    _hr = [cls_hit(truth[b], ANS[b]['kr']) for b in _bs]
    _b, _c, _p = mcnemar([h[0] for h in _h06], [h[0] for h in _hr])
    _bh, _ch, _ph = mcnemar([h[1] for h in _h06], [h[1] for h in _hr])
    EXP_CLS[_name] = {'n': len(_bs), 'ex06': np.mean([h[0] for h in _h06]) if _bs else None,
                      'exr': np.mean([h[0] for h in _hr]) if _bs else None, 'b': _b, 'c': _c, 'p': _p,
                      'hd06': np.mean([h[1] for h in _h06]) if _bs else None,
                      'hdr': np.mean([h[1] for h in _hr]) if _bs else None, 'bh': _bh, 'ch': _ch, 'ph': _ph}
    _bs = [b for b in ORDER if _conf is None or truth[b]['confidence'] == _conf]
    _c06 = np.array([counts(truth[b], ANS[b]['L06']) for b in _bs]).reshape(-1, 3)
    _cr = np.array([counts(truth[b], ANS[b]['Lr']) for b in _bs]).reshape(-1, 3)
    _P0, _R0, _F0 = _prf(*_c06.sum(axis=0))
    _P1, _R1, _F1 = _prf(*_cr.sum(axis=0))
    EXP_ACT[_name] = {'n': len(_bs), 'P06': _P0, 'R06': _R0, 'F06': _F0, 'Pr': _P1, 'Rr': _R1, 'Fr': _F1,
                      'diff': 100 * (_F0 - _F1) if _F0 is not None and _F1 is not None else None,
                      'ex06': float(np.mean((_c06[:, 1] + _c06[:, 2]) == 0)) if _bs else None,
                      'exr': float(np.mean((_cr[:, 1] + _cr[:, 2]) == 0)) if _bs else None}
BOOT = boot_diff(np.array([counts(truth[b], ANS[b]['L06']) for b in ORDER]),
                 np.array([counts(truth[b], ANS[b]['Lr']) for b in ORDER]))
PER_LABEL = {}
for _lab in LABELS:
    _row = {'support': sum(_lab in truth[b]['labels_required'] for b in ORDER)}
    for _arm, _k in (('06', 'L06'), ('r', 'Lr')):
        _tp = sum(_lab in truth[b]['labels_required'] and _lab in ANS[b][_k] for b in ORDER)
        _fp = sum(_lab in ANS[b][_k] and _lab not in truth[b]['labels_required'] and _lab not in truth[b]['labels_optional']
                  for b in ORDER)
        _fn = sum(_lab in truth[b]['labels_required'] and _lab not in ANS[b][_k] for b in ORDER)
        _row[_arm] = _prf(_tp, _fp, _fn)
    PER_LABEL[_lab] = _row

# the old truth on the same answers (notebook 12's scoring), and how far the two truths agree
_heads_old = V.class_headlines(FC.LLM_BOSSERHOF_SUBCATEGORIES, NM)
OLD = {}
_oc = [(b, _set(units.at[b, 'cls_truth'])) for b in ORDER]
_oc = [(b, t) for b, t in _oc if t]
OLD['cls_n'] = len(_oc)
for _arm in ('06', 'r'):
    _hits = [V.class_hits(t, ANS[b]['k' + _arm], _heads_old) for b, t in _oc]
    OLD[f'ex{_arm}'] = float(np.mean([h[0] for h in _hits]))
    OLD[f'hd{_arm}'] = float(np.mean([h[1] for h in _hits]))
_both = [(b, t) for b, t in _oc if not truth[b]['no_activity']]
OLD['cls_agree'] = float(np.mean([bool(set(t) & set(acc_of(truth[b]))) for b, t in _both]))
OLD['cls_agree_n'] = len(_both)
OLD['cls_no_activity'] = sum(truth[b]['no_activity'] for b, _ in _oc)


def six(labels):
    return V.to_categories(list(labels), FC.MID_LABEL_TO_ACTIVITY) & S6


def six_counts(t, pred):
    """six-category counts through FINAL's map; categories only optional labels give are neither credited nor wrong"""
    req = six(t['labels_required'])
    opt = six(t['labels_optional']) - req
    p = six(pred) - opt
    return len(p & req), len(p - req), len(req - p)


_oa = [(b, _set(units.at[b, 'act_truth'])) for b in ORDER]
_oa = [(b, t) for b, t in _oa if t is not None]
OLD['act_n'] = len(_oa)
for _arm, _k in (('06', 'L06'), ('r', 'Lr')):
    _d, _ = V.set_scores([t for _, t in _oa], [six(ANS[b][_k]) for b, _ in _oa], SIX)
    OLD[f'F{_arm}'] = float(_d.set_index('category').loc['micro', 'f1'])
    _c = np.array([six_counts(truth[b], ANS[b][_k]) for b in ORDER]).sum(axis=0)
    OLD[f'Fnew{_arm}'] = _prf(*_c)[2]
OLD['act_agree'] = float(np.mean([(t & S6) == six(truth[b]['labels_required']) for b, t in _oa]))

# what the review did
REVIEW = {'sent': len(SENT), 'answered': sum(t['reviewed'] for t in truth.values()),
          'changed': sum(bool(t['changes']) for t in truth.values())}
for _arm, _k, _l in (('06', 'k06', 'L06'), ('r', 'kr', 'Lr')):
    _cls_new = _lab_new = 0
    for b, t in truth.items():
        if not t['reviewed']:
            continue
        bl = t['blind']
        if not t['no_activity'] and not bl['no_activity']:
            _cls_new += cls_hit(t, ANS[b][_k])[0] and not cls_hit(bl, ANS[b][_k])[0]
        _lab_new += sum(counts(t, ANS[b][_l])[1:]) == 0 and sum(counts(bl, ANS[b][_l])[1:]) > 0
    REVIEW[f'cls_now_right_{_arm}'] = _cls_new
    REVIEW[f'labels_now_right_{_arm}'] = _lab_new
REVIEW['best_changed'] = sum(t['reviewed'] and t['class_best'] != t['blind']['class_best'] for t in truth.values())
REVIEW['required_changed'] = sum(t['reviewed'] and set(t['labels_required']) != set(t['blind']['labels_required'])
                                 for t in truth.values())


# ── 4. what a place's row shows ──────────────────────────────────────────────────────────────────────────────────────
def show_cls(k):
    return '(no class)' if k is None else SHOW.get(k, k)


def show_head(k):
    return '–' if k is None else SHOW.get(HEAD[k], HEAD[k])


def show_heads(ks):
    return ' | '.join(_unique(show_head(k) for k in sorted(ks, key=lambda k: (RANK.get(HEAD[k], len(RANK)), k))))


def show_old_cls(t):
    if t is None:
        return '(no old truth)'
    return ' | '.join(show_cls(k) for k in sorted(t, key=lambda k: (RANK.get(k, len(RANK)), k))) if t else 'no class'


def show_old_act(t):
    if t is None:
        return '(no old truth)'
    return ', '.join(c for c in SIX if c in t) if t & S6 else ('no activity' if not t else 'work only')


def miss_extra(t, pred):
    req, opt = set(t['labels_required']), set(t['labels_optional'])
    missed = [lab for lab in LABELS if lab in req - set(pred)]
    extra = [lab for lab in LABELS if lab in set(pred) - opt - req]
    return ' · '.join(p for p in (('missed ' + ', '.join(missed)) if missed else '',
                                  ('extra ' + ', '.join(extra)) if extra else '') if p)


def _poi(r, site=False):
    name, use = _txt(r['name']), _txt(r['poi_use']) or 'POI'
    where = f', in {_txt(r["parent_name"])}' if r['poi_role'] == 'unit' and _txt(r['parent_name']) else ''
    text = f'{name} ({use}{where})' if name else f'({use}{where})'
    return f'site: {text}' if site else text


pois = pois[pois['building_id'].isin(truth)].copy()
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
_ll = units.geometry.representative_point().to_crs(4326)
MAP = {b: f'https://www.google.com/maps/place/{y:.6f},{x:.6f}/@{y:.6f},{x:.6f},19z'
       for b, x, y in zip(units.index, _ll.x, _ll.y)}


def place_text(b):
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


def old_verdict(rows_text, dim):
    status, comment = ('Status_D', 'Comment_D') if dim == 'class' else ('Status_B', 'Comment_B')
    rows = [int(r) for r in str(rows_text).split(';')]
    parts = []
    for r in rows:
        s, c = _txt(vrows.at[r, status]) or '–', _txt(vrows.at[r, comment])
        text = f'{s}: {c}' if c else s
        parts.append(f'row {r}: {text}' if len(rows) > 1 else text)
    return ' | '.join(parts)


def review_text(t):
    if not t['reviewed']:
        return ''
    return t['changes'] or 'reviewed: no change'


def common(b):
    t = truth[b]
    city = _txt(b06.at[b, 'city'])
    return {'place': place_text(b), 'city': re.sub(r'\s*,\s*(Stadt|Flecken)$', '', city) if city else '–', 'map': MAP[b],
            'alkis': _txt(b06.at[b, 'label_en']) or '–', 'address': _txt(b06.at[b, 'address']) or '–', 'bid': b,
            'rows': str(units.at[b, 'rows']).replace(';', ', '), 'pois': pois_text(b),
            'l_type': _txt(b06.at[b, 'llm_type']) or '–', 'l_conf': _txt(b06.at[b, 'llm_confidence']) or '–',
            'l_route': ROUTE.get(units.at[b, 'route_copied'], _txt(units.at[b, 'route_copied']) or '–'),
            'l_reason': _txt(b06.at[b, 'llm_reason']) or '–', 'r_layer': LAYER.get(ANS[b]['layer'], ANS[b]['layer']),
            'l_cls': show_cls(ANS[b]['k06']), 'r_cls': show_cls(ANS[b]['kr']), 't_conf': t['confidence'],
            'reason': t['reason'] or '–', 'web': t['web'] or '', 'changed': 'yes' if t['changed'] else '',
            'review': review_text(t)}


def _mark(exact, near):
    return '✓' if exact else ('≈' if near else '✗')


def _judge_note(t):
    return 'Judge: ' + (t['reason'] or '–') + (f"\nWeb: {t['web']}" if t['web'] else '') + \
        (f"\nReview: {t['changes']}" if t['changes'] else '')


CLS_ROWS = []
for _i, b in enumerate(CLS_PLACES, 1):
    t = truth[b]
    r = common(b)
    acc = sorted(t['class_accept'], key=lambda k: (RANK.get(k, len(RANK)), k))
    r.update(n=_i, t_best=show_cls(t['class_best']), t_also=' | '.join(show_cls(k) for k in acc) or '–',
             o_truth=show_old_cls(_set(units.at[b, 'cls_truth'])), o_verdict=old_verdict(units.at[b, 'rows'], 'class'))
    _lm, _rm = _mark(*cls_hit(t, ANS[b]['k06'])), _mark(*cls_hit(t, ANS[b]['kr']))
    r['_expect'] = {'t_head': show_heads(acc_of(t)), 'l_head': show_head(ANS[b]['k06']), 'r_head': show_head(ANS[b]['kr']),
                    'l_mark': _lm, 'r_mark': _rm,
                    'who': ('both right' if _lm == _rm == '✓' else 'only LLM right' if _lm == '✓'
                            else 'only rules right' if _rm == '✓' else 'neither')}
    r['_notes'] = {'t_best': _judge_note(t), 'l_cls': f"LLM's reason ({r['l_conf']} confidence): {r['l_reason']}"}
    CLS_ROWS.append(r)

ACT_ROWS = []
for _i, b in enumerate(ORDER, 1):
    t = truth[b]
    r = common(b)
    r.update(n=_i, t_req=', '.join(t['labels_required']) or ('no activity' if t['no_activity'] else '– (staff only)'),
             t_opt=', '.join(t['labels_optional']) or '–', l_lab=', '.join(ANS[b]['L06']) or '–',
             r_lab=', '.join(ANS[b]['Lr']) or '–', l_miss=miss_extra(t, ANS[b]['L06']), r_miss=miss_extra(t, ANS[b]['Lr']),
             o_truth=show_old_act(_set(units.at[b, 'act_truth'])), o_verdict=old_verdict(units.at[b, 'rows'], 'act'))
    _exp, _err = {}, {}
    for side, k in (('l', 'L06'), ('r', 'Lr')):
        tp, fp, fn = counts(t, ANS[b][k])
        _exp.update({f'{side}tp': tp, f'{side}fp': fp, f'{side}fn': fn,
                     f'{side}_mark': '✓' if fp + fn == 0 else ('≈' if tp else '✗')})
        _err[side] = fp + fn
    _exp['who'] = ('both right' if _err['l'] == _err['r'] == 0 else 'only LLM right' if _err['l'] == 0
                   else 'only rules right' if _err['r'] == 0 else 'LLM closer' if _err['l'] < _err['r']
                   else 'rules closer' if _err['r'] < _err['l'] else 'equally off')
    r['_expect'] = _exp
    r['_notes'] = {'t_req': _judge_note(t), 'l_lab': f"LLM's reason ({r['l_conf']} confidence): {r['l_reason']}"}
    ACT_ROWS.append(r)


# ── 5. the workbook ──────────────────────────────────────────────────────────────────────────────────────────────────
def font(size=10, bold=False, italic=False, color='000000', underline=None):
    return Font(name='Arial', size=size, bold=bold, italic=italic, color=color, underline=underline)


def fill(rgb):
    return PatternFill(fill_type='solid', start_color=rgb, end_color=rgb)


BLOCKS = {          # title, dark, light
    'place':   ('PLACE', '595959', 'E7E6E6'),
    'truth':   ('NEW TRUTH (blind judgment, reviewed)', '5B3A8E', 'E6DEF0'),
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
CONF = (('high', 'E2EFDA', '375623'), ('medium', 'FFF2CC', '7F6000'), ('low', 'FCE4D6', '843C0C'))
CENTER = Alignment(horizontal='center', vertical='center')
LEFT = Alignment(horizontal='left', vertical='center')
EDGE = Side(style='thin', color='A6A6A6')
LABS = '{' + ','.join(f'"{lab}"' for lab in LABELS) + '}'          # the eleven labels as an array constant
CATC = f'Lists!$A$2:$A${len(SHOW) + 1}'                             # the catalogue on the hidden sheet Lists
CATG = f'Lists!$B$2:$B${len(SHOW) + 1}'

DETAILS_COMMON = [
    ('reason', "Judge's reason", 60, 'details', 'text'), ('web', 'Web finding', 50, 'details', 'text'),
    ('changed', 'Changed since OSM', 10, 'details', 'text'), ('review', 'Review', 50, 'details', 'text'),
]
CONTEXT = [
    ('l_conf', 'LLM confidence', 11, 'details', 'text'), ('l_route', 'LLM call', 20, 'details', 'text'),
    ('address', 'Address', 24, 'details', 'text'), ('bid', 'Building ID', 19, 'details', 'text'),
    ('rows', 'Sample row', 10, 'details', 'text'),
    ('pois', 'POIs on the building (site: = around it)', 50, 'details', 'text'),
    ('l_reason', "LLM's reason", 80, 'details', 'text'),
]
PLACE = [
    ('n', 'No.', 5, 'place', 'int'), ('place', 'Place', 34, 'place', 'text'), ('city', 'City', 15, 'place', 'text'),
    ('map', 'Map', 6, 'place', 'link'), ('alkis', 'ALKIS building use', 30, 'place', 'text'),
]
CLS_COLS = PLACE + [
    ('t_best', 'Best class', 30, 'truth', 'text'), ('t_also', 'Also accepted', 36, 'truth', 'text'),
    ('t_head', 'Main group(s)', 30, 'truth', 'text'), ('t_conf', 'Judge', 9, 'truth', 'conf'),
    ('l_type', "LLM's description", 34, 'llm', 'text'), ('l_cls', 'LLM class', 32, 'llm', 'text'),
    ('l_mark', 'LLM ✓', 7, 'llm', 'mark'),
    ('r_layer', 'Rules decided by', 14, 'rules', 'text'), ('r_cls', 'Rules class', 32, 'rules', 'text'),
    ('r_mark', 'Rules ✓', 7, 'rules', 'mark'),
    ('who', 'Who is right', 23, 'cmp', 'who'),
] + DETAILS_COMMON + [
    ('o_truth', 'Old truth (previous validator)', 34, 'details', 'grey'),
    ('o_verdict', "Old validator's verdict", 30, 'details', 'grey'),
    ('l_head', 'LLM main group', 30, 'details', 'text'), ('r_head', 'Rules main group', 30, 'details', 'text'),
] + CONTEXT + [
    ('h_lex', 'LLM exact (1/0)', 9, 'helpers', 'helper'), ('h_lhd', 'LLM main group (1/0)', 9, 'helpers', 'helper'),
    ('h_rex', 'Rules exact (1/0)', 9, 'helpers', 'helper'), ('h_rhd', 'Rules main group (1/0)', 9, 'helpers', 'helper'),
    ('h_lonly', 'Only LLM exact (1/0)', 9, 'helpers', 'helper'),
    ('h_ronly', 'Only rules exact (1/0)', 9, 'helpers', 'helper'),
    ('h_lonlyhd', 'Only LLM main group (1/0)', 9, 'helpers', 'helper'),
    ('h_ronlyhd', 'Only rules main group (1/0)', 9, 'helpers', 'helper'),
    ('h_high', 'Judge high (1/0)', 9, 'helpers', 'helper'), ('h_rev', 'Reviewed (1/0)', 9, 'helpers', 'helper'),
]
ACT_COLS = PLACE + [
    ('t_req', 'Labels required', 32, 'truth', 'text'), ('t_opt', 'Labels optional', 28, 'truth', 'text'),
    ('t_conf', 'Judge', 9, 'truth', 'conf'),
    ('l_lab', 'LLM labels', 32, 'llm', 'text'), ('l_mark', 'LLM ✓', 7, 'llm', 'mark'),
    ('l_miss', 'LLM missed / extra', 32, 'llm', 'text'),
    ('r_layer', 'Rules decided by', 14, 'rules', 'text'), ('r_lab', 'Rules labels', 32, 'rules', 'text'),
    ('r_mark', 'Rules ✓', 7, 'rules', 'mark'), ('r_miss', 'Rules missed / extra', 32, 'rules', 'text'),
    ('who', 'Who is closer', 24, 'cmp', 'who'),
] + DETAILS_COMMON + [
    ('o_truth', 'Old truth (previous validator, six categories)', 34, 'details', 'grey'),
    ('o_verdict', "Old validator's verdict", 30, 'details', 'grey'),
    ('l_type', "LLM's description", 34, 'details', 'text'), ('l_cls', 'LLM class', 30, 'details', 'text'),
    ('r_cls', 'Rules class', 30, 'details', 'text'),
] + CONTEXT + [(f'{s}{x}', f'{who} {what} (n)', 9, 'helpers', 'helper')
               for s, who in (('l', 'LLM'), ('r', 'Rules')) for x, what in (('tp', 'right'), ('fp', 'extra'),
                                                                            ('fn', 'missed'))] + [
    ('h_lex', 'LLM exact set (1/0)', 9, 'helpers', 'helper'), ('h_rex', 'Rules exact set (1/0)', 9, 'helpers', 'helper'),
    ('h_lfewer', 'LLM fewer errors (1/0)', 9, 'helpers', 'helper'),
    ('h_rfewer', 'Rules fewer errors (1/0)', 9, 'helpers', 'helper'),
    ('h_high', 'Judge high (1/0)', 9, 'helpers', 'helper'), ('h_rev', 'Reviewed (1/0)', 9, 'helpers', 'helper'),
]


def _found(needle, hay):
    """Excel: is the text of cell `needle` one of the ' | '-separated entries of `hay` (any case)"""
    return f'ISNUMBER(SEARCH(" | "&{needle}&" | "," | "&{hay}&" | "))'


def _in_group(hay, group):
    """Excel: does any entry of `hay` (' | '-separated) lie in main group `group` (a cell or a quoted text)"""
    return f'SUMPRODUCT(ISNUMBER(SEARCH(" | "&{CATC}&" | "," | "&{hay}&" | "))*({CATG}={group}))>0'


def cls_formulas(L, r):
    c = {k: f'{v}{r}' for k, v in L.items()}
    hay = f'{c["t_best"]}&" | "&{c["t_also"]}'
    groups = [f'IF({_in_group(hay, chr(34) + h + chr(34))}," | {h}","")' for h in HEADS]
    return {
        't_head': f'=MID({"&".join(groups)},4,999)',
        'l_head': f'=IFERROR(INDEX({CATG},MATCH({c["l_cls"]},{CATC},0)),"–")',
        'r_head': f'=IFERROR(INDEX({CATG},MATCH({c["r_cls"]},{CATC},0)),"–")',
        'l_mark': f'=IF({_found(c["l_cls"], hay)},"✓",IF({_in_group(hay, c["l_head"])},"≈","✗"))',
        'r_mark': f'=IF({_found(c["r_cls"], hay)},"✓",IF({_in_group(hay, c["r_head"])},"≈","✗"))',
        'who': (f'=IF({c["l_mark"]}="✓",IF({c["r_mark"]}="✓","both right","only LLM right"),'
                f'IF({c["r_mark"]}="✓","only rules right","neither"))'),
        'h_lex': f'=IF({c["l_mark"]}="✓",1,0)', 'h_lhd': f'=IF({c["l_mark"]}="✗",0,1)',
        'h_rex': f'=IF({c["r_mark"]}="✓",1,0)', 'h_rhd': f'=IF({c["r_mark"]}="✗",0,1)',
        'h_lonly': f'={c["h_lex"]}*(1-{c["h_rex"]})', 'h_ronly': f'=(1-{c["h_lex"]})*{c["h_rex"]}',
        'h_lonlyhd': f'={c["h_lhd"]}*(1-{c["h_rhd"]})', 'h_ronlyhd': f'=(1-{c["h_lhd"]})*{c["h_rhd"]}',
        'h_high': f'=IF({c["t_conf"]}="high",1,0)', 'h_rev': f'=IF({c["review"]}<>"",1,0)',
    }


def act_formulas(L, r):
    c = {k: f'{v}{r}' for k, v in L.items()}
    req = f'ISNUMBER(SEARCH({LABS},{c["t_req"]}))'
    opt = f'ISNUMBER(SEARCH({LABS},{c["t_opt"]}))'
    out = {}
    for s, col in (('l', 'l_lab'), ('r', 'r_lab')):
        p = f'ISNUMBER(SEARCH({LABS},{c[col]}))'
        out[f'{s}tp'] = f'=SUMPRODUCT({p}*{req})'
        out[f'{s}fp'] = f'=SUMPRODUCT({p}*(1-{opt})*(1-{req}))'
        out[f'{s}fn'] = f'=SUMPRODUCT({req}*(1-{p}))'
    el, er = f'({c["lfp"]}+{c["lfn"]})', f'({c["rfp"]}+{c["rfn"]})'
    out['l_mark'] = f'=IF({el}=0,"✓",IF({c["ltp"]}>0,"≈","✗"))'
    out['r_mark'] = f'=IF({er}=0,"✓",IF({c["rtp"]}>0,"≈","✗"))'
    out['who'] = (f'=IF(AND({el}=0,{er}=0),"both right",IF({el}=0,"only LLM right",IF({er}=0,"only rules right",'
                  f'IF({el}<{er},"LLM closer",IF({er}<{el},"rules closer","equally off")))))')
    out['h_lex'] = f'=IF({c["l_mark"]}="✓",1,0)'
    out['h_rex'] = f'=IF({c["r_mark"]}="✓",1,0)'
    out['h_lfewer'] = f'=IF({el}<{er},1,0)'
    out['h_rfewer'] = f'=IF({er}<{el},1,0)'
    out['h_high'] = f'=IF({c["t_conf"]}="high",1,0)'
    out['h_rev'] = f'=IF({c["review"]}<>"",1,0)'
    return out


def _clean(v):
    """text safe for a cell: no control characters, never read as a formula"""
    if isinstance(v, str):
        v = ILLEGAL_CHARACTERS_RE.sub('', v)
        if v[:1] == '=':
            v = ' ' + v
    return v


def _spans(cols):
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
    for row, k0, k1, value, fmt, block, want in banner(L, last):
        c0 = next(i for i, c in enumerate(cols, 1) if c[0] == k0)
        c1 = next(i for i, c in enumerate(cols, 1) if c[0] == k1)
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
              'conf': (font(9), CENTER), 'helper': (font(9, color='7F7F7F'), CENTER)}
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
                cell.comment = Comment(_clean(note), 'note', width=420, height=170)
    for key, kind in ((c[0], c[4]) for c in cols):
        rng = f'{L[key]}{FIRST}:{L[key]}{last}'
        for text, bg, fg in {'mark': MARKS, 'who': WHO, 'conf': CONF}.get(kind, ()):
            ws.conditional_formatting.add(rng, CellIsRule(operator='equal', formula=[f'"{text}"'], fill=fill(bg),
                                                          font=Font(color=fg, bold=kind == 'mark')))
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
        (3, 't_best', 't_conf', f'={_sum(L, "h_high", last)}', '"judged with high confidence: "#,##0', 'truth',
         sum(truth[b]['confidence'] == 'high' for b in CLS_PLACES)),
        (4, 't_best', 't_conf', f'={_sum(L, "h_rev", last)}', '"reviewed: "#,##0', 'truth',
         sum(truth[b]['reviewed'] for b in CLS_PLACES)),
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
        (3, 't_req', 't_conf', f'={_sum(L, "h_high", last)}', '"judged with high confidence: "#,##0', 'truth',
         sum(truth[b]['confidence'] == 'high' for b in ORDER)),
        (4, 't_req', 't_conf', f'={_sum(L, "h_rev", last)}', '"reviewed: "#,##0', 'truth',
         sum(truth[b]['reviewed'] for b in ORDER)),
        (3, 'l_lab', 'l_miss', f1('l'), '"F1: "0.0%', 'llm', e['F06']),
        (4, 'l_lab', 'l_lab', prec('l'), '"precision: "0.0%', 'llm', e['P06']),
        (4, 'l_mark', 'l_miss', rec('l'), '"recall: "0.0%', 'llm', e['R06']),
        (3, 'r_layer', 'r_miss', f1('r'), '"F1: "0.0%', 'rules', e['Fr']),
        (4, 'r_layer', 'r_lab', prec('r'), '"precision: "0.0%', 'rules', e['Pr']),
        (4, 'r_mark', 'r_miss', rec('r'), '"recall: "0.0%', 'rules', e['Rr']),
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
_sub = ('One row per place the new truth gives a class.  ✓ the best class or one also accepted  ·  ≈ another class in '
        'the same main group  ·  ✗ wrong or no class.  Filter with the ▼ buttons in row 6.  Hover over a truth to read '
        "the judge's reason, over an LLM class for the LLM's.")
LC, LAST_C, _e = place_sheet(ws_cls, CLS_COLS, CLS_ROWS, cls_formulas,
                             f'Building class: new truth, LLM and rules side by side ({len(CLS_ROWS):,} places)',
                             _sub, cls_banner, 'tblBuildingClass')
EXPECT.update(_e)
_sub = ('One row per place; the eleven MiD labels besides work.  ✓ every required label and nothing outside required or '
        'optional  ·  ≈ partly right  ·  ✗ nothing right.  An optional label is neither credited nor counted wrong.')
LA, LAST_A, _e = place_sheet(ws_act, ACT_COLS, ACT_ROWS, act_formulas,
                             f'Activities: new truth, LLM and rules side by side ({len(ACT_ROWS):,} places)',
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
PCT = '0.0%'
P_FMT = '[<0.001]"< 0.001";[<0.01]0.0000;0.000'


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
    put(first, text, font(9, bold=True, color='FFFFFF'), align=Alignment(horizontal='center', vertical='center',
                                                                         wrap_text=True), bg=BLOCKS[block][1])
    if first != last_:
        ws.merge_cells(cells)


def sub(cell, text, block):
    put(cell, text, HEADF, align=Alignment(horizontal='center', vertical='center', wrap_text=True), bg=BLOCKS[block][2])


put('B2', 'New validation: LLM and rules against a blind re-judgment', font(16, bold=True, color='1F1F1F'))
put('B3', f'The same {len(ORDER):,} places as notebook 12, judged again in FINAL\'s own label scheme: blind first, then '
          'reviewed where an answer fell outside the judgment.', font(10, color='595959'))
put('B4', 'Sheets:', font(10, bold=True))
for _cell, _sheet, _text in (('C4', 'Building class', f'Building class ({len(CLS_ROWS):,} places) ▸'),
                             ('F4', 'Activities', f'Activities ({len(ACT_ROWS):,} places) ▸'),
                             ('I4', 'Notes', 'Notes ▸')):
    _c = put(_cell, _text, font(10, color='0563C1', underline='single'))
    _c.hyperlink = Hyperlink(ref=_cell, location=f"'{_sheet}'!A1", display=_text)

_SUBL = {'all': 'All places', 'high': "Judge's confidence high", 'medium': "Judge's confidence medium",
         'low': "Judge's confidence low"}

# building class
put('B6', 'Building class (Bosserhof)', font(12, bold=True, color='1F1F1F'))
head('C7:C8', 'Places', 'place')
head('D7:H7', 'Exact class (best or also accepted)', 'cmp')
head('I7:M7', 'Right main group', 'cmp')
for _c0 in ('D', 'I'):
    _cols = [get_column_letter(ws[f'{_c0}8'].column + k) for k in range(5)]
    for _col, _t, _b in zip(_cols, ('LLM', 'Rules', 'only LLM right', 'only rules right', 'p (paired test)'),
                            ('llm', 'rules', 'llm', 'rules', 'cmp')):
        sub(f'{_col}8', _t, _b)
ws.row_dimensions[8].height = 26
for _r, (_name, _conf) in zip(range(9, 13), SUBSETS):
    e = EXP_CLS[_name]
    put(f'B{_r}', _SUBL[_name], font(10, bold=_name == 'all'))
    if _conf is None:
        _n = f'=COUNT({cr("h_lex")})'

        def S(k):
            return f'SUM({cr(k)})'
    else:
        _n = f'=COUNTIF({cr("t_conf")},"{_conf}")'

        def S(k, _v=_conf):
            return f'SUMIFS({cr(k)},{cr("t_conf")},"{_v}")'
    put(f'C{_r}', _n, fmt='#,##0', align=CENTER, want=e['n'])
    for _cols, (ex, rx, ol, orr, kl, kr_, kb, kc, kp) in (
            (('D', 'E', 'F', 'G', 'H'), ('h_lex', 'h_rex', 'h_lonly', 'h_ronly', 'ex06', 'exr', 'b', 'c', 'p')),
            (('I', 'J', 'K', 'L', 'M'), ('h_lhd', 'h_rhd', 'h_lonlyhd', 'h_ronlyhd', 'hd06', 'hdr', 'bh', 'ch', 'ph'))):
        put(f'{_cols[0]}{_r}', f'=IFERROR({S(ex)}/C{_r},"–")', fmt=PCT, align=CENTER,
            want=e[kl] if e[kl] is not None else '–')
        put(f'{_cols[1]}{_r}', f'=IFERROR({S(rx)}/C{_r},"–")', fmt=PCT, align=CENTER,
            want=e[kr_] if e[kr_] is not None else '–')
        put(f'{_cols[2]}{_r}', f'={S(ol)}', fmt='#,##0', align=CENTER, want=e[kb])
        put(f'{_cols[3]}{_r}', f'={S(orr)}', fmt='#,##0', align=CENTER, want=e[kc])
        _b, _c = f'{_cols[2]}{_r}', f'{_cols[3]}{_r}'
        put(f'{_cols[4]}{_r}', f'=IF({_b}+{_c}=0,1,MIN(1,2*BINOMDIST(MIN({_b},{_c}),{_b}+{_c},0.5,TRUE)))',
            fmt=P_FMT, align=CENTER, want=e[kp])
for _rng, _col in (('D9:D12', '5B9BD5'), ('E9:E12', 'F4B183'), ('I9:I12', '5B9BD5'), ('J9:J12', 'F4B183')):
    ws.conditional_formatting.add(_rng, DataBarRule(start_type='num', start_value=0, end_type='num', end_value=1,
                                                    color=_col))
put('B13', 'Exact: the answer is the class judged best or one also accepted. Main group: it lies in the main group of one '
           'of them.', NOTE)
put('B14', 'p: exact two-sided McNemar test on the places only one of the two gets right (as notebook 12).', NOTE)

# activities
put('B16', 'Activities (the eleven MiD labels besides work)', font(12, bold=True, color='1F1F1F'))
head('C17:C18', 'Places', 'place')
head('D17:F17', 'LLM', 'llm')
head('G17:I17', 'Rules', 'rules')
head('J17:J18', 'F1: LLM − rules (points)', 'cmp')
head('K17:L17', 'Exact set', 'cmp')
for _c, _t, _b in (('D', 'precision', 'llm'), ('E', 'recall', 'llm'), ('F', 'F1', 'llm'), ('G', 'precision', 'rules'),
                   ('H', 'recall', 'rules'), ('I', 'F1', 'rules'), ('K', 'LLM', 'llm'), ('L', 'Rules', 'rules')):
    sub(f'{_c}18', _t, _b)
ws.row_dimensions[18].height = 26
for _r, (_name, _conf) in zip(range(19, 23), SUBSETS):
    e = EXP_ACT[_name]
    put(f'B{_r}', _SUBL[_name], font(10, bold=_name == 'all'))
    if _conf is None:
        put(f'C{_r}', f'=COUNT({ar("ltp")})', fmt='#,##0', align=CENTER, want=e['n'])

        def S(k):
            return f'SUM({ar(k)})'

        def X(s):
            return f'SUMPRODUCT(--(({ar(s + "fp")}+{ar(s + "fn")})=0))'
    else:
        put(f'C{_r}', f'=COUNTIF({ar("t_conf")},"{_conf}")', fmt='#,##0', align=CENTER, want=e['n'])

        def S(k, _v=_conf):
            return f'SUMIFS({ar(k)},{ar("t_conf")},"{_v}")'

        def X(s, _v=_conf):
            return f'SUMPRODUCT((({ar(s + "fp")}+{ar(s + "fn")})=0)*({ar("t_conf")}="{_v}"))'
    for _side, (cp, cr_, cf), (kp, kr2, kf) in (('l', ('D', 'E', 'F'), ('P06', 'R06', 'F06')),
                                               ('r', ('G', 'H', 'I'), ('Pr', 'Rr', 'Fr'))):
        tp, fp, fn = (S(f'{_side}{x}') for x in ('tp', 'fp', 'fn'))
        put(f'{cp}{_r}', f'=IFERROR({tp}/({tp}+{fp}),"–")', fmt=PCT, align=CENTER, want=e[kp] if e[kp] is not None else '–')
        put(f'{cr_}{_r}', f'=IFERROR({tp}/({tp}+{fn}),"–")', fmt=PCT, align=CENTER,
            want=e[kr2] if e[kr2] is not None else '–')
        put(f'{cf}{_r}', f'=IFERROR(2*{tp}/(2*{tp}+{fp}+{fn}),"–")', fmt=PCT, align=CENTER,
            want=e[kf] if e[kf] is not None else '–')
    put(f'J{_r}', f'=IFERROR((F{_r}-I{_r})*100,"–")', fmt='+0.0;"−"0.0;0.0', align=CENTER,
        want=e['diff'] if e['diff'] is not None else '–')
    put(f'K{_r}', f'=IFERROR({X("l")}/C{_r},"–")', fmt=PCT, align=CENTER, want=e['ex06'] if e['ex06'] is not None else '–')
    put(f'L{_r}', f'=IFERROR({X("r")}/C{_r},"–")', fmt=PCT, align=CENTER, want=e['exr'] if e['exr'] is not None else '–')
for _rng, _col in (('F19:F22', '5B9BD5'), ('I19:I22', 'F4B183')):
    ws.conditional_formatting.add(_rng, DataBarRule(start_type='num', start_value=0, end_type='num', end_value=1,
                                                    color=_col))


def _p(p):
    return f'< {2 / RULES_VS_LLM_BOOTSTRAP:.3f}' if p == 0 else f'{p:.2g}'


put('B23', f'Paired bootstrap of the F1 difference ({RULES_VS_LLM_BOOTSTRAP:,} resamples of the places, seed '
           f'{RULES_VS_LLM_SEED}): {BOOT[0]:+.1f} points, 95 % interval {BOOT[1]:+.1f} .. {BOOT[2]:+.1f}, p {_p(BOOT[3])}'
           + ('; significant.' if BOOT[1] > 0 or BOOT[2] < 0 else '; not significant.'), NOTE)
put('B24', 'A required label the answer misses counts against it; a label outside required and optional counts against '
           'it; an optional label counts neither way.', NOTE)

# per label
put('B26', 'Per label', font(12, bold=True, color='1F1F1F'))
sub('B27', 'label', 'place')
sub('C27', 'places requiring it', 'place')
for _c, _t, _b in (('D', 'LLM precision', 'llm'), ('E', 'LLM recall', 'llm'), ('F', 'LLM F1', 'llm'),
                   ('G', 'Rules precision', 'rules'), ('H', 'Rules recall', 'rules'), ('I', 'Rules F1', 'rules')):
    sub(f'{_c}27', _t, _b)
ws.row_dimensions[27].height = 40
_R, _O = ar('t_req'), ar('t_opt')
for _r, _lab in enumerate(LABELS, 28):
    put(f'B{_r}', _lab)
    has_r = f'ISNUMBER(SEARCH("{_lab}",{_R}))'
    has_o = f'ISNUMBER(SEARCH("{_lab}",{_O}))'
    put(f'C{_r}', f'=SUMPRODUCT(--{has_r})', fmt='#,##0', align=CENTER, want=PER_LABEL[_lab]['support'])
    for _arm, _col, cols3 in (('06', 'l_lab', 'DEF'), ('r', 'r_lab', 'GHI')):
        has_p = f'ISNUMBER(SEARCH("{_lab}",{ar(_col)}))'
        tp = f'SUMPRODUCT({has_p}*{has_r})'
        fp = f'SUMPRODUCT({has_p}*(1-{has_o})*(1-{has_r}))'
        fn = f'SUMPRODUCT({has_r}*(1-{has_p}))'
        want = PER_LABEL[_lab][_arm]
        put(f'{cols3[0]}{_r}', f'=IFERROR({tp}/({tp}+{fp}),"–")', fmt=PCT, align=CENTER,
            want=want[0] if want[0] is not None else '–')
        put(f'{cols3[1]}{_r}', f'=IFERROR({tp}/({tp}+{fn}),"–")', fmt=PCT, align=CENTER,
            want=want[1] if want[1] is not None else '–')
        put(f'{cols3[2]}{_r}', f'=IFERROR(2*{tp}/(2*{tp}+{fp}+{fn}),"–")', fmt=PCT, align=CENTER,
            want=want[2] if want[2] is not None else '–')
_r = 28 + len(LABELS)
for _rng, _col in ((f'F28:F{_r - 1}', '5B9BD5'), (f'I28:I{_r - 1}', 'F4B183')):
    ws.conditional_formatting.add(_rng, DataBarRule(start_type='num', start_value=0, end_type='num', end_value=1,
                                                    color=_col))

# old truth against new
_r += 1
put(f'B{_r}', 'The same answers against the old truth and the new', font(12, bold=True, color='1F1F1F'))
_r += 1
for _c, _t, _b in (('C', 'old: LLM', 'llm'), ('D', 'old: Rules', 'rules'), ('E', 'new: LLM', 'llm'),
                   ('F', 'new: Rules', 'rules')):
    sub(f'{_c}{_r}', _t, _b)
ws.row_dimensions[_r].height = 26
_old_rows = (('Bosserhof, exact class', OLD['ex06'], OLD['exr'], EXP_CLS['all']['ex06'], EXP_CLS['all']['exr']),
             ('Bosserhof, right main group', OLD['hd06'], OLD['hdr'], EXP_CLS['all']['hd06'], EXP_CLS['all']['hdr']),
             ("Activities, six categories by FINAL's map: F1", OLD['F06'], OLD['Fr'], OLD['Fnew06'], OLD['Fnewr']))
for _label, *_vals in _old_rows:
    _r += 1
    put(f'B{_r}', _label)
    for _c, _v in zip('CDEF', _vals):
        put(f'{_c}{_r}', float(_v), fmt=PCT, align=CENTER)
_r += 1
put(f'B{_r}', f"Values, not formulas: old = notebook 12's scoring on the previous validator's truth ({OLD['cls_n']:,} / "
              f"{OLD['act_n']:,} places); new = this workbook's truth, its labels mapped to the six categories by FINAL's "
              'map.', NOTE)
_r += 1
put(f'B{_r}', f"The two truths share an accepted class on {100 * OLD['cls_agree']:.0f} % of {OLD['cls_agree_n']:,} places "
              f"and the same six categories on {100 * OLD['act_agree']:.0f} % of {OLD['act_n']:,}; the new judgment finds "
              f"no activity at {OLD['cls_no_activity']} places the old truth gave a class.", NOTE)

# who is right
_r += 2
put(f'B{_r}', 'Who is right, place by place', font(12, bold=True, color='1F1F1F'))
for _title, _sheet_rng, _cats, _rows in (
        ('Building class (exact)', cr('who'), ('both right', 'only LLM right', 'only rules right', 'neither'), CLS_ROWS),
        ('Activities (closer: fewer wrong labels)', ar('who'),
         ('both right', 'only LLM right', 'only rules right', 'LLM closer', 'rules closer', 'equally off'), ACT_ROWS)):
    _r += 1
    put(f'B{_r}', _title, HEADF, bg=BLOCKS['cmp'][2])
    sub(f'C{_r}', 'places', 'cmp')
    sub(f'D{_r}', 'share', 'cmp')
    for _cat in _cats:
        _r += 1
        _want = sum(rr['_expect']['who'] == _cat for rr in _rows)
        _bg, _fg = next((bg, fg) for t, bg, fg in WHO if t == _cat)
        put(f'B{_r}', _cat, font(10, color=_fg), bg=_bg)
        put(f'C{_r}', f'=COUNTIF({_sheet_rng},"{_cat}")', fmt='#,##0', align=CENTER, want=_want)
        put(f'D{_r}', f'=C{_r}/{len(_rows)}', fmt=PCT, align=CENTER, want=_want / len(_rows))
    _r += 1

# how good the new truth is
_r += 1
put(f'B{_r}', 'How good the new truth is', font(12, bold=True, color='1F1F1F'))
_lines = []
if RELIABILITY:
    _lines.append(f"• {RELIABILITY['pairs']} places were judged blind twice, by different judges: the same best class on "
                  f"{100 * RELIABILITY['same_best']:.0f} %, each best class accepted by the other on "
                  f"{100 * RELIABILITY['best_accepted_by_other']:.0f} %,")
    _lines.append(f"   the same required labels on {100 * RELIABILITY['same_required']:.0f} %, labels compatible "
                  f"(each required label allowed by the other) on {100 * RELIABILITY['compatible_labels']:.0f} %.")
_conf_n = {c: sum(truth[b]['confidence'] == c for b in ORDER) for c in ('high', 'medium', 'low')}
_lines.append(f"• The judge's confidence: high {_conf_n['high']}, medium {_conf_n['medium']}, low {_conf_n['low']} "
              f"places; the web was used at {sum(bool(truth[b]['web']) for b in ORDER)} and showed "
              f"{sum(truth[b]['changed'] for b in ORDER)} places changed since the OpenStreetMap record.")
_lines.append(f"• Review: {REVIEW['sent']} places had an answer outside the blind judgment; the reviewers changed "
              f"{REVIEW['changed']}, accepting the LLM's class at {REVIEW['cls_now_right_06']} and the rules' at "
              f"{REVIEW['cls_now_right_r']},")
_lines.append(f"   the LLM's labels at {REVIEW['labels_now_right_06']} and the rules' at {REVIEW['labels_now_right_r']} "
              f"places (the answers were anonymous); best class corrected at {REVIEW['best_changed']}, required labels at "
              f"{REVIEW['required_changed']}.")
for _line in _lines:
    _r += 1
    put(f'B{_r}', _line)

# how to read
_r += 2
put(f'B{_r}', 'How to read', font(12, bold=True, color='1F1F1F'))
for _line in (
        "• The new truth is an AI judgment (Claude), not a person's: blind, with FINAL's own label and class definitions, "
        "the author's rulings, the record the LLM saw,",
        '   the other OpenStreetMap tags and web lookups. It sees no imagery: where the evidence is thin it accepts '
        "several readings (judge's confidence low).",
        '• Unlike the old truth it was not seeded by any answer: the LLM and the rules were shown to the reviewers only '
        'after the blind judgment, anonymously.',
        "• Optional labels and accepted alternative classes make it tolerant of readings a careful validator would also "
        'accept; the old truth had few of them.',
        '• Marks and scores are formulas: change a truth or an answer cell and they follow; filter a place sheet and its '
        'rows 3-4 follow.'):
    _r += 1
    put(f'B{_r}', _line)
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


def _rel(path):
    for name, base in (('FINAL', FINAL_DIR), ('RULES', ROOT)):
        try:
            return f'{name}/{Path(path).resolve().relative_to(Path(base).resolve()).as_posix()}'
        except ValueError:
            pass
    return Path(path).name


_notes = [
    ('Notes', 'title'),
    ('How the new truth was made', 'h'),
    ("1. Blind: each place was judged by an AI validator (Claude) that saw no answer of either pipeline and no old truth "
     '- only the record the LLM saw,', ''),
    ('   the other OpenStreetMap tags of its POIs, the address, and the web (for unclear or possibly changed places). '
     '30 judges of about 37 places each.', ''),
    ("   The judging guide (guide.md) gives FINAL's own label and class definitions verbatim, the author's rulings and "
     'consistency rulings for frequent cases.', ''),
    ("2. Review: where the LLM's or the rules' answer fell outside the blind judgment, a reviewer saw both answers "
     'anonymously and in random order,', ''),
    ('   and added an answer to the accepted classes or labels only where a careful validator would accept it '
     '(review_guide.md).', ''),
    (f"3. Reliability: {RELIABILITY['pairs'] if RELIABILITY else 60} places were judged a second time by another judge, "
     'without the judges knowing; see the Summary.', ''),
    ('What the truth holds', 'h'),
    ("Class: the class judged best and the classes also accepted. The headline is accepted wherever the record alone "
     'cannot separate its subcategories', ''),
    ('   (the LLM was told to answer the headline then). No activity (garages, sheds, barns, homes, vacant): no class; '
     'such places are left out of the Building class sheet.', ''),
    ("Labels: the eleven MiD labels besides work (work is added by rule in both pipelines). Required: a main purpose "
     'meets the label\'s core idea.', ''),
    ('   Optional: a careful validator would also accept it; it is neither credited nor counted wrong. "– (staff '
     'only)": nobody but staff comes.', ''),
    ("Main group: one of the 8 headlines of the Bosserhof catalogue; marks, main groups and scores are formulas over the "
     "text cells (classes as written in FINAL's catalogue, several separated by ' | ').", ''),
    ('Reading the sheets', 'h'),
    ("Judge: the judge's confidence - high (an occupant or name decides it), medium (the kind of building does), low "
     '(little more than land use and size).', ''),
    ("Old truth: the previous validator's check of the ORIGINAL pipeline (notebook 09), for comparison; it leans on that "
     "pipeline's answers.", ''),
    ("LLM: FINAL's step-05 answers as stored in 06 (model requested: gpt-oss-120b; which model answered is not "
     'confirmed). Rules: rule_utils.py, notebook 11, main run.', ''),
]
_r = 2
for _text, _kind in _notes:
    if _kind == 'title':
        ws.cell(_r, 2, _text).font = font(16, bold=True, color='1F1F1F')
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


_r = note_table(_r + 1, 'The Bosserhof catalogue', ('Main group', 'Classes'),
                [(h, '; '.join(SHOW[V.norm_class(s, NM)] for s in subs) or '(a class of its own)')
                 for h, subs in FC.LLM_BOSSERHOF_SUBCATEGORIES.items()])
_inputs = [(DIR / 'guide.md', 'the judging guide'), (DIR / 'review_guide.md', 'the review guide'),
           (DIR / 'places.csv', 'the places and batches'), (DIR / 'blind.json', 'the blind judgments'),
           (DIR / 'truth.json', 'the new truth'), (FINAL_CLASSIFIED_FILE, "the LLM's answers (FINAL 06)"),
           (FINAL_VALIDATION_FILE, 'the places and the old truth (FINAL 09)'),
           (RULES_ON_FINAL_FILE, "the rules' answers (notebook 11)")]
_r = note_table(_r, 'Inputs', ('What', 'sha256 (first 12)', 'File'),
                [(w, _sha(p), _rel(p)) for p, w in _inputs if Path(p).exists()])
for _row in ws.iter_rows(min_row=_r - len(_inputs) - 1, max_row=_r - 1, min_col=2, max_col=4):
    for _c in _row:
        _c.alignment = Alignment(vertical='top', wrap_text=False)
ws.cell(_r, 2, f"RULES at {_git(ROOT, 'rev-parse', '--short', 'HEAD')} on {_git(ROOT, 'branch', '--show-current')}; "
               f"built {datetime.date.today().isoformat()} by scripts/13_new_validation_workbook.py.").font = NOTE

ws = wb.create_sheet('Lists')            # the catalogue the main-group formulas look up
ws.sheet_state = 'hidden'
ws['A1'], ws['B1'] = 'Class', 'Main group'
for _i, _k in enumerate(SHOW, 2):
    ws.cell(_i, 1, SHOW[_k])
    ws.cell(_i, 2, SHOW[HEAD[_k]])

wb.properties.title = 'New validation: LLM and rules against a blind re-judgment'
wb.properties.creator = 'scripts/13_new_validation_workbook.py'
wb.active = 0
OUT.parent.mkdir(parents=True, exist_ok=True)
wb.save(TMP)
print(f'wrote {TMP.name}: {len(CLS_ROWS):,} class places, {len(ACT_ROWS):,} activity places')


# ── 6. let Excel calculate and save, then check what it stored ──────────────────────────────────────────────────────
def _alive(pid):
    out = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'], capture_output=True, text=True).stdout
    return str(pid) in out


def excel_recalculate(path):
    """a hidden Excel instance of our own calculates and saves the file; only that instance is ever stopped"""
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
        book.Worksheets('Notes').UsedRange.Rows.AutoFit()
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
        assert len(s.tables) == 1 and s.freeze_panes == f'C{FIRST}', f'{name}: table or frozen panes lost'
        n_notes = sum(c.comment is not None for row in s.iter_rows(min_row=FIRST) for c in row)
        n_links = sum(c.hyperlink is not None for row in s.iter_rows(min_row=FIRST) for c in row)
        assert n_notes == 2 * n_rows and n_links == n_rows, f'{name}: notes {n_notes}, links {n_links}'
    return len(EXPECT)


if excel_recalculate(TMP):
    _n = check_stored(TMP)              # on a failure TMP stays (*.unverified.xlsx) and OUT is left as it was
    os.replace(TMP, OUT)
    print(f'Excel recalculated it; {_n:,} stored values equal the Python scoring -> {OUT}')
else:
    os.replace(TMP, OUT)
    print(f'Excel is not available here: {OUT} calculates when it is opened (stored values not checked)')

e, a = EXP_CLS['all'], EXP_ACT['all']
print(f"new truth: {len(ORDER):,} places, {len(CLS_PLACES):,} with a class, reviewed {REVIEW['answered']} of "
      f"{REVIEW['sent']} sent")
print(f"Bosserhof exact: LLM {100 * e['ex06']:.1f} %, rules {100 * e['exr']:.1f} % (only LLM {e['b']}, only rules "
      f"{e['c']}, p {e['p']:.2g}); main group {100 * e['hd06']:.1f} vs {100 * e['hdr']:.1f} (p {e['ph']:.2g})")
print(f"labels F1: LLM {100 * a['F06']:.1f} (P {100 * a['P06']:.1f}, R {100 * a['R06']:.1f}), rules {100 * a['Fr']:.1f} "
      f"(P {100 * a['Pr']:.1f}, R {100 * a['Rr']:.1f}); bootstrap {BOOT[0]:+.1f} ({BOOT[1]:+.1f} .. {BOOT[2]:+.1f})")
print(f"old truth -> new: LLM exact {100 * OLD['ex06']:.1f} -> {100 * e['ex06']:.1f}, rules {100 * OLD['exr']:.1f} -> "
      f"{100 * e['exr']:.1f}; six-category F1 LLM {100 * OLD['F06']:.1f} -> {100 * OLD['Fnew06']:.1f}, rules "
      f"{100 * OLD['Fr']:.1f} -> {100 * OLD['Fnewr']:.1f}")
