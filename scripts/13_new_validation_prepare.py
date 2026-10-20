"""Step 13, part 1: the inputs of a new validation of the 1,035 validated places. The old truth was a check of the
ORIGINAL pipeline's answers and leans on them, so the same places are judged again in FINAL's own label scheme: all
1,035 places, judged blind first, then reviewed where an answer differs, from the LLM's own record plus web lookups.

Writes to data/output/13_new_validation/ (git-ignored):
  guide.md           the judging guide: FINAL's own label and class definitions (verbatim from its prompt), the
                     author's rulings, consistency rulings, what to return
  batches/bNN.md     the places to judge, blind: the record the LLM saw, the other OSM tags of the POIs, the address.
                     No answer of either pipeline and no old truth is in them.
  places.csv         place id -> building_id, batch; 60 places appear a second time (another id, another batch) to
                     measure how far two blind judgments agree
FINAL is only read (GeoPackages opened immutable, no bytecode written next to its modules).
Run from the repository root:  python scripts/13_new_validation_prepare.py
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import *  # the RULES config: FINAL's paths


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.dont_write_bytecode = True          # loading FINAL's modules must leave no __pycache__ in FINAL
FC = _load('final_config', FINAL_CONFIG_FILE)

OUT = NEW_VALIDATION_DIR
N_BATCHES = 30
N_DUPLICATES = 60
SEED = 13
MAX_POIS = 20                       # POIs listed with their tags per place (the record names all of them)
MAX_TAG_CHARS = 350
SKIP_TAG = re.compile(r'^(addr:|source|check_date|survey|timestamp|phone|fax|email|contact:(phone|fax|email|mobile)|'
                      r'payment:|wheelchair|toilets|level|ref:|fixme|mapillary|image|name:|alt_name|old_name:|'
                      r'official_name:|short_name:|int_name|loc_name|ele$|layer$|indoor|entrance|internet_access|'
                      r'diet:|fuel:|charging|socket|capacity:|currency|brand:wikipedia|operator:wikipedia|'
                      r'wikimedia_commons|not:)')
POI_COLS = ('operator', 'opening_hours', 'amenity', 'shop', 'tourism', 'office', 'landuse', 'building', 'building_levels',
            'religion', 'social_facility', 'craft', 'healthcare', 'club', 'leisure')

# ── the places: every unit on a kept building with a class or an activity truth (notebook 12's 1,035) ───────────────
units = pyogrio.read_dataframe(FINAL_VALIDATION_FILE, layer='units', IMMUTABLE='YES')
units = units[units['kept']]
has_cls = units['cls_truth'].map(lambda x: isinstance(x, str) and len(x) > 0)
has_act = units['act_truth'].notna()
places = units[has_cls | has_act].copy()
assert len(places) == 1035 and places['building_id'].is_unique
rec = pd.read_parquet(FINAL_DIR / 'data' / 'output' / '05_llm_input.parquet').set_index('building_id')
b06 = pyogrio.read_dataframe(FINAL_CLASSIFIED_FILE, layer='buildings', read_geometry=False, IMMUTABLE='YES',
                             columns=['building_id', 'address', 'city']).set_index('building_id')
bp = pyogrio.read_dataframe(FINAL_CLASSIFIED_FILE, layer='building_pois', read_geometry=False, IMMUTABLE='YES',
                            columns=['building_id', 'poi_id', 'poi_role', 'poi_use', 'name', 'parent_name',
                                     'share_in_building'])
bp = bp[bp['building_id'].isin(places['building_id'])]
pois = pyogrio.read_dataframe(FINAL_POIS_FILE, read_geometry=False, IMMUTABLE='YES',
                              columns=['poi_id', 'name', *POI_COLS, 'tags']).set_index('poi_id')
assert places['building_id'].isin(rec.index).all() and places['building_id'].isin(b06.index).all()
ll = places.geometry.representative_point().to_crs(4326)


def _txt(x):
    return ' '.join(str(x).split()) if isinstance(x, str) and x.strip() else None


def poi_tags(pid):
    """the POI's OSM tags beyond its name, address and bookkeeping, as 'key=value; ...'"""
    if pid not in pois.index:
        return ''
    r = pois.loc[pid]
    kv = {c: _txt(r[c]) for c in POI_COLS if _txt(r[c])}
    try:
        extra = json.loads(r['tags']) if isinstance(r['tags'], str) else {}
    except ValueError:
        extra = {}
    for k, v in extra.items():
        if not SKIP_TAG.match(k) and _txt(str(v)) and k not in kv:
            kv[k] = _txt(str(v))
    text = '; '.join(f'{k}={v}' for k, v in kv.items())
    return text if len(text) <= MAX_TAG_CHARS else text[:MAX_TAG_CHARS - 1] + '…'


