"""
validation_utils.py — Ground-truth decoding and metrics for the validation benchmark.

Single source of truth for the maths, imported by notebooks 06-10. Kept as a module
rather than inlined in a notebook so the definitions cannot drift between the arms:
both classifiers are scored by literally the same functions.

WHAT IS BEING SCORED: a classifier's predictions against the HUMAN label recorded in
the annotation workbook. Note what that means for the LLM specifically — the workbook
arrived PRE-FILLED with an earlier LLM run's answers, and green means the human read
that answer and affirmed it. So on green rows the "truth" IS an LLM output, which
makes the LLM's own score there partly circular while leaving the rule engine's score
genuinely held out. Notebook 09 reports the green/red split instead of averaging over
it, and notebook 10 measures the model's self-consistency directly.

TWO DIMENSIONS, TWO METRICS — this is the whole design:

  activities      A multi-label SET per building, so "wrong" has direction:
                  over-prediction (claiming an activity that isn't there) and
                  under-prediction (missing one) are different failures with
                  opposite downstream effects. Over-prediction MISALLOCATES zone
                  capacity onto a building with no claim to it; under-prediction
                  REMOVES the building from that activity's redistribution
                  entirely. Reported as micro-averaged precision / recall, never
                  collapsed into a single accuracy number.

  bosserhof_class A SINGLE label per building, so plain accuracy is the right
                  metric — it either matches or it doesn't.

Micro-averaging is over label INSTANCES, not rows: a building that over-predicts
two activities contributes two false positives. That is what makes precision and
recall interpretable as "of the activity claims made, how many were real" and "of
the real activities, how many were found".
"""

import math
import re

import pandas as pd

from config import (
    MID_LABEL_TO_ACTIVITY, BOSSERHOF_WEIGHTS, BOSSERHOF_NORMALIZATION_MAP,
    BOSSERHOF_HEADLINE_CLASSES, VALIDATION_NO_ACTIVITY_TERMS,
    VALIDATION_ACTIVITY_TYPO_FIXES, ZONE_ACTIVITY_COLUMNS,
)


def collapse_to_zone_activities(mid_labels):
    """Map a classifier's MiD label set onto the 7 zone activity names.

    The classifier emits 12 MiD labels; the ground truth is recorded in the 7 zone
    activity names, because that is the granularity the zone data supplies and the
    granularity the validator worked at. The collapse is many-to-one
    (work+business -> Workers, leisure+sports+meetup+lessons -> Leisure, ...), so
    it must be applied before any comparison or the two sides are not measuring
    the same thing.
    """
    # list() before any truth test. Parquet round-trips a list column as
    # numpy.ndarray, and `if not mid_labels` raises
    #   ValueError: truth value of an array with more than one element is ambiguous
    # for length >= 2 — but passes for length 0 and 1, so a sparse test misses it.
    # rule_utils returns real Python lists, so this would have failed ONLY for the
    # LLM arm, only after a multi-hour run, and read as an LLM defect.
    if mid_labels is None:
        return set()
    mid_labels = list(mid_labels)
    if not mid_labels:
        return set()
    return {MID_LABEL_TO_ACTIVITY[label]
            for label in mid_labels if label in MID_LABEL_TO_ACTIVITY}


# ──────────────────────────────────────────────────────────────────────────────
# BOSSERHOF NORMALISATION
# ──────────────────────────────────────────────────────────────────────────────
# Lifted verbatim out of notebook 09 so the TRUTH side and the PREDICTION side
# run the same code. They previously did not: the truth went through this full
# stack, while score_bosserhof's prediction side was only
#     '' if v is None else str(v).strip().lower()
# Run the 46 Bosserhof strings the system prompt authorises through both: the
# weak path resolves 30/46, this one resolves 46/46. Casualties of the weak path
# included 'restaurants / gastronomy', 'retail (small-scale)', 'open-plan
# office', 'hypermarkets / superstores' and 'fitness / wellness' — the model is
# explicitly told to emit those spellings, and every one of them scored wrong for
# punctuation reasons alone.
#
# Applying it to both arms cannot advantage either: clean_bosserhof is a provable
# identity on all 47 BOSSERHOF_WEIGHTS keys, so it cannot change a rule-engine
# prediction, which only ever emits those keys.

