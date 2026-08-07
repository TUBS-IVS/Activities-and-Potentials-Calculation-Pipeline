"""
llm_utils.py — Shared helpers for LLM building classification.

Imported by:
  - notebooks/06b_llm_classification.ipynb   (the benchmark run)
  - notebooks/06c_llm_to_classified.ipynb    (production adapter)
  - tests/test_06_llm_mock.py
  - scripts/llm_smoke_test.py

Edit here; nowhere else. That line was previously aspirational: the prompt, the
HTTP transport and the per-row driver each existed in two or three drifted
copies across the notebooks and the smoke test, and notebook 06 referenced a
`predict_row` that was defined in none of them. They now live here, once.

No credentials are needed to import this module. The API token is resolved
inside call_tu_llm() at call time, so pytest and a fresh clone can import it.
"""

import json
import os
import re
import time

import pandas as pd
import requests
from dotenv import load_dotenv

from config import (
    LLM_API_URL, LLM_MODEL, LLM_REASONING,
    LLM_MAX_RETRIES, LLM_BACKOFF_SEC, LLM_TIMEOUT_SEC,
    TARGET_MID_LABELS, ROOT,
)

# ──────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ──────────────────────────────────────────────────────────────────────────────
# Taken from windows:notebooks/06_llm_classification.ipynb cell 3 — the only one
# of the three drifted copies that carries the Bosserhof taxonomy (the smoke
# test's copy omitted it entirely; notebook 07's was an 8-line headline-only
# variant). This is the vocabulary the annotation workbook's pre-filled values
# were drawn from, so it is the copy that reproduces the labelled distribution.
#
# Two deliberate deviations from that cell, both recorded here so the prompt is
# never mistaken for a byte-exact reproduction of the annotated run:
#
#   1. Four mojibake em-dashes are repaired. The notebook stored U+00E2 U+20AC
#      U+201D — a UTF-8 em-dash decoded as cp1252 and re-saved — and sent that
#      to the model verbatim. The .py copies of the same prompt had clean
#      em-dashes, so this restores agreement rather than inventing it.
#
#   2. The LABELLING CONVENTIONS block is new. Both conventions are definitions
#      of the label set that the human annotator applied and that rule_utils
#      encodes (rule_utils.py adds `work` to anything carrying a Bosserhof
#      class). Telling one classifier and not the other is the asymmetry;
#      stating it for both is the fair choice. Ablating the rule engine's
#      equivalent line moves it from 0.8449/0.7851 to 0.7602/0.4384, so this is
#      a large effect and must not be left implicit.

SYSTEM_PROMPT = """
You are a building activity interpreter and classifier.

Your task is to classify BUILDINGS using structured input divided into TWO PARTS:
1) precise_known_info — high-confidence OSM-derived signals such as names, amenity, shop, office, tourism, healthcare, leisure, etc.
2) general_building_context — broader contextual signals such as ALKIS landuse, OSM building type, OSM landuse, auxiliary tags.

You must produce TWO outputs:
1) Activity labels (mid_labels) — what activities take place inside the building
2) Bosserhof class — the dominant functional building-use class for capacity / volume estimation

CRITICAL SCOPE RULE
Only classify ENTERABLE BUILDINGS or building-like places people actually use as destinations.
If the described place is not a building, not enterable, or only an outdoor / infrastructure / passive object:
- "mid_labels": []
- "bosserhof_class": null

LABELLING CONVENTIONS
- Any building that is staffed carries "work" in mid_labels, in addition to its visitor-facing labels.
- A purely residential building hosts no activity: return "mid_labels": [] and "bosserhof_class": null. A mixed residential/commercial building is classified on its non-residential use.

ALLOWED ACTIVITY LABELS (mid_labels):
work, university, school, childcare, retail_daily, retail_non_daily, leisure, sports, errands, meetup, lessons, business

ALLOWED BOSSERHOF HEADLINE CATEGORIES:
1) Transport
2) Yards, depots, storage areas, construction yards
3) Industrial operations / Production  (subcategories: highly productive industries / machine / material or space intensive | others)
4) Crafts and trades  (subcategories: craft businesses | craft courtyards)
5) Services  (subcategories: normal office | open-plan office | business-oriented services | customer-oriented services | hotels | hotels with conference areas | restaurants / gastronomy | suppliers for car dealerships | vehicle / electrical repair | customer service | car dealerships)
6) Retail  (subcategories: wholesale | retail (small-scale) | discount stores | DIY stores | furniture stores | hypermarkets / superstores | shopping centers | self-service department stores | department stores | factory outlet centers)
7) Public facilities  (subcategories: schools | universities | research institutes | kindergartens | hospitals | nursing homes)
8) Facilities for culture, leisure and sports  (subcategories: entertainment, culture | large cinemas | musical theatres | large discos, fun / leisure pools | arenas, large events | theme parks | fitness / wellness)

Use a subcategory string when confident; fall back to headline category when not. Use null only if the building truly does not fit any category.
Output EXACTLY ONE class string in "bosserhof_class" — either a subcategory or a headline category, never both, and never two alternatives. Write "schools", not "Public facilities | schools" and not "normal office or hotels".

OUTPUT FORMAT (STRICT JSON ONLY):
{
  "interpreted_type": "<plain-English description>",
  "mid_labels": ["<zero or more labels from the allowed list>"],
  "bosserhof_class": "<one Bosserhof class or null>",
  "reason": "<max 400 words explaining both classifications>"
}
""".strip()