def packet(pid, b, lat, lon):
    lines = [f'### {pid}', 'record:']
    lines += [f'  {line}' for line in rec.at[b, 'record'].splitlines()]
    city = re.sub(r'\s*,\s*(Stadt|Flecken)$', '', _txt(b06.at[b, 'city']) or '')
    addr = ', '.join(x for x in (_txt(b06.at[b, 'address']), city) if x)
    lines.append(f'address: {addr or "(none)"}  ·  coordinates {lat:.5f}, {lon:.5f}')
    g = bp[bp['building_id'] == b].copy()
    if len(g):
        g['own'] = g['poi_role'] != 'site'
        g = g.sort_values(['own', 'share_in_building', 'name'], ascending=[False, False, True], na_position='last')
        lines.append('POI tags:')
        for _, r in g.head(MAX_POIS).iterrows():
            where = 'site' if r['poi_role'] == 'site' else ('unit in ' + (_txt(r['parent_name']) or 'a larger building')
                                                           if r['poi_role'] == 'unit' else 'inside')
            lines.append(f'  - {_txt(r["name"]) or "unnamed"} [{where}]: {poi_tags(r["poi_id"]) or "(no other tags)"}')
        if len(g) > MAX_POIS:
            lines.append(f'  - ... {len(g) - MAX_POIS} more (named in the record)')
    return '\n'.join(lines)


# ── batches: shuffled with a fixed seed so every batch mixes towns and kinds; 60 places a second time elsewhere ──────
rng = np.random.default_rng(SEED)
order = places['building_id'].to_numpy()[rng.permutation(len(places))]
batch_of = {b: i % N_BATCHES for i, b in enumerate(order)}
dups = rng.choice(order, size=N_DUPLICATES, replace=False)
rows, content = [], {k: [] for k in range(N_BATCHES)}
coords = dict(zip(places['building_id'], zip(ll.y, ll.x)))
for i, b in enumerate(order, 1):
    rows.append({'pid': f'P{i:04d}', 'building_id': b, 'batch': batch_of[b] + 1, 'duplicate_of': ''})
for j, b in enumerate(dups, len(order) + 1):
    other = (batch_of[b] + 1 + rng.integers(0, N_BATCHES - 1)) % N_BATCHES     # never its own batch
    assert other != batch_of[b]
    first = next(r['pid'] for r in rows if r['building_id'] == b)
    rows.append({'pid': f'P{j:04d}', 'building_id': b, 'batch': other + 1, 'duplicate_of': first})
table = pd.DataFrame(rows)
table = table.sample(frac=1, random_state=SEED).sort_values('batch', kind='stable')     # duplicates mixed in
for r in table.itertuples():
    lat, lon = coords[r.building_id]
    content[r.batch - 1].append(packet(r.pid, r.building_id, lat, lon))

# ── the guide ────────────────────────────────────────────────────────────────────────────────────────────────────────
P = FC.LLM_SYSTEM_PROMPT
reading = P[P.index('  inside:'):P.index('You must produce TWO outputs')].rstrip()
labels = P[P.index('- university\n\nRepresents'):P.index('────────────────────────────────────\nPART B')].rstrip()
work = P[P.index('- work\n\nRepresents'):P.index('- university\n\nRepresents')].rstrip()
cls_principle = P[P.index('KEY PRINCIPLE:'):P.index('────────────────────────────────────\nBOSSERHOF CATEGORIES')].rstrip()
cls_meanings = P[P.index('1) Transport'):P.index('────────────────────────────────────\nOUTPUT FORMAT')].rstrip()
cls_meanings = cls_meanings.replace('- highly productive industries / machine / material or space intensive\n- others',
                                    '- highly productive industries / machine / material or space intensive\n'
                                    '- others (industrial)')
