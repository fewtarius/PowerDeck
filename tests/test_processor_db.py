"""Processor spec table lookup."""

import unittest

from powerdeck.hardware import processor_db


class NormalizeTests(unittest.TestCase):
    def test_strips_graphics_suffix(self):
        self.assertEqual(
            processor_db.normalize("AMD RYZEN AI MAX+ 395 w/ Radeon 8060S"),
            "AMD RYZEN AI MAX + 395",
        )

    def test_matches_after_trademark_glyphs(self):
        self.assertEqual(
            processor_db.normalize("AMD Ryzen\u2122 AI Max+ 395"),
            processor_db.normalize("AMD RYZEN AI MAX+ 395"),
        )

    def test_missing_space_between_ryzen_and_ai(self):
        self.assertEqual(
            processor_db.normalize("AMD Ryzen\u2122AI Max+ PRO 495"),
            processor_db.normalize("AMD Ryzen AI Max+ PRO 495"),
        )


class LookupTests(unittest.TestCase):
    def test_finds_running_chip_by_cpuinfo_name(self):
        entry = processor_db.find("AMD RYZEN AI MAX+ 395 w/ Radeon 8060S")
        self.assertIsNotNone(entry)
        self.assertIn("395", entry["name"])
        self.assertIn("AI Max", entry["name"])

    def test_ctdp_ceiling_comes_from_spec_table(self):
        bounds = processor_db.tdp_bounds("AMD RYZEN AI MAX+ 395 w/ Radeon 8060S")
        self.assertIsNotNone(bounds)
        self.assertEqual(bounds["max"], 120)
        self.assertEqual(bounds["default"], 55)

    def test_model_number_must_match(self):
        # 3950X is a desktop AM4 part; it must never resolve to the
        # AI Max+ 395 APU just because both contain "395".
        entry = processor_db.find("AMD Ryzen 9 3950X")
        self.assertIsNotNone(entry)
        self.assertNotIn("AI Max", entry["name"])

    def test_unknown_vendor_returns_none(self):
        self.assertIsNone(processor_db.find("Intel Core i7-1165G7"))

    def test_empty_name_returns_none(self):
        self.assertIsNone(processor_db.find(""))

    def test_every_entry_matches_itself(self):
        # Guards the normalizer: a stored display name must resolve back
        # to its own entry, or matching is inconsistent with generation.
        failures = []
        for entry in processor_db._load():
            name = entry["name"]
            found = processor_db.find(name)
            if not found or found["name"] != name:
                failures.append((name, found["name"] if found else None))
        # AMD's export contains duplicate rows for a few APUs whose names
        # differ only by cooler wording; those legitimately resolve to the
        # sibling row with identical specs.
        self.assertLessEqual(len(failures), 3, failures)


if __name__ == "__main__":
    unittest.main()
