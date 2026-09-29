"""Index one AVD file: DualLattice + FFT vertices + optional IPA/OCR/YOLO shots."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dual_lattice import FPS_NTSC
from harmonic import lattice_for, rfft_mag, rms_peaks, sequences_for_duration
from paths import INDEX_DB, ensure
from phonetic import phones_to_ipa
from tokens import GLYPHS, SCHEMA, TRACK_COUNT
from viseme import visemes_of

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def ffprobe(path: Path) -> Dict[str, Any]:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return {}
    return json.loads(r.stdout)


def _stream(probe: Dict[str, Any], codec_type: str) -> Dict[str, Any]:
    for s in probe.get("streams") or []:
        if s.get("codec_type") == codec_type:
            return s
    return {}


def read_samples(path: Path, fs: int = 48000) -> tuple:
    """Return (mono float samples, fs). wav direct; else ffmpeg pcm."""
    if np is None:
        return [], fs
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as w:
            n, c, rate, sw = w.getnframes(), w.getnchannels(), w.getframerate(), w.getsampwidth()
            raw = w.readframes(n)
        dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(sw, np.int16)
        x = np.frombuffer(raw, dtype=dtype).astype(float)
        if c > 1:
            x = x.reshape(-1, c).mean(axis=1)
        peak = float(np.max(np.abs(x)) or 1.0)
        return x / peak, rate
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(fs), "-f", "f32le", "pipe:1"],
        capture_output=True,
    )
    if r.returncode != 0:
        return [], fs
    x = np.frombuffer(r.stdout, dtype=np.float32).astype(float)
    return x, fs


def _shots_from_vertices(duration: float, vertices: List[dict], ipa: List[str], ocr: List[str], yolo: List[dict]) -> List[dict]:
    seq = sequences_for_duration(duration)
    shots = []
    for i, s in enumerate(seq):
        shots.append({
            "t0": s["t0"],
            "t1": s["t1"],
            "glyph": GLYPHS[i % len(GLYPHS)],
            "camera": "C",
            "yolo": yolo,
            "ocr": ocr,
            "ipa": ipa,
            "visemes": visemes_of(ipa),
            "L": {"lab": [0, 0, 0], "contrast": 0.0},
            "S": {"sense": "color"},
            "role": s["role"],
        })
    return shots


def whisper_ipa(path: Path) -> List[str]:
    """Optional WhisperX json next to media (`*.whisper.json` phones). Never required."""
    for cand in (path.with_suffix(".whisper.json"), Path(str(path) + ".whisper.json")):
        if cand.is_file():
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return []
            phones = []
            for seg in data.get("segments") or []:
                for w in seg.get("words") or []:
                    for p in w.get("phones") or []:
                        phones.append(p if isinstance(p, str) else p.get("phone", ""))
            return phones_to_ipa(phones)
    return []


def sidecar_path(media: Path) -> Path:
    return Path(str(media) + ".film.json")


def index_file(media: Path, yolo: Optional[List[dict]] = None) -> Path:
    media = media.resolve()
    if not media.is_file():
        raise FileNotFoundError(media)
    probe = ffprobe(media)
    fmt = probe.get("format") or {}
    vs = _stream(probe, "video")
    aus = _stream(probe, "audio")
    duration = float(fmt.get("duration") or 0.0)
    fs = int(float((aus.get("sample_rate") or 48000)))
    fps = FPS_NTSC
    if vs.get("r_frame_rate") and "/" in str(vs.get("r_frame_rate")):
        a, b = vs["r_frame_rate"].split("/", 1)
        if float(b):
            fps = float(a) / float(b)
    elif vs.get("avg_frame_rate") and "/" in str(vs.get("avg_frame_rate")):
        a, b = vs["avg_frame_rate"].split("/", 1)
        if float(b):
            fps = float(a) / float(b)
    samples, got_fs = read_samples(media, fs=fs or 48000)
    if got_fs:
        fs = int(got_fs)
    if duration <= 0 and len(samples) and fs:
        duration = len(samples) / float(fs)
    k = None
    if vs.get("nb_frames"):
        try:
            k = int(vs["nb_frames"])
        except (TypeError, ValueError):
            k = None
    lat = lattice_for(duration, fs=fs or 48000, fps=fps, k_claimed=k)
    vertices = rms_peaks(samples, fs or 48000) if len(samples) else []
    fft = rfft_mag(samples) if len(samples) else [0.0] * 64
    ipa = whisper_ipa(media)
    ocr: List[str] = []
    if media.suffix.lower() in {".mp4", ".mkv", ".mov", ".webm"}:
        try:
            from ocr_frames import ocr_at_times
            times = [s["t0"] for s in sequences_for_duration(duration)]
            ocr = ocr_at_times(media, times)
        except Exception:
            ocr = []
    yolo = list(yolo or [])
    shots = _shots_from_vertices(duration, vertices, ipa, ocr, yolo)
    doc = {
        "schema": SCHEMA,
        "source": str(media),
        "sha256": sha256_file(media),
        "lattice": {**lat, "fft_in": fft, "fft_out": list(fft)},
        "tracks": TRACK_COUNT,
        "sequences": sequences_for_duration(duration),
        "vertices": vertices,
        "shots": shots,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
    }
    out = sidecar_path(media)
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    _upsert_sqlite(doc, out)
    return out


def _upsert_sqlite(doc: Dict[str, Any], sidecar: Path) -> None:
    ensure()
    conn = sqlite3.connect(INDEX_DB)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS media ("
            "sha256 TEXT PRIMARY KEY, path TEXT, duration REAL, indexed_at TEXT, sidecar TEXT)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO media(sha256, path, duration, indexed_at, sidecar) VALUES (?,?,?,?,?)",
            (
                doc["sha256"],
                doc["source"],
                (doc.get("sequences") or [{}])[-1].get("t1", 0) if doc.get("sequences") else 0,
                doc.get("indexed_at"),
                str(sidecar),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="film-language index")
    p.add_argument("--file", required=True)
    p.add_argument("--yolo-class", action="append", default=[])
    args = p.parse_args(argv)
    yolo = [{"class": c, "conf": 1.0} for c in args.yolo_class]
    path = index_file(Path(args.file), yolo=yolo or None)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
