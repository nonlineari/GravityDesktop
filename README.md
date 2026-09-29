# GravityDesktop

Desktop recorder, downloader, and convert pipeline. ffmpeg is an external program (`FFMPEG_PATH`, default `/usr/bin/ffmpeg`). This repository does not vendor ffmpeg, media, or model weights.

Private through 17 December 2026.

## For ffmpeg contributors

Command lines are in the source. Sample video is not.

| Area | Where |
|---|---|
| VP9/AV1 to H.264 (`libx264`, CRF 19, no scale) | `vp9_to_h264_args` in `nls_video_pipe.py` |
| Channel layouts (`pan`, `channelsplit`, `amerge`). Eight channels are 7.1 because AAC has no 8.1 | `nls_codec_plan` in `nls_video_pipe.py` and `GravityDesktop.java` |
| Loudness −23 LUFS, true peak −1.5 dBTP, `loudnorm` with `linear=true` | `loudnormLinearFilter` in `GravityDesktop.java`, `loudnorm_linear_filter` in `nls_video_pipe.py` |
| Peak −1 dBFS via `volumedetect` | `docs/audio/normalization.md` |
| Recorder encode and the gravity channel split/mix | `GravityDesktop.java` |
| ffmpeg 6.1 unlabeled 6-channel AAC | `test_pipeline_convert.py` |

`GravityDesktopConvertTest.java` and `test_pipeline_convert.py` call the system ffmpeg. They do not ship picture or sound.

## Install

[installation_guide.md](installation_guide.md) installs the system packages and clones the repository. [setup_init.md](setup_init.md) initializes that clone.

## Run

```bash
./run.sh
```

Needs a JDK and system `ffmpeg` / `ffprobe`. `yt-dlp` is not in this repo. `yt-dlp-run` uses `.venv/bin/python3` when that environment exists (`requirements-venv.txt`: curl_cffi, yt-dlp, secretstorage). Serve and mint use `/usr/bin/python3`, not that venv.

Cookies, ngrok auth, and the SSH hop host stay in `~/.config/gravity-desktop/`.

## Left out on purpose

Video, audio, downloads, recordings, `REC-SAVED.json`, `.venv`, `.venv-whisper`, compiled classes, the yt-dlp zipapp, `.deb` packages, personal photos, and the separate `onionSearcher` checkout.

## Shared pipeline files

These files live in this repository. The [`nls-video-monitor`](https://github.com/nonlineari/nls-video-monitor) submodule keeps the same names as symlinks back to the parent (`../file`). GravityDesktop is the copy you edit. The submodule still holds pipeline-only files such as `install.sh` and `test_vpn_compat.py`.

Clone both together:

```bash
git clone --recurse-submodules https://github.com/nonlineari/GravityDesktop.git
```

Linked files: `nls_video_pipe.py`, `gravity_serve.html`, `hierarchy_interpreter.py`, `version.json`, `setup-cookies.sh`, `run-gravity-serve.sh`, `restart-gravity-serve.sh`, `archive-gravity-serve.sh`, `verify-gravity-api.sh`, `notify-mm.sh`, `ARCHITECTURE.md`, `Installation.md`, `GRAVITYDESKTOP_JAVA.md`, `INTERLATERUS.md`, `BLOCKCODE_NFT_CLIENT.md`, `LINUX_SYSTEM_MAP.md`, `AnalogOnAnalog.md`, `plan.md`, `plan.html`, `plan.original.md`.

`nls-video-monitor` is private through 17 December 2026, same as this repo.

## License

Source code is under the MIT License ([LICENSE](LICENSE)). Copyright (c) 2026 CIM.

Documentation, diagrams, and images are under Creative Commons Attribution 4.0 International ([LICENSE-CC-BY-4.0](LICENSE-CC-BY-4.0)). Credit CIM, link to the license, and note changes when you share those materials.
