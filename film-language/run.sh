#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$ROOT/py${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT"

GRAAL="${GRAALVM_HOME:-$HOME/tools/graalvm}"
if [[ ! -x "$GRAAL/bin/javac" ]]; then GRAAL=""; fi
JAVAC="${GRAAL:+$GRAAL/bin/javac}"
JAVA="${GRAAL:+$GRAAL/bin/java}"
JAVAC="${JAVAC:-javac}"
JAVA="${JAVA:-java}"
GRAAL_LIB="${FILM_GRAAL_LIB:-$HOME/cim/04_rand_blockcode/lib}"
OUT="$ROOT/java/out"

usage() {
  cat <<EOF
GravityDesktop Film Language  ·  GraalVM host + CPython lean ML

  ./run.sh              Graal/Swing EMP (PLAN|ELEVATION|MODEL)
  ./run.sh emp          same (Qt prototype is frozen: ./run.sh qt)
  ./run.sh qt           prototype-1 PySide EMP (visual spec only)
  ./run.sh test         unit tests + FilmLivecode
  ./run.sh --help       CLI help
  ./run.sh index --file <media>
  ./run.sh search --q 'ipa:θ yolo:POV_IMAGE' --file <sidecar>
  ./run.sh compile --prompt '...' --file <sidecar> [--dry-run]
  ./run.sh splice --edl <edl.json>
EOF
}

build_java() {
  mkdir -p "$OUT"
  local cp="."
  if [[ -d "$GRAAL_LIB" ]]; then cp="$GRAAL_LIB/*"; fi
  "$JAVAC" -encoding UTF-8 -d "$OUT" -cp "$cp" "$ROOT"/java/*.java "$ROOT"/../Sigma9.java
}

java_cp() {
  if [[ -d "$GRAAL_LIB" ]]; then echo "$OUT:$GRAAL_LIB/*"; else echo "$OUT"; fi
}

cmd="${1:-}"
if [[ "$cmd" == "--help" || "$cmd" == "help" ]]; then
  usage
  echo
  python3 "$ROOT/py/cli.py" --help
  exit 0
fi
if [[ "$cmd" == "test" ]]; then
  python3 -m unittest discover -s "$ROOT/tests" -v
  build_java
  "$JAVA" -cp "$(java_cp)" FilmLivecode "cut POV where /θ/ hits ILL(T)"
  "$JAVA" -cp "$(java_cp)" IdcLoop
  exit 0
fi
if [[ "$cmd" == "qt" ]]; then
  export PYTHONPATH="$ROOT/py:$ROOT/qt${PYTHONPATH:+:$PYTHONPATH}"
  export QT_QPA_PLATFORMTHEME="${QT_QPA_PLATFORMTHEME:-gtk3}"
  export GTK_USE_PORTAL="${GTK_USE_PORTAL:-0}"
  export QT_LOGGING_RULES="${QT_LOGGING_RULES:-qt.qpa.theme.gnome=false}"
  exec python3 "$ROOT/qt/emp_armature.py"
fi
if [[ "$cmd" == "index" || "$cmd" == "search" || "$cmd" == "compile" || "$cmd" == "splice" ]]; then
  exec python3 "$ROOT/py/cli.py" "$@"
fi

# default and emp: Graal host
build_java
exec "$JAVA" -cp "$(java_cp)" GravityDesktopFilm "$@"
