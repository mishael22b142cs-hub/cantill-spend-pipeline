import csv
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from cantill_pipeline.classify import classify_records, load_taxonomy  # noqa: E402

LEAVES = [
    ("Mining Operating Materials", "Roof Bolts", "Roof Bolts"),
    ("Mining Operating Materials", "Mining Explosives", "Mining Explosives"),
    ("Facilities", "Electrical", "Electrical Motors"),
]


class TestLoadTaxonomy(unittest.TestCase):
    def test_reads_variable_depth_csv(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["category_l1", "category_l2", "category_l3", "category_l4"])
            writer.writerow(["Direct Materials", "Aluminium", "Ingot", ""])
            writer.writerow(["Direct Materials", "Aluminium", "Ingot", ""])  # duplicate
            writer.writerow(["Packaging", "Pallets", "", ""])
            path = f.name
        try:
            leaves = load_taxonomy(path)
            self.assertIn(("Direct Materials", "Aluminium", "Ingot"), leaves)
            self.assertIn(("Packaging", "Pallets"), leaves)
            self.assertEqual(len(leaves), 2)  # de-duplicated
        finally:
            os.unlink(path)


class TestZeroShotClassification(unittest.TestCase):
    def test_lexically_obvious_line_goes_to_the_right_leaf(self):
        texts = ["ROOF BOLT STEEL 10MM", "MINING EXPLOSIVE DETONATOR"]
        results = classify_records(texts, LEAVES)
        self.assertEqual(results[0][0], LEAVES[0])
        self.assertEqual(results[1][0], LEAVES[1])
        self.assertEqual(results[0][2], "zero_shot")

    def test_confidence_is_in_unit_range(self):
        results = classify_records(["ELECTRICAL MOTOR"], LEAVES)
        self.assertGreaterEqual(results[0][1], 0.0)
        self.assertLessEqual(results[0][1], 1.0)


class TestSupervisedBlend(unittest.TestCase):
    def test_uses_supervised_when_labels_given(self):
        train_texts = ["GENERIC PART A"] * 20 + ["GENERIC PART B"] * 20
        train_leaves = [LEAVES[0]] * 20 + [LEAVES[1]] * 20
        results = classify_records(["GENERIC PART A"], LEAVES, train_texts, train_leaves)
        self.assertEqual(results[0][2], "supervised")

    def test_falls_back_to_zero_shot_without_labels(self):
        results = classify_records(["ROOF BOLT"], LEAVES, None, None)
        self.assertEqual(results[0][2], "zero_shot")


if __name__ == "__main__":
    unittest.main()
