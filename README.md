# Building-Level Activity Capacity Pipeline — Rule-Based Classification

> **Institution:** [Institute of Transportation and Urban Engineering](https://www.tu-braunschweig.de/isv), TU Braunschweig
> **Author:** Mayur Patel

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-156%20passing-brightgreen)](docs/pipeline.md#running-the-tests)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Agent-based travel demand models need to know **what happens in each building and how much of it** — how many
workers, shoppers, pupils or visitors a building can hold. Such data are rarely available. This repository derives
them for every building in a region from open and official data:

- **ALKIS** — authoritative 3D cadastral buildings (Germany / Lower Saxony): footprint, height, official function code
- **OpenStreetMap** — POIs, land use and supplementary building footprints
- **A deterministic, tag-based classifier** ([`rule_utils.py`](rule_utils.py)) — gives each building a set of MiD
  activity labels and a Bosserhof worker-density class from structured OSM tags and ALKIS codes alone: no LLM, no
  API call, no business-name matching
- **Zone-level activity totals** (workers, pupils, shoppers, …), redistributed to the buildings in proportion to
  building volume × worker density

The result is a building-level activity potential dataset for transport modelling and agent-based simulation.

This branch is the **rules-only variant**. It asks how far a fully deterministic, transparent classifier gets, and
measures the answer against hand-checked ground truth and against an LLM classifier on the same buildings.

---

## Key results

| Question | Answer | Details |
|---|---|---|
| How much does the rule engine decide, and from what? | 90 % of buildings by ALKIS code, 2 % by POI tags; one generic ALKIS code covers 43 % of all buildings | [classification.md](docs/classification.md#three-layers-strict-precedence) |
| How accurate is it against a hand-annotated sample? | Activities: precision **84.5 %**, recall **78.5 %** (882 buildings). Bosserhof class: **50.3 %** (874 buildings) | [validation.md](docs/validation.md#rule-engine-scores--measured-held-out) |
| Where it fails, why? | Business names carry the missing information; the generic ALKIS commercial code cannot be split by rules | [validation.md](docs/validation.md#why-the-gap--the-mechanisms) |
| Does an LLM do better on the same buildings? | Zone activities: level (F1 71.2 vs 72.6 %, n.s.). Fine Bosserhof class: the LLM leads (64.8 vs 59.6 %, p = 0.0014); by more under a blind AI re-judgment (90.1 vs 77.4 %) | [rules-vs-llm.md](docs/rules-vs-llm.md) |

Every figure comes from a notebook in this repository, committed with its outputs.

---

## How it works

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Stage 1 · Geometric preprocessing                    (notebooks 02, 01)│
│  ─ Clip the OSM PBF, extract POIs and OSM building footprints           │
│  ─ Clean ALKIS 3D buildings, compute footprint area & volume            │
│  ─ Merge duplicate/overlapping polygons (POI-aware)                     │
├─────────────────────────────────────────────────────────────────────────┤
│  Stage 2 · Semantic enrichment                         (notebooks 03–05)│
│  ─ Clean OSM POIs                                                       │
│  ─ Spatial-join ALKIS function codes, OSM land use, OSM building tags   │
│  ─ Attach POIs to buildings (intersection + 100 m nearest neighbour)    │
├─────────────────────────────────────────────────────────────────────────┤
│  Stage 3 · Rule-based classification                       (notebook 06)│
│  ─ rule_utils.classify_building(), first layer that answers wins:       │
│    1. OSM POI tags   2. ALKIS function code   3. OSM building/land use  │
│  ─ Deterministic, no API calls, < 1 min for 574,435 buildings           │
├─────────────────────────────────────────────────────────────────────────┤
│  Stage 4 · Activity-informed disaggregation            (notebooks 07–08)│
│  ─ Assign buildings to traffic analysis zones                           │
│  ─ Redistribute zone totals ∝ building volume × Bosserhof weight        │
│  ─ Hierarchical fallback (zone → neighbours → study area), volume caps  │
├─────────────────────────────────────────────────────────────────────────┤
│  Evaluation                                        (notebooks 09–12, 13)│
│  ─ 09–10  score the rules against a hand-annotated sample               │
│  ─ 11–12  run the rules on the LLM pipeline's buildings, compare both   │
│  ─ 13     a new blind validation of the same places                     │
└─────────────────────────────────────────────────────────────────────────┘
```

> **Run order is 02 → 03 → 01 → 04 → 05 → 06 → 07 → 08**, not numeric: notebook 01 needs notebook 03's POIs
> ([why](docs/pipeline.md#why-the-run-order-is-not-numeric)).

---

## Quick start

```bash
git clone -b Rules-based-pipeline https://github.com/TUBS-IVS/Activities-and-Potentials-Calculation-Pipeline.git
cd Activities-and-Potentials-Calculation-Pipeline
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

pytest tests/                                           # 156 tests, no input data needed
python scripts/rule_smoke_test.py --amenity restaurant  # what do the rules say about a tag?
```

To run the full pipeline you need the input data (ALKIS buildings, an OSM extract, zone totals, land use) in
`data/input/` and the `osmium` CLI — see [docs/pipeline.md](docs/pipeline.md). Then run the notebooks in the order
above with `jupyter lab notebooks/`.

---

## Documentation

| Page | Contents |
|---|---|
| [docs/pipeline.md](docs/pipeline.md) | Installation, input data, configuration, run order and runtimes, output files, tests, adapting to a new region |
| [docs/classification.md](docs/classification.md) | How the rule engine works: the three layers, the design decisions, the activity labels, where each rule lives |
| [docs/validation.md](docs/validation.md) | Notebooks 09–10: the hand-annotated sample, how it was decoded, the scores, and the mechanisms behind the errors |
| [docs/rules-vs-llm.md](docs/rules-vs-llm.md) | Notebooks 11–12 and step 13: the rule engine and the LLM pipeline on the same buildings, against two truths |

---

## Repository structure

```
.
├── config.py                ← All settings: paths, CRS, zone columns, worker densities, activity taxonomy
├── rule_utils.py            ← The classifier: rule tables + classify_building()
├── validation_utils.py      ← Validation metrics used by notebook 10
├── requirements.txt
├── CITATION.cff
│
├── notebooks/
│   ├── 01–08_*.ipynb        ← The pipeline (run 02 → 03 → 01 → 04 → 05 → 06 → 07 → 08)
│   ├── 09_validation_ground_truth.ipynb   ← decode the annotated workbook
│   ├── 10_validation_scoring.ipynb        ← score the rules against it
│   ├── 11_rules_on_final.ipynb            ← run the rules on the LLM pipeline's buildings
│   └── 12_rules_vs_llm.ipynb              ← score rules and LLM side by side
│
├── scripts/
│   ├── rule_smoke_test.py                 ← what the rules predict for given tags / ALKIS codes
│   ├── 12_rules_vs_llm_workbook.py        ← step 12 as a place-by-place Excel workbook
│   ├── 13_new_validation_prepare.py       ← step 13: judging guide and blind batches
│   ├── 13_new_validation_review.py        ← step 13: collect judgments, write review files
│   ├── 13_new_validation_workbook.py      ← step 13: new truth, scores, workbook
│   └── nb_clean_filter.py                 ← git filter that strips editor metadata from notebooks
│
├── data/
│   ├── input/               ← your input files (not tracked)
│   ├── output/              ← pipeline outputs (not tracked)
│   ├── reference/           ← ALKIS function codelist and mapping (shipped)
│   └── validation/          ← annotated workbooks, decoded ground truth, scores (shipped)
│
├── docs/                    ← the documentation pages listed above
└── tests/                   ← pytest suite + small fixtures in tests/data/
```

---

## Data availability

The code, notebooks (with outputs), rule tables, the annotated validation sample and its scores are in this
repository. **The input data are not**: ALKIS is licensed by the state survey authority, OSM extracts are available from
[Geofabrik](https://download.geofabrik.de/), and the zone-level targets were provided by Regionalverband Großraum
Braunschweig. Two evaluation steps also read files from outside the repository:

- notebook 10 scores against the 337 MB building file the annotated sample was drawn from (too large for GitHub;
  `VALIDATION_BUILDINGS_FILE` in `config.py`) — see [why it is pinned](docs/validation.md#why-the-scored-input-is-pinned);
- notebooks 11–12 and step 13 read the outputs of the `final-pipeline` branch, checked out next to this one — see
  [setup](docs/rules-vs-llm.md#setup-final-next-to-this-repository).

Notebooks 01–08 and the tests need neither.

---

## Licence

Source code, notebooks and documentation are released under the [MIT Licence](LICENSE).

The **input data is not covered** and is not distributed here: ALKIS cadastral data is licensed by the responsible
state survey authority, OpenStreetMap extracts are © OpenStreetMap contributors under the ODbL, and the zone-level
activity targets were provided by Regionalverband Großraum Braunschweig. See [`LICENSE`](LICENSE) for details.

## Citation

If you use this software, please cite it via [`CITATION.cff`](CITATION.cff) (GitHub's "Cite this repository" button).

## Acknowledgements

This work is part of the **TRANSFORMPATHS** project, funded by the Federal Ministry of Research, Technology and Space
(BMFTR) within the framework of "Research for Sustainability" (FONA), under grant number **01UV2574A**.

The author thanks [Regionalverband Großraum Braunschweig](https://www.regionalverband-braunschweig.de/) for data
provision.

## Contact

**Mayur Patel**
Institute of Transportation and Urban Engineering, TU Braunschweig
m.patel@tu-braunschweig.de · Tel.: +49-531-391-66809
