import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from cantill_pipeline.dedup_item import assign_item_keys, normalize_description  # noqa: E402
from cantill_pipeline.dedup_supplier import assign_supplier_keys, normalize_supplier_name  # noqa: E402


class TestSupplierNormalization(unittest.TestCase):
    def test_strips_legal_suffix_and_punctuation(self):
        a = normalize_supplier_name("Oakent Mining SA (Pty) Ltd")
        b = normalize_supplier_name("OAKENT MINING SA (PTY) LTD")
        self.assertEqual(a, b)

    def test_vendor_id_wins_over_name(self):
        records = [
            {"record_id": "1", "supplier_id_raw": "V200009", "supplier_name_raw": "Yarvex"},
            {"record_id": "2", "supplier_id_raw": "V200009", "supplier_name_raw": "YARVEX (PTY) LTD"},
            {"record_id": "3", "supplier_id_raw": "", "supplier_name_raw": "Completely Different Co"},
        ]
        keys = assign_supplier_keys(records)
        self.assertEqual(keys["1"], keys["2"])
        self.assertNotEqual(keys["1"], keys["3"])

    def test_similar_names_without_id_are_clustered(self):
        records = [
            {"record_id": "1", "supplier_id_raw": "", "supplier_name_raw": "Kinora Industrial Supplies Engineering"},
            {"record_id": "2", "supplier_id_raw": "", "supplier_name_raw": "Kinora  Industrial Supplies Engineering"},
        ]
        keys = assign_supplier_keys(records)
        self.assertEqual(keys["1"], keys["2"])

    def test_no_id_no_name_is_unknown(self):
        records = [{"record_id": "1", "supplier_id_raw": "", "supplier_name_raw": ""}]
        self.assertEqual(assign_supplier_keys(records)["1"], "UNKNOWN-SUPPLIER")


class TestItemDedup(unittest.TestCase):
    def test_normalize_description_strips_punctuation_and_case(self):
        self.assertEqual(normalize_description("VALVE;P/N:A2U90-694075"), "valve p n a2u90 694075")

    def test_item_key_ignores_word_order_and_punctuation(self):
        records = [
            {"record_id": "1", "codes_raw": [], "description": "VALVE;P/N:A2U90-694075"},
            {"record_id": "2", "codes_raw": [], "description": "a2u90 694075 p n valve"},
        ]
        keys = assign_item_keys(records)
        self.assertEqual(keys["1"], keys["2"])

    def test_reliable_code_wins(self):
        records = [
            {"record_id": str(i), "codes_raw": ["M1000001"], "description": "FAN ELEC 22KW"}
            for i in range(6)
        ]
        keys = assign_item_keys(records)
        self.assertEqual(len(set(keys.values())), 1)
        self.assertTrue(list(keys.values())[0].startswith("ITEM-CODE-"))

    def test_junk_placeholder_code_falls_back_to_description(self):
        records = [
            {"record_id": "1", "codes_raw": ["MAT-JUNK"], "description": "valve ball 2 inch"},
            {"record_id": "2", "codes_raw": ["MAT-JUNK"], "description": "lubricant oil 20l"},
            {"record_id": "3", "codes_raw": ["MAT-JUNK"], "description": "steel roof bolt"},
            {"record_id": "4", "codes_raw": ["MAT-JUNK"], "description": "gasket rubber seal"},
            {"record_id": "5", "codes_raw": ["MAT-JUNK"], "description": "welding rod 3mm"},
            {"record_id": "6", "codes_raw": ["MAT-JUNK"], "description": "safety gloves pair"},
        ]
        keys = assign_item_keys(records)
        self.assertEqual(len(set(keys.values())), 6)
        self.assertTrue(all(v.startswith("ITEM-DESC-") for v in keys.values()))

    def test_blank_description_and_code_falls_back_to_unknown_bucket(self):
        records = [{"record_id": "1", "codes_raw": [], "description": "", "raw": {"vendor_id": "V1"}}]
        keys = assign_item_keys(records, fallback_fields=["vendor_id"])
        self.assertTrue(keys["1"].startswith("ITEM-UNKNOWN-"))


if __name__ == "__main__":
    unittest.main()
