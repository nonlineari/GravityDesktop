# Prototype v1 — frozen 2026-09-16

First working armature. **Leave `qt/` as-is.** GraalVM Swing EMP is the live host (`./run.sh`). Index/Search now use the livecode field and load FFT into PLAN/ELEVATION/MODEL. ML remains CPython `py/`.

Tag: `prototype-1`  
Commit: recorded on `master` when this file landed.

## What this prototype is

- Unique subversion next to GravityDesktop (Java host + Python indexer + Qt EMP).
- 6-track FFT timeline (Form Follows Timeline), IPA/YOLO search, Klipp av splice.
- Qt EMP: PLAN | ELEVATION | MODEL (`qt/emp_armature.py`).
- Portal-theme workaround in `qt/qt_env.py` (gtk3, no `org.freedesktop.portal.Settings`).

Launch:

```
cd ~/Downloads/GravityDesktop/film-language
./run.sh test
./run.sh          # Java function strip
./run.sh emp      # Qt EMP (prototype UI)
```

## Known bugs (do not “fix” on this snapshot — next pass)

1. **Index / Search FFF–FFT** — Java strip hardcodes the query and never shows the FFT:
   - `indexSel` runs `indexer.py` but does not load PLAN / FFT bars.
   - `searchSel` always searches `ipa:θ yolo:POV_IMAGE` (not the livecode line).
   - `compileSel` always uses `cut POV where /θ/ hits ILL(T)`.
   - Form-follows-function rows are not wired to Form-follows-timeline (no DualLattice ε / 6-track refresh after Index).
2. **Qt GNOME portal** — mitigated in this snapshot via `qt_env.py`; still a Qt stack issue.
3. YOLO on real media is sidecar-only (no Darknet weights). WhisperX IPA is optional sidecar.

## Next pass (when returning)

**Instead of Qt:** GraalVM on the Java host (Kellyolo L1 pattern — Graal polyglot, not PySide6).

| Now (v1) | Next |
|---|---|
| `qt/emp_armature.py` + PySide6 | Graal context in `GravityDesktopFilm` (JS or Python guest for livecode) |
| PLAN/ELEVATION/MODEL as Qt widgets | Java 2D drawings of the same triad (ObserverStage / FftArmature already exist in lattice-dat) |
| Index/Search hardcoded | Livecode field drives search; Index refreshes 6-track FFT + ε |

Do not delete `qt/`. Keep it as the visual spec for the Graal rebuild.