BOSSERHOF_KNOWN = {k.lower() for k in BOSSERHOF_WEIGHTS}

BOSSERHOF_TYPO_FIXES = {
    'restaurant gastronomy':      'restaurants gastronomy',
    'customer oriented service':  'customer oriented services',
    'business oriented service':  'business oriented services',
    'business oriented business': 'business oriented services',
    'school':                     'schools',
    'kindergarten':               'kindergartens',
    'hospital':                   'hospitals',
    'hotel':                      'hotels',
    'university':                 'universities',
    'research institute':         'research institutes',
    'nursing':                    'nursing homes',
    'nursing home':               'nursing homes',
    'craft business':             'craft businesses',
    'diy store':                  'diy stores',
    'shopping center':            'shopping centers',
    'small scale retail':         'retail small scale',
}
BOSSERHOF_NO_CLASS_TERMS = {'none', 'no', 'vacancy', 'vacant', 'just garages', 'garages'}
BOSSERHOF_SUBSTRING_FIXES = {
    r'\brestaurant gastronomy\b':     'restaurants gastronomy',
    r'\bleisture\b':                  'leisure',
    r'\bcustomer oriented service\b': 'customer oriented services',
    r'\bbusiness oriented service\b': 'business oriented services',
}


def clean_bosserhof(raw):
    """Normalise a Bosserhof string. '' means an explicit no-class; None unusable."""
    if raw is None:
        return None
    text = re.sub(r'[^a-z0-9 ]+', ' ', str(raw).lower())
    text = re.sub(r'\s+', ' ', text).strip()
    if text in ('', 'nan'):
        return None
    if (text in VALIDATION_NO_ACTIVITY_TERMS or text in BOSSERHOF_NO_CLASS_TERMS
            or 'residential' in text):
        return ''
    for pattern, replacement in BOSSERHOF_SUBSTRING_FIXES.items():
        text = re.sub(pattern, replacement, text)
    text = BOSSERHOF_TYPO_FIXES.get(text, text)
    return BOSSERHOF_NORMALIZATION_MAP.get(text, text)


def classes_mentioned(text):
    """Known classes appearing as substrings, longest first so a class containing
    another (retail small scale vs retail) is not double-counted."""
    if not text:
        return []
    found, remaining = [], text
    for known in sorted(BOSSERHOF_KNOWN, key=len, reverse=True):
        if known in remaining:
            found.append(known)
            remaining = remaining.replace(known, ' ')
    return found


def resolve_prediction_bosserhof(raw):
    """Prediction-side counterpart of notebook 09's resolve_bosserhof.

    Deliberately mirrors the SAME stage list the truth side ran — clean, then
    single-class extraction from free text — because clean_bosserhof is a
    semantic normaliser, not merely a formatter, and comparing a semantically
    normalised truth against a raw prediction is not a like-for-like match.

    Where it stops short of the truth side: a prediction naming two or more
    UNRELATED known classes is returned unchanged, so it scores wrong. The truth
    side sets such rows aside as unscoreable, which is right for a human
    annotation ("the validator named several classes, there is no single truth")
    and wrong for a model output ("the model failed to pick one"). Notebook 10
    counts these in the out-of-vocabulary diagnostic so the failure stays visible
    instead of disappearing into the accuracy number.

    HIERARCHICAL ANSWERS ARE NOT AMBIGUITY. Every one of the 8 headline
    categories is itself a scoreable class, so a model answering
    "Public facilities | schools" has named two known classes — but it has not
    failed to choose, it has given a category and its own subcategory. Observed
    on the very first smoke-test call. Scoring that as wrong would measure format
    compliance, not classification, so the more specific class is taken.

    That charity is bounded and cannot be extended to a genuine refusal to pick:
    "normal office or hotels" names two NON-headline classes and still scores
    wrong. And it cannot flatter the LLM relative to the rule engine on any row
    the rule engine could have won, because rule_utils only ever emits a single
    canonical class and so never reaches this branch at all.

    Returns a canonical class, '' for an explicit no-class, or None when there is
    nothing usable — None and '' both score as "no class predicted".
    """
    value = clean_bosserhof(raw)
    if value is None or value == '' or value in BOSSERHOF_KNOWN:
        return value
    mentioned = classes_mentioned(value)
    if len(mentioned) == 1:
        return mentioned[0]
    if len(mentioned) >= 2:
        specific = [m for m in mentioned if m not in BOSSERHOF_HEADLINE_CLASSES]
        if len(specific) == 1:
            return specific[0]
    return value


