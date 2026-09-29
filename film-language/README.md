# GravityDesktop Film Language

**Prototype v1 frozen** — [PROTOTYPE.md](PROTOTYPE.md) (`git tag prototype-1`).  
**Host now:** GraalVM Swing EMP. **ML stays** lean CPython `py/` ([GRAAL.md](GRAAL.md)).

Unique subversion for **film editing via ML prompt**. GravityDesktop.java is untouched.

Search AVD footage by film-language tokens + IPA + YOLO/OCR, then splice onto a **6-track FFT timeline** (Form Follows Timeline).

```
./run.sh --help
./run.sh test
./run.sh          # GraalVM EMP (PLAN|ELEVATION|MODEL)
./run.sh qt       # frozen Qt prototype
```

Index one file:

```
./film-language index --file ~/Downloads/direct-h264-ID.mp4
./film-language search --q 'ipa:θ yolo:POV_IMAGE' --file ~/Downloads/direct-h264-ID.mp4.film.json
./film-language compile --prompt 'cut POV where /θ/ hits ILL(T)' --file … --dry-run
```

Modules: `py/` lean ML, `java/` Graal host + EMP panels, `qt/` frozen visual spec.

See `architecture.md`, `FILM_LANGUAGE.md`, `HARMONIC_EQUATION.md`.
