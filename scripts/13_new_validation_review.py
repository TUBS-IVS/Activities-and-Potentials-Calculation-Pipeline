"""Step 13, part 2: collect the blind judgments, measure how far two blind judgments agree, and write the review files.

Usage:  python scripts/13_new_validation_review.py <workflow output .json> [...]
The workflow outputs hold {batch, places} per stage-1 agent; a batch judged twice keeps its later run.

Writes to data/output/13_new_validation/:
  blind.json          every blind judgment (the 60 repeats included), checked against the guide's lists
  reliability.json    agreement of the 60 places judged twice
  review_guide.md     what a reviewer does
  review/rNN.md       per batch, the places where the LLM's or the rules' answer falls outside the blind judgment: the
                      evidence, the blind judgment and the two answers, anonymous and in a fixed random order
Which answer is which is never written down: it follows from a hash of the building id (see answer_order).
FINAL is only read (immutable).
"""
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pandas as pd
import pyogrio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import *  # the RULES config


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.dont_write_bytecode = True          # loading FINAL's modules must leave no __pycache__ in FINAL
FC = _load('final_config', FINAL_CONFIG_FILE)
V = _load('final_validation', FINAL_VALIDATION_LIB)
NM = FC.BOSSERHOF_NORMALIZATION_MAP
DIR = NEW_VALIDATION_DIR

# the catalogue as the guide writes it, and the normalised key of each class
SHOW = {}
for _h, _subs in FC.LLM_BOSSERHOF_SUBCATEGORIES.items():
    SHOW[V.norm_class(_h, NM)] = _h
    for _s in _subs:
        SHOW[V.norm_class(_s, NM)] = _s
SHOW['others industrial'] = 'others (industrial)'
KEY = {v.lower(): k for k, v in SHOW.items()}
LABELS = [lab for lab in FC.LLM_ACTIVITY_LABELS if lab != 'work']


def key_of(text):
    """a class as written by a judge or a pipeline -> its normalised key (None for none / no class)"""
    if not isinstance(text, str) or not text.strip() or text.strip().lower() in ('none', '(no class)'):
        return None
    t = text.strip().lower()
    return KEY[t] if t in KEY else V.norm_class(text, NM)


def answer_order(building_id):
    """0: Answer 1 is the LLM, Answer 2 the rules; 1: the other way round"""
    return int(hashlib.sha1(building_id.encode()).hexdigest(), 16) % 2


def load_runs(paths):
    """{pid: judgment} from workflow outputs; later files win"""
    out = {}
    for p in paths:
        data = json.loads(Path(p).read_text(encoding='utf-8'))
        for item in data.get('result') or []:
            for j in (item or {}).get('places') or []:
                out[j['pid']] = j
    return out


def clean(j):
    """a judgment checked against the guide's lists, with the small slips repaired and noted"""
    notes = []
    best = key_of(j['class_best'])
    if j['no_activity'] != (best is None):
        notes.append('no_activity and class_best disagreed: no_activity follows class_best')
    acc = [k for k in dict.fromkeys(key_of(c) for c in j['class_accept']) if k and k != best]
    req = [lab for lab in dict.fromkeys(j['labels_required']) if lab in LABELS]
    opt = [lab for lab in dict.fromkeys(j['labels_optional']) if lab in LABELS and lab not in req]
    if len(opt) < len([lab for lab in j['labels_optional'] if lab in LABELS]):
        notes.append('a label was in both lists: kept as required')
    bad = sorted({k for k in [best, *acc] if k is not None} - set(SHOW))
    assert not bad, f'{j["pid"]}: classes outside the catalogue {bad}'
    return {'pid': j['pid'], 'no_activity': best is None, 'class_best': best, 'class_accept': acc,
            'labels_required': req, 'labels_optional': opt, 'changed': bool(j.get('changed')),
            'confidence': j['confidence'], 'web': j.get('web', ''), 'reason': j.get('reason', ''), 'notes': notes}


