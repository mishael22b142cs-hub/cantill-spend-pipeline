import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from cantill_pipeline.exclude import CANCELLED, DUPLICATE, NON_PROCUREMENT, NOT_APPROVED, decide, find_reversal_pairs  # noqa: E402


class TestDecide(unittest.TestCase):
    def _record(self, record_id, status_raw="", raw=None):
        return {"record_id": record_id, "status_raw": status_raw, "raw": raw or {}}

    def test_cancelled_status(self):
        src_cfg = {"status": {"cancelled_values": ["cancelled"], "include_values": ["approved", "paid"]}}
        rec = self._record("X:1", status_raw="Cancelled")
        self.assertEqual(decide(rec, src_cfg, {}, set())[:2], (False, CANCELLED))

    def test_not_approved_status(self):
        src_cfg = {"status": {"cancelled_values": ["cancelled"], "include_values": ["approved", "paid"]}}
        rec = self._record("X:1", status_raw="On Hold")
        self.assertEqual(decide(rec, src_cfg, {}, set())[:2], (False, NOT_APPROVED))

    def test_approved_included(self):
        src_cfg = {"status": {"cancelled_values": ["cancelled"], "include_values": ["approved", "paid"]}}
        rec = self._record("X:1", status_raw="Approved")
        include, reason, _ = decide(rec, src_cfg, {}, set())
        self.assertTrue(include)
        self.assertIsNone(reason)

    def test_non_procurement_keyword_rule(self):
        src_cfg = {
            "exclude_rules": [
                {"reason": NON_PROCUREMENT, "column": "gl_account_description", "equals": ["IC06"]}
            ]
        }
        rec = self._record("X:1", raw={"gl_account_description": "IC06"})
        self.assertEqual(decide(rec, src_cfg, {}, set())[:2], (False, NON_PROCUREMENT))

    def test_duplicate_from_matching(self):
        rec = self._record("TOOL:1")
        dupes = {"TOOL:1": {"duplicate_of": "ERP:1", "ambiguous": False}}
        self.assertEqual(decide(rec, {}, dupes, set())[:2], (False, DUPLICATE))

    def test_no_reason_fires_when_no_status_or_rules(self):
        rec = self._record("ERP:1")
        include, reason, _ = decide(rec, {}, {}, set())
        self.assertTrue(include)
        self.assertIsNone(reason)


class TestReversalPairs(unittest.TestCase):
    def test_offsetting_pair_is_cancelled(self):
        records = [
            {"record_id": "B1", "source_id": "B", "reversal_key": ("INV-1", "001"), "amount_parsed": -100.0},
            {"record_id": "B2", "source_id": "B", "reversal_key": ("INV-1", "001"), "amount_parsed": 100.0},
        ]
        self.assertEqual(find_reversal_pairs(records), {"B1", "B2"})

    def test_non_offsetting_pair_is_not_cancelled(self):
        records = [
            {"record_id": "B1", "source_id": "B", "reversal_key": ("INV-2", "001"), "amount_parsed": 50.0},
            {"record_id": "B2", "source_id": "B", "reversal_key": ("INV-2", "001"), "amount_parsed": 75.0},
        ]
        self.assertEqual(find_reversal_pairs(records), set())

    def test_single_record_key_is_ignored(self):
        records = [{"record_id": "B1", "source_id": "B", "reversal_key": ("INV-3", "001"), "amount_parsed": 0.0}]
        self.assertEqual(find_reversal_pairs(records), set())


if __name__ == "__main__":
    unittest.main()
