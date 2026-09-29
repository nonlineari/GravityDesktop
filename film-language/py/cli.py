#!/usr/bin/env python3
"""film-language CLI — index / search / compile / splice / emp."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# allow `python3 py/cli.py` from film-language/
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="film-language",
        description="GravityDesktop film-language: FFT timeline + IPA/YOLO search + Klipp av splice",
    )
    sub = p.add_subparsers(dest="cmd")

    i = sub.add_parser("index", help="index one AVD file")
    i.add_argument("--file", required=True)
    i.add_argument("--yolo-class", action="append", default=[])

    s = sub.add_parser("search", help="search a .film.json")
    s.add_argument("--q", required=True)
    s.add_argument("--file", required=True)

    c = sub.add_parser("compile", help="prompt → EDL")
    c.add_argument("--prompt", required=True)
    c.add_argument("--file", action="append", default=[])
    c.add_argument("--dry-run", action="store_true")

    sp = sub.add_parser("splice", help="EDL → mp4")
    sp.add_argument("--edl", required=True)
    sp.add_argument("--reencode", action="store_true")

    sub.add_parser("emp", help="open ELEVATION | MODEL | PLAN")

    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help()
        return 0

    if args.cmd == "index":
        from indexer import main as m
        return m(["--file", args.file] + [x for c in args.yolo_class for x in ("--yolo-class", c)])
    if args.cmd == "search":
        from search import search_path
        hits = search_path(Path(args.file), args.q)
        for h in hits:
            print(f"{h['score']:.3f}\t{h['t0']:.3f}\t{h['t1']:.3f}\t{h.get('source')}")
        return 0 if hits else 1
    if args.cmd == "compile":
        from prompt_compiler import main as m
        argv2 = ["--prompt", args.prompt]
        if args.dry_run:
            argv2.append("--dry-run")
        for f in args.file:
            argv2.extend(["--file", f])
        return m(argv2)
    if args.cmd == "splice":
        from splice import main as m
        argv2 = ["--edl", args.edl]
        if args.reencode:
            argv2.append("--reencode")
        return m(argv2)
    if args.cmd == "emp":
        print("EMP is Graal/Swing: ./run.sh   (Qt spec: ./run.sh qt)", file=sys.stderr)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