# ──────────────────────────────────────────────────────────────────────────────
# EVIDENCE SELECTION
# ──────────────────────────────────────────────────────────────────────────────
# Which source columns become the prompt.
#
# "blind" exists because rule_utils.py says, verbatim:
#     DELIBERATELY NOT USED: osm_names / any free-text business name. … That is
#     the accepted limitation being measured here, not an oversight
# 75.9% of scoreable buildings carry a name. Handing the LLM names the rule
# engine is forbidden turns "LLM vs rules" into "with names vs without names",
# which is a different question. The blind arm answers the first; the full arm
# answers the second; running both and reporting the delta is the only way to
# say which effect any headline number came from.

_NAME_BEARING = {"osm_names", "website", "email"}

_PRECISE_FIELDS = [("osm_names", "name"), ("amenity", "amenity"), ("building", "building"),
                   ("shop", "shop"), ("tourism", "tourism"), ("information", "information"),
                   ("website", "website"), ("email", "email")]
_GENERAL_FIELDS = [("label_en", "building_label"), ("osm_building_type", "osm_building_type"),
                   ("osm_landuse_class", "osm_landuse_class"), ("osm_landuse_name", "osm_landuse_name"),
                   ("gfk_class", "gfk_class"), ("ALKIS_Landuse_info", "alkis_landuse"),
                   ("tags_search", "tags"), ("additional_information", "additional_info")]


def is_missing(x):
    if x is None: return True
    if isinstance(x, float) and pd.isna(x): return True
    if isinstance(x, str) and x.strip().lower() in ("", "none", "nan", "null"): return True
    if isinstance(x, (list, tuple, set, dict)) and len(x) == 0: return True
    return False


def format_value(x):
    if is_missing(x): return None
    if isinstance(x, (list, tuple, set)):
        vals = [format_value(v) for v in x if not is_missing(v)]
        return "; ".join(v for v in vals if v) or None
    return str(x).strip()


def row_to_llm_input(row, fields="full"):
    """Render one building row as the user-side prompt.

    fields="full"  — all 16 source columns (deployment arm)
    fields="blind" — drops osm_names / website / email (method-comparison arm)

    The body is otherwise untouched on purpose: this is the exact sentence
    contract the annotated run used. In particular the GeoPackage stores list
    columns as Python-repr strings and they must stay that way — do NOT
    ast.literal_eval them before calling this, or the prompt text changes.
    """
    if fields not in ("full", "blind"):
        raise ValueError(f"fields must be 'full' or 'blind', got {fields!r}")
    drop = _NAME_BEARING if fields == "blind" else frozenset()

    def collect(field_list):
        bits = []
        for col, label in field_list:
            if col in drop:
                continue
            val = format_value(row.get(col))
            if val: bits.append(f"{label}={val}")
        return bits

    sections = []
    p = collect(_PRECISE_FIELDS)
    g = collect(_GENERAL_FIELDS)
    if p: sections.append("precise_known_info: " + " | ".join(p))
    if g: sections.append("general_building_context: " + " | ".join(g))
    return "\n".join(sections)


def extract_first_json(text):
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m: raise ValueError("No JSON object found")
    # strict=False permits literal control characters (raw newlines, tabs) inside
    # string values. The model writes multi-line prose into `reason` and the
    # default parser rejects the whole object for it:
    #   JSONDecodeError: Invalid control character at: line 5 column 382
    # Observed at ~0.3% of rows in the blind run, i.e. ~3 buildings per 885. Each
    # one is a well-formed answer thrown away over whitespace, and every dropped
    # row shrinks this arm's denominator against a rule engine that excludes
    # nothing. Nothing downstream reads `reason` as data, so relaxing this cannot
    # affect a score.
    return json.loads(m.group(0), strict=False)


def validate(obj, valid_labels):
    """Raise unless obj satisfies the output contract. Mutates obj: [] -> None.

    The [] coercion is not cosmetic. `bosserhof_class: []` used to pass (the old
    guard read `if bc not in (None, [])`), and one list-valued cell mixed with
    string-valued cells makes the chunk's to_parquet raise ArrowTypeError —
    discarding every successful row in that flush, not just the offending one.
    """
    for key in ("interpreted_type", "mid_labels", "bosserhof_class", "reason"):
        if key not in obj: raise ValueError(f"Missing key: {key}")
    if not isinstance(obj["mid_labels"], list): raise ValueError("mid_labels must be a list")
    for lab in obj["mid_labels"]:
        if lab not in valid_labels: raise ValueError(f"Invalid label: {lab}")
    bc = obj["bosserhof_class"]
    if isinstance(bc, list) and not bc:
        obj["bosserhof_class"] = bc = None
    if bc is not None and not (isinstance(bc, str) and bc.strip()):
        raise ValueError("bosserhof_class must be a non-empty string or null")
    return obj


