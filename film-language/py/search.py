"""Fused footage search: IPA + YOLO + OCR + harmonic + glyph."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from phonetic import parse_ipa_token
from tokens import (
    CAMERA,
    GLYPHS,
    SCORE_THRESHOLD,
    TRACK_ROLES,
    W_GLYPH,
    W_HARM,
    W_IPA,
    W_OCR,
    W_YOLO,
)
from viseme import viseme_of
from yolo_search import detections_from_shot, match_class

TOKEN_RE = re.compile(
    r"(?:ipa:)?/([^/]+)/|ipa:(\S+)|yolo:(\S+)|glyph:(\S+)|track:(\S+)|ocr:(\S+)|"
    r"(WNIM|FLHS|ILL\(T\)|ILY\(R\)|SLEG\(L\)|LOGOS\(Q\))|\b([CPTDLSM])\b",
    re.IGNORECASE,
)


def parse_query(q: str) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {
        "ipa": [], "yolo": [], "glyph": [], "track": [], "ocr": [], "camera": [],
    }
    if re.search(r"\bPOV\b", q or "", re.I) and "yolo:" not in (q or "").lower():
        out["yolo"].append("POV_IMAGE")
    for m in TOKEN_RE.finditer(q or ""):
        ipa_sl, ipa_b, yolo, glyph, track, ocr, role, cam = m.groups()
        if ipa_sl:
            out["ipa"].append(parse_ipa_token(ipa_sl))
        elif ipa_b:
            out["ipa"].append(parse_ipa_token(ipa_b))
        elif yolo:
            out["yolo"].append(yolo)
        elif glyph:
            out["glyph"].append(glyph)
        elif track:
            out["track"].append(track)
        elif ocr:
            out["ocr"].append(ocr)
        elif role:
            out["track"].append(role)
        elif cam and cam.upper() in CAMERA + ("L", "S", "M"):
            out["camera"].append(cam.upper())
    return out


def leftover_text(q: str) -> str:
    stripped = TOKEN_RE.sub(" ", q or "")
    return re.sub(r"\s+", " ", stripped).strip()


def _hit(a: float) -> float:
    return 1.0 if a else 0.0


def score_shot(shot: Dict[str, Any], tokens: Dict[str, List[str]], near_vertex: bool) -> Tuple[float, Dict[str, float]]:
    ipa_need = tokens.get("ipa") or []
    shot_ipa = [str(x) for x in (shot.get("ipa") or [])]
    visemes = [str(x) for x in (shot.get("visemes") or [])]
    ipa_ok = False
    if ipa_need:
        for p in ipa_need:
            if p in shot_ipa or viseme_of(p) in visemes:
                ipa_ok = True
                break
    else:
        ipa_ok = False

    yolo_ok = False
    dets = detections_from_shot(shot)
    for cls in tokens.get("yolo") or []:
        if match_class(dets, cls):
            yolo_ok = True
            break

    ocr_blob = " ".join(shot.get("ocr") or []).lower()
    ocr_ok = False
    for t in tokens.get("ocr") or []:
        if t.lower() in ocr_blob:
            ocr_ok = True
            break

    glyph_ok = False
    g = shot.get("glyph") or ""
    for want in tokens.get("glyph") or []:
        if want == g or want in GLYPHS and g == want:
            glyph_ok = True
            break

    parts = {
        "ipa": _hit(ipa_ok) if ipa_need else 0.0,
        "yolo": _hit(yolo_ok) if tokens.get("yolo") else 0.0,
        "ocr": _hit(ocr_ok) if tokens.get("ocr") else 0.0,
        "harmonic": _hit(near_vertex),
        "glyph": _hit(glyph_ok) if tokens.get("glyph") else 0.0,
    }
    # If a channel was not requested, do not require it — renormalize requested weights.
    weights = {
        "ipa": W_IPA if ipa_need else 0.0,
        "yolo": W_YOLO if tokens.get("yolo") else 0.0,
        "ocr": W_OCR if tokens.get("ocr") else 0.0,
        "harmonic": W_HARM,
        "glyph": W_GLYPH if tokens.get("glyph") else 0.0,
    }
    wsum = sum(weights.values()) or 1.0
    score = sum(parts[k] * weights[k] for k in parts) / wsum
    return score, parts


def _near_vertex(t0: float, t1: float, vertices: List[dict], slop: float = 0.25) -> bool:
    for v in vertices:
        t = float(v.get("t", -1))
        if t0 - slop <= t <= t1 + slop:
            return True
    return False


def search_doc(doc: Dict[str, Any], query: str) -> List[Dict[str, Any]]:
    tokens = parse_query(query)
    leftover = leftover_text(query)
    stop = {
        "cut", "find", "where", "hits", "hit", "on", "the", "a", "an", "and",
        "track", "harmonic", "vertex", "at", "with", "for", "to", "of", "in",
        "when", "pov",
    }
    extra = [w for w in leftover.split() if w.lower() not in stop]
    if extra:
        tokens.setdefault("ocr", []).append(" ".join(extra))
    vertices = doc.get("vertices") or []
    hits = []
    for shot in doc.get("shots") or []:
        t0, t1 = float(shot.get("t0", 0)), float(shot.get("t1", 0))
        sc, parts = score_shot(shot, tokens, _near_vertex(t0, t1, vertices))
        if sc >= SCORE_THRESHOLD:
            hits.append({
                "source": doc.get("source"),
                "t0": t0,
                "t1": t1,
                "score": round(sc, 4),
                "parts": parts,
                "shot": shot,
            })
    hits.sort(key=lambda h: -h["score"])
    return hits


def load_sidecar(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def search_path(sidecar_or_media: Path, query: str) -> List[Dict[str, Any]]:
    p = Path(sidecar_or_media)
    if p.suffix == ".json":
        return search_doc(load_sidecar(p), query)
    film = Path(str(p) + ".film.json")
    if not film.is_file():
        film = p.with_suffix(p.suffix + ".film.json")
    if not film.is_file():
        return []
    return search_doc(load_sidecar(film), query)
