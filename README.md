# Cantill spend pipeline & classifier

Takes a company's raw purchase data and its category tree, combines and cleans the data, decides
what counts as spend, de-duplicates suppliers and items, and classifies every line into the
company's category tree — driven entirely by a per-company config file, with no company- or
category-specific logic in the code.

## Setup

```
pip install -r requirements.txt
```

Only two dependencies: `pyyaml` (config files) and `scikit-learn` (TF-IDF + logistic regression
for classification; pulls in `numpy`/`scipy`). No pandas, no GPU, no API keys, no network access.

Place the task's data files under `data/` (gitignored, never committed — see "Data" below):

```
data/company_A/erp_goods_receipts.csv
data/company_A/invoice_tool_export.csv
data/company_A/labels_A.csv
data/company_A/taxonomy_A.csv
data/company_B/invoice_lines.csv
data/company_B/fx_rates_usd.csv
data/company_B/seed_labels.csv
data/company_B/taxonomy_B.csv
```

## The one command

```
python run.py --config configs/company_A.yaml --labels data/company_A/labels_A.csv --out outputs/mishael__A.csv
python run.py --config configs/company_B.yaml --labels data/company_B/seed_labels.csv --out outputs/mishael__B.csv
```

`--labels` is optional and only ever used to train the supervised classification layer (see
APPROACH.md) — it is never required. Omit it, or pass `--zero-shot-only`, to classify purely from
the taxonomy file, e.g. for an unseen company:

```
python run.py --config submission/company_C.yaml --out submission/mishael__C.csv
```

Both companies (65,549 + 41,028 = 106,577 records combined) run end to end, classification
included, in well under a minute on a laptop — see APPROACH.md for measured runtimes.

## Running a new company

Write a new YAML config under `configs/` (or anywhere, and pass its path) describing: the input
file(s) and how they join, which column is the amount/currency/date/supplier/description/status,
VAT handling, FX handling, and any exclusion rules you can see in that company's own account codes.
`configs/company_B.yaml` is the simplest example (single file, no cross-system matching);
`configs/company_A.yaml` shows the two-system case. No code changes are needed for a new company.

## Tests

```
python -m unittest discover -s tests
```

51 unit tests covering date/VAT/currency parsing, PO-reference matching, exclusion-reason logic,
supplier/item de-duplication, and the classifier — no extra dependencies beyond the two above.

To measure accuracy against a labels file (what produced the numbers in APPROACH.md):

```
python tests/eval_against_labels.py --config configs/company_A.yaml --labels data/company_A/labels_A.csv --zero-shot-only
python tests/eval_against_labels.py --config configs/company_A.yaml --labels data/company_A/labels_A.csv --train-labels data/company_A/labels_A.csv
python tests/eval_against_labels.py --config configs/company_B.yaml --labels data/company_B/seed_labels.csv
```

## Data

The task's CSVs are confidential and are **not** committed (see `.gitignore`). Everything the
tool needs to run is in `configs/*.yaml`, `src/`, `run.py`, and `requirements.txt`.

## AI tools used

Built with Claude Code (Anthropic) as a pair-programming/build assistant. The shipped tool itself
makes no LLM API calls — classification is local TF-IDF/logistic-regression, zero cost, no keys
required (see APPROACH.md for why, and the accuracy trade-off that implies).

## Repo layout

```
configs/                 company_A.yaml, company_B.yaml (submission/company_C.yaml added at blind test)
src/cantill_pipeline/     ingest, clean, matching, exclude, dedup_supplier, dedup_item, classify, pipeline
run.py                    CLI entry point
tests/                    unit tests + eval_against_labels.py
out/                      scratch/ad-hoc output CSVs (gitignored)
outputs/                  the two required build-deadline deliverables: mishael__A.csv, mishael__B.csv (committed)
APPROACH.md, DECISIONS.md
```
