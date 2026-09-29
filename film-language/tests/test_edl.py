import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py"))

from splice import splice_edl


def _have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") and shutil.which("ffprobe")


def _probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return float(r.stdout.strip() or 0)


@unittest.skipUnless(_have_ffmpeg(), "ffmpeg required")
class Splice(unittest.TestCase):
    def test_two_clips_duration(self):
        td = tempfile.mkdtemp(prefix="film-edl-")
        try:
            a = Path(td) / "a.mp4"
            b = Path(td) / "b.mp4"
            out = Path(td) / "out.mp4"
            for dest, freq in ((a, 440), (b, 660)):
                subprocess.check_call([
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-i", f"sine=frequency={freq}:duration=1",
                    "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
                    "-shortest", "-c:v", "libx264", "-c:a", "aac", str(dest),
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            edl = {
                "output": str(out),
                "clips": [
                    {"source": str(a), "in": 0.0, "out": 0.4},
                    {"source": str(b), "in": 0.0, "out": 0.4},
                ],
            }
            splice_edl(edl, reencode=True)
            self.assertTrue(out.is_file())
            dur = _probe_duration(out)
            self.assertGreater(dur, 0.55)
            self.assertLess(dur, 1.05)
        finally:
            shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
