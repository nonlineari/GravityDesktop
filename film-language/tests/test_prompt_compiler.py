import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py"))

from prompt_compiler import compile_edl, tokens_from_prompt


class Compiler(unittest.TestCase):
    def test_tokens(self):
        toks = tokens_from_prompt("cut POV where /θ/ hits ILL(T)")
        joined = " ".join(toks)
        self.assertIn("ipa:θ", joined)
        self.assertIn("yolo:POV_IMAGE", joined)
        self.assertIn("track:ILL(T)", joined)

    def test_edl_from_doc(self):
        doc = {
            "source": "/tmp/clip.mp4",
            "vertices": [{"t": 1.2, "kind": "alpha"}],
            "shots": [{
                "t0": 1.0, "t1": 2.4, "glyph": "helix_cut",
                "yolo": [{"class": "POV_IMAGE", "conf": 0.95}],
                "ocr": [], "ipa": ["θ"], "visemes": ["dental"], "role": "ILL(T)",
            }],
        }
        edl = compile_edl("cut POV where /θ/ hits ILL(T)", [doc], out_id="testedl")
        self.assertTrue(edl["clips"])
        self.assertAlmostEqual(edl["clips"][0]["in"], 1.0)
        self.assertAlmostEqual(edl["clips"][0]["out"], 2.4)
        self.assertTrue(edl["edl_path"].endswith("testedl.json"))


if __name__ == "__main__":
    unittest.main()
