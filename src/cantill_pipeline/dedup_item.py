"""One item_key per real item, where different codes or descriptions mean
the same thing.

Strategy:
  1. If a record has a code (material_number etc.) that is *reliable* - i.e.
     in this dataset that code is consistently associated with one item, not
     reused across many unrelated descriptions as a junk/placeholder value
     (company B's invoice_lines.csv reuses 'MAT-1000007' as a filler on
     ~10,000 unrelated rows) - use the code as the key.
  2. Otherwise, normalize the description (lowercase, strip units/punctuation,
     drop stopword-ish noise, sort the remaining tokens) and use that
     canonical token signature as the key, so word-order/typo variants of
     the same item collapse together.
  3. If there is neither a usable code nor any description text, fall back to
     a per-(fallback columns) "unknown item" bucket instead of merging every
     blank-description row into one giant item.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

_PUNCT_RE = re.compile(r"[;,:/\\\-_.()\[\]]+")
_WS_RE = re.compile(r"\s+")
_UNIT_TOKENS = {
    "ea", "pc", "pcs", "kg", "mm", "cm", "m", "l", "ml", "no", "nr", "set",
    "unit", "units", "x", "qty",
}


def normalize_description(text: str) -> str:
    text = (text or "").lower()
    text = _PUNCT_RE.sub(" ", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def _signature(text: str) -> str:
    norm = normalize_description(text)
    tokens = [t for t in norm.split(" ") if t and t not in _UNIT_TOKENS]
    if not tokens:
        return ""
    return " ".join(sorted(set(tokens)))


def _reliable_codes(
    records: list[dict], code_field: str, desc_field: str, max_distinct_signatures: int = 3,
    min_occurrences_to_judge: int = 5,
) -> set[str]:
    """A code is 'reliable' if, across this dataset, it maps to a small
    number of distinct description signatures (real items occasionally get
    re-described, but a junk/placeholder code gets reused across hundreds of
    unrelated items)."""
    code_to_signatures: dict[str, Counter] = defaultdict(Counter)
    for rec in records:
        codes = rec.get("codes_raw") or []
        if not codes:
            continue
        code = codes[0]
        sig = _signature(rec.get(desc_field, ""))
        if sig:
            code_to_signatures[code][sig] += 1

    reliable = set()
    for code, sigs in code_to_signatures.items():
        total = sum(sigs.values())
        if total < min_occurrences_to_judge:
            reliable.add(code)  # not enough evidence either way; trust it
            continue
        if len(sigs) <= max_distinct_signatures:
            reliable.add(code)
    return reliable


def assign_item_keys(
    records: list[dict], desc_field: str = "description", code_field: str = "codes_raw",
    fallback_fields: list[str] | None = None,
) -> dict[str, str]:
    fallback_fields = fallback_fields or []
    reliable_codes = _reliable_codes(records, code_field, desc_field)

    keys: dict[str, str] = {}
    for rec in records:
        codes = rec.get(code_field) or []
        code = codes[0] if codes else None
        if code and code in reliable_codes:
            keys[rec["record_id"]] = f"ITEM-CODE-{code}"
            continue

        sig = _signature(rec.get(desc_field, ""))
        if sig:
            keys[rec["record_id"]] = f"ITEM-DESC-{sig}"
            continue

        fallback_parts = [str(rec.get(f) or rec.get("raw", {}).get(f, "")) for f in fallback_fields]
        fallback_key = "|".join(p for p in fallback_parts if p) or "NONE"
        keys[rec["record_id"]] = f"ITEM-UNKNOWN-{fallback_key}"

    return keys
