import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from cantill_pipeline.matching import find_duplicates, parse_secondary_ref  # noqa: E402


class TestParseSecondaryRef(unittest.TestCase):
    def test_slash_form(self):
        self.assertEqual(parse_secondary_ref("4510085877/10.0"), ("4510085877", "10"))

    def test_po_prefix_with_space(self):
        self.assertEqual(parse_secondary_ref("PO 4510109330"), ("4510109330", None))

    def test_po_prefix_with_hash(self):
        self.assertEqual(parse_secondary_ref("PO#4510078152"), ("4510078152", None))

    def test_bare_number(self):
        self.assertEqual(parse_secondary_ref("817386"), ("817386", None))

    def test_blank(self):
        self.assertEqual(parse_secondary_ref(""), ("", None))


class TestFindDuplicates(unittest.TestCase):
    def _record(self, source_id, record_id, match_primary_key=None, match_ref_raw=""):
        return {
            "source_id": source_id,
            "record_id": record_id,
            "match_primary_key": match_primary_key,
            "match_ref_raw": match_ref_raw,
        }

    def test_exact_po_and_item_match_is_duplicate(self):
        records = [
            self._record("ERP", "ERP:1", match_primary_key=("4510000018", "10.0")),
            self._record("TOOL", "TOOL:1", match_ref_raw="4510000018/10.0"),
        ]
        cfg = {"enabled": True, "primary_source": "ERP", "secondary_source": "TOOL"}
        dupes = find_duplicates(records, cfg)
        self.assertIn("TOOL:1", dupes)
        self.assertFalse(dupes["TOOL:1"]["ambiguous"])

    def test_po_number_only_fallback_still_matches(self):
        records = [
            self._record("ERP", "ERP:1", match_primary_key=("4510109330", "10.0")),
            self._record("TOOL", "TOOL:1", match_ref_raw="PO 4510109330"),
        ]
        cfg = {"enabled": True, "primary_source": "ERP", "secondary_source": "TOOL"}
        dupes = find_duplicates(records, cfg)
        self.assertIn("TOOL:1", dupes)

    def test_unmatched_tool_invoice_is_not_a_duplicate(self):
        records = [
            self._record("ERP", "ERP:1", match_primary_key=("4510000018", "10.0")),
            self._record("TOOL", "TOOL:1", match_ref_raw="9999999999/10.0"),
        ]
        cfg = {"enabled": True, "primary_source": "ERP", "secondary_source": "TOOL"}
        dupes = find_duplicates(records, cfg)
        self.assertNotIn("TOOL:1", dupes)

    def test_disabled_matching_returns_nothing(self):
        records = [self._record("ERP", "ERP:1"), self._record("TOOL", "TOOL:1", match_ref_raw="1/1")]
        self.assertEqual(find_duplicates(records, {"enabled": False}), {})


if __name__ == "__main__":
    unittest.main()
