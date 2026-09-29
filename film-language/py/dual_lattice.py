"""
Dual sequential lattices forced to share one timeline.

Copied from lattice-dat (lean reuse). Do not rewrite.

Audio lattice:  t = n / fs   (exact when T*fs is integer)
Visual lattice: t = k / fps  (may leave a fractional residual vs audio T)

CER_NNLR reference:
  T=3640.724, fs=48000 → N=174754752 exact
  fps=30000/1001, K=109112 → residual ≈ 0.0203 s ≈ 0.607 frames
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# NTSC / CER default
FPS_NTSC = 30000 / 1001  # ≈ 29.97002997


class LatticeMode(str, Enum):
    AUDIO_MASTER = "audio-master"
    VISUAL_MASTER = "visual-master"
    INDEPENDENT = "independent"
    LOCKED = "locked"


@dataclass
class Residual:
    """Mismatch between audio-time and visual-time on a shared timeline."""

    epsilon_sec: float
    epsilon_frames: float
    epsilon_samples: float
    t_audio: float
    t_visual: float

    def as_dict(self) -> dict:
        return {
            "epsilon_sec": self.epsilon_sec,
            "epsilon_frames": self.epsilon_frames,
            "epsilon_samples": self.epsilon_samples,
            "t_audio": self.t_audio,
            "t_visual": self.t_visual,
            "epsilon_ms": self.epsilon_sec * 1000.0,
        }


class AudioLattice:
    """Sample-index sequential lattice."""

    def __init__(self, fs: int = 48000, n: int = 0, N: Optional[int] = None):
        if fs <= 0:
            raise ValueError("fs must be positive")
        self.fs = int(fs)
        self.n = int(n)
        self.N = None if N is None else int(N)

    @property
    def dt(self) -> float:
        return 1.0 / self.fs

    @property
    def t(self) -> float:
        return self.n / self.fs

    def step(self, frames: int) -> None:
        self.n = max(0, self.n + int(frames))
        if self.N is not None:
            self.n = min(self.n, self.N)

    def seek_time(self, t_sec: float) -> None:
        self.n = max(0, int(round(t_sec * self.fs)))
        if self.N is not None:
            self.n = min(self.n, self.N)

    def seek_sample(self, n: int) -> None:
        self.n = max(0, int(n))
        if self.N is not None:
            self.n = min(self.n, self.N)

    def set_length_samples(self, N: int) -> None:
        self.N = int(N)

    def set_length_seconds(self, T: float) -> None:
        self.N = int(round(T * self.fs))

    def remaining(self) -> Optional[int]:
        if self.N is None:
            return None
        return max(0, self.N - self.n)

    def as_dict(self) -> dict:
        return {
            "fs": self.fs,
            "n": self.n,
            "N": self.N,
            "t": self.t,
            "dt": self.dt,
        }


class VisualLattice:
    """Frame-index sequential lattice."""

    def __init__(self, fps: float = FPS_NTSC, k: int = 0, K: Optional[int] = None):
        if fps <= 0:
            raise ValueError("fps must be positive")
        self.fps = float(fps)
        self.k = int(k)
        self.K = None if K is None else int(K)

    @property
    def dt(self) -> float:
        return 1.0 / self.fps

    @property
    def t(self) -> float:
        return self.k / self.fps

    def step(self, frames: int = 1) -> None:
        self.k = max(0, self.k + int(frames))
        if self.K is not None:
            self.k = min(self.k, self.K)

    def seek_time(self, t_sec: float) -> None:
        self.k = max(0, int(round(t_sec * self.fps)))
        if self.K is not None:
            self.k = min(self.k, self.K)

    def seek_frame(self, k: int) -> None:
        self.k = max(0, int(k))
        if self.K is not None:
            self.k = min(self.k, self.K)

    def set_length_frames(self, K: int) -> None:
        self.K = int(K)

    def set_length_seconds(self, T: float) -> None:
        self.K = int(round(T * self.fps))

    def as_dict(self) -> dict:
        return {
            "fps": self.fps,
            "k": self.k,
            "K": self.K,
            "t": self.t,
            "dt": self.dt,
        }


class DualLattice:
    """
    Two sequential lattices forced to share one timeline.

    Modes control which lattice drives the shared head and how the other follows.
    """

    def __init__(
        self,
        fs: int = 48000,
        fps: float = FPS_NTSC,
        mode: LatticeMode = LatticeMode.AUDIO_MASTER,
    ):
        self.audio = AudioLattice(fs=fs)
        self.visual = VisualLattice(fps=fps)
        self.mode = mode if isinstance(mode, LatticeMode) else LatticeMode(mode)
        # Independent mode: separate visual rate multiplier (tape capstan drift)
        self.visual_rate = 1.0  # relative speed of visual head in independent mode

    def residual(self) -> Residual:
        ta, tv = self.audio.t, self.visual.t
        eps = ta - tv
        return Residual(
            epsilon_sec=eps,
            epsilon_frames=eps * self.visual.fps,
            epsilon_samples=eps * self.audio.fs,
            t_audio=ta,
            t_visual=tv,
        )

    def residual_at_claimed(
        self,
        T: float,
        K_claimed: Optional[int] = None,
        N_claimed: Optional[int] = None,
    ) -> Residual:
        """
        CER-style cross-check: audio length T vs claimed integer frame count.
        Does not move the playhead.
        """
        t_audio = T if N_claimed is None else N_claimed / self.audio.fs
        if K_claimed is None:
            t_visual = T  # ideal lock
        else:
            t_visual = K_claimed / self.visual.fps
        eps = t_audio - t_visual
        return Residual(
            epsilon_sec=eps,
            epsilon_frames=eps * self.visual.fps,
            epsilon_samples=eps * self.audio.fs,
            t_audio=t_audio,
            t_visual=t_visual,
        )

    def sync_visual_to_audio(self) -> None:
        self.visual.seek_time(self.audio.t)

    def sync_audio_to_visual(self) -> None:
        self.audio.seek_time(self.visual.t)

    def advance_audio(self, frames: int) -> Residual:
        """Advance by audio frames; update visual per mode."""
        frames = int(frames)
        if self.mode == LatticeMode.AUDIO_MASTER:
            self.audio.step(frames)
            self.visual.seek_time(self.audio.t)
        elif self.mode == LatticeMode.VISUAL_MASTER:
            # interpret frames as audio block but pull audio to visual time after visual step
            dt = frames / self.audio.fs
            self.visual.step(max(1, int(round(dt * self.visual.fps))))
            self.audio.seek_time(self.visual.t)
        elif self.mode == LatticeMode.INDEPENDENT:
            self.audio.step(frames)
            dt = frames / self.audio.fs
            vframes = int(round(dt * self.visual.fps * self.visual_rate))
            self.visual.step(vframes)
        elif self.mode == LatticeMode.LOCKED:
            self.audio.step(frames)
            # snap visual so residual minimized at sample boundary
            self.visual.seek_time(self.audio.t)
        return self.residual()

    def seek_time(self, t_sec: float) -> Residual:
        if self.mode == LatticeMode.VISUAL_MASTER:
            self.visual.seek_time(t_sec)
            self.audio.seek_time(self.visual.t)
        else:
            self.audio.seek_time(t_sec)
            if self.mode != LatticeMode.INDEPENDENT:
                self.visual.seek_time(self.audio.t)
            # independent: only move audio head unless caller moves visual
        return self.residual()

    def set_lengths_from_audio_seconds(self, T: float, K_claimed: Optional[int] = None) -> None:
        self.audio.set_length_seconds(T)
        if K_claimed is not None:
            self.visual.set_length_frames(K_claimed)
        else:
            self.visual.set_length_seconds(T)

    def as_dict(self) -> dict:
        r = self.residual()
        return {
            "mode": self.mode.value,
            "audio": self.audio.as_dict(),
            "visual": self.visual.as_dict(),
            "residual": r.as_dict(),
            "visual_rate": self.visual_rate,
        }


# --- CER_NNLR constants for tests and demos ---
CER_T = 3640.724
CER_FS = 48000
CER_N = 174_754_752  # exact: T * fs
CER_FPS = FPS_NTSC
CER_K = 109_112
