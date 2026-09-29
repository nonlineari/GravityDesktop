#!/usr/bin/env bash
# GravityDesktop (main) + GravityDesktopLattice (sources/operators → lattice-dat).
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
export DISPLAY="${DISPLAY:-:0.0}"
cd "$APP_DIR"
# main GravityDesktop keeps exec; run it in a subshell so we can also start the subversion
if [[ -x "$APP_DIR/run.sh" ]]; then
  ( cd "$APP_DIR" && bash "$APP_DIR/run.sh" ) &
fi
exec "$APP_DIR/run-lattice-subversion.sh"
