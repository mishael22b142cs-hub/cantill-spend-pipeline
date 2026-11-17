"""One supplier_key per real supplier, however its name is typed.

When a source has no supplier name at all (company B: only vendor_id),
supplier_key is just the vendor_id - it is already an atomic, de-duplicated
identifier, nothing to cluster.

When a name is available (company A), we normalize it (strip legal
suffixes/punctuation/case) and union near-duplicates whose normalized names
share enough tokens, using union-find over a token index so the cost stays
roughly linear instead of comparing every pair.
"""
from __future__ import annotations

import re
from collections import defaultdict

_LEGAL_SUFFIXES = [
    r"\(PTY\)\s*LTD", r"\(PROPRIETARY\)\s*LIMITED", r"PROPRIETARY LIMITED",
    r"\(PTY\)", r"PTY LTD", r"PTY", r"LIMITED", r"LTD", r"LLC", r"INC",
    r"CORP(ORATION)?", r"CO\.?,?\s*LTD", r"GMBH", r"S\.?A\.?", r"B\.?V\.?",
    r"N\.?V\.?",
]
_SUFFIX_RE = re.compile(r"\b(" + "|".join(_LEGAL_SUFFIXES) + r")\b", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^A-Z0-9 ]")
_WS_RE = re.compile(r"\s+")


def normalize_supplier_name(name: str) -> str:
    name = (name or "").upper()
    name = _SUFFIX_RE.sub(" ", name)
    name = _PUNCT_RE.sub(" ", name)
    name = _WS_RE.sub(" ", name).strip()
    return name


class _UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _tokens(name: str) -> set[str]:
    return {t for t in name.split(" ") if len(t) > 2}


def assign_supplier_keys(
    records: list[dict], name_field: str = "supplier_name_raw", id_field: str = "supplier_id_raw",
    token_match_threshold: float = 0.6,
) -> dict[str, str]:
    """Returns {record_id: supplier_key}.

    A system-assigned vendor/supplier ID is the client's own master-data
    key and is far more reliable than fuzzy name matching, so it wins
    whenever present (company B has only IDs, no names at all; company A
    has both, and most ERP rows do carry a real vendor_id). Fuzzy name
    clustering is the fallback for the remaining rows that have a name but
    no ID (company A: receipts posted without a vendor master link) - each
    of those still needs its own grouping by real-world identity, it just
    can't ride on an ID.
    """
    keys: dict[str, str] = {}
    normalized_by_record: dict[str, str] = {}

    for rec in records:
        vendor_id = (rec.get(id_field) or "").strip()
        if vendor_id:
            keys[rec["record_id"]] = f"VID-{vendor_id}"
            continue
        name = (rec.get(name_field) or "").strip()
        if not name:
            keys[rec["record_id"]] = "UNKNOWN-SUPPLIER"
            continue
        normalized_by_record[rec["record_id"]] = normalize_supplier_name(name)

    if not normalized_by_record:
        return keys

    uf = _UnionFind()
    token_index: dict[str, list[str]] = defaultdict(list)
    seen_norms: dict[str, str] = {}  # normalized name -> canonical normalized name already unioned
    for rid, norm in normalized_by_record.items():
        uf.find(norm)
        if norm in seen_norms:
            continue
        seen_norms[norm] = norm
        toks = _tokens(norm)
        candidate_norms = set()
        for t in toks:
            candidate_norms.update(token_index[t])
        for other in candidate_norms:
            other_toks = _tokens(other)
            if not toks or not other_toks:
                continue
            jaccard = len(toks & other_toks) / len(toks | other_toks)
            if jaccard >= token_match_threshold:
                uf.union(norm, other)
        for t in toks:
            token_index[t].append(norm)

    for rid, norm in normalized_by_record.items():
        root = uf.find(norm)
        keys[rid] = f"SUP-{root}" if root else "UNKNOWN-SUPPLIER"

    return keys
