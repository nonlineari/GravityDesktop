"""Klipp av: ffmpeg splice from an EDL. Stream-copy when possible."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise FileNotFoundError("ffmpeg")
    return exe


def splice_edl(edl: Dict[str, Any], reencode: bool = False) -> Path:
    clips: List[Dict[str, Any]] = edl.get("clips") or []
    if not clips:
        raise ValueError("EDL has no clips")
    out = Path(edl["output"])
    out.parent.mkdir(parents=True, exist_ok=True)
    ff = _ffmpeg()
    with tempfile.TemporaryDirectory(prefix="film-splice-") as td:
        lst = Path(td) / "concat.txt"
        lines = []
        for c in clips:
            src = Path(c["source"]).resolve()
            t0 = float(c["in"])
            t1 = float(c["out"])
            if t1 <= t0:
                continue
            lines.append(f"file '{src.as_posix()}'")
            lines.append(f"inpoint {t0:.6f}")
            lines.append(f"outpoint {t1:.6f}")
        if not lines:
            raise ValueError("no usable clip extents")
        lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cmd_copy = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)]
        cmd_enc = [
            ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", str(out),
        ]
        use = cmd_enc if reencode else cmd_copy
        r = subprocess.run(use, capture_output=True, text=True)
        if r.returncode != 0 and not reencode:
            r = subprocess.run(cmd_enc, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-2000:] if r.stderr else "ffmpeg splice failed")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="film-language splice")
    p.add_argument("--edl", required=True)
    p.add_argument("--reencode", action="store_true")
    args = p.parse_args(argv)
    edl = json.loads(Path(args.edl).read_text(encoding="utf-8"))
    path = splice_edl(edl, reencode=args.reencode)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
