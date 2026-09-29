#!/usr/bin/env bash
# Unique GravityDesktop subversion that locates sources and launches lattice-dat.
# Does not replace ./run.sh (GravityDesktop.java).
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"
export DISPLAY="${DISPLAY:-:0.0}"
javac GravityDesktopLattice.java
exec java GravityDesktopLattice "$@"
