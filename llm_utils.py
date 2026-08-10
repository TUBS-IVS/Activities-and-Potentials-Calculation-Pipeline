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

1) precise_known_info → high-confidence OSM-derived signals such as names, amenity, shop, office, tourism, healthcare, leisure, etc.
2) general_building_context → broader contextual signals such as ALKIS landuse, OSM building type, OSM landuse, auxiliary tags, and other building-context information.

You must produce TWO outputs:
1) Activity labels (mid_labels) → what activities take place inside the building
2) Bosserhof class → the dominant functional building-use class for capacity / volume estimation

────────────────────────────────────
CRITICAL SCOPE RULE
────────────────────────────────────

Only classify ENTERABLE BUILDINGS or building-like places people actually use as destinations.

If the described place is not a building, not enterable, or only an outdoor / infrastructure / passive object:
- "mid_labels": []
- "bosserhof_class": null

────────────────────────────────────
INPUT STRUCTURE AND EVIDENCE PRIORITY
────────────────────────────────────

precise_known_info:
- Primary source for mid_labels
- Usually contains reliable OSM-derived evidence
- May contain several names, shops, amenities, offices, healthcare uses, leisure uses, tourism uses, or other POI functions
- Treat multiple entries as possible multiple activities inside the same building

general_building_context:
- Primary source for Bosserhof classification
- Broader but less precise
- May include ALKIS building/land-use information, OSM building type, tags (General Information About pois), or auxiliary contextual fields
- Use it as fallback for mid_labels only when precise_known_info is weak, empty, or incomplete

────────────────────────────────────
PART A — ACTIVITY LABELS (VISITOR INTENT)
────────────────────────────────────

ALLOWED ACTIVITY LABELS
- work
- university
- school
- childcare
- retail_daily
- retail_non_daily
- leisure
- sports
- errands
- meetup
- lessons
- business

GOAL:
Identify ALL clearly supported activities taking place INSIDE the building.

MANDATORY PROCEDURE:
1) First extract every distinct function from precise_known_info.
   Each name, amenity, shop, office, healthcare, leisure, tourism, craft, service, or other POI-like entry can represent a separate function.
2) Map each extracted function independently to one or more activity labels.
3) Aggregate labels across all functions.
4) Remove duplicates.
5) Do not stop after the first detected function.

If precise_known_info is missing or very weak, use general_building_context to infer likely building activity, but be more conservative.

MULTI-ACTIVITY RULE (VERY IMPORTANT):
- A building may contain MANY activities (e.g., mall, mixed-use building)
- You MUST extract ALL clearly supported activities
- Do NOT collapse multiple activities into one
- Do NOT stop at the first match

Think of the building as a container of activities:
→ Identify EACH distinct function mentioned
→ Map EACH to a label

────────────────────────────────────
LABEL DEFINITIONS
────────────────────────────────────

- work

Represents on-site labor, operational activity, or institutional functioning carried out by people inside the building.
Assign this label whenever the building’s normal use depends on people being physically present
to carry out tasks, responsibilities, operations, supervision, coordination, production,
maintenance, administration, instruction, care, or service provision.
The focus of this label is not why visitors come, but whether the building functions as a place
where human work is performed as part of its regular purpose.
A building should receive "work" whenever people are not merely present incidentally,
but are there in an active functional role that helps the building fulfill its purpose.
This includes cases where the same building also serves customers, students, patients, clients,
guests, or other visitors. In such cases, "work" must be added in parallel with the visitor-oriented label(s),
because the activity of workers is part of the building’s core function.
Core idea: "People are here not only to use the building, but also to make it function."

- university

Represents tertiary/higher-level education activity.
Covers structured learning, teaching, and research at the higher education level
Involves academic instruction, research, and study environments
Distinct from general learning by its institutional and advanced nature
Core idea: “Advanced academic education and research happen here.”

- school

Represents formal compulsory or pre-tertiary education activity.
Covers structured education for children and adolescents
Includes general and vocational schooling
Defined by curriculum-based learning under institutional supervision
Core idea: “Children or teenagers receive structured education here.”

- childcare

Represents supervision and early development care for young children.
Focuses on care, supervision, and early-stage development
Not primarily academic or curriculum-driven (unlike school)
Strong emphasis on custodial and developmental support
Core idea: “Young children are cared for and supervised here.”

- retail_daily

Represents frequent, necessity-driven consumption activity.
Covers acquisition of essential, regularly needed goods
Characterized by high frequency and routine visits
Typically tied to basic living needs
Core idea: “People come here regularly to fulfill essential daily needs.”

- retail_non_daily

Represents infrequent, discretionary consumption activity.
Covers acquisition of non-essential or durable goods
Visits are planned, occasional, or need-based
Often involves comparison, browsing, or larger purchases
Core idea: “People come here occasionally to buy non-essential or long-term goods.”

- leisure

