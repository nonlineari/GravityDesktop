#!/usr/bin/env bash
# Expose gravity-serve (:8766) through the existing ngrok account.
# Does not bypass YouTube 403 — only remote access to the dashboard (China/phone).
set -euo pipefail
PORT="${GRAVITY_SERVE_PORT:-8766}"
AUTH_FILE="${HOME}/.config/gravity-desktop/ngrok-basic-auth"
mkdir -p "$(dirname "$AUTH_FILE")"
chmod 700 "$(dirname "$AUTH_FILE")" 2>/dev/null || true

if [[ ! -f "$AUTH_FILE" ]]; then
  umask 077
  printf 'gravity:%s\n' "$(openssl rand -base64 12 | tr -d '/+=' | head -c 16)" >"$AUTH_FILE"
  chmod 600 "$AUTH_FILE"
fi
BASIC_AUTH="$(tr -d '\n' <"$AUTH_FILE")"

if ! curl -sf --max-time 2 "http://127.0.0.1:${PORT}/api/running" >/dev/null; then
  echo "gravity-serve is not up on 127.0.0.1:${PORT} — start it first (run-gravity-serve.sh)" >&2
  exit 1
fi

# Stop a previous gravity-serve ngrok if this wrapper left one.
if curl -sf --max-time 1 http://127.0.0.1:4040/api/tunnels >/dev/null 2>&1; then
  echo "ngrok agent already running — using existing tunnels"
else
  echo "Starting ngrok tunnel gravity-serve (auth in ~/.config/ngrok/ngrok.yml)"
  nohup ngrok start gravity-serve --log=stdout --log-format=logfmt \
    >/tmp/ngrok-gravity-serve.log 2>&1 &
  echo $! >/tmp/ngrok-gravity-serve.pid
fi
for i in $(seq 1 40); do
  if curl -sf --max-time 1 http://127.0.0.1:4040/api/tunnels 2>/dev/null | grep -q 'public_url'; then
    break
  fi
  sleep 0.25
done

python3 - "$AUTH_FILE" <<'PY'
import json, urllib.request, sys
from pathlib import Path
auth = Path(sys.argv[1]).read_text().strip()
user, _, pw = auth.partition(":")
try:
    data = json.load(urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=3))
except Exception as e:
    print("ngrok API not ready:", e)
    sys.exit(1)
tunnels = data.get("tunnels") or []
https = [t for t in tunnels if str(t.get("public_url","")).startswith("https://")]
pick = https[0] if https else (tunnels[0] if tunnels else None)
if not pick:
    print("No ngrok tunnel yet — check /tmp/ngrok-gravity-serve.log")
    sys.exit(1)
url = pick["public_url"]
print("Gravity Serve public:", url)
print("Basic auth user:", user)
print("Basic auth pass:", pw)
print("Open:", url + "/")
print("(Keep Surfshark connected in China — ngrok domains are often blocked without VPN.)")
PY
