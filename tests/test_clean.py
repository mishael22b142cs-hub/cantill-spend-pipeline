import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from cantill_pipeline.clean import (  # noqa: E402
    net_of_tax, parse_amount, parse_date, parse_vat_rate, to_reporting_currency,
)


class TestParseDate(unittest.TestCase):
    def test_iso(self):
        self.assertEqual(parse_date("2024-03-29"), (date(2024, 3, 29), True))

    def test_blank_is_not_an_error(self):
        self.assertEqual(parse_date(""), (None, True))

    def test_unparseable_is_flagged(self):
        d, ok = parse_date("not-a-date")
        self.assertIsNone(d)
        self.assertFalse(ok)

    def test_iso_with_time_suffix(self):
        d, ok = parse_date("2024-03-29T00:00:00")
        self.assertEqual(d, date(2024, 3, 29))
        self.assertTrue(ok)

    def test_company_supplied_format(self):
        d, ok = parse_date("29/03/2024", extra_formats=["%d/%m/%Y"])
        self.assertEqual(d, date(2024, 3, 29))


class TestVatRate(unittest.TestCase):
    def test_bare_percent_number(self):
        self.assertAlmostEqual(parse_vat_rate("15", None), 0.15)

    def test_fraction(self):
        self.assertAlmostEqual(parse_vat_rate("0.15", None), 0.15)

    def test_percent_sign(self):
        self.assertAlmostEqual(parse_vat_rate("15%", None), 0.15)

    def test_zero(self):
        self.assertAlmostEqual(parse_vat_rate("0", None), 0.0)

    def test_blank_uses_default(self):
        self.assertAlmostEqual(parse_vat_rate("", 0.15), 0.15)
        self.assertAlmostEqual(parse_vat_rate("  ", 0.15), 0.15)


class TestNetOfTax(unittest.TestCase):
    def test_gross_strips_vat(self):
        self.assertAlmostEqual(net_of_tax(115.0, "gross", 0.15), 100.0)

    def test_net_passes_through(self):
        self.assertAlmostEqual(net_of_tax(100.0, "net", 0.15), 100.0)


class TestParseAmount(unittest.TestCase):
    def test_plain(self):
        self.assertAlmostEqual(parse_amount("104243.4"), 104243.4)

    def test_thousands_separator(self):
        self.assertAlmostEqual(parse_amount("1,234.56"), 1234.56)

    def test_blank(self):
        self.assertIsNone(parse_amount(""))

    def test_garbage(self):
        self.assertIsNone(parse_amount("n/a"))


class TestCurrencyConversion(unittest.TestCase):
    def test_same_currency_no_conversion(self):
        amount, ok = to_reporting_currency(100.0, "ZAR", "ZAR", None, None, None)
        self.assertEqual(amount, 100.0)
        self.assertTrue(ok)

    def test_inline_rate_units_per_usd(self):
        # 1507.39 HKD at (say) 7.8 HKD per USD -> ~193.26 USD
        amount, ok = to_reporting_currency(1507.39, "HKD", "USD", 7.8, None, None)
        self.assertTrue(ok)
        self.assertAlmostEqual(amount, 1507.39 / 7.8, places=4)

    def test_missing_rate_fails_gracefully(self):
        amount, ok = to_reporting_currency(100.0, "XYZ", "USD", None, None, None)
        self.assertIsNone(amount)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
