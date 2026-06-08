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
import json
import os
import time
import requests
import pandas as pd
import geopandas as gpd
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config import (
    CONDENSED_BUILDINGS_FILE, LLM_API_URL, LLM_MODEL, LLM_REASONING,
    LLM_TIMEOUT_SEC, LLM_MAX_RETRIES, LLM_BACKOFF_SEC, TARGET_MID_LABELS,
)
from llm_utils import row_to_llm_input, extract_first_json, validate as _validate


def validate(obj):
    _validate(obj, TARGET_MID_LABELS)

load_dotenv(dotenv_path=ROOT / '.env')
TU_TOKEN = os.getenv('TU_KI_TOOLBOX_TOKEN')
if not TU_TOKEN:
    raise RuntimeError('Missing TU_KI_TOOLBOX_TOKEN in .env')

# ── System prompt (copy from NB06) ───────────────────────────────────────────

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

ALLOWED ACTIVITY LABELS (mid_labels):
work, university, school, childcare, retail_daily, retail_non_daily, leisure, sports, errands, meetup, lessons, business

OUTPUT FORMAT (STRICT JSON ONLY):
{
  "interpreted_type": "<plain-English description>",
  "mid_labels": ["<zero or more labels from the allowed list>"],
  "bosserhof_class": "<one Bosserhof class or null>",
  "reason": "<max 400 words explaining both classifications>"
}
""".strip()


def call_tu_llm(user_input):
    headers = {'Authorization': f'Bearer {TU_TOKEN}', 'Accept': 'application/json',
               'Content-Type': 'application/json'}
    payload = {'thread': None, 'prompt': user_input, 'model': LLM_MODEL,
               'customInstructions': SYSTEM_PROMPT, 'hideCustomInstructions': True,
               'reasoning': {'effort': LLM_REASONING}}
    last_err = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            r = requests.post(LLM_API_URL, headers=headers, json=payload,
                              stream=True, timeout=LLM_TIMEOUT_SEC)
            r.raise_for_status()
            full_text = ''
            for line in r.iter_lines(decode_unicode=True):
                if not line: continue
                try: event = json.loads(line)
                except json.JSONDecodeError: continue
                if event.get('type') == 'chunk':
                    full_text += event.get('content', '')
                elif event.get('type') == 'done':
                    if 'response' in event: full_text = event['response']
                    break
            return full_text
        except Exception as e:
            last_err = e
            time.sleep(LLM_BACKOFF_SEC * attempt)
    raise RuntimeError(f'LLM failed after {LLM_MAX_RETRIES} attempts: {last_err}')

def predict_row(gml_id, sentence):
    gml_id = gml_id.item() if hasattr(gml_id, 'item') else gml_id
    sentence = '' if sentence is None else str(sentence)
    try:
        raw = call_tu_llm(sentence)
        obj = extract_first_json(raw)
        validate(obj)
        return {'gml_id': gml_id, 'sentence': sentence,
                'interpreted_type': obj['interpreted_type'],
                'mid_labels': obj['mid_labels'],
                'bosserhof_class': obj['bosserhof_class'],
                'reason': obj['reason'][:120] + '...' if len(obj.get('reason','')) > 120 else obj.get('reason',''),
                'error': None}
    except Exception as e:
        return {'gml_id': gml_id, 'sentence': sentence,
                'interpreted_type': 'ERROR', 'mid_labels': [], 'bosserhof_class': None,
                'reason': None, 'error': str(e)}

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
    args = parser.parse_args()

    print(f'Loading condensed buildings from {CONDENSED_BUILDINGS_FILE}...')
    df = gpd.read_file(CONDENSED_BUILDINGS_FILE)
    df = df.drop(columns=['geometry'])
    print(f'Loaded {len(df):,} buildings. Picking {args.n} diverse samples...\n')

    sample = pick_sample(df, args.n)
    print(f'Selected {len(sample)} buildings across {len(set(b for b,_ in sample))} signal buckets:\n')
    for bucket, row in sample:
        sentence = row_to_llm_input(row.to_dict())
        print(f'  [{bucket}] gml_id={row["gml_id"]}')
        print(f'    Input: {sentence[:120]}{"..." if len(sentence) > 120 else ""}')
    print()

    print(f'Running LLM ({LLM_MODEL}) with {args.workers} workers...\n')
    tasks = [(bucket, row) for bucket, row in sample]

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(predict_row, row['gml_id'],
                            row_to_llm_input(row.to_dict())): (bucket, row)
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