def outside(truth, cls, labels):
    """what of an answer falls outside a judgment: (class outside?, extra labels, missing labels)"""
    ok_cls = (not truth['no_activity']) and cls is not None and cls in [truth['class_best'], *truth['class_accept']]
    allowed = set(truth['labels_required']) | set(truth['labels_optional'])
    return (not ok_cls, sorted(set(labels) - allowed, key=LABELS.index),
            sorted(set(truth['labels_required']) - set(labels), key=LABELS.index))


def show_judgment(t):
    if t['no_activity']:
        cls = 'no activity (no class)'
    else:
        cls = SHOW[t['class_best']] + (f"; also accepted: {', '.join(SHOW[k] for k in t['class_accept'])}"
                                       if t['class_accept'] else '')
    return (f"- class: {cls}\n- labels required: {', '.join(t['labels_required']) or '(none)'}\n"
            f"- labels optional: {', '.join(t['labels_optional']) or '(none)'}\n"
            f"- confidence: {t['confidence']}; reason: {t['reason']}" + (f"\n- web: {t['web']}" if t['web'] else ''))


def show_answer(n, cls, labels, out):
    bad_cls, extra, missing = out
    parts = []
    if bad_cls:
        parts.append('class outside the judgment')
    if extra:
        parts.append(f"labels outside the judgment: {', '.join(extra)}")
    if missing:
        parts.append(f"required labels missing: {', '.join(missing)}")
    return (f"- Answer {n}: class {SHOW.get(cls, cls) if cls else '(no class)'}; labels "
            f"{', '.join(labels) or '(none)'}" + (f"  ->  {'; '.join(parts)}" if parts else '  ->  inside the judgment'))


REVIEW_GUIDE = """# Review guide

Stage 1 judged each place blind. Two classifiers have since answered the same places; you review the places where an
answer falls outside the blind judgment. For each place in your file you get the evidence (as in stage 1), the blind
judgment, and two anonymous answers (Answer 1, Answer 2), each a Bosserhof class and a set of labels ("work" left out),
with the parts that fall outside the judgment.

Read the judging guide first: guide.md, in this folder. Its definitions and rulings apply unchanged.

For each place decide:
1. Class. For each answer's class outside the judgment: would you, as a careful validator, have accepted it as right
   for this place had you thought of it? Then add it to class_accept and say why. If it is merely possible, or it
   contradicts the evidence or a ruling, leave it out.
2. Labels. For each answer label outside the judgment: does a real purpose of the place meet that label's core idea?
   Then add it to labels_optional, or to labels_required if the blind judgment clearly missed a main purpose;
   otherwise leave it out. For each required label an answer misses: keep it required unless it is in fact only a
   secondary purpose; then move it to labels_optional.
3. Correct the blind judgment itself only where it clearly misread or missed evidence (an occupant overlooked, a
   ruling misapplied). A no-activity judgment is reversed only on evidence that people work or visit there.
Judge each answer on its own: the two come from different sources and neither is the reference. Be as strict as in
stage 1; an answer is not right because it is "not absurd". The web is allowed as in stage 1, at most 2 searches for
one place. Do not open, search or list any file other than this guide, guide.md and your review file.

Return for every place in your file: pid; the final no_activity, class_best, class_accept, labels_required and
labels_optional (written exactly as in guide.md); and "changes": one short note per change with its reason, or ""
when nothing changed.
"""


