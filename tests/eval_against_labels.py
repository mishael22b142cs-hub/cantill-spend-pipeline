#!/usr/bin/env python
"""Scores a pipeline run against labels_A.csv or seed_labels.csv.

Usage:
    python tests/eval_against_labels.py --config configs/company_A.yaml \
        --labels data/company_A/labels_A.csv --zero-shot-only
    python tests/eval_against_labels.py --config configs/company_A.yaml \
        --labels data/company_A/labels_A.csv --train-labels data/company_A/labels_A.csv
    python tests/eval_against_labels.py --config configs/company_B.yaml \
        --labels data/company_B/seed_labels.csv

Reports leaf/L1/L2 classification accuracy on the labelled subset, plus
pairwise-clustering F1 for supplier_key/item_key against the labels'
supplier_key/item_key when present, and exclusion accuracy when the labels
file carries include/exclusion_reason (seed_labels.csv does).
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from cantill_pipeline.pipeline import run  # noqa: E402


def load_gold(path: str) -> dict[str, dict]:
    gold = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        level_cols = sorted(
            (c for c in reader.fieldnames or [] if c.lower().startswith("category_l")),
            key=lambda c: int("".join(filter(str.isdigit, c)) or 0),
        )
        for row in reader:
            rid = row.get("record_id") or row.get("line_id")
            if rid is None:
                continue
            levels = []
            for col in level_cols:
                val = (row.get(col) or "").strip()
                if not val:
                    break
                levels.append(val)
            gold[rid] = {
                "leaf": tuple(levels),
                "supplier_key": row.get("supplier_key"),
                "item_key": row.get("item_key"),
                "include": row.get("include"),
                "exclusion_reason": row.get("exclusion_reason"),
            }
    return gold


def _n_choose_2(n: int) -> int:
    return n * (n - 1) // 2


def pairwise_f1(pred_keys: dict[str, str], gold_keys: dict[str, str]) -> tuple[float, float, float]:
    """Precision/recall/F1 of 'these two records are the same entity', the
    standard clustering-quality metric (robust to the two sides using
    completely different key names/IDs). Computed via contingency-table
    counts (not materialized pairs) so one giant cluster doesn't blow up
    memory/time."""
    ids = [i for i in gold_keys if i in pred_keys]

    gold_sizes: dict[str, int] = defaultdict(int)
    pred_sizes: dict[str, int] = defaultdict(int)
    contingency: dict[tuple[str, str], int] = defaultdict(int)
    for i in ids:
        g, p = gold_keys[i], pred_keys[i]
        gold_sizes[g] += 1
        pred_sizes[p] += 1
        contingency[(g, p)] += 1

    tp = sum(_n_choose_2(c) for c in contingency.values())
    gold_pairs = sum(_n_choose_2(n) for n in gold_sizes.values())
    pred_pairs = sum(_n_choose_2(n) for n in pred_sizes.values())

    if not pred_pairs and not gold_pairs:
        return 1.0, 1.0, 1.0
    precision = tp / pred_pairs if pred_pairs else 0.0
    recall = tp / gold_pairs if gold_pairs else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--labels", required=True, help="Gold labels file to score against")
    parser.add_argument("--train-labels", default=None, help="Labels file to TRAIN the supervised layer (omit for pure zero-shot)")
    parser.add_argument("--zero-shot-only", action="store_true")
    args = parser.parse_args()

    gold = load_gold(args.labels)
    rows, stats = run(args.config, labels_path=args.train_labels, zero_shot_only=args.zero_shot_only)

    pred_by_id = {r["record_id"]: r for r in rows}

    leaf_total = leaf_correct = l1_correct = l2_correct = 0
    pred_supplier, gold_supplier, pred_item, gold_item = {}, {}, {}, {}
    exclusion_total = exclusion_correct = 0

    for rid, g in gold.items():
        pred = pred_by_id.get(rid)
        if pred is None:
            continue
        # blank gold key means the labeller made no claim for this row (e.g.
        # labels_A leaves item_key blank whenever there's no material code) -
        # skip it rather than scoring ourselves against an undefined cluster.
        if g["supplier_key"]:
            pred_supplier[rid] = pred["supplier_key"]
            gold_supplier[rid] = g["supplier_key"]
        if g["item_key"]:
            pred_item[rid] = pred["item_key"]
            gold_item[rid] = g["item_key"]

        if g["include"] is not None:
            exclusion_total += 1
            pred_include = str(pred["include"])
            gold_include = (g["include"] or "1").strip()
            if pred_include == gold_include:
                exclusion_correct += 1

        if not g["leaf"]:
            continue
        pred_leaf = tuple(x for x in (pred["l1"], pred["l2"], pred["l3"], pred["l4"]) if x)
        leaf_total += 1
        if pred_leaf == g["leaf"]:
            leaf_correct += 1
        if pred_leaf and g["leaf"] and pred_leaf[0] == g["leaf"][0]:
            l1_correct += 1
        if len(pred_leaf) >= 2 and len(g["leaf"]) >= 2 and pred_leaf[:2] == g["leaf"][:2]:
            l2_correct += 1

    mode = "zero-shot (no labels used)" if args.zero_shot_only or not args.train_labels else f"supervised (trained on {args.train_labels})"
    print(f"=== {args.config} scored against {args.labels} | classifier mode: {mode} ===")
    print(f"runtime: {stats['runtime_seconds']:.2f}s for {stats['n_records']} records")
    if leaf_total:
        print(f"leaf accuracy:  {leaf_correct}/{leaf_total} = {leaf_correct/leaf_total:.3f}")
        print(f"L1  accuracy:   {l1_correct}/{leaf_total} = {l1_correct/leaf_total:.3f}")
        print(f"L1+L2 accuracy: {l2_correct}/{leaf_total} = {l2_correct/leaf_total:.3f}")
    if exclusion_total:
        print(f"include/exclude accuracy: {exclusion_correct}/{exclusion_total} = {exclusion_correct/exclusion_total:.3f}")

    if gold_supplier:
        sp, sr, sf1 = pairwise_f1(pred_supplier, gold_supplier)
        print(f"supplier clustering: precision={sp:.3f} recall={sr:.3f} F1={sf1:.3f} (n={len(gold_supplier)})")
    else:
        print("supplier clustering: n/a (labels file has no supplier_key)")
    if gold_item:
        ip, ir, if1 = pairwise_f1(pred_item, gold_item)
        print(f"item clustering:     precision={ip:.3f} recall={ir:.3f} F1={if1:.3f} (n={len(gold_item)})")
    else:
        print("item clustering:     n/a (labels file has no item_key)")


if __name__ == "__main__":
    main()
