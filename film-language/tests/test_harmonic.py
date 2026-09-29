import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py"))

from dual_lattice import CER_FS, CER_K, CER_N, CER_T, DualLattice, LatticeMode
from harmonic import H, lattice_for, rfft_mag, rms_peaks, sequence_index, sequences_for_duration
from tokens import TRACK_COUNT, TRACK_ROLES

try:
    import numpy as np
except ImportError:
    np = None


class Sequences(unittest.TestCase):
    def test_six_cover_duration(self):
        T = 35.39
        seq = sequences_for_duration(T)
        self.assertEqual(len(seq), TRACK_COUNT)
        self.assertEqual([s["role"] for s in seq], list(TRACK_ROLES))
        self.assertAlmostEqual(seq[0]["t0"], 0.0)
        self.assertAlmostEqual(seq[-1]["t1"], T, places=5)
        for i in range(1, 6):
            self.assertAlmostEqual(seq[i]["t0"], seq[i - 1]["t1"], places=5)

    def test_sequence_index_edges(self):
        self.assertEqual(sequence_index(0, 12), 0)
        self.assertEqual(sequence_index(11.9, 12), 5)
        self.assertEqual(sequence_index(12, 12), 5)

    def test_fib_weights_sum_one(self):
        seq = sequences_for_duration(10)
        self.assertAlmostEqual(sum(s["F"] for s in seq), 1.0, places=6)


class Dual(unittest.TestCase):
    def test_cer_residual(self):
        d = DualLattice(fs=CER_FS, fps=30000 / 1001)
        r = d.residual_at_claimed(CER_T, K_claimed=CER_K, N_claimed=CER_N)
        self.assertGreater(r.epsilon_sec, 0.015)
        self.assertLess(r.epsilon_sec, 0.025)

    def test_audio_master_lock(self):
        d = DualLattice(fs=48000, fps=30.0, mode=LatticeMode.AUDIO_MASTER)
        d.advance_audio(4800)
        self.assertAlmostEqual(d.audio.t, 0.1)
        self.assertLess(abs(d.residual().epsilon_sec), 1e-5)

    def test_lattice_for_keys(self):
        lat = lattice_for(2.0, fs=48000, fps=30.0, k_claimed=60)
        self.assertEqual(lat["N"], 96000)
        self.assertEqual(lat["K"], 60)
        self.assertIn("epsilon_sec", lat)


@unittest.skipIf(np is None, "numpy required")
class FftVertices(unittest.TestCase):
    def test_rfft_normalized(self):
        t = np.linspace(0, 1, 48000, endpoint=False)
        x = np.sin(2 * math.pi * 440 * t)
        mag = rfft_mag(x, bins=64)
        self.assertEqual(len(mag), 64)
        self.assertAlmostEqual(max(mag), 1.0, places=5)

    def test_rms_peaks_on_burst(self):
        fs = 8000
        x = np.concatenate([
            np.zeros(fs),
            0.9 * np.sin(2 * math.pi * 220 * np.arange(fs) / fs),
            np.zeros(fs),
        ])
        peaks = rms_peaks(x, fs, hop=256, win=512)
        self.assertTrue(peaks)
        ts = [p["t"] for p in peaks]
        self.assertTrue(any(0.8 < t < 2.2 for t in ts))

    def test_H_finite(self):
        mag = [0.5] * 8
        v = H(0.3, 6.0, mag)
        self.assertTrue(math.isfinite(v))


if __name__ == "__main__":
    unittest.main()
