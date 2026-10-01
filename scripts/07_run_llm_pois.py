#!/usr/bin/env python
"""07_run_llm_pois.py - the POI run (step 07), for a machine that stays on.

Reads the records of notebook 07 section 2 (07_llm_poi_input.parquet: one record per
POI placed in a building; every poi_id in it is asked, there is no plan file), asks the
model once per POI - the POI system prompt and one record, nothing else - appends every
validated answer to the answers file at once and shows progress exactly as
05_run_llm.py does: one line redrawn per call in a terminal, a status block every
minute (what the log gets when detached) and the same block as JSON in
data/output/07_llm_poi_status.json. Stop it any time; start it again and it continues
where it stopped. Nothing is ever re-asked that has a valid answer under the current
prompt.

    cd <repo>
    python scripts/07_run_llm_pois.py --sample          # the sample POIs from config, once each
    python scripts/07_run_llm_pois.py --limit 200       # the first 200 pending calls, then stop
    python scripts/07_run_llm_pois.py                   # every POI of the input file

Detached on the Linux machine, with the status blocks in a log file:

    nohup nice -n 10 python scripts/07_run_llm_pois.py > data/output/07_llm_poi_run.log 2>&1 &
    tail -f data/output/07_llm_poi_run.log              # watch
    cat  data/output/07_llm_poi_status.json             # the same facts as JSON

Options as in 05_run_llm.py: --workers N sends N requests at a time (config default 1 -
the rate limit is undocumented, ask the operators before raising it); --ids a,b,c asks
only those poi_ids; --answers FILE writes somewhere else than the main answers file;
--status-every S changes the seconds between status blocks.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd                                                       # noqa: E402

from config import (                                                      # noqa: E402
    LLM_POI_INPUT_FILE, LLM_POI_ANSWERS_FILE, LLM_POI_SAMPLE_ANSWERS_FILE, LLM_POI_STATUS_FILE,
    LLM_POI_SAMPLE_IDS, LLM_POI_SYSTEM_PROMPT, LLM_POI_OUTPUT_SCHEMA, LLM_MAX_WORKERS, LLM_STATUS_EVERY_S,
)
from lib.llm_client import prompt_sha                                    # noqa: E402
from lib.llm_run import run, load_answers, done_ids, answer_columns       # noqa: E402

ID_COL = "poi_id"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", action="store_true", help="the sample POIs from config, once each")
    ap.add_argument("--ids", help="comma-separated poi_ids instead of the whole input file")
    ap.add_argument("--limit", type=int, default=None, help="stop after this many pending calls")
    ap.add_argument("--workers", type=int, default=LLM_MAX_WORKERS, help="requests at a time")
    ap.add_argument("--answers", type=Path, default=None,
                    help="answers file (default: the sample file with --sample, else the main one)")
    ap.add_argument("--status-every", type=float, default=LLM_STATUS_EVERY_S, help="seconds between status blocks")
    args = ap.parse_args(argv)

    if not LLM_POI_INPUT_FILE.exists():
        sys.exit(f"missing {LLM_POI_INPUT_FILE} - run notebook 07 section 2 first")
    records = pd.read_parquet(LLM_POI_INPUT_FILE, columns=[ID_COL, "record"])
    if records[ID_COL].duplicated().any():
        sys.exit(f"a {ID_COL} appears twice in {LLM_POI_INPUT_FILE.name}")
    records = dict(zip(records[ID_COL], records["record"]))

    if args.sample:
        ids, answers, label = list(LLM_POI_SAMPLE_IDS), args.answers or LLM_POI_SAMPLE_ANSWERS_FILE, "sample"
    elif args.ids:
        ids, answers, label = [s.strip() for s in args.ids.split(",") if s.strip()], args.answers or LLM_POI_ANSWERS_FILE, "ids"
    else:
        ids, answers, label = sorted(records), args.answers or LLM_POI_ANSWERS_FILE, "full"
    sha = prompt_sha(LLM_POI_SYSTEM_PROMPT)
    if args.limit is not None:
        done = done_ids(load_answers(answers, answer_columns(ID_COL, LLM_POI_OUTPUT_SCHEMA)), sha, ID_COL)
        ids = [p for p in ids if p not in done][: args.limit]

    summary = run(ids, records, answers, label=label, workers=args.workers, status_every_s=args.status_every,
                  status_file=LLM_POI_STATUS_FILE, id_col=ID_COL,
                  system_prompt=LLM_POI_SYSTEM_PROMPT, schema=LLM_POI_OUTPUT_SCHEMA)
    print(f"\n{label}: done {summary['done']:,}, ok {summary['ok']:,}, failed {summary['failed']:,} -> {answers}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
