#!/usr/bin/env bash
# Safe restart — avoids pkill -f matching the wrapper shell (SIGTERM to self).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${GRAVITY_SERVE_PORT:-8766}"

stop_gravity_serve() {
  # Match subcommand gravity-serve only — never gravity-server (substring trap).
  local pids
  pids=$(pgrep -af 'nls_video_pipe\.py' 2>/dev/null | awk '/gravity-serve( |$)/ && $0 !~ /gravity-server/ {print $1}' || true)
  if [[ -n "$pids" ]]; then
    echo "Stopping gravity-serve: $pids"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 1
  fi
}

stop_gravity_serve
exec "${DIR}/run-gravity-serve.sh" "$@"