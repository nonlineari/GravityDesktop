import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py"))

from phonetic import parse_ipa_token, to_arpabet, to_ipa
from viseme import viseme_of, visemes_of


class IpaRoundtrip(unittest.TestCase):
    def test_th(self):
        self.assertEqual(to_ipa("TH"), "θ")
        self.assertEqual(to_arpabet("θ"), "TH")

    def test_stress_strip(self):
        self.assertEqual(to_ipa("AH0"), "ʌ")

    def test_parse_token(self):
        self.assertEqual(parse_ipa_token("ipa:/θ/"), "θ")
        self.assertEqual(parse_ipa_token("/θ/"), "θ")
        self.assertEqual(parse_ipa_token("θ"), "θ")

    def test_viseme_dental(self):
        self.assertEqual(viseme_of("θ"), "dental")
        self.assertIn("dental", visemes_of(["θ", "ə"]))


if __name__ == "__main__":
    unittest.main()
