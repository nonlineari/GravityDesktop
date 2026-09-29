# Installation guide

Install GravityDesktop on a Debian or Ubuntu machine. This guide covers the system packages and the clone. First-run initialization of that clone is [setup_init.md](setup_init.md).

Source code is MIT. This document, the other documentation, the diagrams, and the images are Creative Commons Attribution 4.0. See [LICENSE](LICENSE) and [LICENSE-CC-BY-4.0](LICENSE-CC-BY-4.0).

The GitHub repositories are private through 17 December 2026. Cloning needs an account that can read them.

## Requirements

| Tool | Required | Role |
|---|---|---|
| JDK (`java`, `javac`) | yes | Compiles and runs `GravityDesktop.java` |
| Python 3.10+ at `/usr/bin/python3` | yes | Serve, mint, and `nls_video_pipe.py` |
| ffmpeg and ffprobe | yes | Encode, probe, loudness, channel split |
| yt-dlp | yes | Downloads. Not stored in git |
| Deno | yes for YouTube | JS runtime for yt-dlp |
| curl | yes | Fetches Deno and the yt-dlp program |
| ffplay | no | Preview |
| notify-send | no | Desktop notifications from the pipeline |
| `rich` | no | TUI polish for `nls-video monitor` |

ffmpeg from the distro packages needs the `libx264` and `aac` encoders. The VP56 path also needs `libvpx`. `./check-paths.sh` reports `libx264` and `aac` after setup.

## Packages

```bash
sudo apt update
sudo apt install default-jdk ffmpeg python3 python3-venv python3-pip yt-dlp python3-secretstorage curl
```

`python3-secretstorage` lets yt-dlp read a browser cookie database. A Netscape `cookies.txt` works without it. `ffplay` is in the same `ffmpeg` package on Ubuntu.

Confirm the compilers and the encoders:

```bash
java -version
javac -version
/usr/bin/python3 --version
ffmpeg -hide_banner -encoders | grep -E 'libx264|libvpx|aac'
```

## Clone

```bash
gh auth login
gh repo clone nonlineari/GravityDesktop -- --recurse-submodules
cd GravityDesktop
```

`--recurse-submodules` fetches `nls-video-monitor`. Shared files such as `nls_video_pipe.py`, `gravity_serve.html`, `hierarchy_interpreter.py`, `version.json`, the serve scripts, and the pipeline docs live in this repository. Inside the submodule those names are symlinks to `../file`, so they resolve only in a full clone. Pipeline-only files (`install.sh`, `test_vpn_compat.py`) stay in the submodule.

## Not in the clone

Git ignores local data. You create or download these during [setup_init.md](setup_init.md):

| Left out | Why |
|---|---|
| Video, audio, and `REC-SAVED.json` | Recordings and downloads stay on the machine |
| `.venv` | Local interpreter for `yt-dlp-run` only |
| `yt-dlp` zipapp and `*.deb` | Third-party binaries |
| `*.class` | `javac` output |
| `cookies.txt`, ngrok auth, SSH config | `~/.config/gravity-desktop/` |

## Layout

| Path | Role |
|---|---|
| Repository root | Swing UI, `run.sh`, docs, film-language |
| `nls-video-monitor/` | Pipeline source (submodule) |
| `~/.config/gravity-desktop/` | Cookies and the local env file |
| `~/.config/nls-video/` | Pipeline config |
| `~/.local/share/nls-video/` | Job database and visualist catalog |
| `~/.local/share/interlaterus-desktop/` | Blockcode database and catalogs |
| `~/.local/bin/nls-video` | Pipeline command, created by setup |
| `~/Downloads/` | Default folder for `direct-h264-*` downloads |

Scripts resolve their own directory. The clone does not have to live at `~/Downloads/GravityDesktop`.

Next: [setup_init.md](setup_init.md).