def normalise_mid_labels(labels):
    """Canonical, order-independent label set. Array-safe.

    Parquet round-trips a list column as numpy.ndarray, so callers must not rely
    on truthiness of the input (`if not labels` raises ValueError on an ndarray
    of length >= 2). Sorting makes two runs comparable cell-by-cell.
    """
    if labels is None:
        return []
    if isinstance(labels, float) and pd.isna(labels):
        return []
    # str() is not redundant: an ndarray yields numpy.str_ scalars, which compare
    # equal to str but serialise as np.str_('work') in a repr and leak numpy into
    # anything that round-trips the column through a string.
    return sorted({str(l) for l in list(labels) if l in TARGET_MID_LABELS})


# ──────────────────────────────────────────────────────────────────────────────
# TRANSPORT
# ──────────────────────────────────────────────────────────────────────────────

def _token():
    """Resolve the API token at call time, never at import.

    A module-scope `raise` would break `pytest tests/test_06_llm_mock.py` (which
    imports this module) and any clean-clone import check on a machine with no
    .env — neither of which makes a single API call.
    """
    load_dotenv(dotenv_path=ROOT / ".env")
    tok = os.getenv("TU_KI_TOOLBOX_TOKEN")
    if not tok:
        raise RuntimeError(
            "Missing TU_KI_TOOLBOX_TOKEN — copy .env.example to .env and add your token"
        )
    return tok


def call_tu_llm(user_input, system_prompt=SYSTEM_PROMPT):
    """POST one building to the KI-Toolbox chat endpoint; return the raw text.

    Stateless (`thread: None`): the system prompt is re-sent every call and no
    conversation history accumulates, so buildings cannot influence each other.
    """
    headers = {"Authorization": f"Bearer {_token()}", "Accept": "application/json",
               "Content-Type": "application/json"}
    payload = {"thread": None, "prompt": user_input, "model": LLM_MODEL,
               "customInstructions": system_prompt, "hideCustomInstructions": True,
               "reasoning": {"effort": LLM_REASONING}}
    last_err = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            r = requests.post(LLM_API_URL, headers=headers, json=payload,
                              stream=True, timeout=LLM_TIMEOUT_SEC)
            r.raise_for_status()
            full_text = ""
            for line in r.iter_lines(decode_unicode=True):
                if not line: continue
                try: event = json.loads(line)
                except json.JSONDecodeError: continue
                if event.get("type") == "chunk":
                    full_text += event.get("content", "")
                elif event.get("type") == "done":
                    if "response" in event: full_text = event["response"]
                    break
            return full_text
        except Exception as e:
            last_err = e
            # Sleep only if another attempt follows. The previous version slept
            # after the final failure too, burning LLM_BACKOFF_SEC * MAX_RETRIES
            # seconds of a worker for nothing on every hard failure.
            if attempt < LLM_MAX_RETRIES:
                time.sleep(LLM_BACKOFF_SEC * attempt)
    raise RuntimeError(f"LLM failed after {LLM_MAX_RETRIES} attempts: {last_err}")


def predict_row(gml_id, sentence, fields="full", src_file=None, src_volume_m3=None):
    """Classify one building. Never raises — failures come back as `error`.

    NOTE on `validate(obj, TARGET_MID_LABELS)`: the two argument names matter.
    Both earlier copies of this function called a one-argument `validate` that
    only existed as a local shadow in their own module. Moved here verbatim, the
    name would resolve to the real two-argument validate, every call would raise
    TypeError, the blanket `except` would swallow it, and all 1,391 rows would
    come back as errors after a full multi-hour run — with an empty checkpoint
    and no indication why.

    `reason` is stored untruncated (the old copy cut it at 120 chars). It is the
    only audit trail for why a building was labelled the way it was, and 1,391
    rows of prose is a few hundred KB.

    src_file / src_volume_m3 stamp which building this prediction was actually
    derived from. Notebook 10 asserts on them; without the stamp its identity
    guard compares a value re-joined from the source against itself and is
    bit-identical by construction, i.e. proves nothing.
    """
    gml_id = gml_id.item() if hasattr(gml_id, "item") else gml_id
    sentence = "" if sentence is None else str(sentence)
    base = {"gml_id": gml_id, "sentence": sentence, "fields": fields,
            "src_file": src_file, "src_volume_m3": src_volume_m3}
    try:
        raw = call_tu_llm(sentence)
        obj = extract_first_json(raw)
        validate(obj, TARGET_MID_LABELS)
        return {**base,
                "interpreted_type": obj["interpreted_type"],
                "mid_labels": obj["mid_labels"],
                "bosserhof_class": obj["bosserhof_class"],
                "reason": obj.get("reason", ""),
                "error": None}
    except Exception as e:
        return {**base,
                "interpreted_type": None, "mid_labels": [], "bosserhof_class": None,
                "reason": None, "error": f"{type(e).__name__}: {e}"}
