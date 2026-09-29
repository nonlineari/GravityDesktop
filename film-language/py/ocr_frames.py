"""Tesseract OCR on ffmpeg keyframes. Empty list if tools missing."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List


def _have(*names: str) -> bool:
    return all(shutil.which(n) for n in names)


def ocr_at_times(media: Path, times: List[float]) -> List[str]:
    if not media.is_file() or not times or not _have("ffmpeg", "tesseract"):
        return []
    found: List[str] = []
    with tempfile.TemporaryDirectory(prefix="film-ocr-") as td:
        for i, t in enumerate(times):
            png = Path(td) / f"k{i:03d}.png"
            r = subprocess.run(
                [
                    "ffmpeg", "-y", "-ss", f"{max(t, 0):.3f}", "-i", str(media),
                    "-frames:v", "1", "-q:v", "3", str(png),
                ],
                capture_output=True, text=True,
            )
            if r.returncode != 0 or not png.is_file():
                continue
            out_base = Path(td) / f"o{i:03d}"
            subprocess.run(
                ["tesseract", str(png), str(out_base), "-l", "eng", "--psm", "6"],
                capture_output=True, text=True,
            )
            txt = Path(str(out_base) + ".txt")
            if txt.is_file():
                line = txt.read_text(encoding="utf-8", errors="replace").strip()
                if line:
                    found.append(line)
    return found
