"""YOLO search/view only. Never alter, delete, eval, or invent conf on real media."""

from __future__ import annotations

from typing import Any, Dict, List


def detections_from_shot(shot: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = shot.get("yolo") or []
    out = []
    for d in raw:
        if isinstance(d, dict) and d.get("class"):
            out.append({"class": str(d["class"]), "conf": float(d.get("conf") or 0.0)})
        elif isinstance(d, str) and d:
            out.append({"class": d, "conf": 0.0})
    return out


def format_hit(det: Dict[str, Any], path: str = "") -> str:
    where = f" at {path}" if path else ""
    return f"YOLO-DETECT: class={det['class']} conf={det.get('conf', 0):.2f}{where}"


def match_class(dets: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    q = query.strip().upper()
    hits = []
    for d in dets:
        if d["class"].upper() == q or q in d["class"].upper():
            hits.append(d)
    return hits
