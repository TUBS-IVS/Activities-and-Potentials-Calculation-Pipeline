#!/usr/bin/env python
"""05_run_llm.py - the LLM run, for a machine that stays on.

Reads the plan (step 05.4) and the records (step 05.2), asks the model once per
planned call - the system prompt and one building's record, nothing else -
appends every validated answer to the answers file at once, and shows progress:
in a terminal one line is redrawn after every call; every minute a status block
is printed (that is what the log gets when the run is detached) and written to
data/output/05_llm_status.json for a second terminal. Stop it any time; start it
again and it continues where it stopped. Nothing is ever re-asked that has a
valid answer under the current prompt.

    cd <repo>
    python scripts/05_run_llm.py --sample            # the ten sample buildings, once each
    python scripts/05_run_llm.py --limit 200         # the first 200 pending calls, then stop
    python scripts/05_run_llm.py                     # everything the plan asks for

Detached on the Linux machine, with the status blocks in a log file:

    nohup python scripts/05_run_llm.py > data/output/05_llm_run.log 2>&1 &
    tail -f data/output/05_llm_run.log               # watch
    cat  data/output/05_llm_status.json              # the same facts as JSON

Or inside tmux / screen, where the progress line is redrawn live.

Options: --workers N sends N requests at a time (config default 1 - the rate
limit is undocumented, ask the operators before raising it); --ids a,b,c asks
only those buildings; --answers FILE writes somewhere else than the main
answers file; --status-every S changes the seconds between status blocks.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd                                                       # noqa: E402

from config import (                                                      # noqa: E402
    LLM_INPUT_FILE, LLM_PLAN_FILE, LLM_ANSWERS_FILE, LLM_SAMPLE_ANSWERS_FILE, LLM_STATUS_FILE,
    LLM_SAMPLE_BUILDING_IDS, LLM_MAX_WORKERS, LLM_STATUS_EVERY_S,
)
from lib.llm_client import prompt_sha                                    # noqa: E402
from lib.llm_run import run, load_answers, done_ids                       # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", action="store_true", help="the sample buildings from config, once each")
    ap.add_argument("--ids", help="comma-separated building ids instead of the plan")
    ap.add_argument("--limit", type=int, default=None, help="stop after this many pending calls")
    ap.add_argument("--workers", type=int, default=LLM_MAX_WORKERS, help="requests at a time")
    ap.add_argument("--answers", type=Path, default=None,
                    help="answers file (default: the sample file with --sample, else the main one)")
    ap.add_argument("--status-every", type=float, default=LLM_STATUS_EVERY_S, help="seconds between status blocks")
    args = ap.parse_args(argv)

    for f in (LLM_INPUT_FILE, LLM_PLAN_FILE):
        if not f.exists():
            sys.exit(f"missing {f} - run notebook 05 sections 2 and 4 first")
    records = pd.read_parquet(LLM_INPUT_FILE, columns=["building_id", "record"])
    records = dict(zip(records["building_id"], records["record"]))

    if args.sample:
        ids, answers, label = list(LLM_SAMPLE_BUILDING_IDS), args.answers or LLM_SAMPLE_ANSWERS_FILE, "sample"
    elif args.ids:
        ids, answers, label = [s.strip() for s in args.ids.split(",") if s.strip()], args.answers or LLM_ANSWERS_FILE, "ids"
    else:
        plan = pd.read_parquet(LLM_PLAN_FILE)
        ids, answers, label = sorted(plan["answered_by"].unique()), args.answers or LLM_ANSWERS_FILE, "full"
    if args.limit is not None:
        done = done_ids(load_answers(answers), prompt_sha())
        ids = [b for b in ids if b not in done][: args.limit]

    summary = run(ids, records, answers, label=label, workers=args.workers,
                  status_every_s=args.status_every, status_file=LLM_STATUS_FILE)
    print(f"\n{label}: done {summary['done']:,}, ok {summary['ok']:,}, failed {summary['failed']:,} -> {answers}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
