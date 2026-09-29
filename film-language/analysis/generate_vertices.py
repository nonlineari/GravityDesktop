#!/usr/bin/env python3
"""Print 6-sequence windows + RMS vertices for one media file."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py"))

from indexer import index_file


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: generate_vertices.py <media>", file=sys.stderr)
        return 2
    side = index_file(Path(sys.argv[1]))
    doc = json.loads(side.read_text())
    print("sequences", json.dumps(doc["sequences"], indent=2))
    print("vertices", len(doc["vertices"]))
    for v in doc["vertices"][:12]:
        print(f"  t={v['t']:.3f}  rms={v['rms_db']}  bin={v['fft_bin']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
