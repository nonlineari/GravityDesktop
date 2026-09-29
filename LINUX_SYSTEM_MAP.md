# GravityDesktop → Linux system map

**Principle:** all communication is community — on Linux that means **user processes**, **loopback ports**, **XDG state**, and **shared files**, not root daemons by default.

Projects live under `~/Downloads/`. Processes run as the login user, not as root.

---

## 1. Process tree (user space)

```text
$USER (login session)
│
├── python3 …/nls_video_pipe.py gravity-server --port 4242     # community live protocol
├── python3 …/nls_video_pipe.py gravity-serve  --port 8766     # community HTML + APIs
│     └── [optional] thread: cron-runner (GRAVITY_CRON_ENABLED)
│
├── java GravityDesktop                                         # desktop client (when run.sh)
├── python3 interlaterus_desktop.py watch|character|export     # mint / form / NCOMM
├── python3 …/nls_video_pipe.py worker                          # optional convert queue
│
└── audio-ml-toolkit/                                           # community voice + secure IM
      ├── .venv/bin/python  interface.py | im_client.py | …
      └── demucs / whisperx / tts envs (if activated)
```

| Community role | Linux process | Start |
|----------------|---------------|--------|
| Live catalog pulse | `gravity-server` | `nls-video gravity-server --port 4242` |
| Shared dashboard | `gravity-serve` | `./run-gravity-serve.sh` or `nls-video gravity-serve` |
| Desktop operator UI | `java GravityDesktop` | `~/Downloads/GravityDesktop/run.sh` |
| Mint / character / NCOMM | `interlaterus_desktop.py` | `run-interlaterus.sh …` |
| Voice + secure IM | tools in `audio-ml-toolkit` | `cd ~/Downloads/audio-ml-toolkit` |
| Background AVD/POS | cron thread **or** system crontab | `GRAVITY_CRON_ENABLED=1` / `cron tick` |

All of the above run as your user, not as system services, unless you install systemd units later.

---

## 2. Network (loopback community bus)

| Port | Bind | Process | Community meaning |
|------|------|---------|-------------------|
| **4242/tcp** | `127.0.0.1` | gravity-server | Shared live jobs + visualist slice |
| **8766/tcp** | `127.0.0.1` | gravity-serve | Shared HTML UI + REST APIs |
| **8765/tcp** | (optional) | nls-video serve | Alternate pipeline dashboard |
| ephemeral | TCP IM | audio-ml `im_client` / `ec_communicator` | Peer chat (localhost or LAN if bound) |

```bash
# inspect
ss -ltnp | grep -E '4242|8766|8765'
curl -sS http://127.0.0.1:8766/api/running | head
curl -sS http://127.0.0.1:8766/api/gravity | head
```

Default is **localhost only** — community on one machine; open bind / SSH tunnel / NCOMM for multi-host.

---

## 3. Filesystem (XDG + project roots)

### Project code (install roots)

| Path | Role |
|------|------|
| `~/Downloads/nls-video-monitor/` | Source: `nls_video_pipe.py`, HTML, docs |
| `~/Downloads/GravityDesktop/` | Runtime: Java app, yt-dlp, launch scripts (symlinks into monitor) |
| `~/Downloads/audio-ml-toolkit/` | Community voice ML + secure communicators |

### XDG config (`~/.config/…`)

| Path | Role |
|------|------|
| `~/.config/gravity-desktop/cookies.txt` | yt-dlp cookies (community auth to hosts) |
| `~/.config/gravity-desktop/remote-nav.tsv` | remote viewer nav |
| `~/.config/nls-video/config.json` | pipeline presets / visualist root |

### XDG data (`~/.local/share/…`) — shared community state

| Path | Role |
|------|------|
| `~/.local/share/nls-video/jobs.db` | jobs + **cron_tasks** / **cron_runs** |
| `~/.local/share/nls-video/visualist_catalog.json` | processed catalog |
| `~/.local/share/nls-video/position_index.json` | AVD↔POS community index |
| `~/.local/share/nls-video/proof-of-spatio.json` | POS proof digest |
| `~/.local/share/nls-video/gravity-serve-running.json` | running version for mm |
| `~/.local/share/nls-video/logs/` | job / runtime logs |
| `~/.local/share/interlaterus-desktop/blockcode_registry.db` | SQLite mints + vertices |
| `~/.local/share/interlaterus-desktop/nls_media_catalog.json` | interlaterus catalog |
| `~/.local/share/interlaterus-desktop/ncomm_export_manifest.json` | **NCOMM** peer sync |
| `~/.local/share/interlaterus-desktop/character_catalog.json` | Character Designer |
| `~/.local/share/interlaterus-desktop/characters/` | staged 2D/3D assets |

### Media exchange directories

