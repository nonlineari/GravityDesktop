# GravityDesktop continuity (2026-08-25)

VPN is optional (geo-restricted browsing / travel), not required for normal internet.

## Run

```bash
nls-video gravity-server --port 4242
~/Downloads/GravityDesktop/run-gravity-serve.sh    # http://127.0.0.1:8766/
~/Downloads/GravityDesktop/run.sh                  # Java UI
~/Downloads/GravityDesktop/run-gravity-ngrok.sh    # optional public dashboard
```

Jobs: **Cancel Job** (selected row) and **⏹ Stop + Refresh** (all live jobs + refresh). Esc = Stop + Refresh.

Gravity Serve (`http://127.0.0.1:8766/`) **Chain** tab serves `docs/gravity` and `docs/audio` (drawings and the markdown). **norm** on the bar is `off`, `peak` (−1 dBFS), or `loudness` (−23 LUFS, true peak −1.5 dBTP). A direct download rewrites audio with that gain before the tesseract mint. **Norm** on a download or WYHIWYREC card rewrites that file in `~/Downloads`. `POST /api/normalize` with `{path, mode}`.

## SSH SOCKS (preferred over Surfshark for downloads)

Surfshark exits are datacenters (Cyberzone / M247) and YouTube 403s them. Use an SSH dynamic tunnel instead:

```bash
# once: put user@host in ~/.config/gravity-desktop/env
echo 'GRAVITY_SSH_HOST=user@your-vps' >> ~/.config/gravity-desktop/env
ssh-copy-id -i ~/.ssh/id_ed25519_gravity.pub user@your-vps
~/Downloads/GravityDesktop/run-ssh-socks.sh
```

GravityDesktop auto-uses `socks5://127.0.0.1:1080` (`net: SSH SOCKS :1080`) and will not bind Surfshark.

## VPN checkbox (HKG default off)

| State | Downloads |
|---|---|
| VPN unchecked | HKT ISP (`net: HKG/direct`). Leave this for YouTube. |
| VPN + **Astrill** | Bind `tun0` (`198.18.x`) via `/usr/local/Astrill/astrill`. Stealth/OpenVPN. Archive `~/Downloads/NLS-Astrill`. Config `~/.config/astrill`. |
| VPN + **Surfshark** | Bind Surfshark WG (`--force-ipv4 --source-address`). Datacenter 403 on YouTube. |

**Do not stack** Surfshark and Astrill. Provider combo: auto / Astrill / Surfshark (`GRAVITY_VPN_PROVIDER`). Env: `GRAVITY_USE_VPN=1`.

YouTube **403 IP restricted** on Surfshark Cyberzone exits is expected. Astrill `tun0` is the China-hotel path. SSH VPS still preferred for YouTube.

YouTube **403 IP restricted** on Surfshark Cyberzone exits is expected. Switch city or uncheck VPN.

## Audio rec (form follows function)

**rec:** function buttons arm a mode (filled = armed). Click the armed function again, or **REC**, to start.

| Control | Function |
|---|---|
| **WYHIWYREC** | TASCAM/PipeWire monitor — what you hear |
| **net stream** | Icecast/URL dump of the bar |
| **catalog** | selected ASC row |
| **REC** | trigger the armed function with current **opt:** |
| **STOP** / **SAVE** | end capture / copy file |

**opt:** row follows the armed function (irrelevant options hide):

| Armed | Options |
|---|---|
| WYHIWYREC | format, NTS 1/2 (hear URL), hear, auto, sig |
| net stream | format, NTS 1/2, copy |
| catalog | format, copy |

**out:** sink/port picker + ↻ + **route** + **alsa** (card profiles on/off) + **pw** (PipeWire virtual `gravity-pw`).  
Laptop **Speaker** is its own out: entry (PipeWire reports availability unknown; still selectable).
SIGNAL meter shows only for WYHIWYREC.

Takes saved under `~/Downloads/asc-rec-*` (index: `REC-SAVED.json`). Sidecar: `<file>.rec.json` (`fn`, `title`, `source_url`, `format`).

Gravity Serve catalogs (http://127.0.0.1:8766/):
- **Recent Downloads** cards show real titles (YouTube oEmbed + sidecar), duration, size, resolution, codec, mint, source URL.
- **WYHIWYREC** tab lists `asc-rec-*` takes (WYHIWYREC / net stream / catalog) with duration, codec, 48 kHz, size, Play + Locate. ffmpeg stillimage **MP4** wraps (`asc-rec-*.mp4`) show as rec-video (H.264 + audio) and play in the video player.
- APIs: `GET /api/downloads` → `{items, recs, counts}`, `GET /api/recs`.

ffmpeg (GravityDesktop): VP56 + θ-rotate used to deadlock (`redirectErrorStream(true)` + `waitFor` with nobody reading stdout). Now `-hide_banner -nostdin -nostats -loglevel error` and both streams discarded. Hear/ffplay stderr discarded too.

## Files

- Swing source: `GravityDesktop.java` (this directory)
- Backend: `~/Downloads/nls-video-monitor/nls_video_pipe.py`, `gravity_serve.html`, `test_vpn_compat.py`
- Rec index: `REC-SAVED.json`
- Grok memory: `~/.grok/memory/MEMORY.md` and `~/.grok/memory/gravitydesktop-downloads/`