def as_label_set(value):
    """Coerce a label cell to a set, whatever container it arrived in.

    `set(value or [])` is NOT safe here and the failure is loud but misleading:
    parquet round-trips a list column as numpy.ndarray, and `value or []` raises
    "truth value of an array with more than one element is ambiguous" — for
    length >= 2 only, so a length-0/1 test misses it. In-memory sets work fine,
    so the bug appears only after predictions have been written and re-read,
    i.e. in the scoring notebook rather than the notebook that produced them.
    """
    if value is None:
        return set()
    if isinstance(value, float) and math.isnan(value):
        return set()
    return set(value)


def confusion_counts(predicted, truth):
    """Per-building confusion counts for two activity sets.

    Returns (n_true_positive, n_over_predicted, n_missed).
    """
    predicted, truth = as_label_set(predicted), as_label_set(truth)
    return (len(predicted & truth),
            len(predicted - truth),
            len(truth - predicted))


def error_direction(n_over_predicted, n_missed):
    """Label the shape of a per-building error."""
    if n_over_predicted and n_missed:
        return "both"
    if n_over_predicted:
        return "over_prediction"
    if n_missed:
        return "under_prediction"
    return "exact"


def score_activities(pairs):
    """Micro-averaged multi-label metrics.

    `pairs` is an iterable of (key, predicted_set, truth_set).
    Returns (metrics_dict, per_row_list).
    """
    rows = []
    tp = fp = fn = 0
    for key, predicted, truth in pairs:
        row_tp, row_fp, row_fn = confusion_counts(predicted, truth)
        tp, fp, fn = tp + row_tp, fp + row_fp, fn + row_fn
        rows.append({
            "key": key,
            "predicted": sorted(as_label_set(predicted)),
            "truth": sorted(as_label_set(truth)),
            "n_true_positive": row_tp,
            "n_over_predicted": row_fp,
            "n_missed": row_fn,
            "has_over_prediction": int(row_fp > 0),
            "has_missed_prediction": int(row_fn > 0),
            "exact_match": int(row_fp == 0 and row_fn == 0),
            "error_direction": error_direction(row_fp, row_fn),
        })

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    n = len(rows)
    metrics = {
        "n_rows": n,
        "n_true_positive": tp,
        "n_over_predicted": fp,
        "n_missed": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "exact_match_rate": (sum(r["exact_match"] for r in rows) / n) if n else 0.0,
        "rows_with_over_prediction": sum(r["has_over_prediction"] for r in rows),
        "rows_with_missed_prediction": sum(r["has_missed_prediction"] for r in rows),
    }
    for direction in ("exact", "over_prediction", "under_prediction", "both"):
        metrics[f"rows_{direction}"] = sum(
            1 for r in rows if r["error_direction"] == direction)
    return metrics, rows


