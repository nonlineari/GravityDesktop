"""XDG paths for the film-language index. Local AVD only."""

from __future__ import annotations

import os
from pathlib import Path

HOME = Path.home()
SHARE = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share"))
ROOT = SHARE / "gravity-desktop" / "film-language"
INDEX_DB = ROOT / "index.sqlite"
EDL_DIR = ROOT / "edl"
CUTS_DIR = HOME / "Videos" / "NLS-Visualist" / "film-cuts"
MODULE_ROOT = Path(__file__).resolve().parents[1]


def ensure() -> Path:
    ROOT.mkdir(parents=True, exist_ok=True)
    EDL_DIR.mkdir(parents=True, exist_ok=True)
    CUTS_DIR.mkdir(parents=True, exist_ok=True)
    return ROOT
