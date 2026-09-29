#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
# App Python is system (apt yt_dlp). Venv is ONLY for yt-dlp-run (curl_cffi TLS/JA3).
export PATH="${HOME}/.deno/bin:/usr/bin:/usr/local/bin:${HOME}/.local/bin:${PATH}"
export YTDLP_PATH="${YTDLP_PATH:-${DIR}/yt-dlp-run}"
if /usr/bin/python3 -c "import yt_dlp" 2>/dev/null; then
  PY=/usr/bin/python3
else
  echo "No module named yt_dlp on /usr/bin/python3 — sudo apt install yt-dlp" >&2
  exit 1
fi
# Optional: source ~/.config/gravity-desktop/env (from setup-cookies.sh --use-browser)
[[ -f "${HOME}/.config/gravity-desktop/env" ]] && source "${HOME}/.config/gravity-desktop/env"
PORT="${GRAVITY_SERVE_PORT:-8766}"
GRAVITY_PORT="${GRAVITY_SERVER_PORT:-4242}"
# In-process AVD/POS cron (mint_watch / pos_reconcile / avd_scan). Set 0 to disable.
export GRAVITY_CRON_ENABLED="${GRAVITY_CRON_ENABLED:-1}"
export GRAVITY_CRON_POLL_SEC="${GRAVITY_CRON_POLL_SEC:-45}"
echo "Gravity Serve → http://127.0.0.1:${PORT}/"
echo "Ensure gravity-server is running: nls-video gravity-server --port ${GRAVITY_PORT}"
echo "Cron runner: GRAVITY_CRON_ENABLED=${GRAVITY_CRON_ENABLED} poll=${GRAVITY_CRON_POLL_SEC}s"
exec "${PY}" "${DIR}/nls_video_pipe.py" gravity-serve --port "${PORT}" --gravity-port "${GRAVITY_PORT}" "$@"