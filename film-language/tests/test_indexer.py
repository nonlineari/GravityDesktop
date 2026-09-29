import math
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py"))

try:
    import numpy as np
except ImportError:
    np = None

from tokens import TRACK_COUNT


@unittest.skipIf(np is None, "numpy required")
class IndexerWav(unittest.TestCase):
    def test_index_sine_wav(self):
        from indexer import index_file
        import json
        td = tempfile.TemporaryDirectory()
        wav = Path(td.name) / "sine.wav"
        fs, T = 8000, 1.2
        x = (0.4 * np.sin(2 * math.pi * 440 * np.arange(int(fs * T)) / fs)).astype(np.int16)
        # scale to int16
        x = (0.4 * np.sin(2 * math.pi * 440 * np.arange(int(fs * T)) / fs))
        pcm = (x * 32767).astype(np.int16)
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(fs)
            w.writeframes(pcm.tobytes())
        side = index_file(wav)
        doc = json.loads(side.read_text())
        self.assertEqual(len(doc["sequences"]), TRACK_COUNT)
        self.assertEqual(len(doc["lattice"]["fft_in"]), 64)
        self.assertAlmostEqual(doc["sequences"][-1]["t1"], T, delta=0.05)
        td.cleanup()


if __name__ == "__main__":
    unittest.main()
