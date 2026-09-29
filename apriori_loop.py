#!/usr/bin/env python3
"""Reset Gravity tesseract/tetragrammaton to the a priori looping mind.

Finite: 16 tesseract vertices (2^4), 11 IDC composition steps (hierarchy).
Infinite: Gray-code walk wraps (Escher stairs). One bit-flip = one Duchamp frame.
Man Ray: each vertex is a still. Temporal code: t_loop.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import sigma9

IDC = list("⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻⿰")  # 11 composition operators → 11D
TETRA = ("Y", "H", "W", "H")  # tetragrammaton → tesseract x,y,z,t
SIGMA9 = sigma9.sigma()
DIMS = ("x", "y", "z", "t")
XDG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "gravity-desktop"
OUT = XDG / "apriori_loop.json"
HERE = Path(__file__).resolve().parent / "apriori_loop.json"


def gray4() -> list:
    """Binary-reflected Gray code, 4 bits: Hamiltonian cycle on the tesseract."""
    walk = []
    for i in range(16):
        g = i ^ (i >> 1)
        walk.append([(g >> d) & 1 for d in range(4)])
    return walk


def cycle_next(vertex) -> list:
    walk = gray4()
    v = list(vertex)
    for i, p in enumerate(walk):
        if p == v:
            return walk[(i + 1) % 16]
    return walk[0]


def idc_level(level: int) -> str:
    """Hierarchy 11→1 maps onto IDC 0→10."""
    if level < 1 or level > 11:
        return IDC[0]
    return IDC[11 - level]


def document() -> dict:
    walk = gray4()
    return {
        "schema": "gravity.apriori-loop.v1",
        "mind": "finite/infinite",
        "temporal": "t_loop",
        "tetragrammaton": list(TETRA),
        "sigma9": {"deriv": list(sigma9.DERIV), "sigma": SIGMA9, "max": sigma9.MAX},
        "tesseract_dims": list(DIMS),
        "idc": IDC,
        "hierarchy": {str(lvl): idc_level(lvl) for lvl in range(11, 0, -1)},
        "vertex_origin": [0, 0, 0, 0],
        "vertex_walk": walk,
        "walk_closes": walk[0] == [0, 0, 0, 0] and cycle_next(walk[-1]) == walk[0],
        "a_priori": {
            "escher": "Ascending and Descending — 16-step Gray walk wraps",
            "duchamp": "Nude Descending a Staircase — one bit-flip per frame",
            "man_ray": "rayograph — each vertex is a finite photographic take",
        },
        "local_vertex": walk[0],
        "tesseract_id": "apriori-loop",
    }


def reset() -> Path:
    XDG.mkdir(parents=True, exist_ok=True)
    doc = document()
    OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    HERE.write_text(json.dumps({k: doc[k] for k in (
        "schema", "mind", "temporal", "tetragrammaton", "sigma9", "tesseract_dims", "idc", "a_priori"
    )}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return OUT


def main(argv=None) -> int:
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "reset"
    if cmd in ("reset", "write"):
        path = reset()
        doc = json.loads(path.read_text(encoding="utf-8"))
        print("gravity tesseract tetragrammaton → a priori t_loop")
        print("  mind: finite 16 vertices / infinite Gray wrap (Escher)")
        print("  stair: Duchamp one-bit descent  ·  Man Ray still = vertex")
        print("  IDC:", "".join(IDC))
        print("  YHWH →", list(zip(TETRA, DIMS)))
        print("  sigma", SIGMA9, sigma9.DERIV)
        print("  walk:", " → ".join("".join(str(b) for b in v) for v in doc["vertex_walk"][:4]), "… → 0000")
        print("  wrote", path)
        return 0
    if cmd == "next":
        v = [int(x) for x in (argv[1:5] or [0, 0, 0, 0])]
        n = cycle_next(v)
        print(n)
        return 0
    print("usage: apriori_loop.py reset | next [x y z t]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