Represents hedonic, relaxation, or enjoyment-oriented activity.
Focuses on free-time use driven by pleasure, comfort, or experience
Includes passive or active enjoyment, but not primarily goal-oriented tasks
Distinguished by non-obligatory participation. People choose to go here for enjoyment, not out of necessity or obligation.
Core idea: “People come here to relax, enjoy, or spend free time.”

- sports

Represents physical activity, exercise, or bodily training.
Focuses on intentional physical exertion or fitness improvement
Can be recreational or structured, but always movement-centered
Distinguished from leisure by physical intensity and purpose
Core idea: “People come here to be physically active or train their body.”

- errands

Represents task-oriented, functional activities needed for daily life management.
Covers practical obligations or maintenance tasks
Typically short, goal-driven visits with a clear outcome
Often involves services, administration, or personal maintenance
Core idea: “People come here to complete necessary tasks or obligations.”

- meetup

Represents social interaction and gathering activity.
Focuses on interpersonal connection and shared presence
Can be informal or organized, but the primary purpose is social exchange
Not necessarily tied to consumption or formal structure
Core idea: “People come here to meet and interact with others.”

- lessons

Represents structured instruction or skill acquisition activity.
Focuses on learning guided by an instructor
Can occur at any level (formal or informal), but always organized and instructional
Distinguished from general education by activity type (learning session), not institution
Core idea: “People come here to learn something through instruction.”

- business

Represents professional or organizational interaction activity (non-routine workplace).
Covers goal-oriented professional interactions, often external-facing
Includes meetings, consulting, administrative dealings, or formal exchanges
Distinct from "work" because it reflects the visitor’s purpose, not employment
Core idea: “People come here for professional or organizational matters.”

────────────────────────────────────
PART B — BOSSERHOF BUILDING-USE CLASS
────────────────────────────────────

GOAL
Assign EXACTLY ONE Bosserhof label that matches the categories/subcategories.

KEY PRINCIPLE:
Bosserhof is NOT about activities — it is about the BUILDING TYPE.

SOURCE PRIORITY FOR BOSSERHOF:
1) general_building_context is the primary source
2) precise_known_info supports or refines the choice
3) mid_labels can help interpret use, but must not override stronger building-type evidence

DOMINANCE HEURISTIC:
Choose the dominant function using:
1) explicit building type or ALKIS function
2) landuse / area context
3) scale indicators such as mall, shopping centre, school complex, office building, industrial hall, hospital, hotel
4) repeated / majority functions among multiple entries
5) if still unclear, choose the closest headline class rather than null

MULTI-TENANT BUILDINGS:
- Extract ALL activities (mid_labels)
- Assign ONE dominant Bosserhof class

STEP 1 — Subcategory FIRST (preferred)
If you can confidently map the building to ONE of the Bosserhof SUBCATEGORIES listed below,
output that subcategory label (exact string match).

STEP 2 — Headline category fallback (MANDATORY WHEN SUBCATEGORY IS UNCERTAIN)
If the exact subcategory is uncertain but the dominant functional sector is inferable,
you MUST output the corresponding HEADLINE category.
Do not return null when a headline category can reasonably represent the building's dominant use.

STEP 3 — No assignment
If the building does not fit reliably in any headline category OR is not an enterable building,
output bosserhof_class = null.

────────────────────────────────────
ALLOWED BOSSERHOF HEADLINE CATEGORIES AND SUBCATEGORIES
────────────────────────────────────

NEAREST-VALID-CLASS RULE (MANDATORY)

If the building is clearly enterable and supports a recognizable human activity,
you MUST assign the closest Bosserhof class, even if the fit is imperfect.

1) Transport
- no fixed subcategories given; use headline when transport building with staff is clear
Notes: Transport-related buildings with operational staff (depots, terminals)
Exclude: stops/platforms/tracks

2) Yards, depots, storage areas, construction yards
- no fixed subcategories given; use headline when storage/yard with staff is clear
Notes: Storage or operational yards with staff
Exclude: pure storage without staff, open yards without buildings

3) Industrial operations / Production
Subcategories:
- highly productive industries / machine / material or space intensive
- others

4) Crafts and trades
Subcategories:
- craft businesses
- craft courtyards

5) Services
Subcategories:
- normal office
- open-plan office
- business-oriented services
- customer-oriented services
- hotels
- hotels with conference areas
- restaurants / gastronomy
- suppliers for car dealerships
- vehicle / electrical repair
- customer service
- car dealerships

6) Retail
Subcategories:
- wholesale
- retail (small-scale)
- discount stores
- DIY stores
- furniture stores
- hypermarkets / superstores
- shopping centers
- self-service department stores
- department stores
- factory outlet centers

7) Public facilities
Subcategories:
- schools
- universities
- research institutes
- kindergartens
- hospitals
- nursing homes

8) Facilities for culture, leisure and sports
Subcategories:
- entertainment, culture
- large cinemas
- musical theatres
- large discos, fun / leisure pools
- arenas, large events
- theme parks
- fitness / wellness

────────────────────────────────────
OUTPUT FORMAT (STRICT JSON ONLY)
────────────────────────────────────