| Path | Role |
|------|------|
| `~/Downloads/direct-h264-*.mp4` | acquisition drop zone (GravityDesktop) |
| `~/Videos/NLS-Visualist/` | worker convert outputs (if used) |
| `~/Downloads/audio-ml-toolkit/{audio,synthesized}.wav` | community voice artefacts |
| `~/Downloads/audio-ml-toolkit/dataset/` | clip corpus / TextGrids |

### CLI on PATH

| Path | Role |
|------|------|
| `~/.local/bin/nls-video` | → `nls_video_pipe.py` |
| `/usr/bin/ffmpeg`, `/usr/bin/ffprobe` | probe / convert / frame extract |
| `/usr/bin/java` | GravityDesktop |
| `/usr/bin/python3` | all Python community services |
| `~/.deno/bin/deno` | yt-dlp JS runtime |

---

## 4. Community pipes → Linux primitives

```text
┌──────────────────── Linux ────────────────────┐
│  files (XDG + Downloads)  = shared memory      │
│  127.0.0.1 ports          = local community bus│
│  user processes           = community services │
│  notify-send / json flags = human awareness    │
│  crontab / in-process     = shared maintenance │
└───────────────────────────────────────────────┘
         ▲                    ▲
         │                    │
   GravityDesktop        audio-ml-toolkit
   interlaterus          (IM / voice / MIDI)
   gravity-serve
```

| Community pipe | Linux primitive |
|----------------|-----------------|
| Gravity live | TCP `127.0.0.1:4242` + JSON lines |
| HTML dashboard | HTTP `127.0.0.1:8766` |
| NCOMM | file `ncomm_export_manifest.json` (+ optional SSH/USB copy) |
| audio-ML voice | files under `audio-ml-toolkit/` + venv binaries |
| audio-ML secure IM | TCP sockets from `ec_communicator` / `im_client` |
| Character form | files in `character_catalog.json` + `characters/` |
| Cron AVD/POS | SQLite in `jobs.db` + optional `crontab` |
| Desktop notify | `notify-send` D-Bus notification |

---

## 5. Typical Linux session (bring community up)

```bash
# Terminal A — live protocol
nls-video gravity-server --port 4242

# Terminal B — HTML community UI (+ cron if GRAVITY_CRON_ENABLED=1)
~/Downloads/GravityDesktop/run-gravity-serve.sh
# → http://127.0.0.1:8766/

# Terminal C — desktop operator (optional)
~/Downloads/GravityDesktop/run.sh

# Terminal D — mint watch (optional)
~/Downloads/GravityDesktop/run-interlaterus.sh watch

# Terminal E — community voice / IM (optional)
cd ~/Downloads/audio-ml-toolkit
source .venv/bin/activate   # if present
# python interface.py   or   python im_client.py …
```

One-shot community maintenance:

```bash
nls-video cron tick --all
python3 ~/Downloads/nls-video-monitor/interlaterus_desktop.py character list
python3 ~/Downloads/nls-video-monitor/interlaterus_desktop.py export
```

Optional **system crontab** (headless community reconcile):

```cron
*/10 * * * * $HOME/.local/bin/nls-video cron tick >> $HOME/.local/share/nls-video/cron.log 2>&1
```

---

## 6. Packages (Debian/Ubuntu-style)

```bash
sudo apt install default-jdk python3 ffmpeg python3-venv
# optional
sudo apt install python3-secretstorage libnotify-bin
# yt-dlp: prefer bundled ~/Downloads/GravityDesktop/yt-dlp
# deno: curl -fsSL https://deno.land/install.sh | sh
```

---

## 7. Optional systemd user units (community always-on)

Not installed by default. Sketch for multi-login resilience:

```ini
# ~/.config/systemd/user/gravity-server.service
[Unit]
Description=NLS Gravity community protocol
After=network.target

[Service]
ExecStart=%h/.local/bin/nls-video gravity-server --port 4242
Restart=on-failure

[Install]
WantedBy=default.target
```

```ini
# ~/.config/systemd/user/gravity-serve.service
[Unit]
Description=NLS Gravity community HTML
After=gravity-server.service

[Service]
Environment=GRAVITY_CRON_ENABLED=1
WorkingDirectory=%h/Downloads/nls-video-monitor
ExecStart=/usr/bin/python3 %h/Downloads/nls-video-monitor/nls_video_pipe.py gravity-serve --port 8766 --gravity-port 4242
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now gravity-server gravity-serve
```

---

## 8. Quick health check

```bash
ss -ltn | grep -E '4242|8766'
test -f ~/.local/share/nls-video/position_index.json && echo POS_OK
test -f ~/.local/share/interlaterus-desktop/blockcode_registry.db && echo MINT_OK
~/Downloads/GravityDesktop/check-paths.sh
curl -sS http://127.0.0.1:8766/api/cron | python3 -m json.tool | head
```

---

*See also: [ARCHITECTURE.md](ARCHITECTURE.md) (community principle), [Installation.md](Installation.md), `~/Downloads/audio-ml-toolkit/COMMUNICATOR_ARCH.md`.*
