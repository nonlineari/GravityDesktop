# GraalVM host — lean ML env

Host JVM: `$HOME/tools/graalvm` (CE 21).  
Optional polyglot jars: `$HOME/cim/04_rand_blockcode/lib` (GraalPy 24.2.1) for **livecode only**.

**ML stays CPython** (`py/`): numpy FFT, IPA, Tesseract, YOLO sidecar.  
Graal guest must not import numpy/torch/whisper.

```
livecode (GraalPy expand, else Java)
    → cli.py search / indexer.py / splice.py   ← lean ML env
    → FilmDoc → PLAN / ELEVATION / MODEL (Java 2D)
```

`qt/` is prototype-1 visual spec. `./run.sh qt` still opens it.