{
  "interpreted_type": "<plain-English description of what the place most likely is>",
  "mid_labels": ["<zero or more activity labels from the allowed list>"],
  "bosserhof_class": "<one Bosserhof class or null>",
  "reason": "<max 400 words. Explain both classifications, referencing OSM tags, keywords, and any verification used. Explicitly justify the Bosserhof choice or why it is null.>"
}
""".strip()


# ──────────────────────────────────────────────────────────────────────────────
# EVIDENCE SELECTION
# ──────────────────────────────────────────────────────────────────────────────
# Which source columns become the prompt.
#
# "full" is the DEFAULT and the headline arm. Business names are the whole reason
# to put an LLM on this problem: the model knows what "Deutsche Bank",
# "Ernsting's family" or "Ilseder Landkrug" are, and no rule table can encode
# that world knowledge.
#
# rule_utils.py says, verbatim:
#     DELIBERATELY NOT USED: osm_names / any free-text business name. … That is
#     the accepted limitation being measured here, not an oversight
# That is a limitation of the RULE ENGINE which the comparison exists to expose —
# not a handicap the LLM should adopt so the contest looks even. Deciding which
# classifier to deploy means letting each use what it can.
#
# "blind" withholds the same three fields, and is the ABLATION rather than the
# fair fight: full - blind is exactly what business-name world knowledge buys,
# which is the quantitative argument for choosing the LLM over the rules.

# Identifying, business-specific evidence. Withheld by the "blind" ablation
# because these are what rule_utils cannot use.
_NAME_BEARING = {"osm_names", "website", "email"}

_PRECISE_FIELDS = [("osm_names", "name"), ("amenity", "amenity"), ("building", "building"),
                   ("shop", "shop"), ("tourism", "tourism"), ("information", "information"),
                   ("website", "website"), ("email", "email")]
_GENERAL_FIELDS = [("label_en", "building_label"), ("osm_building_type", "osm_building_type"),
                   ("osm_landuse_class", "osm_landuse_class"), ("osm_landuse_name", "osm_landuse_name"),
                   ("gfk_class", "gfk_class"), ("ALKIS_Landuse_info", "alkis_landuse"),
                   ("tags_search", "tags"), ("additional_information", "additional_info")]

# DELIBERATELY NOT SENT, and why:
#
#   gml_id         a bare row identifier; carries no information.
#
#   alkis_address  24% of values are the city alone ("Braunschweig, Stadt"),
#                  and a street name adds little without a business name to
#                  attach it to. Weak field.
#
#   volume_m3      genuinely informative — every building has one, spanning
#                  70 to 1,748,585 m3, and the Bosserhof class is by definition
#                  about capacity / volume estimation. The human annotator saw
#                  it (workbook column H).
#
# Both are withheld to keep this run's field set IDENTICAL to the earlier run
# that pre-filled the annotation workbook. That earlier run used the same model
# (gpt-oss-120b) and these same 16 fields, so holding the inputs fixed makes
# "does the model reproduce itself" answerable — any disagreement is the model,
# not the prompt. Adding fields and measuring reproducibility at the same time
# would confound the two.
#
# Revisit volume_m3 as a separate variant AFTER the reproducibility question is
# settled; it is the most promising unused column the preprocessing produces.


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

    fields="full"  — all 16 source columns. THE headline arm; the default.
    fields="blind" — drops osm_names / website / email. The names ablation.

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
            raw = row.get(col)
            if col == "volume_m3":
                # Round: the raw value carries 12 decimal places of false
                # precision ("1554.252340847505"), which is noise in the prompt
                # and costs tokens for nothing.
                if is_missing(raw):
                    continue
                try:
                    bits.append(f"{label}={round(float(raw)):,}")
                except (TypeError, ValueError):
                    pass
                continue
            val = format_value(raw)
            if val: bits.append(f"{label}={val}")
        return bits

    sections = []
    p = collect(_PRECISE_FIELDS)
    g = collect(_GENERAL_FIELDS)
    if p: sections.append("precise_known_info: " + " | ".join(p))
    if g: sections.append("general_building_context: " + " | ".join(g))
    return "\n".join(sections)


def extract_first_json(text):
    # Parse the FIRST JSON object and ignore whatever follows it.
    #
    # The previous `re.search(r"\{.*\}", ..., DOTALL)` was greedy: it captured
    # from the first "{" to the LAST "}" anywhere in the response. When the model
    # emitted the object and then kept talking — a second object, or prose
    # containing a brace — the captured span was two values glued together and
    # json.loads rejected the lot with "Extra data: line 6 column 1". A complete,
    # correct answer was thrown away because of what came after it.
    #
    # raw_decode stops at the end of the first well-formed value, so trailing
    # content is simply ignored.
    start = text.find("{")
    if start != -1:
        try:
            obj, _ = json.JSONDecoder(strict=False).raw_decode(text[start:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass   # fall through to the span-based attempt below

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
