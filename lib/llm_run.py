"""The run: many buildings, once each, resumable, with visible progress (step 05.5).

Every answer is appended to a JSON-lines file the moment it is validated, one
line per building, flushed to disk. That is the checkpoint: a crash or a Ctrl-C
loses at most the call in flight, and a re-run skips every building that
already has a valid answer under the current prompt. Only valid answers count
as done, so a failed building is asked again on the next run without anyone
having to find it. The previous pipeline flushed a parquet every 25 rows and
needed later sweeps for the failures; this needs neither.

Progress, for a machine that runs for days:
  * in a terminal, one progress line is redrawn after every call - bar,
    done/total, seconds per call, ETA with the finishing time, failures, the
    last answer;
  * every LLM_STATUS_EVERY_S seconds a status block is printed on its own lines
    (this is what a log file gets when the run is detached with nohup) and
    written as JSON to LLM_STATUS_FILE, so a second terminal can read it: how
    far, how fast, when it ends, failures and retries, the confidence and class
    mix so far, the last building.

Notebook 05 uses the same `run` for the ten-building sample; scripts/05_run_llm.py
uses it for everything else.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

from config import LLM_MODEL, LLM_MAX_WORKERS, LLM_STATUS_EVERY_S, LLM_STATUS_FILE, WORK_IMPLIED_BY
from lib.llm_client import classify, prompt_sha, read_token

ANSWER_COLUMNS = [
    "building_id", "ok", "interpreted_type", "mid_labels", "bosserhof_class", "confidence", "reason",
    "attempts", "error", "error_kind", "retry_errors", "raw_on_fail", "elapsed_s", "model", "prompt_sha", "ts",
]


# ------------------------------------------------------------------ the answers file
def load_answers(path) -> pd.DataFrame:
    """Every line of the answers file as a row; a torn last line (crash mid-write) is skipped."""
    rows, torn = [], 0
    p = Path(path)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    torn += 1
    df = pd.DataFrame(rows)
    for c in ANSWER_COLUMNS:
        if c not in df.columns:
            df[c] = pd.Series([None] * len(df), dtype="object")
    df = df[ANSWER_COLUMNS]
    if torn:
        print(f"  !!  {torn} unreadable line(s) in {p.name} skipped (a write cut short)")
    return df


def valid_answers(answers: pd.DataFrame, sha: str) -> pd.DataFrame:
    """The valid answers under the prompt `sha`, one per building (the latest wins)."""
    if answers.empty:
        return answers
    ok = answers[(answers["ok"] == True) & (answers["prompt_sha"] == sha)]          # noqa: E712 - object column
    return ok.sort_values("ts").drop_duplicates("building_id", keep="last")


def done_ids(answers: pd.DataFrame, sha: str) -> set:
    return set(valid_answers(answers, sha)["building_id"])


# ------------------------------------------------------------------ progress
def _hms(seconds) -> str:
    seconds = int(max(0, seconds or 0))
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    return (f"{d}d " if d else "") + f"{h}:{m:02d}:{s:02d}"


class _Progress:
    def __init__(self, total: int, label: str):
        self.t0 = time.time()
        self.total, self.label = total, label
        self.n = self.ok = self.fail = self.retried = 0
        self.busy_s = 0.0
        self.conf, self.classes, self.labels = Counter(), Counter(), Counter()
        self.work_only = 0
        self.last = None

    def add(self, a: dict):
        self.n += 1
        self.busy_s += a["elapsed_s"]
        if a["ok"]:
            self.ok += 1
            self.conf[a["confidence"]] += 1
            self.classes[a["bosserhof_class"]] += 1
            self.labels.update(a["mid_labels"])
            if a["mid_labels"] == ["work"]:
                self.work_only += 1
        else:
            self.fail += 1
        if a["attempts"] > 1:
            self.retried += 1
        self.last = a

    # -- the numbers ---------------------------------------------------------------
    def as_dict(self) -> dict:
        elapsed = time.time() - self.t0
        rate = self.n / elapsed if elapsed > 0 and self.n else 0.0
        remaining = self.total - self.n
        eta_s = (remaining / rate) if rate else None
        eta_at = (dt.datetime.now() + dt.timedelta(seconds=eta_s)) if eta_s is not None else None
        return {
            "label": self.label, "time": dt.datetime.now().isoformat(timespec="seconds"),
            "done": self.n, "total": self.total, "ok": self.ok, "failed": self.fail, "retried": self.retried,
            "elapsed_s": round(elapsed), "s_per_call": round(self.busy_s / self.n, 1) if self.n else None,
            "calls_per_min": round(rate * 60, 2), "eta_s": round(eta_s) if eta_s is not None else None,
            "eta_at": eta_at.isoformat(timespec="minutes") if eta_at else None,
            "confidence": dict(self.conf), "top_classes": self.classes.most_common(6),
            "top_labels": self.labels.most_common(6), "work_only": self.work_only,
            "last": None if self.last is None else {
                k: self.last.get(k) for k in ("building_id", "ok", "interpreted_type", "mid_labels",
                                              "bosserhof_class", "confidence", "elapsed_s", "attempts", "error")},
        }

    def _eta_text(self, d: dict) -> str:
        if d["done"] >= d["total"]:
            return "finished"
        if d["eta_s"] is None:
            return "ETA -"
        return f"ETA {_hms(d['eta_s'])} (ends {d['eta_at'][5:16].replace('T', ' ')})"

    def _last_text(self, width: int) -> str:
        a = self.last
        if a is None:
            return ""
        if a["ok"]:
            return f"{a['building_id']} → {', '.join(a['mid_labels'])} | {a['bosserhof_class']} ({a['confidence']})"[:width]
        return f"{a['building_id']} FAILED: {a['error']}"[:width]

    # -- one redrawn line, for a terminal ---------------------------------------------
    def bar(self, width: int | None = None) -> str:
        width = width or shutil.get_terminal_size((120, 20)).columns
        d = self.as_dict()
        frac = d["done"] / d["total"] if d["total"] else 1.0
        cells = 24
        filled = int(round(frac * cells))
        head = (f"[{'#' * filled}{'.' * (cells - filled)}] {d['done']:,}/{d['total']:,} {100 * frac:5.1f}% | "
                f"{d['s_per_call'] or 0:.1f} s/call | {self._eta_text(d)} | ok {self.ok:,} · failed {self.fail:,}")
        room = width - len(head) - 4
        return (head + (" | " + self._last_text(room) if room > 20 else ""))[: width - 1]

    # -- the block, for the log and the status file ----------------------------------------
    def block(self) -> str:
        d = self.as_dict()
        pct = 100.0 * d["done"] / d["total"] if d["total"] else 100.0

        def mix(counter, n, order=None):
            items = sorted(counter.items(), key=lambda kv: order.index(kv[0])) if order else counter.most_common(n)
            return " · ".join(f"{k} {100 * v / self.ok:.0f}%" for k, v in items[:n]) if self.ok else "-"

        rows = [
            f"{d['time'][11:]} {self.label} | {d['done']:,}/{d['total']:,} {pct:.1f}% | ok {self.ok:,} · failed {self.fail:,} · "
            f"retried {self.retried:,} | {d['s_per_call']} s/call · {d['calls_per_min']}/min | elapsed {_hms(d['elapsed_s'])} · "
            f"{self._eta_text(d)}",
            f"         confidence {mix(self.conf, 3, ('high', 'medium', 'low'))} | classes {mix(self.classes, 4)}",
            f"         labels {mix(self.labels, 5)} | work as the only label "
            + (f"{100 * self.work_only / self.ok:.0f}%" if self.ok else "-"),
        ]
        if self.last is not None:
            a = self.last
            if a["ok"]:
                rows.append(f"         last {a['building_id']} {a['elapsed_s']}s: \"{a['interpreted_type'][:70]}\" → "
                            f"{', '.join(a['mid_labels'])} | {a['bosserhof_class']} ({a['confidence']})")
            else:
                rows.append(f"         last {a['building_id']} FAILED after {a['attempts']} attempts: {a['error'][:120]}")
        return "\n".join(rows)


def _write_status(path, progress: _Progress):
    if path is None:
        return
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(progress.as_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass                                                # the status file is a convenience, never a reason to stop


# ------------------------------------------------------------------ the run
def run(building_ids, records: dict, answers_file, *, label: str = "run", workers: int = LLM_MAX_WORKERS,
        status_every_s: float = LLM_STATUS_EVERY_S, status_file=LLM_STATUS_FILE, out=print,
        live_bar: bool | None = None) -> dict:
    """Classify every building in `building_ids` that has no valid answer yet, once.

    records: building_id -> record text. Appends to answers_file as it goes. `live_bar`
    (default: only when stdout is a terminal) redraws one progress line after every call;
    the status block is printed every status_every_s seconds in any case. Returns the final
    status dict; a KeyboardInterrupt stops cleanly and returns what was done."""
    ids = [str(b) for b in building_ids]
    if len(set(ids)) != len(ids):
        raise ValueError("a building appears twice in the list to classify")
    sha = prompt_sha()
    prior = load_answers(answers_file)
    done = done_ids(prior, sha)
    stale = int(((prior["ok"] == True) & (prior["prompt_sha"] != sha)).sum()) if len(prior) else 0   # noqa: E712
    pending = [b for b in ids if b not in done]
    missing = [b for b in pending if b not in records]
    if missing:
        raise KeyError(f"{len(missing)} building(s) to classify have no record, e.g. {missing[:3]}")
    read_token()                                            # fail now, not after the first pause
    if live_bar is None:
        live_bar = out is print and sys.stdout.isatty()
    out(f"{label}: {len(ids):,} buildings, {len(done):,} already answered under prompt {sha}, {len(pending):,} to do"
        + (f"; {stale:,} earlier answers under another prompt are ignored" if stale else "")
        + f" | model {LLM_MODEL}, {workers} request(s) at a time -> {Path(answers_file).name}")
    sys.stdout.flush()
    progress = _Progress(len(pending), label)
    if not pending:
        _write_status(status_file, progress)
        return progress.as_dict()

    Path(answers_file).parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    local = threading.local()

    def _session():
        if getattr(local, "s", None) is None:
            local.s = requests.Session()
        return local.s

    def one(b):
        a = classify(records[b], session=_session())
        a.update({"building_id": b, "model": LLM_MODEL, "prompt_sha": sha,
                  "ts": dt.datetime.now().isoformat(timespec="seconds")})
        return a

    next_block = time.time() + status_every_s
    bar_shown = False

    def emit_block():
        nonlocal bar_shown
        if bar_shown:
            sys.stdout.write("\n")
            bar_shown = False
        out(progress.block())
        sys.stdout.flush()                                  # a log file under nohup gets the block now, not when the buffer fills
        _write_status(status_file, progress)

    with open(answers_file, "a", encoding="utf-8") as f:
        def record_answer(a):
            nonlocal next_block, bar_shown
            with lock:
                f.write(json.dumps({k: a.get(k) for k in ANSWER_COLUMNS}, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
                progress.add(a)
                if live_bar:
                    sys.stdout.write("\r" + progress.bar())
                    sys.stdout.flush()
                    bar_shown = True
                if time.time() >= next_block or progress.n == progress.total or progress.n == 1:
                    emit_block()
                    next_block = time.time() + status_every_s

        try:
            if workers <= 1:
                for b in pending:
                    record_answer(one(b))
            else:
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futures = [ex.submit(one, b) for b in pending]
                    for fut in as_completed(futures):
                        record_answer(fut.result())
        except KeyboardInterrupt:
            if bar_shown:
                sys.stdout.write("\n")
            out(f"{label}: interrupted after {progress.n:,} of {progress.total:,}; everything answered so far is on disk, "
                "run again to resume")
            _write_status(status_file, progress)
            d = progress.as_dict()
            d["interrupted"] = True
            return d
    _write_status(status_file, progress)
    return progress.as_dict()


# ------------------------------------------------------------------ after the model
def apply_work_rule(labels) -> list:
    """The model's labels plus 'work' wherever any label in WORK_IMPLIED_BY is present."""
    labels = list(labels)
    if any(l in WORK_IMPLIED_BY for l in labels) and "work" not in labels:
        labels.append("work")
    return labels
