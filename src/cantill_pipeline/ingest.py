"""Read each source file declared in a company config into a list of plain
dict "records" with a normalized set of keys. Every bit of company-specific
knowledge (which column is what) lives in the config, not here.
"""
from __future__ import annotations

import csv
from typing import Any

from .config import resolve


def _get(row: dict, column: str | None) -> str:
    if not column:
        return ""
    return (row.get(column) or "").strip()


def _join_columns(row: dict, columns: list[str] | None) -> str:
    if not columns:
        return ""
    parts = [_get(row, c) for c in columns]
    return " ".join(p for p in parts if p)


def load_source(cfg: dict[str, Any], src: dict[str, Any]) -> list[dict]:
    path = resolve(cfg, src["path"])
    records = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rid = _get(row, src["id_column"])
            record = {
                "source_id": src["id"],
                "record_id": f"{src['record_id_prefix']}{rid}",
                "raw": row,
                "raw_id": rid,
                "amount_raw": _get(row, src["amount"]["column"]),
                "amount_kind": src["amount"].get("kind", "net"),
                "vat_rate_raw": _get(row, src["amount"].get("vat_rate_column")),
                "vat_rate_default": src["amount"].get("vat_rate_default"),
                "currency_raw": _get(row, src.get("currency", {}).get("column")),
                "currency_default": src.get("currency", {}).get("default"),
                "date_raw": _get(row, src["date"]["column"]),
                "date_formats": src["date"].get("formats", []),
                "supplier_id_raw": _get(row, src.get("supplier", {}).get("id_column")),
                "supplier_name_raw": _get(row, src.get("supplier", {}).get("name_column")),
                "description": _join_columns(row, src.get("description_columns")),
                "codes_raw": [_get(row, c) for c in src.get("code_columns", []) if _get(row, c)],
                "status_raw": _get(row, (src.get("status") or {}).get("column")),
                "source_cfg": src,
            }
            # fields used by matching.py (A: ERP po_number/po_item, TOOL po_reference)
            match_cfg = src.get("match", {})
            record["match_primary_key"] = tuple(
                _get(row, c) for c in match_cfg.get("primary_key_columns", [])
            ) or None
            record["match_ref_raw"] = _get(row, match_cfg.get("ref_column"))

            # fields used for data-driven reversal/cancellation detection
            reversal_cols = src.get("reversal_key_columns")
            if reversal_cols:
                record["reversal_key"] = tuple(_get(row, c) for c in reversal_cols)
            else:
                record["reversal_key"] = None

            # currency conversion helper fields (B: currency_rate column, fx lookup by month)
            fx_src_cfg = src.get("fx", {})
            record["fx_rate_raw"] = _get(row, fx_src_cfg.get("rate_column"))
            record["fx_date_raw"] = record["date_raw"]

            records.append(record)
    return records


def load_all_sources(cfg: dict[str, Any]) -> list[dict]:
    all_records: list[dict] = []
    for src in cfg["sources"]:
        all_records.extend(load_source(cfg, src))
    return all_records
