"""One building in, one validated answer out (step 05.5).

The transport is the previous pipeline's (llm_utils.call_tu_llm): a stateless
POST to the TU Braunschweig KI-Toolbox with the system prompt sent as
customInstructions on every call, the streamed reply assembled from its chunks.
Nothing accumulates between calls, so buildings cannot influence each other.

What is new is that every reply is checked the moment it arrives and the
building is asked again at once when the check fails - the previous pipeline
left failed rows for later sweeps and, when a well-formed HTTP 200 carried a
malformed body, lost the row. Two failure kinds, two medicines:

  * a transport failure (timeout, connection error, HTTP error) is not the
    model's doing: wait with a growing pause, send the same text again; HTTP
    429 waits longer because the previous pipeline saw fast retries hit the
    same wall three times;
  * an invalid reply (no JSON, an unknown class string, an empty label list) is
    the model's doing: ask again with the validation error appended to the
    record, so the model sees what was wrong.

After LLM_MAX_ATTEMPTS the building comes back as failed with its error and the
raw reply, never as a guess. `classify` never raises for a per-building
problem; it raises only when there is no token, because then no call can work.

The token is read at call time from the environment or ROOT/.env and is never
printed. Nothing here writes files; lib/llm_run.py does that.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time

import requests

from config import (
    LLM_API_URL, LLM_MODEL, LLM_TIMEOUT_S, LLM_TOKEN_ENV, LLM_ENV_FILE,
    LLM_MAX_ATTEMPTS, LLM_BACKOFF_S, LLM_RATE_LIMIT_PAUSE_S,
    LLM_SYSTEM_PROMPT, LLM_OUTPUT_SCHEMA,
)


class TransportError(Exception):
    """The request did not produce a reply text: network, timeout, HTTP status, empty stream."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class InvalidAnswer(Exception):
    """A reply arrived but is not a valid answer under LLM_OUTPUT_SCHEMA."""


def read_token() -> str:
    """The API token, from the environment first, else from ROOT/.env (KEY=value lines)."""
    tok = os.getenv(LLM_TOKEN_ENV)
    if not tok and LLM_ENV_FILE.exists():
        for line in LLM_ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == LLM_TOKEN_ENV:
                tok = value.strip().strip('"').strip("'")
                break
    if not tok:
        raise RuntimeError(
            f"no {LLM_TOKEN_ENV}: set it in the environment or put a line "
            f"{LLM_TOKEN_ENV}=... into {LLM_ENV_FILE} (git-ignored)")
    return tok


def prompt_sha(system_prompt: str = LLM_SYSTEM_PROMPT) -> str:
    """Twelve hex characters that identify the prompt text; stored with every answer so a
    resumed run never mixes answers given under a different prompt."""
    return hashlib.sha1(system_prompt.encode("utf-8")).hexdigest()[:12]


# ------------------------------------------------------------------ transport
def call_llm(user_text: str, system_prompt: str = LLM_SYSTEM_PROMPT, *,
             session=None, timeout: float = LLM_TIMEOUT_S, token: str | None = None) -> str:
    """POST one record to the chat endpoint and return the reply text. Raises TransportError.

    The endpoint takes the system prompt (customInstructions) and the one record
    (prompt), nothing else: it has no reasoning or temperature setting."""
    headers = {"Authorization": f"Bearer {token or read_token()}",
               "Accept": "application/json", "Content-Type": "application/json"}
    payload = {"thread": None, "prompt": user_text, "model": LLM_MODEL,
               "customInstructions": system_prompt, "hideCustomInstructions": True}
    http = session or requests
    try:
        r = http.post(LLM_API_URL, headers=headers, json=payload, stream=True, timeout=timeout)
    except requests.RequestException as e:
        raise TransportError(f"{type(e).__name__}: {e}") from e
    if r.status_code >= 400:
        try:
            body = " ".join(r.text.split())[:200]
        except Exception:                                    # noqa: BLE001 - the status is the message
            body = ""
        raise TransportError(f"HTTP {r.status_code} {body}".strip(), status=r.status_code)
    parts, done = [], False
    try:
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("type")
            if kind == "chunk":
                parts.append(event.get("content", ""))
            elif kind == "done":
                if "response" in event:
                    parts = [event["response"]]
                done = True
                break
            elif kind == "error":
                raise TransportError(f"server error event: {json.dumps(event)[:200]}")
    except requests.RequestException as e:
        raise TransportError(f"{type(e).__name__} while streaming: {e}") from e
    text = "".join(parts)
    if not text.strip():
        raise TransportError("empty reply" + ("" if done else " (stream ended without a done event)"))
    return text