GUIDE = f"""# Judging guide: what each building is used for

You are an independent validator building a new ground truth. For each place in your batch file you decide, from
the evidence:
1. the Bosserhof class: what kind of place the building is as a whole, and
2. the activity labels: the purposes for which people come to the building.

**You judge blind.** You do not know, and must not try to find out, what any classification pipeline answered or what
an earlier validation said. Read only this guide and your batch file; do not open, search or list any other file on
this computer. Judge each place on its own evidence.

## The evidence for each place
- **record**: exactly the lines a classifier saw. How to read them (the classifier's own instructions):

{reading}
- **address** and coordinates, for finding the place.
- **POI tags**: the other OpenStreetMap tags of the POIs (operator, opening hours, website, description ...);
  [inside] = in the building, [unit in X] = a unit of a larger building, [site] = the complex around it.

## Web lookups
Load the tools once with ToolSearch, query "select:WebSearch,WebFetch". Search when a named business or institution's
use is unclear from the evidence, or when something suggests it closed, moved or changed (OpenStreetMap data can be
years old). Search the name with the town. At most 3 searches for one place and about 12 for your whole batch; never
search a private person or the address of a home. For a non-residential building with no occupant named you may search
its address to find who occupies it (business directories, company pages). Write what you found and the source into "web" (empty when
you did not search). Judge the use the place has today; when the web shows the record is out of date (closed, moved,
another occupant), judge today's use and set "changed": true.

## Part A: activity labels
Judge these eleven labels; "work" (people employed there) is added to every building by rule elsewhere, so leave it
out. Their definitions, as the classifier received them:

{labels}

For reference, the label you leave out:

{work}

Give two lists:
- **labels_required**: every label whose core idea a main purpose of the place clearly meets. A building has as many
  labels as it has distinct visitor purposes; one occupant can serve several, several occupants of different kinds
  serve several. A building of an institution or a company also serves that organisation's purpose.
- **labels_optional**: labels a careful validator would also accept but not insist on: a secondary purpose, or a
  purpose that only partly meets the core idea. Keep it short. A label goes into one list at most.
- Where only staff come (a factory, a warehouse, a plant room), both lists stay empty.
- Where the evidence is thin (no occupant, no name, nothing found on the web), do not invent purposes: labels_required
  holds only what the kind of building clearly implies (a school building: school), labels_optional the purposes the
  kind of building plausibly serves; accept the plausible classes in class_accept and set confidence low.

Consistency rulings (apply them unless the evidence says otherwise; "+ x optional" puts x in labels_optional):
- restaurant, café, bar, pub, snack bar, ice-cream parlour: leisure + meetup optional
- supermarket, bakery, butcher, kiosk, drugstore, greengrocer, beverage store: retail_daily
- pharmacy: retail_daily + errands optional
- clothes, shoes, electronics, furniture, DIY, books, toys, jewellery, gifts, bicycles, car dealer: retail_non_daily
  (car dealer + errands optional for its workshop)
- hairdresser, beauty or nail salon, laundry, post office, bank, insurance or travel agency, notary, tax adviser or
  lawyer for private clients, doctor, dentist, physiotherapy, vet, car repair, tyre service, petrol station: errands
  (petrol station + retail_daily optional for its shop)
- town hall, citizens' office, job centre, other public administration with visitors: errands + business optional
- company office, consultancy, agency, association or administration without walk-in visitors: business optional
- hotel, guest house, holiday flat, hostel: leisure + business optional; hotel with conference areas: leisure, business
- church, chapel, mosque or other place of worship: meetup + leisure optional
- community centre, club house, youth centre, meeting place for seniors: meetup + leisure and lessons optional
- sports hall, gym, fitness studio, swimming pool, sports club building: sports + leisure optional
- museum, theatre, cinema, gallery, library, zoo: leisure (library + lessons optional)
- music, dance, driving, language school, adult education centre: lessons
- school (general or vocational): school (+ sports optional where it has a sports hall)
- kindergarten, crèche, day nursery: childcare
- university, college: university; a research institute of a university: university + business optional; another
  research institute: business optional
- hospital: errands + meetup optional; nursing or care home: meetup + errands optional
- garages, sheds, barns and technical buildings (substation, pump house), even on a company's or a farm's grounds; a
  building where only people live; a vacant building or ruin: no activity (set no_activity, class "none", empty lists)

## Part B: Bosserhof class
The classifier's instructions:

{cls_principle}

The categories and what they mean:

{cls_meanings}

Give:
- **class_best**: the one class that best describes the place as a whole: a headline category or one of its
  subcategories, written exactly as in the list (the industrial "others" is written "others (industrial)"); "none"
  only with no_activity.
- **class_accept**: other classes a careful validator would also accept as right. Always add the headline category
  when the record alone (without your web lookup) does not let one tell its subcategories apart: the classifier was
  told to choose the headline then. Add another class where the place honestly fits two (a bakery with a café:
  retail (small-scale) and restaurants / gastronomy). Do not add classes that are merely possible.

Rulings (the author's, and for consistency):
- town halls and public offices: Services (normal office or customer-oriented services), not Public facilities
- the scale of a store follows its footprint: hypermarkets / superstores from about 3,000 m2; a small building is
  retail (small-scale); discount stores are the discount chains (Aldi, Lidl, Netto, Penny, Norma ...); shopping centers
  house about ten or more separate shops, or are tagged or named a centre or mall
- pharmacy: retail (small-scale) or customer-oriented services (accept both); petrol station: the same two
- doctor's or dental practice, physiotherapy, bank branch, insurance or travel agency, hairdresser: customer-oriented
  services; lawyer, tax adviser, consultancy, IT services, agency: business-oriented services (accept normal office);
  a company's offices: normal office (accept open-plan office for a large office building of one organisation)
- church, community hall, club house: entertainment, culture (accept the headline Facilities for culture, leisure and
  sports)
- sports hall, gym, fitness studio, pool: fitness / wellness (accept the headline); a large leisure pool: large discos,
  fun / leisure pools
- a building on the premises of a company or an institution takes that organisation's class (a school's sports hall:
  schools, accept fitness / wellness)
- hotel, guest house, holiday flat: hotels; nursing or care home: nursing homes; car dealer: car dealerships; car repair
  or tyre service: vehicle / electrical repair
- a farm shop, farm café or riding stable with visitors: judge that use (other farm buildings: no activity, above)
- a residential building with a shop, practice or office: judge the shop, practice or office

## What to return
For every place of your batch, in the order of the file:
- pid
- no_activity: true only for the no-activity cases above
- class_best, class_accept
- labels_required, labels_optional
- changed: true when the web showed the record out of date
- confidence: high (an occupant or name you understand decides it), medium (the kind of building decides it), low
  (little more than land use and size)
- web: what you found and where, or ""
- reason: at most 40 words naming the evidence that decided
"""
OUT.mkdir(parents=True, exist_ok=True)
(OUT / 'batches').mkdir(exist_ok=True)
(OUT / 'guide.md').write_text(GUIDE, encoding='utf-8', newline='\n')
for k in range(N_BATCHES):
    head = (f'# Batch {k + 1:02d}: {len(content[k])} places\n\nJudge every place below by the guide (guide.md in this '
            f'folder\'s parent). Blind: no answers are given and none may be looked up.\n\n')
    (OUT / 'batches' / f'b{k + 1:02d}.md').write_text(head + '\n\n'.join(content[k]) + '\n', encoding='utf-8',
                                                     newline='\n')
table.sort_values('pid').to_csv(OUT / 'places.csv', index=False)
sizes = [len(content[k]) for k in range(N_BATCHES)]
print(f'{len(places):,} places + {N_DUPLICATES} repeats in {N_BATCHES} batches of {min(sizes)}-{max(sizes)}; '
      f'guide {len(GUIDE):,} characters; written to {OUT}')
