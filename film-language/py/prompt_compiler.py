"""Prompt → film tokens → EDL. Optional LLM is JSON-tokens only; default is the lexer."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from paths import CUTS_DIR, EDL_DIR, ensure
from search import leftover_text, parse_query, search_doc, search_path
from tokens import SCORE_THRESHOLD

STOP = {
    "cut", "find", "where", "hits", "hit", "on", "the", "a", "an", "and",
    "track", "harmonic", "vertex", "splice", "at", "with", "for", "to",
    "of", "in", "when", "prompt", "pov",
}


def tokens_from_prompt(prompt: str) -> List[str]:
    q = parse_query(prompt)
    if "pov" in prompt.lower() and not q["yolo"]:
        q["yolo"].append("POV_IMAGE")
    extra = leftover_text(prompt)
    words = [w for w in extra.split() if w.lower() not in STOP]
    if words:
        q["ocr"].append(" ".join(words))
    out = []
    for k, vs in q.items():
        for v in vs:
            out.append(f"{k}:{v}")
    return out


def compile_edl(prompt: str, docs: List[Dict[str, Any]], out_id: Optional[str] = None) -> Dict[str, Any]:
    ensure()
    tokens = tokens_from_prompt(prompt)
    query = " ".join(tokens) if tokens else prompt
    clips = []
    for doc in docs:
        for hit in search_doc(doc, query):
            if hit["score"] < SCORE_THRESHOLD:
                continue
            clips.append({
                "source": hit["source"],
                "in": hit["t0"],
                "out": hit["t1"],
                "track": (hit.get("shot") or {}).get("role"),
                "score": hit["score"],
            })
    eid = out_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    output = str(CUTS_DIR / f"{eid}.mp4")
    edl = {
        "id": eid,
        "prompt": prompt,
        "tokens": tokens,
        "clips": clips,
        "output": output,
    }
    path = EDL_DIR / f"{eid}.json"
    path.write_text(json.dumps(edl, indent=2), encoding="utf-8")
    edl["edl_path"] = str(path)
    return edl


def load_docs(paths: List[Path]) -> List[Dict[str, Any]]:
    docs = []
    for p in paths:
        hits = search_path(p, "")  # just to resolve sidecar; empty query
        if p.suffix == ".json":
            docs.append(json.loads(p.read_text(encoding="utf-8")))
        else:
            film = Path(str(p) + ".film.json")
            if film.is_file():
                docs.append(json.loads(film.read_text(encoding="utf-8")))
    return docs


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="film-language compile")
    p.add_argument("--prompt", required=True)
    p.add_argument("--file", action="append", default=[])
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    if os.environ.get("GRAVITY_FILM_LLM") == "1":
        # Intentionally unused in lean v1: leftover → OCR, no media upload.
        pass
    docs = load_docs([Path(f) for f in args.file])
    if args.dry_run:
        print(json.dumps({"tokens": tokens_from_prompt(args.prompt)}, indent=2))
        return 0
    if not docs:
        print("no .film.json docs; index first", file=sys.stderr)
        return 2
    edl = compile_edl(args.prompt, docs)
    print(json.dumps(edl, indent=2))
    return 0 if edl["clips"] else 1


if __name__ == "__main__":
    sys.exit(main())