# ------------------------------------------------------------------ parsing and validation
def parse_answer(text: str) -> dict:
    """The first JSON object in the reply, code fences tolerated. Raises InvalidAnswer."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[A-Za-z]*\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t)
    start = t.find("{")
    if start < 0:
        raise InvalidAnswer("no JSON object in the reply")
    try:
        obj, _ = json.JSONDecoder(strict=False).raw_decode(t[start:])
    except json.JSONDecodeError as e:
        raise InvalidAnswer(f"the JSON does not parse ({e.msg} at char {e.pos})") from e
    if not isinstance(obj, dict):
        raise InvalidAnswer("the JSON value is not an object")
    return obj


def _canon(value, allowed, what: str) -> str:
    """The value as the exact allowed string. Whitespace and letter case are normalised,
    nothing else: 'Public facilities / schools' is not a class and is rejected."""
    if not isinstance(value, str) or not value.strip():
        raise InvalidAnswer(f"{what} must be a non-empty string")
    v = " ".join(value.split())
    if v in allowed:
        return v
    by_lower = {a.lower(): a for a in allowed}
    if v.lower() in by_lower:
        return by_lower[v.lower()]
    raise InvalidAnswer(f'{what} "{v}" is not one of the allowed strings')


def _text(value, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidAnswer(f"{what} must be a non-empty string")
    return " ".join(value.split())


def validate_answer(obj: dict, schema: dict = LLM_OUTPUT_SCHEMA) -> dict:
    """The answer with exactly the schema's fields, every string canonical. Raises InvalidAnswer."""
    props = schema["properties"]
    missing = [k for k in schema["required"] if k not in obj]
    if missing:
        raise InvalidAnswer(f"missing field(s): {', '.join(missing)}")
    labels = obj["mid_labels"]
    if isinstance(labels, str):
        labels = [labels]
    if not isinstance(labels, list):
        raise InvalidAnswer("mid_labels must be a list")
    allowed_labels = props["mid_labels"]["items"]["enum"]
    seen: list[str] = []
    for lab in labels:
        c = _canon(lab, allowed_labels, "activity label")
        if c not in seen:
            seen.append(c)
    if not seen:
        raise InvalidAnswer("mid_labels is empty; every building receives at least one label")
    return {
        "interpreted_type": _text(obj["interpreted_type"], "interpreted_type"),
        "mid_labels": seen,
        "bosserhof_class": _canon(obj["bosserhof_class"], props["bosserhof_class"]["enum"], "bosserhof_class"),
        "confidence": _canon(obj["confidence"], props["confidence"]["enum"], "confidence"),
        "reason": _text(obj["reason"], "reason"),
    }


# ------------------------------------------------------------------ one building
_FAILED = {"interpreted_type": None, "mid_labels": [], "bosserhof_class": None, "confidence": None, "reason": None}


def classify(record: str, *, system_prompt: str = LLM_SYSTEM_PROMPT,
             max_attempts: int = LLM_MAX_ATTEMPTS, session=None, token: str | None = None,
             sleep=time.sleep) -> dict:
    """Ask, check, re-ask until the answer is valid or the attempts are spent. Never raises
    for a per-building problem. Returns the answer fields plus attempts, error, error_kind,
    retry_errors (what each failed attempt said), raw_on_fail, elapsed_s."""
    t0 = time.perf_counter()
    retry_errors: list[str] = []
    raw_last = None
    user_text = record
    for attempt in range(1, max_attempts + 1):
        try:
            raw_last = call_llm(user_text, system_prompt, session=session, token=token)
            answer = validate_answer(parse_answer(raw_last))
            return {"ok": True, **answer, "attempts": attempt, "error": None, "error_kind": None,
                    "retry_errors": retry_errors, "raw_on_fail": None,
                    "elapsed_s": round(time.perf_counter() - t0, 2)}
        except TransportError as e:
            retry_errors.append(f"transport: {e}")
            user_text = record                          # not the model's fault: the same text again
            if attempt < max_attempts:
                pause = LLM_RATE_LIMIT_PAUSE_S if e.status == 429 else LLM_BACKOFF_S[min(attempt - 1, len(LLM_BACKOFF_S) - 1)]
                sleep(pause)
        except InvalidAnswer as e:
            retry_errors.append(f"invalid: {e}")
            user_text = (f"{record}\n\nYour previous reply was rejected: {e}. "
                         "Reply with the JSON object only, using the exact strings from the lists.")
    last = retry_errors[-1] if retry_errors else "unknown"
    return {"ok": False, **_FAILED, "attempts": max_attempts, "error": last,
            "error_kind": last.split(":", 1)[0], "retry_errors": retry_errors[:-1],
            "raw_on_fail": (raw_last or "")[:2000], "elapsed_s": round(time.perf_counter() - t0, 2)}
