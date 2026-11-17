"""End-to-end orchestration: ingest -> match -> clean -> exclude -> dedup ->
classify -> output rows. One function, `run`, used by both run.py (the CLI)
and tests/eval_against_labels.py (which also wants the in-memory rows).
"""
from __future__ import annotations

import csv
import time
from typing import Any

from . import classify, dedup_item, dedup_supplier, exclude, matching
from .clean import FxTable, net_of_tax, parse_amount, parse_date, parse_vat_rate, to_reporting_currency
from .config import load_config, resolve
from .ingest import load_all_sources

OUTPUT_COLUMNS = [
    "record_id", "include", "exclusion_reason", "supplier_key", "item_key",
    "spend", "l1", "l2", "l3", "l4", "confidence",
]


def _clean_records(records: list[dict], cfg: dict) -> FxTable:
    fx_path = cfg.get("fx", {}).get("rate_table_file")
    fx_table = FxTable(resolve(cfg, fx_path) if fx_path else None)
    reporting_currency = cfg["reporting_currency"]

    for rec in records:
        amount = parse_amount(rec["amount_raw"])
        vat_rate = parse_vat_rate(rec["vat_rate_raw"], rec["vat_rate_default"])
        net_amount = net_of_tax(amount, rec["amount_kind"], vat_rate) if amount is not None else None

        date_parsed, date_ok = parse_date(rec["date_raw"], rec["date_formats"])
        month = date_parsed.strftime("%Y-%m") if date_parsed else None

        inline_rate = None
        if rec.get("fx_rate_raw"):
            try:
                inline_rate = float(rec["fx_rate_raw"])
            except ValueError:
                inline_rate = None

        currency = rec["currency_raw"] or rec["currency_default"] or reporting_currency
        if net_amount is not None:
            converted, fx_ok = to_reporting_currency(
                net_amount, currency, reporting_currency, inline_rate, fx_table, month,
            )
        else:
            converted, fx_ok = None, True

        rec["amount_parsed"] = amount
        rec["date_parsed"] = date_parsed
        rec["date_ok"] = date_ok
        rec["spend_candidate"] = converted if converted is not None else 0.0
        rec["fx_ok"] = fx_ok and (net_amount is None or converted is not None)
    return fx_table


def _apply_exclusions(records: list[dict], cfg: dict) -> None:
    reversal_ids = exclude.find_reversal_pairs(records, amount_field="amount_parsed")
    duplicates = matching.find_duplicates(records, cfg.get("matching", {}))
    for rec in records:
        include, reason, conf = exclude.decide(rec, rec["source_cfg"], duplicates, reversal_ids)
        rec["include"] = include
        rec["exclusion_reason"] = reason
        rec["decision_confidence"] = conf
        rec["spend"] = rec["spend_candidate"] if include else 0.0


def _apply_dedup(records: list[dict], cfg: dict) -> None:
    supplier_keys = dedup_supplier.assign_supplier_keys(records)
    item_fallback_cols = cfg.get("classification", {}).get("item_fallback_columns", ["source_id"])
    item_keys = dedup_item.assign_item_keys(records, fallback_fields=item_fallback_cols)
    for rec in records:
        rec["supplier_key"] = supplier_keys.get(rec["record_id"], "UNKNOWN-SUPPLIER")
        rec["item_key"] = item_keys.get(rec["record_id"], "ITEM-UNKNOWN")


def _apply_classification(
    records: list[dict], cfg: dict, labels: dict[str, tuple[str, ...]] | None, zero_shot_only: bool,
) -> dict:
    taxonomy_path = resolve(cfg, cfg["taxonomy_file"])
    leaves = classify.load_taxonomy(taxonomy_path)
    max_depth = max((len(leaf) for leaf in leaves), default=3)

    included = [rec for rec in records if rec["include"]]
    texts = [rec["description"] for rec in included]

    train_texts = train_leaves = None
    if labels and not zero_shot_only:
        train_texts, train_leaves = [], []
        for rec in included:
            leaf = labels.get(rec["record_id"])
            if leaf:
                train_texts.append(rec["description"])
                train_leaves.append(leaf)
        if len(train_texts) < 10:
            train_texts = train_leaves = None

    predictions = classify.classify_records(texts, leaves, train_texts, train_leaves)

    for rec, (leaf, score, mode) in zip(included, predictions):
        rec["category_leaf"] = leaf
        rec["category_confidence"] = score
        rec["category_mode"] = mode

    for rec in records:
        if not rec["include"]:
            rec["category_leaf"] = ()
            rec["category_confidence"] = rec["decision_confidence"]
            rec["category_mode"] = "excluded"

    return {"max_depth": max_depth, "n_leaves": len(leaves), "n_trained_on": len(train_texts or [])}


def to_output_row(rec: dict, max_depth: int) -> dict:
    leaf = rec.get("category_leaf") or ()
    levels = list(leaf) + [""] * (max_depth - len(leaf))
    levels = levels[:max_depth]
    while len(levels) < 4:
        levels.append("")
    row = {
        "record_id": rec["record_id"],
        "include": 1 if rec["include"] else 0,
        "exclusion_reason": rec["exclusion_reason"] or "",
        "supplier_key": rec["supplier_key"],
        "item_key": rec["item_key"],
        "spend": round(rec["spend"], 2),
        "l1": levels[0], "l2": levels[1], "l3": levels[2], "l4": levels[3],
        "confidence": round(rec.get("category_confidence", 0.0), 4),
    }
    return row


def run(
    config_path: str,
    labels_path: str | None = None,
    zero_shot_only: bool = False,
    out_path: str | None = None,
) -> tuple[list[dict], dict]:
    t0 = time.time()
    cfg = load_config(config_path)
    records = load_all_sources(cfg)

    _clean_records(records, cfg)
    _apply_exclusions(records, cfg)
    _apply_dedup(records, cfg)

    labels = None
    if labels_path:
        labels = _load_labels(labels_path)

    stats = _apply_classification(records, cfg, labels, zero_shot_only)
    stats["runtime_seconds"] = time.time() - t0
    stats["n_records"] = len(records)
    stats["n_included"] = sum(1 for r in records if r["include"])
    stats["total_spend"] = sum(r["spend"] for r in records)

    rows = [to_output_row(rec, stats["max_depth"]) for rec in records]

    if out_path:
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    return rows, stats


def _load_labels(path: str) -> dict[str, tuple[str, ...]]:
    """Reads a labels file (labels_A.csv or seed_labels.csv shape) into
    {record_id: leaf_path_tuple}. record_id in these files is the bare
    ERP/B line_id; the caller's config record_id_prefix must be applied by
    whoever built the file, so we try both the raw id and common prefixes."""
    labels: dict[str, tuple[str, ...]] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        level_cols = sorted(
            (c for c in reader.fieldnames or [] if c.lower().startswith("category_l")),
            key=lambda c: int("".join(filter(str.isdigit, c)) or 0),
        )
        for row in reader:
            if "include" in row and row["include"] not in ("1", "", None):
                if row["include"] not in ("1", 1):
                    continue
            levels = []
            for col in level_cols:
                val = (row.get(col) or "").strip()
                if not val:
                    break
                levels.append(val)
            if not levels:
                continue
            rid = row["record_id"] if "record_id" in row else row.get("line_id")
            if rid is None:
                continue
            for candidate in (rid, f"ERP:{rid}", rid):
                labels[candidate] = tuple(levels)
    return labels
