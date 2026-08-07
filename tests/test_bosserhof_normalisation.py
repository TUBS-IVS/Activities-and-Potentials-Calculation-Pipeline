"""
test_bosserhof_normalisation.py — pins the Bosserhof string normaliser.

Why this file exists: the truth side of the benchmark ran notebook 09's
clean_bosserhof, while the prediction side of score_bosserhof ran only
`str(v).strip().lower()`. Nothing detected the mismatch, because the rule engine
happens to emit exactly the canonical keys and so scored identically under both.
The gap was invisible until a classifier emitted the spellings the system prompt
actually authorises — at which point it would have looked like a bad model
rather than a bad comparison.

The two properties that make sharing one normaliser FAIR are asserted here:
  1. It is an identity on every BOSSERHOF_WEIGHTS key, so it cannot alter a
     rule-engine prediction.
  2. It resolves every Bosserhof spelling the system prompt authorises, so it
     does not silently penalise the LLM for punctuation.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import BOSSERHOF_WEIGHTS
from llm_utils import SYSTEM_PROMPT
from validation_utils import (
    BOSSERHOF_KNOWN, clean_bosserhof, classes_mentioned,
    resolve_prediction_bosserhof,
)


# ── The fairness properties ───────────────────────────────────────────────────

@pytest.mark.parametrize("key", sorted(BOSSERHOF_WEIGHTS))
def test_identity_on_every_canonical_key(key):
    """Sharing the normaliser between arms must not move the rule engine."""
    assert clean_bosserhof(key) == key.lower()


def test_resolves_every_class_the_prompt_authorises():
    """Every Bosserhof spelling in the system prompt must land on a known class.

    Parsed out of the prompt itself rather than hard-coded, so editing the
    prompt's vocabulary without re-checking the normaliser fails here instead of
    six hours into a paid run.
    """
    # Scope strictly to the Bosserhof block. The prompt uses "1) ... 2) ..."
    # numbering for prose elsewhere too, so an unscoped parser scrapes sentences.
    head = "ALLOWED BOSSERHOF HEADLINE CATEGORIES:"
    assert head in SYSTEM_PROMPT, "prompt no longer declares the Bosserhof vocabulary"
    block = SYSTEM_PROMPT.split(head, 1)[1].split("\n\n", 1)[0]

    authorised = []
    for line in block.splitlines():
        line = line.strip()
        if not re.match(r"^\d+\)", line):
            continue
        body = line.split(")", 1)[1]
        if "(subcategories:" in body:
            headline, inner = body.split("(subcategories:", 1)
            authorised.append(headline.strip())
            authorised += [s.strip() for s in inner.rsplit(")", 1)[0].split("|")]
        else:
            authorised.append(body.strip())

    authorised = [a for a in authorised if a]
    assert len(authorised) >= 38, f"only parsed {len(authorised)} classes from the prompt"

    unresolved = [a for a in authorised
                  if resolve_prediction_bosserhof(a) not in BOSSERHOF_KNOWN]
    assert not unresolved, (
        f"{len(unresolved)} of {len(authorised)} prompt-authorised Bosserhof strings do "
        f"not resolve to a known class and would score wrong on formatting alone: "
        f"{unresolved}")


# ── Specific behaviours the scorer depends on ─────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("restaurants / gastronomy", "restaurants gastronomy"),
    ("retail (small-scale)",     "retail small scale"),
    ("Normal Office",            "normal office"),
    ("  hotels  ",               "hotels"),
    ("Restaurant Gastronomy",    "restaurants gastronomy"),   # typo table
    ("school",                   "schools"),                  # singular -> plural
])
def test_punctuation_and_typo_handling(raw, expected):
    assert clean_bosserhof(raw) == expected


@pytest.mark.parametrize("raw", ["residential", "Seems Residential", "none", "vacant",
                                 "just garages", "living"])
def test_no_class_terms_become_empty_string(raw):
    """'' is a real scoreable value meaning 'no class', distinct from None."""
    assert clean_bosserhof(raw) == ""


@pytest.mark.parametrize("raw", [None, "", "   ", "nan"])
def test_unusable_becomes_none(raw):
    assert clean_bosserhof(raw) is None


def test_longest_match_wins():
    """'retail small scale' must not also register the shorter 'retail'."""
    assert classes_mentioned("retail small scale") == ["retail small scale"]


def test_single_class_extracted_from_prose():
    """A model that answers in a sentence still gets credit for naming one class."""
    assert resolve_prediction_bosserhof(
        "probably normal office, given the tenant list") == "normal office"


def test_multi_class_prediction_is_left_raw():
    """Two classes named = the model failed to pick one; it must score wrong.

    Contrast with the truth side, which EXCLUDES such rows: a human naming two
    classes means the annotation is ambiguous, but a model naming two means the
    model did not answer the question.
    """
    out = resolve_prediction_bosserhof("either normal office or hotels")
    assert out not in BOSSERHOF_KNOWN
    assert len(classes_mentioned(out)) >= 2


def test_mock_fixture_classes_all_resolve():
    """The mock LLM in test_06_llm_mock.py must emit scoreable classes.

    Otherwise the mock tests pass while asserting a vocabulary the real scorer
    would reject.
    """
    for cls in ["kindergartens", "schools", "hospitals", "discount stores",
                "restaurants / gastronomy", "normal office"]:
        assert resolve_prediction_bosserhof(cls) in BOSSERHOF_KNOWN, cls
