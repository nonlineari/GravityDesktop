# Setup init

Initialize a GravityDesktop clone after [installation_guide.md](installation_guide.md). Run these commands from the repository root. Nothing here commits cookies, the virtualenv, media, or class files.

```bash
cd GravityDesktop
```

`~/Downloads` must exist and be writable. Downloads and the default recording index are written there.

## Desktop virtualenv

This environment is only for `yt-dlp-run` (curl_cffi TLS impersonation and cookie decrypt). Serve, mint, and `run-interlaterus.sh` call `/usr/bin/python3`. Do not put this virtualenv on `PATH` for those commands.

```bash
/usr/bin/python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements-venv.txt
```

`requirements-venv.txt` installs `curl_cffi`, `yt-dlp`, and `secretstorage`.

## yt-dlp program

`yt-dlp-run` executes `./yt-dlp` with the virtualenv interpreter. The zipapp is not in git.

```bash
curl -fsSL -o yt-dlp https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp
chmod +x yt-dlp
```

`run.sh` prefers `./yt-dlp-run` when that file is executable, then `./yt-dlp`, then `/usr/bin/yt-dlp`.

The pipeline still imports `yt_dlp` on system Python. The apt package from the installation guide provides that import. Check it:

```bash
/usr/bin/python3 -c "import yt_dlp"
```

## Deno

YouTube extraction needs Deno. `run.sh` prepends `~/.deno/bin` to `PATH`.

```bash
curl -fsSL https://deno.land/install.sh | sh
export PATH="$HOME/.deno/bin:$PATH"
```

## Pipeline command

```bash
chmod +x nls-video-monitor/install.sh
./nls-video-monitor/install.sh
```

This writes `~/.local/bin/nls-video`, with `NLS_VIDEO_HOME` set to the submodule directory. `~/.local/bin` needs to be on `PATH`.

```bash
nls-video --help
```

## Compile the UI

`./run.sh` runs `javac GravityDesktop.java` on every launch. To compile once during init:

```bash
javac GravityDesktop.java
```

Class files stay in the working tree and are gitignored.

## Check

```bash
./check-paths.sh
```

Required checks should print `OK`: `java`, `javac`, `ffmpeg`, `libx264`, `/usr/bin/python3`, Deno, `./yt-dlp`, `GravityDesktop.java`, and `nls_video_pipe.py`.

Warnings are expected when a feature is off: ffplay, notify-send, node, Tor, Astrill, the gravity server not listening yet. A failed YouTube simulate line means the network or the cookies are not ready. It does not mean the compile failed.

## First launch

Desktop UI:

```bash
./run.sh
```

Jobs in the UI also need the gravity server:

```bash
nls-video gravity-server --port 4242
```

Browser dashboard, in a second terminal, from the same clone:

```bash
./run-gravity-serve.sh
```

Open http://127.0.0.1:8766/. The script listens on port 8766 and expects the gravity server on port 4242. It refuses to start when `/usr/bin/python3` cannot import `yt_dlp`.

Optional mint watch, also on system Python:

```bash
./run-interlaterus.sh watch
```

## Cookies

Cookies are optional until a site asks for a logged-in session. They live under `~/.config/gravity-desktop/`, which `run.sh` creates. They are not part of the repository.

List browsers that have a cookie database:

```bash
./setup-cookies.sh --list
```

Write a Netscape file:

```bash
./setup-cookies.sh brave
```

Or point the UI at a browser database:

```bash
./setup-cookies.sh brave --use-browser
```

That records `GRAVITY_COOKIES_BROWSER` in `~/.config/gravity-desktop/env`. `run.sh` sources that file when it is present.

## Local env

Overrides go in `~/.config/gravity-desktop/env`, not in the clone. `run.sh` already defaults ffmpeg to `/usr/bin/ffmpeg` and leaves VPN off. Set a proxy or a VPN flag there only when a download needs it.

```bash
# ~/.config/gravity-desktop/env
# GRAVITY_COOKIES_BROWSER=brave
# GRAVITY_PROXY=socks5://127.0.0.1:1080
```

## Stay out of git

| Path | Created by |
|---|---|
| `.venv/` | The virtualenv step |
| `yt-dlp` | The zipapp download |
| `*.class` | `javac` |
| `~/.config/gravity-desktop/` | `run.sh` and `setup-cookies.sh` |
| `~/Downloads/direct-h264-*` | A download |

`git status` in a clean clone should not list those.
