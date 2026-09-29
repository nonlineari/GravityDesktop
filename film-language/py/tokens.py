"""Film-language constants from the notebooks. One place, no magic strings."""

from __future__ import annotations

PHI = 1.6180339887
TRACK_COUNT = 6
TRACK_ROLES = ("WNIM", "FLHS", "ILL(T)", "ILY(R)", "SLEG(L)", "LOGOS(Q)")
FIB_WEIGHTS = (1, 1, 2, 3, 5, 8)  # F_s for sequences 0..5
GLYPHS = ("k_stand", "ss_ll", "sol_f", "helix_cut", "k_arrow", "fork")
CAMERA = ("C", "P", "T", "D")  # Cut Pan Tilt Dolly
AUDIO_VERBS = ("G", "A", "A2", "T")  # Gain Attack sustain Time
SHOT_CLASS = ("IN", "IS", "IM")
SCHEMA = "gravity.film-language.v1"

# search fusion — pinned for tests
W_IPA = 0.35
W_YOLO = 0.25
W_OCR = 0.15
W_HARM = 0.15
W_GLYPH = 0.10
SCORE_THRESHOLD = 0.55

ALPHA = 1.0  # sinewave dynamics
BETA = 1.0  # harmonic construction
