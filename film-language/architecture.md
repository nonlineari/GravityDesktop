# Architecture — GravityDesktop Film Language

Lean unique subversion. Host: `java/GravityDesktopFilm.java`. Brain: `py/`. Drawings: `qt/`.

```
AVD (direct-h264 / asc-rec)
    → indexer (DualLattice + FFT vertices)
    → search (IPA ∪ YOLO ∪ OCR ∪ glyph ∪ harmonic)
    → prompt_compiler → EDL
    → splice (Klipp av / ffmpeg)
```

Views share one DualLattice clock:

| Drawing | Function |
|---|---|
| PLAN | 6-track FFT timeline, cut ticks at vertices |
| ELEVATION | AUDIO IN α vs AUDIO OUT β + residual ε |
| MODEL | ObserverStage particles (shots), φ rays |

Form follows function: Index, Search, Compile, Splice, Preview.  
Form follows timeline: PLAN *is* the FFT, not a ruler of seconds.

Local catalog: `*.film.json` + `~/.local/share/gravity-desktop/film-language/index.sqlite`.  
No new port. No SSH/.NET. No eval. YOLO is view/search only.
