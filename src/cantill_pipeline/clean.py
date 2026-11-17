"""Amount, VAT, date and currency cleaning. Pure functions, no I/O, so they
are easy to unit-test against every format variant found during EDA.
"""
from __future__ import annotations

import csv
import re
from datetime import date, datetime

# Every date format actually observed (or plausible) across A and B.
_DATE_FORMATS_DEFAULT = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%m/%d/%Y",
    "%d.%m.%Y",
    "%Y%m%d",
]


def parse_date(raw: str, extra_formats: list[str] | None = None) -> tuple[date | None, bool]:
    """Returns (parsed_date_or_None, ok). ok is False when raw was non-empty
    but could not be parsed by any known format (should be flagged, not
    silently dropped)."""
    raw = (raw or "").strip()
    if not raw:
        return None, True  # blank date: not an error, just missing
    formats = (extra_formats or []) + _DATE_FORMATS_DEFAULT
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date(), True
        except ValueError:
            continue
    # last-resort: ISO-ish prefix e.g. "2024-03-29T00:00:00"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), True
        except ValueError:
            pass
    return None, False


def parse_vat_rate(raw: str, default: float | None) -> float:
    """Handles '15', '0.15', '15%', '0', blank. Blank -> default (A's rule:
    15% when the rate is blank)."""
    raw = (raw or "").strip()
    if not raw:
        return default if default is not None else 0.0
    raw = raw.rstrip("%")
    try:
        value = float(raw)
    except ValueError:
        return default if default is not None else 0.0
    # '15' means 15%, '0.15' already a fraction. Treat >=1 as a percentage.
    if value >= 1:
        value = value / 100.0
    return value


def parse_amount(raw: str) -> float | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    raw = raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def net_of_tax(amount: float, kind: str, vat_rate: float) -> float:
    """kind: 'net' (already net, return as-is) or 'gross' (strip VAT)."""
    if kind == "gross":
        return amount / (1.0 + vat_rate)
    return amount


def _month_key(month: str) -> tuple[int, int] | None:
    m = re.match(r"^(\d{4})-(\d{2})$", month or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


class FxTable:
    """Monthly currency -> units-per-USD lookup, e.g. fx_rates_usd.csv. Falls
    back to the nearest available month for the same currency when the exact
    month is missing (invoices can post in a month the rate file skipped)."""

    def __init__(self, path: str | None):
        self.rates: dict[tuple[str, str], float] = {}
        self.months_by_currency: dict[str, list[str]] = {}
        if not path:
            return
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                currency = row["currency"].strip().upper()
                month = row["month"].strip()
                try:
                    rate = float(row["units_per_usd"])
                except (KeyError, ValueError):
                    continue
                self.rates[(currency, month)] = rate
                self.months_by_currency.setdefault(currency, []).append(month)

    def units_per_usd(self, currency: str, month: str) -> float | None:
        currency = currency.strip().upper()
        exact = self.rates.get((currency, month))
        if exact is not None:
            return exact
        available = self.months_by_currency.get(currency)
        target = _month_key(month)
        if not available or target is None:
            return None
        best_month = min(
            available,
            key=lambda m: abs(
                (_month_key(m) or (9999, 9999))[0] * 12 + (_month_key(m) or (9999, 9999))[1]
                - (target[0] * 12 + target[1])
            ),
        )
        return self.rates.get((currency, best_month))


def to_reporting_currency(
    amount: float,
    currency: str,
    reporting_currency: str,
    inline_rate_units_per_usd: float | None,
    fx_table: FxTable | None,
    month: str | None,
) -> tuple[float | None, bool]:
    """Returns (converted_amount_or_None, ok).

    `reporting_currency` is either the company's native currency (A: ZAR,
    with amounts already in ZAR, no conversion needed) or USD (B/C), in
    which case `inline_rate_units_per_usd` (B's `currency_rate`, "units of
    the line currency per 1 USD") is used when present, else a monthly
    lookup in `fx_table`.
    """
    currency = (currency or reporting_currency or "").strip().upper()
    if currency == reporting_currency.strip().upper() or not currency:
        return amount, True
    rate = inline_rate_units_per_usd
    if not rate and fx_table and month:
        rate = fx_table.units_per_usd(currency, month)
    if not rate:
        return None, False
    # rate = units of `currency` per 1 USD -> USD = amount_in_currency / rate
    return amount / rate, True
