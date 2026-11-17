#!/usr/bin/env python
"""One-command CLI entry point.

    python run.py --config configs/company_A.yaml --out out/mishael__A.csv
    python run.py --config configs/company_A.yaml --labels data/company_A/labels_A.csv --out out/mishael__A.csv
    python run.py --config configs/company_A.yaml --zero-shot-only --out out/mishael__A_zeroshot.csv
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from cantill_pipeline.pipeline import run  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Cantill spend pipeline & classifier")
    parser.add_argument("--config", required=True, help="Path to a company YAML/JSON config")
    parser.add_argument("--labels", default=None, help="Optional labels file to train the supervised classifier layer (never required)")
    parser.add_argument("--zero-shot-only", action="store_true", help="Ignore --labels; classify using the tree alone")
    parser.add_argument("--out", required=True, help="Output CSV path")
    args = parser.parse_args()

    rows, stats = run(args.config, labels_path=args.labels, zero_shot_only=args.zero_shot_only, out_path=args.out)

    print(f"wrote {len(rows)} rows to {args.out}")
    print(
        f"included={stats['n_included']}/{stats['n_records']} "
        f"total_spend={stats['total_spend']:,.2f} "
        f"trained_on={stats['n_trained_on']} leaves "
        f"runtime={stats['runtime_seconds']:.2f}s"
    )


if __name__ == "__main__":
    main()
