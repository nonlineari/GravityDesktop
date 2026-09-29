"""Form Follows Timeline: FFT vertices on a 6-sequence DualLattice."""

from __future__ import annotations

import math
from typing import Iterable, List, Sequence

from dual_lattice import DualLattice, FPS_NTSC
from tokens import ALPHA, BETA, FIB_WEIGHTS, PHI, TRACK_COUNT, TRACK_ROLES

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


def sequences_for_duration(duration_sec: float) -> List[dict]:
    t = max(float(duration_sec), 0.0)
    w = t / TRACK_COUNT if t else 0.0
    total_f = float(sum(FIB_WEIGHTS))
    out = []
    for s, (role, f) in enumerate(zip(TRACK_ROLES, FIB_WEIGHTS)):
        out.append({
            "s": s,
            "t0": round(s * w, 6),
            "t1": round(t if s == TRACK_COUNT - 1 else (s + 1) * w, 6),
            "F": f / total_f,
            "role": role,
        })
    return out


def sequence_index(t: float, duration_sec: float) -> int:
    if duration_sec <= 0:
        return 0
    s = int(math.floor(TRACK_COUNT * t / duration_sec))
    return max(0, min(TRACK_COUNT - 1, s))


def downsample_mag(mag: Sequence[float], bins: int = 64) -> List[float]:
    if mag is None or len(mag) == 0:
        return [0.0] * bins
    n = len(mag)
    if n == bins:
        return [float(x) for x in mag]
    out = []
    for i in range(bins):
        a = int(i * n / bins)
        b = int((i + 1) * n / bins)
        chunk = mag[a:max(a + 1, b)]
        peak = max(chunk)
        out.append(float(peak))
    mx = max(out) or 1.0
    return [x / mx for x in out]


def rfft_mag(samples: Sequence[float], bins: int = 64) -> List[float]:
    if np is None:
        return [0.0] * bins
    x = np.asarray(samples, dtype=float)
    if x.size == 0:
        return [0.0] * bins
    x = x * np.hanning(x.size)
    spec = np.fft.rfft(x)
    mag = np.abs(spec)
    return downsample_mag(mag, bins)


def rms_peaks(
    samples: Sequence[float],
    fs: int,
    hop: int = 1024,
    win: int = 2048,
) -> List[dict]:
    """TheFormat local-max above mean+3 dB. Returns t, rms_db, fft_bin, kind=alpha."""
    if np is None or fs <= 0:
        return []
    x = np.asarray(samples, dtype=float)
    if x.size < win:
        win = max(8, int(x.size))
        hop = max(1, win // 2)
    if x.size == 0:
        return []
    frames = []
    times = []
    for i in range(0, max(1, x.size - win + 1), hop):
        chunk = x[i:i + win]
        rms = float(np.sqrt(np.mean(chunk * chunk)) + 1e-12)
        frames.append(20.0 * math.log10(rms))
        times.append(i / float(fs))
    if not frames:
        return []
    mean = sum(frames) / len(frames)
    thresh = mean + 3.0
    n_spec = max(1, win // 2)
    peaks = []
    for i in range(1, len(frames) - 1):
        v = frames[i]
        if v > thresh and v >= frames[i - 1] and v >= frames[i + 1]:
            bin_i = int((i / max(1, len(frames) - 1)) * 63)
            peaks.append({
                "t": round(times[i], 6),
                "rms_db": round(v, 4),
                "fft_bin": bin_i,
                "kind": "alpha",
            })
    return peaks


def H(t: float, duration_sec: float, mag: Sequence[float], phase: Iterable[float] | None = None) -> float:
    """α sine reconstruction + β Fibonacci sequence window."""
    mag = list(mag) or [0.0]
    n = len(mag)
    T = max(duration_sec, 1e-9)
    ph = list(phase) if phase is not None else [0.0] * n
    while len(ph) < n:
        ph.append(0.0)
    dyn = 0.0
    for m, a in enumerate(mag):
        dyn += a * math.sin(2.0 * math.pi * m * t / T + ph[m])
    s = sequence_index(t, duration_sec)
    seq = sequences_for_duration(duration_sec)[s]
    cons = seq["F"] * (PHI ** s)
    return ALPHA * dyn + BETA * cons


def lattice_for(duration_sec: float, fs: int = 48000, fps: float = FPS_NTSC, k_claimed: int | None = None) -> dict:
    d = DualLattice(fs=fs, fps=fps)
    k = k_claimed if k_claimed is not None else int(round(duration_sec * fps))
    n = int(round(duration_sec * fs))
    d.set_lengths_from_audio_seconds(duration_sec, K_claimed=k)
    r = d.residual_at_claimed(duration_sec, K_claimed=k, N_claimed=n)
    return {
        "fs": fs,
        "fps": fps,
        "N": n,
        "K": k,
        "epsilon_sec": r.epsilon_sec,
        "mode": d.mode.value,
    }
