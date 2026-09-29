#!/usr/bin/env bash
# SSH dynamic SOCKS for GravityDesktop (replaces Surfshark for downloads).
# YouTube 403s on Surfshark datacenter IPs; an SSH hop on a normal VPS/home box does not.
#
# Setup once:
#   ssh-copy-id -i ~/.ssh/id_ed25519_gravity.pub USER@HOST
#   printf 'GRAVITY_SSH_HOST=USER@HOST\n' >> ~/.config/gravity-desktop/env
#
# Run:
#   ~/Downloads/GravityDesktop/run-ssh-socks.sh
set -euo pipefail
CFG="${HOME}/.config/gravity-desktop"
ENVF="${CFG}/env"
KEY="${HOME}/.ssh/id_ed25519_gravity"
PORT="${GRAVITY_SOCKS_PORT:-1080}"
mkdir -p "$CFG" "${HOME}/.ssh"
chmod 700 "${HOME}/.ssh"

if [[ -f "$ENVF" ]]; then
  # shellcheck disable=SC1090
  source "$ENVF"
fi
HOST="${GRAVITY_SSH_HOST:-}"

if [[ ! -f "$KEY" ]]; then
  ssh-keygen -t ed25519 -f "$KEY" -N "" -C "gravity-socks@$(hostname)" >/dev/null
  echo "Created $KEY"
  echo "Public key:"
  cat "${KEY}.pub"
fi

if [[ -z "$HOST" ]]; then
  echo "Set GRAVITY_SSH_HOST=user@your-vps in $ENVF" >&2
  echo "Need a SSH host that is NOT a VPN datacenter (Hetzner/DO/home box is fine)." >&2
  echo "Public key to install on the host:" >&2
  cat "${KEY}.pub" >&2
  exit 2
fi

if ss -tln | grep -q "127.0.0.1:${PORT}"; then
  echo "SOCKS already listening on 127.0.0.1:${PORT}"
else
  echo "Starting ssh -N -D ${PORT} ${HOST}"
  # -o ExitOnForwardFailure so a dead hop does not look like a working proxy
  nohup ssh -N -D "127.0.0.1:${PORT}" \
    -i "$KEY" \
    -o IdentitiesOnly=yes \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    "$HOST" >/tmp/gravity-ssh-socks.log 2>&1 &
  echo $! >/tmp/gravity-ssh-socks.pid
  for i in $(seq 1 20); do
    if ss -tln | grep -q "127.0.0.1:${PORT}"; then
      break
    fi
    sleep 0.25
  done
fi

if ! ss -tln | grep -q "127.0.0.1:${PORT}"; then
  echo "SOCKS did not come up. Log:" >&2
  tail -20 /tmp/gravity-ssh-socks.log >&2
  exit 1
fi

# GravityDesktop already reads GRAVITY_PROXY; persist for next launch
umask 077
touch "$ENVF"
chmod 600 "$ENVF"
if grep -q '^GRAVITY_PROXY=' "$ENVF" 2>/dev/null; then
  sed -i "s|^GRAVITY_PROXY=.*|GRAVITY_PROXY=socks5://127.0.0.1:${PORT}|" "$ENVF"
else
  echo "GRAVITY_PROXY=socks5://127.0.0.1:${PORT}" >>"$ENVF"
fi
if grep -q '^GRAVITY_GEO_PROXY=' "$ENVF" 2>/dev/null; then
  sed -i "s|^GRAVITY_GEO_PROXY=.*|GRAVITY_GEO_PROXY=socks5://127.0.0.1:${PORT}|" "$ENVF"
else
  echo "GRAVITY_GEO_PROXY=socks5://127.0.0.1:${PORT}" >>"$ENVF"
fi

echo "SOCKS 127.0.0.1:${PORT} → $HOST"
echo "GRAVITY_PROXY=socks5://127.0.0.1:${PORT}"
echo "Restart GravityDesktop (or leave it if it already auto-detects :1080)."
echo -n "Exit IP via SOCKS: "
timeout 12 curl -4 -sS --max-time 10 --socks5-hostname "127.0.0.1:${PORT}" https://ipinfo.io/ip || echo "(probe failed)"
echo
