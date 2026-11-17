"""Cross-system record matching: when a company has two systems (A: SAP
goods receipts + the AP invoice tool), find which secondary-system records
are really the same purchase as a primary-system record, so the purchase is
counted once (via the primary record) and the secondary copy is excluded as
DUPLICATE.

PO references show up in several typed-by-hand/export shapes in the tool
file: "4510085877/10.0", "PO 4510109330", "PO#4510078152", "817386" (bare).
We normalize all of them to (po_number, po_item_or_None) and join against
the ERP's own (po_number, po_item).
"""
from __future__ import annotations

import re
from collections import defaultdict

_PO_PREFIX_RE = re.compile(r"^\s*PO\s*#?\s*", re.IGNORECASE)


def normalize_po_number(raw: str) -> str:
    raw = (raw or "").strip()
    raw = _PO_PREFIX_RE.sub("", raw)
    return raw.split("/")[0].strip()


def normalize_po_item(raw: str) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return str(int(round(float(raw))))
    except ValueError:
        return raw


def parse_secondary_ref(raw: str) -> tuple[str, str | None]:
    raw = (raw or "").strip()
    raw = _PO_PREFIX_RE.sub("", raw)
    if "/" in raw:
        po_num, po_item = raw.split("/", 1)
        return po_num.strip(), normalize_po_item(po_item)
    return raw.strip(), None


def find_duplicates(records: list[dict], matching_cfg: dict) -> dict[str, dict]:
    """Returns {secondary_record_id: {"duplicate_of": erp_record_id, "ambiguous": bool}}
    for every secondary record that matches a primary record."""
    if not matching_cfg.get("enabled"):
        return {}

    primary_id = matching_cfg["primary_source"]
    secondary_id = matching_cfg["secondary_source"]

    primary_by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
    primary_by_number: dict[str, list[str]] = defaultdict(list)

    for rec in records:
        if rec["source_id"] != primary_id:
            continue
        key = rec.get("match_primary_key")
        if not key or not key[0]:
            continue
        po_num = normalize_po_number(key[0])
        po_item = normalize_po_item(key[1]) if len(key) > 1 else None
        if po_item:
            primary_by_key[(po_num, po_item)].append(rec["record_id"])
        primary_by_number[po_num].append(rec["record_id"])

    result: dict[str, dict] = {}
    for rec in records:
        if rec["source_id"] != secondary_id:
            continue
        ref_raw = rec.get("match_ref_raw")
        if not ref_raw:
            continue
        po_num, po_item = parse_secondary_ref(ref_raw)
        if not po_num:
            continue
        candidates = []
        if po_item and (po_num, po_item) in primary_by_key:
            candidates = primary_by_key[(po_num, po_item)]
        elif po_num in primary_by_number:
            candidates = primary_by_number[po_num]
        if candidates:
            result[rec["record_id"]] = {
                "duplicate_of": candidates[0],
                "ambiguous": len(candidates) > 1,
            }
    return result