def score_bosserhof(pairs):
    """Single-label accuracy.

    `pairs` is an iterable of (key, predicted, truth). Both sides are compared
    after casefolding; `""` is a meaningful value meaning "no class", and matches
    a prediction of None or "".
    Returns (metrics_dict, per_row_list).
    """
    def norm(value):
        return "" if value is None else str(value).strip().lower()

    rows, correct = [], 0
    for key, predicted, truth in pairs:
        p, t = norm(predicted), norm(truth)
        is_match = (p == t)
        correct += is_match
        rows.append({
            "key": key,
            "predicted": p or "(no class)",
            "truth": t or "(no class)",
            "match": int(is_match),
        })
    n = len(rows)
    return {"n_rows": n, "n_correct": correct,
            "accuracy": (correct / n) if n else 0.0}, rows


def per_activity_breakdown(pairs):
    """Per-activity over-prediction vs miss counts.

    Answers "which activities does this classifier invent, and which does it
    overlook" — a single precision figure cannot show that, and the two have
    different consequences for a transport model.
    """
    from collections import Counter
    over, miss, present = Counter(), Counter(), Counter()
    for _key, predicted, truth in pairs:
        predicted, truth = as_label_set(predicted), as_label_set(truth)
        over.update(predicted - truth)
        miss.update(truth - predicted)
        present.update(truth)
    activities = sorted(set(over) | set(miss) | set(present))
    return [{
        "activity": a,
        "in_truth": present.get(a, 0),
        "over_predicted": over.get(a, 0),
        "missed": miss.get(a, 0),
        "net_over": over.get(a, 0) - miss.get(a, 0),
    } for a in activities]


def format_activity_report(metrics, title="ACTIVITIES"):
    """Label-instance accounting, written out so every figure is traceable.

    Counts individual activity labels, not buildings: a building with three
    activities contributes three labels. Every label is one of Workers,
    Retail_Daily, Retail_Non-Daily, Leisure, School, University, Kindergarten.
    """
    m = metrics
    correct = m["n_true_positive"]
    extra = m["n_over_predicted"]
    missing = m["n_missed"]
    predicted = correct + extra
    truth = correct + missing

    lines = [
        f"{title}",
        "  Counting individual activity LABELS, not buildings.",
        "",
        f"  buildings scored                     : {m['n_rows']:,}",
        f"  labels the human recorded  (truth)   : {truth:,}",
        f"  labels the engine predicted          : {predicted:,}",
        "",
        f"    correct   (predicted AND true)     : {correct:,}",
        f"    extra     (predicted, NOT true)    : {extra:,}",
        f"    missing   (true, NOT predicted)    : {missing:,}",
        "",
        f"  precision = {correct:,} / {predicted:,} = {m['precision']:.1%}"
        "     of the labels predicted, this share was right",
        f"  recall    = {correct:,} / {truth:,} = {m['recall']:.1%}"
        "     of the labels that exist, this share was found",
        "",
        f"  arithmetic check: {correct:,} + {extra:,} = {predicted:,} predicted"
        f"   |  {correct:,} + {missing:,} = {truth:,} truth",
        "",
        f"  buildings matching the human exactly : {m['rows_exact']:,}"
        f" of {m['n_rows']:,} ({m['exact_match_rate']:.1%})",
        f"    extra labels only                  : {m['rows_over_prediction']:,}"
        "   (misallocates capacity)",
        f"    missing labels only                : {m['rows_under_prediction']:,}"
        "   (removes capacity)",
        f"    both                               : {m['rows_both']:,}",
    ]
    return "\n".join(lines)


def label_accounting(pairs):
    """The four headline counts for a set of (key, predicted, truth) triples.

    Returned as a plain dict so it can be tabulated across subsets (e.g. the rows
    the validator marked green vs red) without re-deriving the arithmetic.
    """
    metrics, _rows = score_activities(pairs)
    correct = metrics["n_true_positive"]
    n_predicted = correct + metrics["n_over_predicted"]
    n_truth = correct + metrics["n_missed"]
    p_lo, p_hi = wilson_interval(correct, n_predicted)
    r_lo, r_hi = wilson_interval(correct, n_truth)
    return {
        "buildings": metrics["n_rows"],
        "truth_labels": n_truth,
        "predicted_labels": n_predicted,
        "correct": correct,
        "extra": metrics["n_over_predicted"],
        "missing": metrics["n_missed"],
        "precision": metrics["precision"],
        "precision_lo": p_lo,
        "precision_hi": p_hi,
        "recall": metrics["recall"],
        "recall_lo": r_lo,
        "recall_hi": r_hi,
        "exact_set_match": metrics["exact_match_rate"],
    }


