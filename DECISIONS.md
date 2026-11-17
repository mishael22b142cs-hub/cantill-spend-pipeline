# Decisions

What we found in the data and what we assumed, in the order it came up.

## Company A

**ERP goods receipts are always spend; only the invoice-tool file has a status gate.** All 37,029
ERP rows are present with a category in `labels_A.csv` (zero blank categories), and SAP posts a
goods receipt only once goods have actually been received, so we treat every ERP row as spend
unless it is a `DUPLICATE` of something counted via the invoice tool. 434 ERP rows have a negative
`value_zar` (returns/credits); we keep them as negative spend rather than excluding them, since
`labels_A` categorizes them too.

**PO reference matching.** `invoice_tool_export.csv`'s `po_reference` shows up in at least five
shapes typed/exported differently: `"4510085877/10.0"`, `"PO 4510109330"`, `"PO#4510078152"`,
bare `"817386"`, and blank (18% of rows — likely non-PO service invoices). We normalize by
stripping a `PO`/`PO#` prefix and splitting on `/` into `(po_number, po_item)`, then join against
ERP's own `po_number`/`po_item`. When the tool reference has no item number, we fall back to
matching on `po_number` alone against any ERP line under that PO (`matching.py`). This is an
approximation — a multi-line PO could match the wrong specific line — but it is the conservative
direction for the brief's actual ask ("count each real purchase once"): under-matching would
double-count spend, which is worse than an occasional imprecise match. We flag these as
`ambiguous` internally and give them a lower exclusion-decision confidence (0.6 vs 1.0).

**VAT rate parsing.** `vat_rate` appears as `"15"`, `"0.15"`, `"15%"`, `"0"`, and blank. We strip a
trailing `%`, and treat any resulting value `>= 1` as a percentage (divide by 100); blank uses the
brief's 15% default. (`clean.parse_vat_rate`)

**Status.** Only `Approved`/`Paid` count; `Cancelled` → `CANCELLED`; `On Hold`/`Rejected` →
`NOT_APPROVED` (matches the brief's examples exactly: 188 cancelled, 172 on hold + 143 rejected =
315 not-approved, out of 28,520 tool rows).

## Company B

**No approval-status column exists in `invoice_lines.csv`.** We looked for one and there isn't
one — `document_type` (PV/RE/CA/Z6/...) doesn't cleanly separate approved-vs-not (e.g. `CA` rows
have both zero and large positive amounts, so it isn't a reliable "cancelled" flag either). We
therefore cannot apply a `NOT_APPROVED` filter for B/C-like files with this shape; the only
exclusion signals available are account-based (`NON_PROCUREMENT`) and data-driven cancellation
(below). This is a genuine gap, not an oversight — flagged here rather than silently assumed away.

**Cancellation via offsetting pairs.** With no status column, we detect cancelled/reversed postings
by grouping rows that share `(invoice_number, invoice_line)` and checking whether exactly two rows
share that key with amounts netting to ~0 (e.g. `B000001`/`B000002`, both invoice `B-INV-1000001`
line `001`, amounts `-13827.64`/`+13827.64`). 70 such pairs (140 rows) were found this way.

**NON_PROCUREMENT accounts.** `gl_account_description` contains clearly intercompany values
(`IC06`, `IC Payables`, `I/C Payable`, `IC05`, `IC67`, `IC22`, `IC37`, `IC23`) and FX/financing
values (`FXW`, `F2WU`, `F1W`), versus clearly-trade-payable values (`AP - Other`, `AP - Metal`,
`AP - Freight`, `Trade Creditor`, `TRADE PAYABLE NATIONAL`/`EXPORT`, ...). Many other
`gl_account_description` values are short cryptic codes (`PEUS`, `P106`, `PMXN`, ...) that look like
they were anonymized along with everything else in this dataset — we only excluded the codes we
could read a clear meaning from, declared as an explicit `equals` list in `configs/company_B.yaml`
(not a code change), rather than guessing at the cryptic ones.

**`material_number` is not a reliable item identifier for B.** It's blank for 10,574/41,028 rows and
`'MAT-1000007'` alone covers another 10,484 rows that are otherwise unrelated items — it reads as a
filler/placeholder, not a real material code. `dedup_item.py` detects this automatically (a code
reused across many distinct description texts is "unreliable" and ignored) rather than hardcoding
that one value, so the same logic would catch an equivalent placeholder in company C.

**Classification signal for blank descriptions.** 16,695/41,028 rows (41%) have a blank
`line_description`. We add `gl_account_description` as a second text column feeding the classifier
(`configs/company_B.yaml`) purely because it's often weakly informative (e.g. `"AP - Freight"`) —
this cut the share of zero-confidence classifications roughly in half. It's a config change, not a
code change, so it generalizes: any company whose primary description column is sparse can list a
second column the same way.

## Supplier de-duplication

We prioritize the system's own vendor/supplier ID over fuzzy name matching whenever one exists,
and only fuzzy-cluster by normalized name when there's no ID at all (`dedup_supplier.py`). This
matters for A specifically: `labels_A`'s own golden `supplier_key` for the ~56% of ERP rows with a
**blank** `vendor_id` turns out to be one single giant bucket covering well over 100 completely
unrelated company names (confirmed by inspection — `SG-f85711` alone spans `OAKENT MINING`,
`DUNBROOK STEEL`, `IVESMORE POWER`, etc.). That's a data-quality artifact of A's own ERP (a generic
placeholder vendor used when the receipt wasn't linked to a vendor master record), not evidence
that those are the same real supplier. We deliberately do not replicate it — doing so would mean
merging unrelated suppliers whenever an ID happens to be missing, which would be wrong for B (no
names, ID always present) and for an unseen company C. This shows up as capped recall in our own
`pairwise_f1` check against `labels_A` (precision stays 1.000 — we never wrongly merge two
differently-named real companies) — see APPROACH.md.

## Item de-duplication

`labels_A.item_key` is blank for every one of the 15,816 ERP rows with no `material_number` — i.e.
the golden labels don't attempt to group free-text/service items at all, they only key off the
material code. Our tool still assigns those rows a real item_key (a normalized, token-sorted
signature of the description text), because the output format has no "blank item_key" option and
free-text/service lines are still real, distinct items that a procurement head would want grouped.
Our self-measured item-clustering accuracy (see APPROACH.md) is computed only over the rows where
`labels_A` actually defines a grouping, to avoid penalizing ourselves against an undefined target.

## Output semantics

- `confidence` for an **excluded** row is our confidence in the *exclusion decision*, not a
  category confidence (there's no category to be confident about): 1.0 for an explicit status/
  account match, 0.9 for the algorithmic reversal-pair/keyword detections, 1.0 for an exact
  PO-number+item duplicate match, 0.6 for an ambiguous PO-number-only duplicate match.
- `confidence` for an **included** row is the classifier's own score (see APPROACH.md for what
  that means in zero-shot vs. supervised mode).
- FX conversion (B/C) falls back to the nearest available month in `fx_rates_usd.csv` for the same
  currency when the exact invoice month is missing from the table, rather than failing the line.
