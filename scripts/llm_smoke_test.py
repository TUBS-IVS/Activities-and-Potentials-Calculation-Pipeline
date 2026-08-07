"""
llm_smoke_test.py — Run the real LLM on a small diverse sample to verify
end-to-end output quality and format before committing to the full dataset.

Usage (from project root):
    python scripts/llm_smoke_test.py           # 10 buildings (default)
    python scripts/llm_smoke_test.py --n 20    # 20 buildings
    python scripts/llm_smoke_test.py --n 5 --workers 2
"""

import sys
import argparse
import pandas as pd
import geopandas as gpd
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config import LLM_MODEL, VALIDATION_BUILDINGS_FILE
# Prompt, transport and per-row driver all come from llm_utils. This script used
# to carry its own copies; the prompt had drifted (no Bosserhof taxonomy at all)
# so a green smoke test said nothing about what notebook 06b would actually send.
from llm_utils import SYSTEM_PROMPT, row_to_llm_input, predict_row

# ── Sample selection ──────────────────────────────────────────────────────────

def pick_sample(df, n):
    """Pick n rows spread across different signal types for diverse coverage."""
    rng = pd.core.common  # just for reproducibility via seed below
    buckets = {
        'school':      df[df['amenity'].astype(str).str.contains('school', na=False)],
        'kindergarten':df[df['amenity'].astype(str).str.contains('kindergarten', na=False)],
        'restaurant':  df[df['amenity'].astype(str).str.contains('restaurant', na=False)],
        'supermarket': df[df['shop'].astype(str).str.contains('supermarket', na=False)],
        'hospital':    df[df['amenity'].astype(str).str.contains('hospital', na=False)],
        'office':      df[df['amenity'].astype(str).str.contains('office', na=False)],
        'named':       df[df['osm_names'].notna() & ~df['amenity'].notna() & ~df['shop'].notna()],
        'sparse':      df[df['amenity'].isna() & df['shop'].isna() & df['osm_names'].isna()],
    }
    per_bucket = max(1, n // len(buckets))
    rows = []
    for label, bucket in buckets.items():
        if len(bucket) == 0:
            continue
        sample = bucket.sample(min(per_bucket, len(bucket)), random_state=42)
        for _, row in sample.iterrows():
            rows.append((label, row))
    # fill remaining slots with sparse rows if needed
    if len(rows) < n:
        extra = buckets['sparse'].sample(min(n - len(rows), len(buckets['sparse'])), random_state=99)
        for _, row in extra.iterrows():
            rows.append(('sparse_extra', row))
    return rows[:n]

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--n', type=int, default=10, help='Number of buildings to test')
    parser.add_argument('--workers', type=int, default=4, help='Parallel API workers')
    parser.add_argument('--fields', choices=['full', 'blind'], default='full',
                        help="'blind' drops osm_names/website/email, matching the "
                             "evidence the rule engine is allowed to see")
    args = parser.parse_args()

    # The FROZEN benchmark file, not the regenerated CONDENSED_BUILDINGS_FILE.
    # notebook 05 derives gml_id from a positional row index, so a regenerated
    # file renumbers every building — smoke-testing against it would exercise
    # rows that notebook 06b will never send.
    if not VALIDATION_BUILDINGS_FILE.exists():
        raise SystemExit(f'Benchmark buildings file not found:\n  {VALIDATION_BUILDINGS_FILE}\n'
                         'See config.VALIDATION_BUILDINGS_FILE.')
    print(f'Loading benchmark buildings from {VALIDATION_BUILDINGS_FILE}...')
    df = gpd.read_file(VALIDATION_BUILDINGS_FILE)
    df = df.drop(columns=['geometry'])
    print(f'Loaded {len(df):,} buildings. Picking {args.n} diverse samples '
          f'(fields={args.fields})...\n')

    sample = pick_sample(df, args.n)
    print(f'Selected {len(sample)} buildings across {len(set(b for b,_ in sample))} signal buckets:\n')
    for bucket, row in sample:
        sentence = row_to_llm_input(row.to_dict(), fields=args.fields)
        print(f'  [{bucket}] gml_id={row["gml_id"]}')
        print(f'    Input: {sentence[:120]}{"..." if len(sentence) > 120 else ""}')
    print()

    print(f'Running LLM ({LLM_MODEL}) with {args.workers} workers...\n')
    tasks = [(bucket, row) for bucket, row in sample]

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(predict_row, row['gml_id'],
                            row_to_llm_input(row.to_dict(), fields=args.fields),
                            args.fields, VALIDATION_BUILDINGS_FILE.name,
                            row.get('volume_m3')): (bucket, row)
            for bucket, row in tasks
        }
        for future in as_completed(futures):
            bucket, row = futures[future]
            result = future.result()
            result['bucket'] = bucket
            results.append(result)

    # Sort by bucket name for readable output
    results.sort(key=lambda r: r['bucket'])

    # ── Print results ──
    ok = [r for r in results if r['error'] is None]
    errors = [r for r in results if r['error'] is not None]

    print('=' * 70)
    print(f'RESULTS: {len(ok)}/{len(results)} succeeded, {len(errors)} errors')
    print('=' * 70)

    for r in results:
        status = 'OK  ' if r['error'] is None else 'FAIL'
        print(f'\n[{status}] [{r["bucket"]}] gml_id={r["gml_id"]}')
        print(f'  Input:      {r["sentence"][:100]}{"..." if len(r["sentence"]) > 100 else ""}')
        if r['error']:
            print(f'  ERROR:      {r["error"]}')
        else:
            print(f'  Type:       {r["interpreted_type"]}')
            print(f'  mid_labels: {r["mid_labels"]}')
            print(f'  bosserhof:  {r["bosserhof_class"]}')
            print(f'  Reason:     {r["reason"]}')

    print('\n' + '=' * 70)
    if errors:
        print(f'WARNING: {len(errors)} rows failed. Check error messages above.')
        print('These would be picked up by NB07 (error rerun) in the full pipeline.')
    else:
        print('All rows classified successfully. Output format is valid.')
        print('Safe to run the full NB06.')

if __name__ == '__main__':
    main()