if __name__ == '__main__':
    places = pd.read_csv(DIR / 'places.csv', dtype=str).fillna('')
    raw = load_runs(sys.argv[1:])
    missing = sorted(set(places['pid']) - set(raw))
    print(f'{len(raw):,} judgments read; {len(missing)} places still to judge'
          + (f" (batches {sorted(set(places.set_index('pid').loc[missing, 'batch'].astype(int)))})" if missing else ''))
    blind = {pid: clean(j) for pid, j in raw.items() if pid in set(places['pid'])}
    (DIR / 'blind.json').write_text(json.dumps(blind, ensure_ascii=False, indent=1), encoding='utf-8')
    slips = sum(bool(t['notes']) for t in blind.values())
    print(f'blind.json: {len(blind):,} judgments ({slips} with a repaired slip); '
          f"no activity {sum(t['no_activity'] for t in blind.values())}, changed on the web "
          f"{sum(t['changed'] for t in blind.values())}, web used {sum(bool(t['web']) for t in blind.values())}")

    # reliability: the places judged twice
    rel = []
    for r in places[places['duplicate_of'] != ''].itertuples():
        a, b = blind.get(r.duplicate_of), blind.get(r.pid)
        if not a or not b:
            continue
        acc_a, acc_b = {a['class_best'], *a['class_accept']}, {b['class_best'], *b['class_accept']}
        ra, rb = set(a['labels_required']), set(b['labels_required'])
        oka, okb = ra | set(a['labels_optional']), rb | set(b['labels_optional'])
        rel.append({'same_no_activity': a['no_activity'] == b['no_activity'],
                    'same_best': a['class_best'] == b['class_best'],
                    'best_accepted_by_other': a['class_best'] in acc_b and b['class_best'] in acc_a,
                    'same_required': ra == rb,
                    'compatible_labels': ra <= okb and rb <= oka,
                    'jaccard_required': len(ra & rb) / len(ra | rb) if ra | rb else 1.0})
    if rel:
        summary = {k: (sum(x[k] for x in rel) / len(rel)) for k in rel[0]}
        summary['pairs'] = len(rel)
        (DIR / 'reliability.json').write_text(json.dumps(summary, indent=1), encoding='utf-8')
        print('two blind judgments of the same place: ' + ', '.join(
            f'{k} {100 * v:.0f} %' if k != 'pairs' else f'{v} pairs' for k, v in summary.items()))

    # the answers, and the places where one falls outside the blind judgment
    b06 = pyogrio.read_dataframe(FINAL_CLASSIFIED_FILE, layer='buildings', read_geometry=False, IMMUTABLE='YES',
                                 columns=['building_id', 'bosserhof_class', 'llm_labels']).set_index('building_id')
    rules = pd.read_parquet(RULES_ON_FINAL_FILE).set_index('building_id')

    def labels_of(text):
        return sorted({lab for lab in str(text).split(';') if lab in LABELS}, key=LABELS.index) if isinstance(text, str) else []

    prim = places[places['duplicate_of'] == '']
    batches = {}
    for r in prim.itertuples():
        t = blind.get(r.pid)
        if t is None:
            continue
        llm = (key_of(b06.at[r.building_id, 'bosserhof_class']), labels_of(b06.at[r.building_id, 'llm_labels']))
        rul = (key_of(rules.at[r.building_id, 'cls_sites']), labels_of(rules.at[r.building_id, 'labels_sites']))
        o_llm, o_rul = outside(t, *llm), outside(t, *rul)
        if not any(o_llm) and not any(o_rul):          # both answers inside the judgment: nothing to review
            continue
        first, second = ((llm, o_llm), (rul, o_rul)) if answer_order(r.building_id) == 0 else ((rul, o_rul), (llm, o_llm))
        batches.setdefault(int(r.batch), []).append((r.pid, t, first, second))
    (DIR / 'review_guide.md').write_text(REVIEW_GUIDE, encoding='utf-8', newline='\n')
    (DIR / 'review').mkdir(exist_ok=True)
    for old in (DIR / 'review').glob('r*.md'):
        old.unlink()
    for k, items in sorted(batches.items()):
        text = (DIR / 'batches' / f'b{k:02d}.md').read_text(encoding='utf-8')
        blocks = {m.group(1): m.group(0).strip() for m in re.finditer(r'### (P\d{4})\n.*?(?=\n### P\d{4}\n|\Z)', text, re.S)}
        body = [f'# Review {k:02d}: {len(items)} places\n\nReview every place below by review_guide.md (in this '
                f"folder's parent).\n"]
        for pid, t, (a1, o1), (a2, o2) in items:
            body.append(f'{blocks[pid]}\n\nBlind judgment:\n{show_judgment(t)}\n\nAnswers:\n'
                        f'{show_answer(1, *a1, o1)}\n{show_answer(2, *a2, o2)}')
        (DIR / 'review' / f'r{k:02d}.md').write_text('\n\n'.join(body) + '\n', encoding='utf-8', newline='\n')
    n_rev = sum(len(v) for v in batches.values())
    print(f'review: {n_rev} of {len(prim)} places in {len(batches)} files (review/rNN.md)')
