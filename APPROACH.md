# Approach

## Pipeline

One YAML config per company (`configs/*.yaml`) declares every piece of company-specific knowledge:
which files exist and how they join, which column is amount/currency/date/supplier/description/
status/PO-reference/GL-account, VAT and FX handling, and any account-level exclusion keywords found
by inspection. No company or category name appears anywhere in `src/`. Stages (`src/cantill_pipeline/`):

1. **ingest.py** — read each source file per config into a normalized record shape.
2. **matching.py** — for a two-system company (A), normalize PO references and join ERP↔tool
   records so each real purchase is counted once.
3. **clean.py** — parse dates (multi-format + regex fallback), strip VAT off gross amounts, convert
   to the reporting currency (inline rate, or the monthly FX table with nearest-month fallback).
4. **exclude.py** — status gate, cancellation (explicit status + data-driven offsetting-pair
   detection for files with no status column), account-keyword `NON_PROCUREMENT` rules, `DUPLICATE`
   from matching — exactly one reason code per excluded row, with a decision confidence.
5. **dedup_supplier.py / dedup_item.py** — one key per real supplier/item (see below).
6. **classify.py** — zero-shot TF-IDF-vs-tree-text, optionally blended with a supervised layer.
7. **pipeline.py / run.py** — orchestration and the `output_template.csv`-shaped CSV writer.

## Matching & de-duplication

**Cross-system matching (A):** normalize `po_reference`'s several typed shapes (`NUM/NUM`,
`PO NUM`, `PO#NUM`, bare `NUM`) into `(po_number, po_item)` and join against the ERP's own PO
fields; a match → the tool row is `DUPLICATE`, the ERP row carries the spend. Falls back to a
po_number-only match (lower confidence) when the tool reference has no item number.

**Suppliers:** prefer the system's own vendor/supplier ID when one exists (exact, no fuzzy logic
needed — this is also company B's *only* option, since it has no supplier names at all); fall back
to normalized-name + token-Jaccard clustering (union-find) only when no ID is present. See
DECISIONS.md for why we deliberately don't replicate `labels_A`'s blank-vendor_id "catch-all"
bucket.

**Items:** prefer a material/item code, but only if it's *reliable* — a code reused across many
unrelated description texts in that dataset (company B's placeholder `material_number`) is detected
automatically and ignored in favor of a normalized, token-sorted description signature. Blank
description + no usable code falls into a per-(configurable fallback column) "unknown item" bucket
instead of being force-merged with everything else.

## Classification into an unseen tree

Two layers, selected automatically per record:

- **Zero-shot** (needs only the taxonomy file, zero labels): concatenate each leaf's level names
  into one text blob, TF-IDF vectorize both that tree corpus and the line's cleaned text — word
  bigrams for lexical overlap, character 3–5-grams for abbreviation/typo tolerance — and take the
  leaf with the highest cosine similarity as both the prediction and the confidence. This is the
  **only** layer available for company C, and the one used for the "classify A from its tree alone"
  test below.
- **Supervised** (only when a labels file is supplied, e.g. for A2/B2): TF-IDF + logistic regression
  trained on that company's own labelled text → leaf. Used whenever its confidence clears a floor;
  falls back to zero-shot otherwise.

No LLM API is used anywhere in the shipped tool — **cost per 1,000 lines: $0**. We considered an
optional LLM pass on low-confidence lines (would likely help the hardest, short/abbreviated/
non-English lines in an unseen tree) but decided against it: it would require API-key plumbing and
a documented fallback for a grading run with no key, for a gain that's hard to size in advance,
versus a fully local tool that is simpler to verify, debug, and run unattended.

## Accuracy measured on A (labels hidden) and B

`python tests/eval_against_labels.py ...` (see README):

| | A — zero-shot only (no labels) | A — supervised (trained on `labels_A`) |
|---|---|---|
| leaf accuracy | 13.6% | **89.0%** |
| L1 accuracy | 40.9% | 95.1% |
| L1+L2 accuracy | 19.3% | 90.7% |

| | B — zero-shot only | B — supervised (trained on `seed_labels`, 3,000 noisy rows) |
|---|---|---|
| leaf accuracy | 28.8% | **82.5%** |
| L1 accuracy | 47.6% | 84.8% |
| include/exclude accuracy | 95.5% (same both modes — exclusion doesn't use the classifier) | 95.5% |

Supplier/item clustering against `labels_A` (pairwise precision/recall/F1 — robust to the two sides
using different key spellings): supplier **precision 1.000**, recall 0.084 (capped by the
blank-vendor_id artifact explained in DECISIONS.md — on the ~44% of rows with a real `vendor_id` our
key matches the master-data ID exactly); item **precision 1.000, recall 0.366, F1 0.536** (computed
only over the subset where `labels_A` defines a grouping at all — see DECISIONS.md). We read
precision=1.000 in both as the more important number here: the tool never incorrectly merges two
different real suppliers or items, which matters more for a spend cube than maximizing recall
against an artifact of the client's own data quality.

The real-world takeaway: zero-shot lexical similarity alone gets roughly 1-in-7 (A) to 1-in-3.5 (B)
leaf categories exactly right with zero supervision, and over 40% of top-level categories right —
a reasonable floor for company C, where this is the only mode available. Whenever labels exist
(A2, B2), the supervised layer lifts leaf accuracy to ~83–89%.

## Runtime

Full pipeline, classification included, on real files, end to end via `python run.py`:

- Company A (37,029 + 28,520 = 65,549 combined records): ~20–30s.
- Company B (41,028 records): ~9–25s.

(The spread per company is almost entirely one-time `sklearn`/`numpy`/`scipy` import cost on cold
Python-process start, not the pipeline logic itself — the classifier stage, timed in isolation
inside the process, is sub-second to a few seconds for either mode.) Both are far under the brief's
60-minutes-for-25,000-lines budget — no network calls, no GPU.
