import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py"))

from search import parse_query, score_shot, search_doc
from tokens import SCORE_THRESHOLD


def _doc():
    shot = {
        "t0": 1.0,
        "t1": 2.0,
        "glyph": "helix_cut",
        "camera": "C",
        "yolo": [{"class": "POV_IMAGE", "conf": 0.95}],
        "ocr": [],
        "ipa": ["θ", "ə"],
        "visemes": ["dental"],
        "role": "ILL(T)",
    }
    return {
        "source": "/tmp/clip.mp4",
        "vertices": [{"t": 1.2, "rms_db": -20.0, "fft_bin": 4, "kind": "alpha"}],
        "shots": [shot],
    }


class Fuse(unittest.TestCase):
    def test_parse_ipa_and_yolo(self):
        q = parse_query("ipa:θ yolo:POV_IMAGE glyph:helix_cut")
        self.assertEqual(q["ipa"], ["θ"])
        self.assertEqual(q["yolo"], ["POV_IMAGE"])
        self.assertEqual(q["glyph"], ["helix_cut"])

    def test_bare_pov_maps_yolo(self):
        q = parse_query("cut POV where /θ/ hits ILL(T)")
        self.assertIn("θ", q["ipa"])
        self.assertIn("POV_IMAGE", q["yolo"])
        self.assertIn("ILL(T)", q["track"])

    def test_theta_pov_beats_threshold(self):
        doc = _doc()
        hits = search_doc(doc, "ipa:θ yolo:POV_IMAGE")
        self.assertTrue(hits)
        self.assertGreaterEqual(hits[0]["score"], SCORE_THRESHOLD)

    def test_missing_ipa_does_not_crash(self):
        doc = _doc()
        doc["shots"][0]["ipa"] = []
        doc["shots"][0]["visemes"] = []
        hits = search_doc(doc, "yolo:POV_IMAGE")
        self.assertTrue(hits)

    def test_score_channels(self):
        shot = _doc()["shots"][0]
        sc, parts = score_shot(
            shot,
            {"ipa": ["θ"], "yolo": ["POV_IMAGE"], "ocr": [], "glyph": ["helix_cut"], "track": [], "camera": []},
            True,
        )
        self.assertEqual(parts["ipa"], 1.0)
        self.assertEqual(parts["yolo"], 1.0)
        self.assertGreaterEqual(sc, SCORE_THRESHOLD)


if __name__ == "__main__":
    unittest.main()
