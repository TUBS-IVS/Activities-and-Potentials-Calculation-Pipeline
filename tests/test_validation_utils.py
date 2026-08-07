"""
test_validation_utils.py — pins the benchmark metric maths.

Nothing pinned it before, despite the module docstring claiming the metrics are
"unit-testable and cannot drift" — `git grep -l validation_utils` returned only
the README, notebook 10 and the module itself. These are the numbers the whole
head-to-head rests on, so they get asserted rather than assumed.

The cases below are not generic sanity checks; each one is a way the LLM arm can
diverge from the rule arm for reasons that have nothing to do with classification
quality.
"""

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from validation_utils import (
    collapse_to_zone_activities, confusion_counts, score_activities,
    score_bosserhof, label_accounting, bosserhof_accounting, wilson_interval,
)


# ── collapse_to_zone_activities: the ndarray landmine ─────────────────────────

def test_collapse_accepts_python_list():
    assert collapse_to_zone_activities(["work", "business"]) == {"Workers"}


@pytest.mark.parametrize("n", [0, 1, 2, 3])
def test_collapse_accepts_numpy_array(n):
    """Parquet round-trips a list column as ndarray.

    `if not arr` raises ValueError for len >= 2 but PASSES for len 0 and 1, so a
    fixture with only short label sets misses it entirely. The rule engine
    returns Python lists and is immune — this would have failed only for the LLM
    arm, only after the API spend, and looked like an LLM defect.
    """
    labels = np.array(["work", "leisure", "school"][:n], dtype=object)
    out = collapse_to_zone_activities(labels)
    assert isinstance(out, set)
    assert len(out) == len(set(labels))


def test_collapse_handles_none_and_empty():
    assert collapse_to_zone_activities(None) == set()
    assert collapse_to_zone_activities([]) == set()
    assert collapse_to_zone_activities(np.array([], dtype=object)) == set()


def test_collapse_drops_unknown_labels_silently():
    assert collapse_to_zone_activities(["work", "NOT_A_LABEL"]) == {"Workers"}


def test_collapse_is_many_to_one():
    """Distinct MiD labels that share a zone activity must not double-count."""
    assert collapse_to_zone_activities(["work", "business"]) == {"Workers"}
    assert len(collapse_to_zone_activities(["leisure", "sports", "meetup"])) == 1


# ── score_bosserhof: None vs '' vs NaN ────────────────────────────────────────

def test_none_prediction_matches_empty_truth():
    """'' truth means 'the human said: no class'. A null prediction agrees."""
    metrics, _ = score_bosserhof([("a", None, "")])
    assert metrics["n_correct"] == 1


def test_nan_prediction_does_not_match_empty_truth():
    """THE trap, pinned deliberately.

    norm() maps None -> '' but float NaN -> the string 'nan', which matches
    nothing. rule_utils returns literal None; parquet hands back NaN. Notebook 10
    must coerce NaN -> None before scoring, and this test is what says so.
    """
    metrics, _ = score_bosserhof([("a", float("nan"), "")])
    assert metrics["n_correct"] == 0


def test_bosserhof_is_case_and_whitespace_insensitive():
    metrics, _ = score_bosserhof([("a", "  Normal Office ", "normal office")])
    assert metrics["n_correct"] == 1


# ── score_activities ──────────────────────────────────────────────────────────

def test_confusion_counts_directions():
    assert confusion_counts({"A", "B"}, {"B", "C"}) == (1, 1, 1)
    assert confusion_counts(set(), {"A"}) == (0, 0, 1)
    assert confusion_counts({"A"}, set()) == (0, 1, 0)


def test_micro_averaging_is_over_labels_not_rows():
    """A building over-predicting two labels contributes two false positives."""
    metrics, _ = score_activities([
        ("a", {"Workers", "Leisure", "School"}, {"Workers"}),
    ])
    assert metrics["n_true_positive"] == 1
    assert metrics["n_over_predicted"] == 2
    assert metrics["precision"] == pytest.approx(1 / 3)
    assert metrics["recall"] == pytest.approx(1.0)


def test_empty_prediction_against_empty_truth_is_an_exact_match():
    """Residential buildings: both sides say 'no activity'. Must not divide by zero."""
    metrics, rows = score_activities([("a", set(), set())])
    assert rows[0]["exact_match"] == 1
    assert metrics["exact_match_rate"] == 1.0
    assert metrics["precision"] == 0.0   # no labels predicted -> undefined, reported as 0


# ── accounting helpers ────────────────────────────────────────────────────────

def test_label_accounting_arithmetic_closes():
    acc = label_accounting([
        ("a", {"Workers", "Leisure"}, {"Workers"}),
        ("b", {"Workers"}, {"Workers", "School"}),
    ])
    assert acc["correct"] + acc["extra"] == acc["predicted_labels"]
    assert acc["correct"] + acc["missing"] == acc["truth_labels"]
    assert acc["buildings"] == 2
    assert acc["precision_lo"] <= acc["precision"] <= acc["precision_hi"]
    assert acc["recall_lo"] <= acc["recall"] <= acc["recall_hi"]


def test_bosserhof_accounting_is_not_label_accounting():
    """label_accounting on single-label data is silently wrong, not loud.

    Its confusion_counts does set(predicted), turning 'normal office' into a set
    of characters. bosserhof_accounting exists precisely so nobody reaches for
    the wrong one.
    """
    pairs = [("a", "normal office", "normal office")]
    assert bosserhof_accounting(pairs)["correct"] == 1
    # the wrong helper compares character sets and still returns a number
    assert label_accounting(pairs)["correct"] == len(set("normal office"))


# ── Wilson interval ───────────────────────────────────────────────────────────

def test_wilson_brackets_the_point_estimate():
    lo, hi = wilson_interval(50, 100)
    assert lo < 0.5 < hi


def test_wilson_stays_in_unit_interval_at_the_extremes():
    for k, n in [(0, 30), (30, 30), (1, 1000)]:
        lo, hi = wilson_interval(k, n)
        assert 0.0 <= lo <= hi <= 1.0


def test_wilson_narrows_with_n():
    narrow = wilson_interval(500, 1000)
    wide = wilson_interval(5, 10)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_wilson_on_empty_is_nan_not_a_crash():
    lo, hi = wilson_interval(0, 0)
    assert math.isnan(lo) and math.isnan(hi)


def test_wilson_matches_known_benchmark_widths():
    """Sanity-check against the subset sizes this benchmark actually reports."""
    lo, hi = wilson_interval(round(0.129 * 155), 155)     # Bosserhof red
    assert (hi - lo) / 2 == pytest.approx(0.053, abs=0.01)
    lo, hi = wilson_interval(round(0.5034 * 874), 874)    # Bosserhof all
    assert (hi - lo) / 2 == pytest.approx(0.033, abs=0.01)