def bosserhof_accounting(pairs):
    """Headline counts for Bosserhof, the single-label dimension.

    label_accounting CANNOT be reused here, and the failure is silent. It
    delegates to score_activities, whose confusion_counts does
    `set(predicted or [])` — on the string 'normal office' that yields a set of
    12 characters, and the function returns a plausible-looking number that means
    nothing at all.
    """
    metrics, _rows = score_bosserhof(pairs)
    lo, hi = wilson_interval(metrics["n_correct"], metrics["n_rows"])
    return {
        "buildings": metrics["n_rows"],
        "correct": metrics["n_correct"],
        "accuracy": metrics["accuracy"],
        "accuracy_lo": lo,
        "accuracy_hi": hi,
    }


def wilson_interval(successes, total, z=1.96):
    """Wilson score 95% interval for a binomial rate. (lo, hi), or (nan, nan).

    Needed because the primary subsets are small and four-decimal point estimates
    invite conclusions they cannot support. At the sizes this benchmark actually
    has: Bosserhof red n=155 at 0.129 is +/- ~5.3 pp, activity red recall n=329
    at 0.670 is +/- ~5.1 pp, and even the full Bosserhof set n=874 at 0.503 is
    +/- ~3.3 pp. An arm difference smaller than that is not a difference.

    Wilson rather than normal-approximation: it stays inside [0, 1] and behaves
    at proportions near 0 or 1, where several per-class rates here sit.
    """
    if not total:
        return (float("nan"), float("nan"))
    p = successes / total
    denom = 1 + z ** 2 / total
    centre = (p + z ** 2 / (2 * total)) / denom
    margin = z * math.sqrt(p * (1 - p) / total + z ** 2 / (4 * total ** 2)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


_ACTIVITY_BY_LOWER = {z.lower(): z for z in ZONE_ACTIVITY_COLUMNS}


def parse_activity_cell(raw):
    """Decode one activity cell. Returns (labels, leftover_tokens).

    `labels` is None when the cell carries no decision at all — a blank correction
    on a red row means "flagged wrong but never corrected", which is not a ground
    truth and must not be scored. An EMPTY SET is different and is a real answer:
    the validator wrote "living" / "residential", meaning no activity happens here.
    config.VALIDATION_NO_ACTIVITY_TERMS draws that line.

    Matching is done by scanning the text for known activity names rather than by
    parsing it as a Python literal. These cells were typed by hand into a
    spreadsheet, and 44 of the 339 corrections are missing a quote or a bracket:

        ['Workers', Retail_Non-Daily']        <- opening quote absent
        ('Workers', 'Retail_Daily']           <- paren instead of bracket
        ['Workers, 'Retail_Non-Daily']        <- quote inside the name

    ast.literal_eval raises on every one. The previous implementation caught that
    and fell back to treating the whole unparsed string as ONE token, which matched
    no activity name and yielded an empty set — silently asserting "this building
    hosts no activities", the exact opposite of what the validator wrote. Both
    classifiers were then charged a false positive for every label they had
    correctly predicted on those 44 rows.

    `leftover` is every word the scan could not account for. The caller raises on
    it: a correction naming an activity this function does not recognise must fail
    loudly, because the silent alternative is a ground truth that quietly omits a
    label and penalises whoever got it right.
    """
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return None, []
    text = str(raw).strip()
    if not re.search(r"[A-Za-z]", text):
        return None, []            # blank, "[]", "[' ']" — no decision recorded

    low = text.lower()
    for wrong, right in VALIDATION_ACTIVITY_TYPO_FIXES.items():
        low = low.replace(wrong.lower(), right.lower())

    # Longest first so "retail_non-daily" is consumed before any shorter name can
    # claim part of it.
    labels, residue = set(), low
    for name in sorted(_ACTIVITY_BY_LOWER, key=len, reverse=True):
        if name in residue:
            labels.add(_ACTIVITY_BY_LOWER[name])
            residue = residue.replace(name, " ")
    for term in VALIDATION_NO_ACTIVITY_TERMS:
        residue = residue.replace(term.lower(), " ")

    leftover = [w for w in re.findall(r"[a-z][a-z_\-]{2,}", residue)]
    return labels, leftover


def decode_final_validation_set(df):
    """Decode ground truth from the validation set built by notebook 06.

    That file is a colour-coded validator's verdict flattened to plain columns:
    for each dimension (activities, Bosserhof) a `..._mistakes_color` of 'green'
    means the validator accepted the pre-filled `Predicted_...` value as-is;
    'red' means they typed a replacement into `..._mistakes`, which is the FULL
    corrected value, not a diff. Any other colour (missing, 'yellow') means the
    row was never decided on that dimension and must not be scored on it.

    Returns df with two new columns added: `activities_truth` (a set of zone
    activity names) and `bosserhof_truth` (a canonical class string, '' for an
    explicit no-class, or None if unscoreable).
    """
    out = df.copy()

    act_color = out["Predicted_activities_mistakes_color"]
    act_source = out["Predicted_activities"].where(act_color == "green",
                                                    out["Predicted_activities_mistakes"])
    parsed = act_source.map(parse_activity_cell)
    out["activities_truth"] = [labels for labels, _ in parsed]
    out.loc[~act_color.isin(("green", "red")), "activities_truth"] = None

    # Fail loudly on anything the scan could not account for. Without this the
    # ground truth silently loses a label and penalises the classifier that got it
    # right — which is precisely how the missing-quote corruption above went
    # unnoticed. Add the spelling to config.VALIDATION_ACTIVITY_TYPO_FIXES only
    # after this has fired and named it; guessing entries in advance would let a
    # future typo be absorbed before the check could report it.
    unknown = {}
    for gid, (_, leftover) in zip(out.get("gml_id", out.index), parsed):
        if leftover:
            unknown[gid] = leftover
    if unknown:
        raise ValueError(
            f"{len(unknown)} activity cells contain tokens that match no known "
            f"activity name: {dict(list(unknown.items())[:10])}. Valid names are "
            f"{sorted(ZONE_ACTIVITY_COLUMNS)}.")

    boss_color = out["Bosserhof_class_mistakes_color"]
    boss_truth = out["Bosserhof_class_predicted"].where(boss_color == "green",
                                                         out["Bosserhof_class_mistakes"])
    out["bosserhof_truth"] = boss_truth.map(clean_bosserhof)
    out.loc[~boss_color.isin(("green", "red")), "bosserhof_truth"] = None

    return out


def format_label_set(value):
    """Render a set/list of labels as a stable, readable cell."""
    if value is None:
        return ""
    return "; ".join(sorted(str(v) for v in value))


# Column order of the side-by-side review sheet. Grouped so a human scanning the
# CSV reads each dimension as one block: what the earlier model said, what the
# validator did to it, what the truth therefore is, what this arm predicted, and
# whether that matched. `sentence` goes last because it is hundreds of characters
# and would push every comparison column off screen.
COMPARISON_COLUMNS = [
    "gml_id", "source_gml_id", "osm_names", "volume_m3",
    # --- activities ---
    "act_prefilled", "act_human_verdict", "act_truth", "act_predicted",
    "act_match", "act_extra", "act_missing",
    # --- bosserhof ---
    "boss_prefilled", "boss_human_verdict", "boss_truth", "boss_predicted",
    "boss_match",
    # --- evidence, last ---
    "sentence",
]


def build_comparison(val, predictions, key="gml_id"):
    """One row per building, every version of the answer side by side.

    `val` is the decoded validation set (see decode_final_validation_set),
    `predictions` a frame carrying `pred_zone_activities` and `pred_bosserhof`.

    The point is manual review: for each dimension the sheet shows the value the
    EARLIER model produced (`*_prefilled`), the validator's verdict on it
    (green = accepted, red = corrected), the resulting truth, and this arm's
    prediction — so a disagreement can be judged from the evidence in the same
    row rather than by joining three files by hand.

    Keeping the pre-filled column matters even though it is not scored: on green
    rows it EQUALS the truth by construction, which is exactly the fact that makes
    a green-row "accuracy" figure self-referential. Showing it inline stops that
    being forgotten.

    Rows unscoreable on a dimension carry an empty truth and `match` = "" rather
    than being dropped, so the sheet always has all the annotated buildings.
    """
    df = val.merge(predictions[[key, "pred_zone_activities", "pred_bosserhof"]],
                   on=key, how="left", validate="one_to_one")

    out = pd.DataFrame({
        "gml_id":        df[key],
        "source_gml_id": df.get("source_gml_id"),
        "osm_names":     df.get("osm_names"),
        "volume_m3":     df.get("volume_m3"),

        "act_prefilled":     df["Predicted_activities"],
        "act_human_verdict": df["Predicted_activities_mistakes_color"],
        "act_truth":         df["activities_truth"].map(format_label_set),
        "act_predicted":     df["pred_zone_activities"].map(format_label_set),

        "boss_prefilled":     df["Bosserhof_class_predicted"],
        "boss_human_verdict": df["Bosserhof_class_mistakes_color"],
        "boss_truth":         df["bosserhof_truth"],
        "boss_predicted":     df["pred_bosserhof"],

        "sentence": df.get("sentence"),
    })

    # Per-row confusion, computed only where a truth exists.
    act_match, act_extra, act_missing = [], [], []
    for truth, pred in zip(df["activities_truth"], df["pred_zone_activities"]):
        if truth is None:
            act_match.append(""); act_extra.append(""); act_missing.append("")
            continue
        tp, fp, fn = confusion_counts(pred, truth)
        act_match.append(int(fp == 0 and fn == 0))
        act_extra.append(format_label_set(set(pred or []) - set(truth)))
        act_missing.append(format_label_set(set(truth) - set(pred or [])))
    out["act_match"], out["act_extra"], out["act_missing"] = act_match, act_extra, act_missing

    def boss_norm(v):
        return "" if v is None else str(v).strip().lower()

    out["boss_match"] = [
        "" if t is None else int(boss_norm(p) == boss_norm(t))
        for t, p in zip(df["bosserhof_truth"], df["pred_bosserhof"])
    ]

    # "Predicted nothing" is an ANSWER, not a blank. Both None (the model returned
    # null, or refused) and "" (an explicit no-class) score identically — see
    # score_bosserhof's norm() — so both are written as one visible marker. Left as
    # an empty cell they would round-trip through CSV as NaN and read as "this row
    # was not evaluated", which is a different and much more forgiving claim.
    for col in ("boss_truth", "boss_predicted"):
        out[col] = out[col].map(lambda v: "(no class)" if v is None or v == "" else v)
    out["act_predicted"] = out["act_predicted"].map(lambda v: v if v else "(none)")
    # act_truth stays blank when the row is genuinely unscoreable on activities.
    out["act_truth"] = [
        "(none)" if (t is not None and not s) else s
        for t, s in zip(df["activities_truth"], out["act_truth"])
    ]

    return out[[c for c in COMPARISON_COLUMNS if c in out.columns]]


def format_bosserhof_report(metrics, title="BOSSERHOF CLASS"):
    m = metrics
    return "\n".join([
        f"{title} — single label, plain accuracy",
        f"  rows scored            : {m['n_rows']:,}",
        f"  correct                : {m['n_correct']:,}",
        f"  accuracy               : {m['accuracy']:.1%}",
    ])
