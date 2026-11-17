"""Decide what counts as spend. Every excluded record gets exactly one
reason code from the brief: CANCELLED, NOT_APPROVED, NON_PROCUREMENT,
DUPLICATE. Priority when more than one could apply: CANCELLED first (a
cancelled/reversed line was never real spend, regardless of anything else),
then NOT_APPROVED, then NON_PROCUREMENT (account-level classification of the
whole line), then DUPLICATE (a counting decision, checked last).
"""
from __future__ import annotations

from collections import defaultdict

CANCELLED = "CANCELLED"
NOT_APPROVED = "NOT_APPROVED"
NON_PROCUREMENT = "NON_PROCUREMENT"
DUPLICATE = "DUPLICATE"


def find_reversal_pairs(records: list[dict], amount_field: str = "amount_parsed") -> set[str]:
    """Data-driven cancellation detection for sources with no status column
    (company B): group records sharing the same reversal_key (e.g.
    invoice_number + invoice_line); when exactly two share a key and their
    raw amounts net to ~0, both are a posting and its reversal."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for rec in records:
        key = rec.get("reversal_key")
        if key and all(key):
            groups[(rec["source_id"], key)].append(rec)

    cancelled_ids: set[str] = set()
    for _, group in groups.items():
        if len(group) != 2:
            continue
        amounts = [r.get(amount_field) for r in group]
        if any(a is None for a in amounts):
            continue
        if abs(sum(amounts)) < 0.01 and any(abs(a) > 0.0001 for a in amounts):
            cancelled_ids.update(r["record_id"] for r in group)
    return cancelled_ids


def _matches_rule(raw_row: dict, rule: dict) -> bool:
    value = (raw_row.get(rule["column"]) or "").strip()
    if "equals" in rule:
        return value.upper() in {v.upper() for v in rule["equals"]}
    if "contains" in rule:
        value_lower = value.lower()
        return any(token.lower() in value_lower for token in rule["contains"])
    return False


def decide(
    record: dict,
    src_cfg: dict,
    duplicates: dict[str, dict],
    reversal_cancelled_ids: set[str],
) -> tuple[bool, str | None, float]:
    """Returns (include, exclusion_reason, decision_confidence). The
    decision_confidence is our confidence in the *exclusion* decision for
    excluded rows (classification confidence takes over for included rows);
    see DECISIONS.md."""
    if record["record_id"] in reversal_cancelled_ids:
        return False, CANCELLED, 0.9  # algorithmic (amounts net to ~0), not an explicit status

    status_cfg = src_cfg.get("status")
    status_raw = (record.get("status_raw") or "").strip().lower()
    if status_cfg:
        cancelled_values = {v.lower() for v in status_cfg.get("cancelled_values", [])}
        include_values = {v.lower() for v in status_cfg.get("include_values", [])}
        if status_raw in cancelled_values:
            return False, CANCELLED, 1.0
        if status_raw not in include_values:
            return False, NOT_APPROVED, 1.0

    for rule in src_cfg.get("exclude_rules", []):
        if rule.get("reason") == NON_PROCUREMENT and _matches_rule(record["raw"], rule):
            return False, NON_PROCUREMENT, 0.9

    dup = duplicates.get(record["record_id"])
    if dup:
        return False, DUPLICATE, 0.6 if dup.get("ambiguous") else 1.0

    return True, None, 1.0
