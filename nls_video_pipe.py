#!/usr/bin/env python3
"""
NLS Video Pipeline + Monitor
Integrates yt-dlp download + ffmpeg H.264 conversion with robust monitoring.

Desktop-friendly on Linux:
- Rich TUI monitor (`nls-video monitor`)
- Simple web dashboard (`nls-video serve`) - the "interface"
- Desktop notifications via notify-send
- Clean sidecar metadata + central catalog for "NLS Visualist data"

Usage:
  nls-video add "https://youtube.com/watch?v=..." --preset balanced-4k
  nls-video list
  nls-video monitor
  nls-video serve          # opens browser dashboard
  nls-video worker         # run the processor (in tmux or &)

Presets (tuned from real usage):
  balanced-4k   (veryfast, crf 19) - good speed/quality compromise
  hq-4k         (medium, crf 18)   - higher quality, slower
  fast-1080     (veryfast, crf 23, 1080p max) - quick turnaround

Data for NLS Visualist:
  On completion writes:
    <output>.mp4
    <output>.nlsvis.json   (per-item structured data)
  Also maintains:
    ~/.local/share/nls-video/visualist_catalog.json  (append-only index of all processed items)

Config: ~/.config/nls-video/config.json  (optional)
"""

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import select
import threading
import time
from dataclasses import dataclass, asdict
import signal
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore
from http.server import HTTPServer, BaseHTTPRequestHandler
import socketserver
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urlparse, parse_qs, unquote
import urllib.request

# Optional integration of the 11D Hierarchy Interpreter (NLS Visualist edition)
try:
    import hierarchy_interpreter
    HIERARCHY_AVAILABLE = True
except ImportError:
    HIERARCHY_AVAILABLE = False

# Optional rich (beautiful TUI / tables). Falls back gracefully.
try:
    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.text import Text
    from rich import print as rprint
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    rprint = print

# JS runtime check for yt-dlp (addresses "No supported JavaScript runtime" warning)
# Supports deno (default in recent yt-dlp), node, etc.
# "pythonJava" install path: Python drives the install, Java app can call this too.
def check_js_runtime():
    """Return name of first found JS runtime or None.
    Deno and Node.js (and bun etc.) are similarly supported as JS runtimes for yt-dlp YouTube extraction.
    """
    for rt in ("deno", "node", "bun", "qjs"):
        if shutil.which(rt):
            return rt
    return None

def ensure_js_runtime(interactive: bool = True, auto_install: bool = False) -> Optional[str]:
    """Check for JS runtime. Warn if missing. Deno and Node.js are treated similarly (both work for --js-runtimes).
    Optionally install Deno (lightweight, recommended by yt-dlp by default).
    """
    rt = check_js_runtime()
    if rt:
        return rt

    msg = "WARNING: No supported JavaScript runtime for yt-dlp. YouTube extraction may miss formats. Only deno is enabled by default in recent yt-dlp."
    if RICH_AVAILABLE:
        print_rich(msg, "yellow")
    else:
        print(msg)
    print("See https://github.com/yt-dlp/yt-dlp/wiki/EJS for details.")
    print("Deno and Node.js are similarly usable as runtimes (Deno is lighter and default-preferred for yt-dlp).")

    if not interactive and not auto_install:
        return None

    if auto_install or (interactive and input("Install Deno now via official script? [y/N]: ").strip().lower() == "y"):
        try:
            print("Installing Deno (curl | sh)...")
            # Note: shell=True is used only for the official install pipe (KISS, documented).
            # Equivalent safe list would be more complex.
            subprocess.check_call(
                'curl -fsSL https://deno.land/install.sh | sh',
                shell=True
            )
            print("Deno installed. You may need to restart your shell or `source` your rc file.")
            # Update PATH for current process
            deno_bin = os.path.expanduser("~/.deno/bin")
            if os.path.isdir(deno_bin):
                os.environ["PATH"] = deno_bin + os.pathsep + os.environ.get("PATH", "")
            return "deno"
        except Exception as e:
            print(f"Auto-install failed: {e}")
            print("Install manually or use your package manager (e.g. pacman -S deno, brew install deno).")
    return None

# Enable terminal line editing for the input bar (cursor arrows, backspace, basic paste support)
try:
    import readline
except ImportError:
    pass  # Windows or minimal env; paste+Enter still works

# ----------------------------- Paths & Defaults -----------------------------
APP_NAME = "nls-video"
XDG_DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / APP_NAME
VACUUM_LOG_PATH = XDG_DATA / "vacuum-log.jsonl"
XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME
XDG_CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / APP_NAME

DB_PATH = XDG_DATA / "jobs.db"
LOG_DIR = XDG_DATA / "logs"
CONFIG_PATH = XDG_CONFIG / "config.json"
CATALOG_PATH = XDG_DATA / "visualist_catalog.json"
INTERLATERUS_CATALOG = Path.home() / ".local" / "share" / "interlaterus-desktop" / "nls_media_catalog.json"
BLOCKCODE_DB = Path.home() / ".local" / "share" / "interlaterus-desktop" / "blockcode_registry.db"
POSITION_INDEX_PATH = XDG_DATA / "position_index.json"
PROOF_OF_SPATIO_PATH = XDG_DATA / "proof-of-spatio.json"
DOWNLOADS_DIR = Path.home() / "Downloads"
TITLE_CACHE_PATH = XDG_CACHE / "download_titles.json"
PROBE_CACHE_PATH = XDG_CACHE / "media_probe.json"
REC_INDEX_PATH = Path(__file__).resolve().parent / "REC-SAVED.json"

_DIRECT_NAME_RE = re.compile(
    r"^(?:direct-h264(?:-rot\d+)?|direct-gif)-(.+)\.(mp4|gif)$",
    re.I,
)
_DIRECT_SEQ_RE = re.compile(r"-(\d{3})$")
_YT_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_X_STATUS_RE = re.compile(
    r"(?:twitter\.com|x\.com)/(?:[^/]+/status|i/status)/(\d+)",
    re.I,
)
HTTP_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_REC_NAME_RE = re.compile(
    r"^asc-rec-(?:(wyhiwyrec)-)?(.+)-(\d{8}-\d{6})\.(wav|mp3|m4a|flac|aac|ogg|mp4)$",
    re.I,
)
REC_STEM_TITLES = {
    "nts1": "NTS 1",
    "nts2": "NTS 2",
    "rinse-fm": "Rinse FM",
    "monitor": "Output monitor",
    "radio": "Radio stream",
    "bbc-co-uk": "BBC",
}
_HOST_TLDS = {
    "com", "net", "org", "fm", "live", "uk", "io", "tv", "co", "de", "info", "au", "us",
}
_TITLE_CACHE_LOCK = threading.Lock()
_PROBE_CACHE_LOCK = threading.Lock()

TIME_AXIOM = "utc"
DERIVED_TIMEZONES: Dict[str, str] = {
    "new_york": "America/New_York",
    "london": "Europe/London",
    "hong_kong": "Asia/Hong_Kong",
    "los_angeles": "America/Los_Angeles",
}
# Standard local timezone — override with GRAVITY_LOCAL_TIMEZONE or TZ (IANA name).
LOCAL_TIMEZONE: str = ""


def resolve_local_timezone() -> str:
    """Resolve standard local TZ var: env GRAVITY_LOCAL_TIMEZONE → TZ → system → London."""
    global LOCAL_TIMEZONE
    if LOCAL_TIMEZONE:
        return LOCAL_TIMEZONE
    for key in ("GRAVITY_LOCAL_TIMEZONE", "TZ"):
        v = os.environ.get(key, "").strip()
        if v and v.upper() not in ("UTC", "GMT", "GMT0"):
            LOCAL_TIMEZONE = v
            return LOCAL_TIMEZONE
    if ZoneInfo is not None:
        try:
            local = datetime.now().astimezone().tzinfo
            key = getattr(local, "key", None)
            if key:
                LOCAL_TIMEZONE = str(key)
                return LOCAL_TIMEZONE
        except Exception:
            pass
    LOCAL_TIMEZONE = "Europe/London"
    return LOCAL_TIMEZONE


def resolve_app_root() -> Path:
    """Project root — never ~/.local/bin (gravity-serve assets break under bin symlink)."""
    env = os.environ.get("NLS_VIDEO_HOME", "").strip()
    if env:
        root = Path(env).expanduser().resolve()
        if (root / "nls_video_pipe.py").is_file():
            return root
    script = Path(__file__).resolve()
    if script.name == "nls_video_pipe.py":
        return script.parent
    parent = script.parent
    if parent.name == "bin" or str(parent).endswith("/.local/bin"):
        for cand in (
            Path.home() / "Downloads" / "nls-video-monitor",
            Path.home() / "Downloads" / "GravityDesktop",
        ):
            if (cand / "nls_video_pipe.py").is_file():
                return cand.resolve()
    return parent


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_utc_iso() -> str:
    return now_utc().isoformat()


def format_utc_axiom(at: Optional[datetime] = None) -> Dict[str, str]:
    at = at or now_utc()
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    else:
        at = at.astimezone(timezone.utc)
    return {"axiom": TIME_AXIOM, "iso": at.isoformat(), "display": at.strftime("%Y-%m-%d %H:%M:%S UTC")}


def format_local_clock(at: Optional[datetime] = None, local_tz: Optional[str] = None) -> Dict[str, str]:
    """Local wall clock projected from UTC axiom via standard LOCAL_TIMEZONE var."""
    at = at or now_utc()
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    else:
        at = at.astimezone(timezone.utc)
    tz_name = local_tz or resolve_local_timezone()
    if ZoneInfo is not None:
        try:
            local = at.astimezone(ZoneInfo(tz_name))
            return {
                "tz": tz_name,
                "iso": local.isoformat(),
                "display": local.strftime("%Y-%m-%d %H:%M:%S %Z"),
            }
        except Exception:
            pass
    return {"tz": tz_name, "iso": at.isoformat(), "display": at.strftime("%Y-%m-%d %H:%M:%S UTC")}


def format_derived_clocks(at: Optional[datetime] = None) -> Dict[str, str]:
    at = at or now_utc()
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    else:
        at = at.astimezone(timezone.utc)
    out: Dict[str, str] = {}
    for key, tz_name in DERIVED_TIMEZONES.items():
        if ZoneInfo is not None:
            try:
                out[key] = at.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M:%S %Z")
                continue
            except Exception:
                pass
        out[key] = at.isoformat()
    return out


def api_time() -> Dict[str, Any]:
    at = now_utc()
    axiom = format_utc_axiom(at)
    derived = format_derived_clocks(at)
    local = format_local_clock(at)
    local_tz = local["tz"]
    return {
        "ok": True,
        "axiom": TIME_AXIOM,
        "utc_iso": axiom["iso"],
        "utc": axiom["display"],
        "local_tz": local_tz,
        "local": local["display"],
        "local_iso": local["iso"],
        "derived": derived,
        "zones": {"axiom": "UTC", "local": local_tz, "derived": DERIVED_TIMEZONES},
        "clocks": {"utc": axiom["display"], "local": local["display"], **derived},
    }


_SCRIPT_DIR = resolve_app_root()
VERSION_PATH = _SCRIPT_DIR / "version.json"
GRAVITY_SERVE_HTML = _SCRIPT_DIR / "gravity_serve.html"
PLAN_HTML = _SCRIPT_DIR / "plan.html"
PLAN_MD = _SCRIPT_DIR / "plan.md"
PLAN_ORIGINAL_MD = _SCRIPT_DIR / "plan.original.md"
RUNTIME_LOG_DIR = Path.home() / ".local" / "share" / "gravity-desktop" / "runtime-logs"
GRAVITY_SERVE_RUNNING_PATH = XDG_DATA / "gravity-serve-running.json"
MM_NOTIFY_PATH = XDG_DATA / "mm-notify.json"
ARCHIVE_LATEST_LINK = XDG_DATA / "archives" / "gravity-serve-latest"


def load_version_manifest() -> Dict[str, Any]:
    try:
        return json.loads(VERSION_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"name": APP_NAME, "version": "0.0.0", "tag": "v0.0.0"}


__version__ = str(load_version_manifest().get("version", "0.0.0"))

# Default media root for NLS Visualist outputs
DEFAULT_VISUALIST_ROOT = Path.home() / "Videos" / "NLS-Visualist"

DEFAULT_PRESETS = {
    "balanced-4k": {
        "description": "Balanced 4K H.264 (veryfast + crf19) - recommended for most desktop work",
        "ffmpeg_extra": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"],
        "max_height": None,
    },
    "hq-4k": {
        "description": "Higher quality 4K (medium preset, crf18) - slower but better efficiency",
        "ffmpeg_extra": ["-c:v", "libx264", "-preset", "medium", "-crf", "18",
                         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart"],
        "max_height": None,
    },
    "fast-1080": {
        "description": "Fast 1080p (veryfast, crf23, scaled) - quick turnaround / editing proxies",
        "ffmpeg_extra": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"],
        "max_height": 1080,
    },
    "interstellar-nonlinear": {
        "description": "Interstellar|nonlineari Visualist: H.264 + VP56 via SCIS noiseprotocol-vcodec + FFMPEG origin transcode + gravity (noiseprotocol secure transport prep). For 1000 years old nonlinear h@k reality aesthetics. Audio is NLS Codec (nonlineari).",
        "ffmpeg_extra": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"],
        "max_height": None,
        "vp56": True,
        "gravity": True,
    },
}

# NLS Codec — short name: nonlineari. Form follows function: keep the source
# channel layout (stereo / quad / 5.1 / 6ch / 7.1 / 8ch). Bitrate follows
# Fibonacci stage scale (φ) instead of collapsing everything to stereo 192k.
NLS_CODEC_NAME = "nls"
NLS_CODEC_LABEL = "NLS Codec"
NLS_CODEC_ALIAS = "nonlineari"
PHI = (1.0 + 5.0 ** 0.5) / 2.0
PHI_INV = PHI - 1.0  # ≈ 0.618 — same stage scale as Character Designer fold.x
NLS_CODEC_BASE_STEREO_K = 192
NLS_LAYOUT_BY_CHANNELS = {
    1: "mono",
    2: "stereo",
    3: "3.0",
    4: "quad",
    5: "5.0",
    6: "5.1",
    7: "6.1",
    8: "7.1",  # 8 discrete; 8.1-style home systems (ffmpeg has no 8.1 AAC layout)
}
NLS_AAC_NAMED_LAYOUTS = {
    "mono", "stereo", "3.0", "quad", "5.0", "5.1", "6.1", "7.1",
    "7.1(wide)", "7.1(wide-side)",
}
# Gravity channel packets — split analog form, mix for hear (Noise transport beds).
GRAVITY_CHANNEL_LABELS = {
    2: ("FL", "FR"),
    4: ("FL", "FR", "BL", "BR"),
    6: ("FL", "FR", "FC", "LFE", "BL", "BR"),
    8: ("FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"),
}
_AUDIO_ENCODER_FLAGS = {
    "-c:a", "-codec:a", "-acodec", "-b:a", "-ab", "-ac",
    "-channel_layout", "-af", "-filter:a", "-metadata:s:a:0",
}

# ----------------------------- Data Model -----------------------------
@dataclass
class Job:
    id: int
    url: str
    title: str
    preset: str
    status: str  # pending, downloading, converting, completed, failed, cancelled
    progress: float  # 0-100
    stage: str       # download | convert | done
    output_path: Optional[str]
    log_path: str
    metadata: Dict[str, Any]
    created: str
    started: Optional[str] = None
    finished: Optional[str] = None
    error: Optional[str] = None
    source_file: Optional[str] = None  # for convert-only on existing local file

    def to_dict(self):
        d = asdict(self)
        if isinstance(d.get("metadata"), str):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except Exception:
                pass
        return d


# ----------------------------- DB Helpers -----------------------------
def get_db():
    XDG_DATA.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            title TEXT,
            preset TEXT,
            status TEXT,
            progress REAL DEFAULT 0,
            stage TEXT,
            output_path TEXT,
            log_path TEXT,
            metadata TEXT,
            created TEXT,
            started TEXT,
            finished TEXT,
            error TEXT,
            source_file TEXT
        )
    """)
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN source_file TEXT")
    except sqlite3.OperationalError:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cron_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            task_type TEXT NOT NULL,
            schedule_cron TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_run TEXT,
            next_run TEXT,
            last_status TEXT,
            last_error TEXT,
            config_json TEXT DEFAULT '{}'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cron_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            started TEXT NOT NULL,
            finished TEXT,
            status TEXT,
            result_json TEXT,
            FOREIGN KEY (task_id) REFERENCES cron_tasks(id)
        )
    """)
    conn.commit()
    _seed_cron_tasks(conn)
    return conn


# Default catalog-positioning cron tasks (interval_sec also in config_json for due checks)
DEFAULT_CRON_TASKS = (
    ("mint_watch", "mint_watch", "*/10 * * * *", 600),
    ("pos_reconcile", "pos_reconcile", "*/30 * * * *", 1800),
    ("avd_scan", "avd_scan", "*/15 * * * *", 900),
)


def _seed_cron_tasks(conn: sqlite3.Connection) -> None:
    """Idempotent seed of mint_watch / pos_reconcile / avd_scan."""
    now = now_utc_iso()
    for name, task_type, schedule, interval_sec in DEFAULT_CRON_TASKS:
        row = conn.execute("SELECT id FROM cron_tasks WHERE name = ?", (name,)).fetchone()
        if row:
            continue
        cfg = json.dumps({"interval_sec": interval_sec})
        conn.execute(
            """
            INSERT INTO cron_tasks
            (name, task_type, schedule_cron, enabled, last_run, next_run, last_status, last_error, config_json)
            VALUES (?, ?, ?, 1, NULL, ?, 'pending', NULL, ?)
            """,
            (name, task_type, schedule, now, cfg),
        )
    conn.commit()


def save_job(conn, job: Job):
    conn.execute("""
        INSERT OR REPLACE INTO jobs
        (id, url, title, preset, status, progress, stage, output_path, log_path, metadata,
         created, started, finished, error, source_file)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        job.id, job.url, job.title, job.preset, job.status, job.progress, job.stage,
        job.output_path, job.log_path, json.dumps(job.metadata),
        job.created, job.started, job.finished, job.error, getattr(job, 'source_file', None)
    ))
    conn.commit()


def load_job(conn, job_id: int) -> Optional[Job]:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return None
    meta = json.loads(row["metadata"] or "{}")
    return Job(
        id=row["id"], url=row["url"], title=row["title"] or "", preset=row["preset"],
        status=row["status"], progress=row["progress"] or 0, stage=row["stage"] or "",
        output_path=row["output_path"], log_path=row["log_path"],
        metadata=meta, created=row["created"], started=row["started"],
        finished=row["finished"], error=row["error"],
        source_file=row["source_file"] if "source_file" in row.keys() else None
    )


def list_jobs(conn, status: Optional[str] = None) -> List[Job]:
    q = "SELECT * FROM jobs"
    params = []
    if status:
        q += " WHERE status = ?"
        params.append(status)
    q += " ORDER BY id DESC"
    rows = conn.execute(q, params).fetchall()
    jobs = []
    for r in rows:
        meta = json.loads(r["metadata"] or "{}")
        jobs.append(Job(
            id=r["id"], url=r["url"], title=r["title"] or "", preset=r["preset"],
            status=r["status"], progress=r["progress"] or 0, stage=r["stage"] or "",
            output_path=r["output_path"], log_path=r["log_path"],
            metadata=meta, created=r["created"], started=r["started"],
            finished=r["finished"], error=r["error"],
            source_file=r["source_file"] if "source_file" in r.keys() else None
        ))
    return jobs


# ----------------------------- Config & Visualist Data -----------------------------
def load_config() -> dict:
    XDG_CONFIG.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    cfg = {
        "visualist_root": str(DEFAULT_VISUALIST_ROOT),
        "default_preset": "balanced-4k",
        "notify": True,
    }
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    return cfg


def ensure_visualist_root(cfg: dict) -> Path:
    root = Path(cfg.get("visualist_root", DEFAULT_VISUALIST_ROOT))
    root.mkdir(parents=True, exist_ok=True)
    return root


def write_visualist_sidecar(video_path: Path, job: Job, cfg: dict):
    """Write per-file .nlsvis.json + update central catalog for NLS Visualist data."""
    sidecar = video_path.with_suffix(".nlsvis.json")
    data = {
        "id": job.id,
        "title": job.title,
        "source_url": job.url,
        "preset": job.preset,
        "output_path": str(video_path),
        "technical": job.metadata.get("technical", {}),
        "processed_at": job.finished,
        "tags": ["youtube", "h264", job.preset],
        "storage_memory_category": job.metadata.get("storage_memory_category", {}),
        "interstellar_nonlinear": job.metadata.get("interstellar_nonlinear", False),
        "gravity_prepared": job.metadata.get("gravity_prepared", False),
        "vp56_gravity_prepared": job.metadata.get("vp56_gravity_prepared", False),
    }
    sidecar.write_text(json.dumps(data, indent=2))

    # Append to central catalog (NLS Visualist data interface)
    catalog = []
    if CATALOG_PATH.exists():
        try:
            catalog = json.loads(CATALOG_PATH.read_text())
        except Exception:
            catalog = []
    catalog.append(data)
    CATALOG_PATH.write_text(json.dumps(catalog, indent=2))

    # Also drop a copy in the Visualist root for easy ingestion
    try:
        root = ensure_visualist_root(cfg)
        dest = root / sidecar.name
        if not dest.exists():
            shutil.copy2(sidecar, dest)
        # Optionally copy the video too (or symlink). For now we just note the path.
    except Exception:
        pass


def desktop_notify(title: str, body: str):
    try:
        subprocess.run(["notify-send", "-a", "NLS Video", title, body], check=False)
    except Exception:
        pass


# ----------------------------- yt-dlp + ffmpeg logic -----------------------------
def sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip()


YTDLP_H264_FORMAT = (
    "bv*[vcodec^=avc][ext=mp4]+ba[ext=m4a]/bv*[vcodec^=avc1]+ba[ext=m4a]/"
    "b[ext=mp4][vcodec^=avc]/bestvideo[vcodec^=avc]+bestaudio/best[vcodec^=avc]"
)
YTDLP_GIF_FORMAT = "best[ext=gif]/best"
# web/mweb/tv only list 360p combined. These clients expose 1080p/2160p DASH.
YT_PLAYER_CLIENTS = "youtube:player_client=tv_embedded,android_sdkless"


def youtube_player_client_args() -> str:
    extra = (os.environ.get("GRAVITY_YT_EXTRACTOR_ARGS") or "").strip()
    return extra if extra else YT_PLAYER_CLIENTS


def youtube_player_clients() -> List[str]:
    raw = youtube_player_client_args()
    if "player_client=" in raw:
        return [c.strip() for c in raw.split("player_client=", 1)[1].split()[0].split(",") if c.strip()]
    return ["tv_embedded", "android_sdkless"]


def ytdlp_format_for_height(target_height: int) -> str:
    if target_height >= 2160:
        return "bv*[height=2160]+ba/bv*[height=1080][ext=mp4]+ba/bv*[height<=1080]+ba/b"
    if target_height >= 1080:
        return "bv*[height=1080][ext=mp4]+ba[ext=m4a]/bv*[height=1080]+ba/b[height<=1080]"
    return "b[height<=360][ext=mp4]/bv*[height<=360]+ba/b[height<=360]"


def preset_target_height(preset_name: Optional[str]) -> int:
    if (preset_name or "") == "fast-1080":
        return 1080
    return 2160


def parse_target_height(raw: Any) -> int:
    s = str(raw or "").strip().lower().replace("p", "")
    try:
        h = int(s)
    except (TypeError, ValueError):
        h = 2160
    if h >= 2160:
        return 2160
    if h >= 1080:
        return 1080
    return 360


@dataclass
class _FormatRow:
    id: str
    ext: str
    resolution: str
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    video_only: bool = False
    audio_only: bool = False
    hls: bool = False
    height: int = 0
    tbr: int = 0


def _parse_format_height(resolution: Optional[str]) -> int:
    if not resolution or resolution == "audio only":
        return 0
    m = re.search(r"\d+x(\d+)", resolution)
    if m:
        return int(m.group(1))
    p = re.search(r"(\d+)p", resolution)
    return int(p.group(1)) if p else 0


def _parse_tbr_k(s: Optional[str]) -> int:
    if not s:
        return 0
    m = re.search(r"(\d+)k\b", s)
    return int(m.group(1)) if m else 0


def parse_format_line(line: Optional[str]) -> Optional[_FormatRow]:
    if not line or not line.strip():
        return None
    if line.startswith("ID ") or line.startswith("---") or line.startswith("[info]"):
        return None
    parts = line.split("|")
    if len(parts) < 3:
        return None
    left = parts[0].strip().split()
    if len(left) < 3 or not re.match(r"[\w.-]+$", left[0]):
        return None
    if left[1].lower() == "mhtml":
        return None
    row = _FormatRow(id=left[0], ext=left[1], resolution=left[2], height=_parse_format_height(left[2]))
    mid = parts[1].strip()
    row.hls = "m3u8" in mid
    row.tbr = _parse_tbr_k(mid)
    right = parts[2].strip()
    if "images" in right or "storyboard" in right:
        return None
    row.video_only = "video only" in right
    row.audio_only = "audio only" in right
    if row.tbr == 0:
        row.tbr = _parse_tbr_k(right)
    tokens = right.split()
    if not tokens:
        return row
    if row.audio_only:
        for t in tokens:
            if t.startswith("mp4a") or t.startswith("opus") or t.startswith("aac"):
                row.acodec = t
                break
    elif row.video_only:
        row.vcodec = tokens[0]
    else:
        row.vcodec = tokens[0]
        for t in tokens[1:]:
            if t.startswith("mp4a") or t.startswith("opus") or t.startswith("aac"):
                row.acodec = t
                break
    return row


def parse_format_rows(lines: List[str]) -> List[_FormatRow]:
    rows: List[_FormatRow] = []
    in_table = False
    for line in lines or []:
        if "Available formats" in line:
            in_table = True
            continue
        if not in_table:
            continue
        row = parse_format_line(line)
        if row:
            rows.append(row)
    return rows


def _pick_best_m4a(rows: List[_FormatRow]) -> Optional[_FormatRow]:
    best = None
    for r in rows:
        if not r.audio_only or r.ext.lower() != "m4a":
            continue
        is_medium = r.acodec is not None and "40.2" in r.acodec
        if best is None or (
            is_medium and (best.acodec is None or "40.2" not in best.acodec)
        ) or (
            not is_medium and best.acodec is not None and "40.5" in best.acodec
        ):
            best = r
    return best


def _pick_best_audio(rows: List[_FormatRow]) -> Optional[_FormatRow]:
    m4a = _pick_best_m4a(rows)
    if m4a:
        return m4a
    for r in rows:
        if r.audio_only:
            return r
    return None


def _height_ladder(target_height: int) -> List[int]:
    if target_height >= 2160:
        return [2160, 1440, 1080, 720, 480, 360]
    if target_height >= 1080:
        return [1080, 720, 480, 360]
    return [360]


def _better_video(cand: _FormatRow, best: Optional[_FormatRow]) -> bool:
    if best is None:
        return True
    if cand.hls != best.hls:
        return not cand.hls
    if cand.tbr != best.tbr:
        return cand.tbr > best.tbr
    return False


def _best_video_at_height(rows: List[_FormatRow], height: int) -> Optional[_FormatRow]:
    best = None
    for r in rows:
        if r.audio_only or r.height != height:
            continue
        if _better_video(r, best):
            best = r
    return best


def _lowest_video(rows: List[_FormatRow]) -> Optional[_FormatRow]:
    best = None
    for r in rows:
        if r.audio_only or r.height <= 0:
            continue
        if best is None or r.height < best.height or (
            r.height == best.height and _better_video(r, best)
        ):
            best = r
    return best


def _merge_spec(video: Optional[_FormatRow], rows: List[_FormatRow]) -> Optional[str]:
    if video is None:
        return None
    if not video.video_only and not video.audio_only:
        return video.id
    audio = _pick_best_audio(rows)
    if audio:
        return f"{video.id}+{audio.id}"
    if video.ext.lower() == "mp4":
        return f"{video.id}+bestaudio[ext=m4a]/bestaudio"
    return f"{video.id}+bestaudio"


def select_height_format(rows: List[_FormatRow], target_height: int) -> Optional[str]:
    for h in _height_ladder(target_height):
        spec = _merge_spec(_best_video_at_height(rows, h), rows)
        if spec:
            return spec
    return _merge_spec(_lowest_video(rows), rows)


def select_gif_format(rows: List[_FormatRow]) -> str:
    best = None
    for r in rows:
        if r.ext.lower() != "gif":
            continue
        if best is None or r.height > best.height:
            best = r
    return best.id if best else YTDLP_GIF_FORMAT


def select_format_from_list(
    lines: List[str],
    gif_mode: bool,
    generic: bool,
    target_height: int,
) -> str:
    rows = parse_format_rows(lines)
    if not rows:
        if gif_mode:
            return YTDLP_GIF_FORMAT
        if generic:
            return "bestvideo*+bestaudio/best"
        return ytdlp_format_for_height(target_height)
    if gif_mode:
        return select_gif_format(rows)
    return select_height_format(rows, target_height) or ytdlp_format_for_height(target_height)


def is_transcode_needed(vcodec: Optional[str]) -> bool:
    if not vcodec:
        return False
    v = vcodec.lower()
    return "vp9" in v or "vp09" in v or v.startswith("av1") or v.startswith("av01")


def h264_sibling_path(src: str) -> str:
    if src.endswith("-avc.mp4"):
        return src
    if src.lower().endswith(".mp4"):
        return src[:-4] + "-avc.mp4"
    return src + "-avc.mp4"


def vp9_to_h264_args(src: str, dest: str) -> List[str]:
    """VP9/AV1 → H.264. No scale — keep source width/height."""
    return [
        "-y",
        "-i",
        src,
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "19",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        dest,
    ]


def transcode_vp9_to_h264(
    src: Path,
    on_progress: Optional[Any] = None,
    cancel_check: Optional[Any] = None,
) -> Optional[Path]:
    """Transcode VP9/AV1 to H.264 at the same pixels. None if not needed or failed."""
    if src is None or not Path(src).is_file():
        return None
    src = Path(src)
    probe = _ffprobe_media(src)
    if not is_transcode_needed(str(probe.get("vcodec") or "")):
        return None
    dest = Path(h264_sibling_path(str(src)))
    if dest.is_file() and dest.stat().st_size > 32:
        return dest
    partial = Path(str(dest) + ".partial.mp4")
    try:
        if partial.exists():
            partial.unlink()
    except Exception:
        pass
    ffmpeg = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error"] + vp9_to_h264_args(
        str(src), str(partial)
    )
    duration = float(probe.get("duration_sec") or 0)
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            if cancel_check and cancel_check():
                proc.terminate()
                break
            if on_progress and line.startswith("out_time_ms=") and duration > 0:
                try:
                    us = int(line.split("=", 1)[1].strip())
                    pct = min(99, max(0, int((us / 1_000_000.0) / duration * 100)))
                    on_progress(pct)
                except (TypeError, ValueError):
                    pass
        rc = proc.wait(timeout=3600)
    except Exception:
        if partial.exists():
            try:
                partial.unlink()
            except Exception:
                pass
        return None
    if rc == 0 and partial.is_file() and partial.stat().st_size > 32:
        try:
            partial.replace(dest)
            return dest
        except Exception:
            return partial if partial.is_file() else None
    if partial.exists():
        try:
            partial.unlink()
        except Exception:
            pass
    return None

_active_ffmpeg_procs: Dict[int, subprocess.Popen] = {}
_active_ffmpeg_lock = threading.Lock()

_direct_dl_lock = threading.Lock()
_direct_dl_state: Dict[str, Any] = {
    "status": "idle",
    "progress": 0.0,
    "message": "",
    "error": None,
    "url": None,
    "path": None,
    "log": [],
    "vacuum": False,
    "tls_ja3": True,
    "detail": False,
}

# Pipeline worker (shared by `nls-video worker` and gravity-serve embedded mode)
WORKER_PID_PATH = XDG_DATA / "worker.pid"
_worker_lock = threading.Lock()
_worker_state: Dict[str, Any] = {
    "running": False,
    "mode": None,  # "standalone" | "embedded"
    "started_at": None,
    "current_job_id": None,
    "last_job_id": None,
    "last_error": None,
    "recovered_ids": [],
    "processed_count": 0,
    "pid": None,
    "stop": False,
}
_worker_thread: Optional[threading.Thread] = None
_gravity_server_lock = threading.Lock()
_gravity_server_state: Dict[str, Any] = {
    "running": False,
    "host": None,
    "port": None,
    "mode": None,
    "error": None,
    "started_at": None,
}
_gravity_server_thread: Optional[threading.Thread] = None
_gravity_server_sock: Optional[socket.socket] = None


class GravityRateLimiter:
    """Mirror GravityDesktop RateLimiter — pacing + 403 cooldown."""

    _lock = threading.Lock()
    _last_request_ms = 0.0
    _cooldown_until_ms = 0.0
    _consecutive_403 = 0

    @classmethod
    def acquire(cls, phase: str = "yt-dlp") -> None:
        min_gap_ms = float(os.environ.get("GRAVITY_MIN_REQUEST_INTERVAL_SEC", "3")) * 1000.0
        with cls._lock:
            now = time.time() * 1000.0
            wait_until = max(cls._last_request_ms + min_gap_ms, cls._cooldown_until_ms)
            wait_ms = wait_until - now
        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)
        with cls._lock:
            cls._last_request_ms = time.time() * 1000.0

    @classmethod
    def on_403(cls) -> None:
        with cls._lock:
            cls._consecutive_403 += 1
            base_sec = float(os.environ.get("GRAVITY_403_COOLDOWN_SEC", "60"))
            cooldown_sec = base_sec * min(cls._consecutive_403, 5)
            cls._cooldown_until_ms = time.time() * 1000.0 + cooldown_sec * 1000.0

    @classmethod
    def on_success(cls) -> None:
        with cls._lock:
            cls._consecutive_403 = max(0, cls._consecutive_403 - 1)

    @classmethod
    def cooldown_seconds_remaining(cls) -> int:
        with cls._lock:
            rem = cls._cooldown_until_ms - time.time() * 1000.0
            return int((rem + 999) // 1000) if rem > 0 else 0


def _env_str(key: str, default: str) -> str:
    v = os.environ.get(key)
    return v.strip() if v and v.strip() else default


def resolve_ytdlp_path() -> str:
    script_dir = _SCRIPT_DIR
    for cand in (
        os.environ.get("YTDLP_PATH"),
        str(script_dir / "yt-dlp"),
        str(Path.home() / "Downloads" / "GravityDesktop" / "yt-dlp"),
        str(Path.home() / ".local" / "bin" / "yt-dlp"),
        "/usr/local/bin/yt-dlp",
        "/usr/bin/yt-dlp",
    ):
        if cand and Path(cand).is_file():
            return cand
    found = shutil.which("yt-dlp")
    return found or "yt-dlp"


def _resolve_proxy_url() -> Optional[str]:
    gravity = os.environ.get("GRAVITY_PROXY")
    if gravity and gravity.strip():
        return gravity.strip()
    for key in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy"):
        v = os.environ.get(key)
        if v and v.strip():
            return v.strip()
    return None


def _env_flag(key: str) -> Optional[bool]:
    v = os.environ.get(key)
    if not v or not str(v).strip():
        return None
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return None


_VPN_NAME_RE = re.compile(
    r"^(tun\d*|tap\d*|wg\d+|ppp\d*|utun\d*|tailscale\d*|"
    r".*surfshark.*|.*nordlynx.*|.*proton.*|.*mullvad.*|"
    r".*wireguard.*|.*vpn.*|.*astrill.*)$"
)
ASTRILL_BIN = "/usr/local/Astrill/astrill"
ASTRILL_CONF_DIR = Path.home() / ".config" / "astrill"
NLS_ASTRILL_DIR = Path.home() / "Downloads" / "NLS-Astrill"


def iface_line_is_vpn(line: str) -> bool:
    """True if an `ip -o link show` line is a live VPN/tunnel (Surfshark WG is state UNKNOWN)."""
    if not line:
        return False
    l = line.strip().lower()
    # "11: surfshark_wg: <POINTOPOINT,...> ... state UNKNOWN"
    m = re.match(r"^\d+:\s+([^:]+):", l)
    if not m:
        return False
    name = m.group(1).strip()
    if not name or name == "lo" or name.startswith(("docker", "veth", "br-", "virbr", "cni")):
        return False
    if "no-carrier" in l or "state down" in l:
        return False
    if "lower_up" not in l and "state up" not in l:
        return False
    if _VPN_NAME_RE.match(name):
        return True
    if "pointopoint" in l:
        return True
    return False


def vpn_interfaces_from_ip_output(blob: str) -> List[str]:
    names: List[str] = []
    for line in (blob or "").splitlines():
        if not iface_line_is_vpn(line):
            continue
        m = re.match(r"^\d+:\s+([^:]+):", line.strip().lower())
        if m:
            names.append(m.group(1).strip())
    return names


def vpn_interface_up() -> bool:
    try:
        out = subprocess.check_output(
            ["ip", "-o", "link", "show"],
            text=True,
            timeout=2,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False
    return bool(vpn_interfaces_from_ip_output(out))


def vpn_addr_line_ipv4(line: str) -> Optional[tuple]:
    """Parse `ip -4 -o addr show` → (iface, ipv4) or None."""
    if not line:
        return None
    m = re.match(
        r"^\d+:\s+(\S+)\s+inet\s+(\d{1,3}(?:\.\d{1,3}){3})/",
        line.strip(),
    )
    if not m:
        return None
    name, ip = m.group(1), m.group(2)
    if ip.startswith("127.") or ip.startswith("169.254."):
        return None
    return name, ip


def vpn_tunnel_ipv4_from_addr_output(blob: str, vpn_ifaces: Optional[List[str]] = None) -> Optional[str]:
    """First IPv4 on a VPN iface. Prefer WireGuard/tun over IPv6-only leftovers."""
    want = {n.lower() for n in (vpn_ifaces or [])}
    fallback: Optional[str] = None
    for line in (blob or "").splitlines():
        parsed = vpn_addr_line_ipv4(line)
        if not parsed:
            continue
        name, ip = parsed
        lname = name.lower()
        if want and lname not in want:
            continue
        if not want and not _VPN_NAME_RE.match(lname) and "pointopoint" not in line.lower():
            continue
        if "wg" in lname or lname.startswith("tun") or lname.startswith("ppp"):
            return ip
        if fallback is None:
            fallback = ip
    return fallback


def vpn_tunnel_ipv4() -> Optional[str]:
    env = os.environ.get("GRAVITY_SOURCE_ADDRESS")
    if env and env.strip():
        return env.strip()
    try:
        links = subprocess.check_output(
            ["ip", "-o", "link", "show"],
            text=True,
            timeout=2,
            stderr=subprocess.DEVNULL,
        )
        addrs = subprocess.check_output(
            ["ip", "-4", "-o", "addr", "show"],
            text=True,
            timeout=2,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None
    return vpn_tunnel_ipv4_from_addr_output(addrs, vpn_interfaces_from_ip_output(links))


def ip_looks_astrill(ip: str) -> bool:
    return bool(ip) and str(ip).startswith("198.18.")


def vpn_provider_from_ifaces(names: Optional[List[str]], astrill_proc: bool = False) -> str:
    """auto-detect: astrill (tun0) vs surfshark vs stacked vs none. Do not stack."""
    surf = False
    tun = False
    for n in names or []:
        l = n.lower()
        if "surfshark" in l:
            surf = True
        if l.startswith("tun") or "astrill" in l:
            tun = True
    if surf and (tun or astrill_proc):
        return "stacked"
    if surf:
        return "surfshark"
    if tun or astrill_proc:
        return "astrill"
    return "none"


def astrill_process_running() -> bool:
    try:
        out = subprocess.check_output(
            ["ps", "-eo", "args="], text=True, timeout=2, stderr=subprocess.DEVNULL
        )
    except Exception:
        return False
    for line in out.splitlines():
        if "/usr/local/Astrill/" in line and "zsh -c" not in line and "eval " not in line:
            return True
    return False


def vpn_provider() -> str:
    env = (os.environ.get("GRAVITY_VPN_PROVIDER") or "auto").strip().lower()
    if "astrill" in env:
        return "astrill"
    if "surfshark" in env:
        return "surfshark"
    try:
        links = subprocess.check_output(
            ["ip", "-o", "link", "show"], text=True, timeout=2, stderr=subprocess.DEVNULL
        )
    except Exception:
        links = ""
    return vpn_provider_from_ifaces(vpn_interfaces_from_ip_output(links), astrill_process_running())


def vpn_tunnel_ipv4_for_provider(
    provider: Optional[str] = None,
    addr_blob: Optional[str] = None,
    vpn_ifaces: Optional[List[str]] = None,
) -> Optional[str]:
    env = os.environ.get("GRAVITY_SOURCE_ADDRESS")
    if env and env.strip() and addr_blob is None:
        return env.strip()
    if addr_blob is None:
        try:
            links = subprocess.check_output(
                ["ip", "-o", "link", "show"], text=True, timeout=2, stderr=subprocess.DEVNULL
            )
            addrs = subprocess.check_output(
                ["ip", "-4", "-o", "addr", "show"], text=True, timeout=2, stderr=subprocess.DEVNULL
            )
        except Exception:
            return None
        return vpn_tunnel_ipv4_for_provider(
            provider, addrs, vpn_interfaces_from_ip_output(links)
        )
    want = {n.lower() for n in (vpn_ifaces or [])}
    astrill_ip = None
    surf_ip = None
    tun_ip = None
    for line in (addr_blob or "").splitlines():
        parsed = vpn_addr_line_ipv4(line)
        if not parsed:
            continue
        name, ip = parsed
        lname = name.lower()
        if want and lname not in want:
            continue
        if "surfshark" in lname:
            surf_ip = ip
        if lname.startswith("tun") or "astrill" in lname:
            tun_ip = ip
            if ip_looks_astrill(ip):
                astrill_ip = ip
    if provider == "surfshark":
        return surf_ip
    if provider == "astrill":
        return astrill_ip or tun_ip
    return astrill_ip or tun_ip or surf_ip


def vpn_route_requested() -> bool:
    """HKG default: ISP. Opt in with GRAVITY_USE_VPN=1 or GRAVITY_VPN_REQUIRED=1 (China / geo)."""
    if _env_flag("GRAVITY_VPN_REQUIRED") is True:
        return True
    if _env_flag("GRAVITY_USE_VPN") is True:
        return True
    return False


def force_ipv4_for_downloads(vpn_up: Optional[bool] = None) -> bool:
    """Force IPv4 only when VPN routing is requested (Surfshark IPv6 / Astrill tun0)."""
    if _env_flag("GRAVITY_FORCE_IPV6") is True:
        return False
    forced = _env_flag("GRAVITY_FORCE_IPV4")
    if forced is False:
        return False
    if forced is True:
        return True
    if vpn_up is False:
        return False
    return vpn_route_requested()


def vpn_compat_ytdlp_args(
    vpn_up: Optional[bool] = None,
    source_address: Optional[str] = None,
) -> List[str]:
    want = vpn_route_requested() or (vpn_up is True)
    ipv4 = force_ipv4_for_downloads(vpn_up=vpn_up if vpn_up is not None else want)
    if source_address is None and want:
        source_address = vpn_tunnel_ipv4_for_provider(vpn_provider()) or vpn_tunnel_ipv4()
    elif source_address is None:
        source_address = None
    timeout_default = "30" if source_address else "20"
    args: List[str] = [
        "--socket-timeout",
        _env_str("GRAVITY_SOCKET_TIMEOUT", timeout_default),
    ]
    if ipv4 or source_address:
        args.append("--force-ipv4")
    if source_address:
        # Only when VPN routing is requested (China / geo-restricted).
        args += ["--source-address", source_address]
    extra = youtube_player_client_args()
    if extra and (ipv4 or source_address or os.environ.get("GRAVITY_YT_EXTRACTOR_ARGS")):
        args += ["--extractor-args", extra, "--remote-components", "ejs:github"]
    elif ipv4 or source_address:
        args += [
            "--extractor-args", youtube_player_client_args(),
            "--remote-components", "ejs:github",
        ]
    return args


def vpn_compat_ytdlp_opts(
    vpn_up: Optional[bool] = None,
    source_address: Optional[str] = None,
) -> Dict[str, Any]:
    want = vpn_route_requested() or (vpn_up is True)
    ipv4 = force_ipv4_for_downloads(vpn_up=vpn_up if vpn_up is not None else want)
    if source_address is None and want:
        source_address = vpn_tunnel_ipv4_for_provider(vpn_provider()) or vpn_tunnel_ipv4()
    elif source_address is None:
        source_address = None
    timeout_default = "30" if source_address else "20"
    opts: Dict[str, Any] = {
        "socket_timeout": float(_env_str("GRAVITY_SOCKET_TIMEOUT", timeout_default)),
    }
    if source_address:
        opts["source_address"] = source_address
    extra = os.environ.get("GRAVITY_YT_EXTRACTOR_ARGS")
    if (ipv4 or source_address) and (not extra or not extra.strip()):
        opts["extractor_args"] = {"youtube": {"player_client": youtube_player_clients()}}
    elif extra and extra.strip() and (ipv4 or source_address):
        opts["extractor_args"] = {"youtube": {"player_client": youtube_player_clients()}}
    return opts


def _cookies_file_path() -> Optional[str]:
    env = os.environ.get("GRAVITY_COOKIES_FILE")
    if env:
        p = Path(env.strip())
        if p.is_file():
            return str(p)
    default = Path.home() / ".config" / "gravity-desktop" / "cookies.txt"
    return str(default) if default.is_file() else None


def _browser_cookie_db_exists(browser: str) -> bool:
    home = Path.home()
    b = browser.lower().split(":")[0].split("+")[0]
    chromium_paths = {
        "brave": [home / ".config" / "BraveSoftware" / "Brave-Browser" / "Default" / "Cookies"],
        "chromium": [home / ".config" / "chromium" / "Default" / "Cookies"],
        "chrome": [home / ".config" / "google-chrome" / "Default" / "Cookies"],
        "edge": [home / ".config" / "microsoft-edge" / "Default" / "Cookies"],
        "opera": [
            home / ".config" / "opera" / "Default" / "Cookies",
            home / ".config" / "opera-stable" / "Default" / "Cookies",
        ],
        "vivaldi": [home / ".config" / "vivaldi" / "Default" / "Cookies"],
        "whale": [
            home / ".config" / "naver-whale" / "Default" / "Cookies",
            home / ".config" / "Naver Whale" / "Default" / "Cookies",
        ],
    }
    if b in chromium_paths:
        return any(p.is_file() for p in chromium_paths[b])
    if b == "safari":
        return (home / "Library" / "Cookies" / "Cookies.binarycookies").is_file()
    if b == "firefox":
        for base in (home / "snap" / "firefox" / "common" / ".mozilla" / "firefox",
                     home / ".mozilla" / "firefox"):
            if not base.is_dir():
                continue
            for prof in base.iterdir():
                if prof.is_dir() and ("default" in prof.name.lower()):
                    if (prof / "cookies.sqlite").is_file():
                        return True
    return False


def _resolve_cookies_browser() -> Optional[str]:
    env = os.environ.get("GRAVITY_COOKIES_BROWSER")
    if env and env.strip():
        return env.strip()
    for candidate in ("brave", "chromium", "chrome", "edge", "firefox", "opera", "vivaldi", "whale", "safari"):
        if _browser_cookie_db_exists(candidate):
            return candidate
    return None


def _resolve_cookie_source(use_private: bool = True) -> Optional[Dict[str, str]]:
    vpn = vpn_route_requested()
    if not use_private and not vpn:
        return None
    f = _cookies_file_path()
    browser = _resolve_cookies_browser()
    # YouTube: cookies.txt signed in; Brave DB still LOGIN_REQUIRED on Shorts.
    if f and Path(f).is_file():
        pass  # fall through; YouTube prefers file below
    # VPN datacenter IPs 403 without a live browser session; skip stale Netscape dumps.
    if vpn and browser and not f:
        return {"kind": "browser", "value": browser}
    if f and browser:
        try:
            age = time.time() - Path(f).stat().st_mtime
        except OSError:
            age = 0
        if age > 2 * 24 * 3600:
            return {"kind": "browser", "value": browser}
    if f:
        return {"kind": "file", "value": f}
    if browser:
        return {"kind": "browser", "value": browser}
    return None


def _output_indicates_403(lines: List[str]) -> bool:
    for line in lines:
        if not line:
            continue
        l = line.lower()
        if any(x in l for x in (
            "403", "forbidden", "http error 403", "rate limit", "rate-limit",
            "too many requests", "429", "precondition check failed",
            "not available in your country", "geo restrict", "geo-restrict",
            "blocked in your region", "copyright grounds",
        )):
            return True
        if "ip" in l and any(x in l for x in ("block", "restrict", "banned")):
            return True
    return False


def _ytdlp_js_runtime() -> Optional[str]:
    rt = check_js_runtime()
    if rt:
        return rt
    deno = Path.home() / ".deno" / "bin" / "deno"
    if deno.is_file():
        return "deno"
    return None


def _build_ytdlp_cli_base(
    url: str, use_private: bool = True, impersonate: Optional[str] = None
) -> List[str]:
    """CLI args shared with GravityDesktop addBaseYtDlpArgs."""
    args = [resolve_ytdlp_path()]
    args += [
        "--min-sleep-interval", _env_str("GRAVITY_MIN_SLEEP_INTERVAL", _env_str("GRAVITY_SLEEP_INTERVAL", "3")),
        "--max-sleep-interval", _env_str("GRAVITY_MAX_SLEEP_INTERVAL", "12"),
        "--sleep-requests", _env_str("GRAVITY_SLEEP_REQUESTS", "1"),
        "--retries", _env_str("GRAVITY_RETRIES", "15"),
        "--fragment-retries", _env_str("GRAVITY_FRAGMENT_RETRIES", "15"),
        "--extractor-retries", _env_str("GRAVITY_EXTRACTOR_RETRIES", "5"),
        "--retry-sleep", "http:exp=1:" + _env_str("GRAVITY_HTTP_RETRY_SLEEP_MAX", "60"),
        "--retry-sleep", "fragment:exp=1:30",
        "--retry-sleep", "extractor:exp=1:20",
        "--concurrent-fragments", "1",
    ]
    limit_rate = os.environ.get("GRAVITY_LIMIT_RATE")
    if limit_rate and limit_rate.strip():
        args += ["--limit-rate", limit_rate.strip()]
    proxy = _resolve_proxy_url()
    if proxy:
        args += ["--proxy", proxy]
        geo = os.environ.get("GRAVITY_GEO_PROXY") or proxy
        args += ["--geo-verification-proxy", geo.strip()]
    args += vpn_compat_ytdlp_args()
    if _is_youtube_url(url):
        extra = youtube_player_client_args()
        if extra:
            args += ["--extractor-args", extra]
        args += ["--remote-components", "ejs:github"]
    if impersonate is None:
        impersonate = (os.environ.get("GRAVITY_IMPERSONATE") or "chrome").strip()
    # YouTube JS/TLS challenge: do not impersonate Chrome. Identify as GravityDesktop.
    if _is_youtube_url(url):
        impersonate = "off"
        args += ["--user-agent", "GravityDesktop/1.1.9"]
    if str(impersonate).lower() not in ("0", "off", "none", "", "false"):
        args += ["--impersonate", "chrome" if impersonate in (True, "1", "true") else str(impersonate)]
    js_rt = _ytdlp_js_runtime()
    if js_rt:
        args += ["--js-runtimes", js_rt]
    cookie_src = _resolve_cookie_source(True if _is_youtube_url(url) else use_private)
    if cookie_src:
        if cookie_src["kind"] == "file":
            args += ["--cookies", cookie_src["value"]]
        else:
            args += ["--cookies-from-browser", cookie_src["value"]]
    args += ["--no-keep-fragments"]
    return args


_JS_RUNTIMES_IS_DICT: Optional[bool] = None


def _js_runtimes_param(runtime: str, cfg: Dict[str, Any]) -> Any:
    """apt yt-dlp 2024 wants a list; 2026 wants {runtime: {config}}. Probe once."""
    global _JS_RUNTIMES_IS_DICT
    if _JS_RUNTIMES_IS_DICT is None:
        try:
            import yt_dlp
            yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "js_runtimes": {runtime: {}}})
            _JS_RUNTIMES_IS_DICT = True
        except Exception:
            _JS_RUNTIMES_IS_DICT = False
    if _JS_RUNTIMES_IS_DICT:
        return {runtime: cfg}
    return [runtime]


def _ytdlp_api_extra_opts(use_private: bool = True) -> Dict[str, Any]:
    """Python yt_dlp options mirroring GravityDesktop pacing/proxy/cookies."""
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "sleep_interval_requests": int(_env_str("GRAVITY_SLEEP_REQUESTS", "1")),
        "sleep_interval": int(_env_str("GRAVITY_MIN_SLEEP_INTERVAL", "3")),
        "max_sleep_interval": int(_env_str("GRAVITY_MAX_SLEEP_INTERVAL", "12")),
        "retries": int(_env_str("GRAVITY_RETRIES", "15")),
        "fragment_retries": int(_env_str("GRAVITY_FRAGMENT_RETRIES", "15")),
        "extractor_retries": int(_env_str("GRAVITY_EXTRACTOR_RETRIES", "5")),
        "concurrent_fragment_downloads": 1,
    }
    proxy = _resolve_proxy_url()
    if proxy:
        opts["proxy"] = proxy
        opts["geo_verification_proxy"] = (os.environ.get("GRAVITY_GEO_PROXY") or proxy).strip()
    opts.update(vpn_compat_ytdlp_opts())
    limit_rate = os.environ.get("GRAVITY_LIMIT_RATE")
    if limit_rate and limit_rate.strip():
        opts["ratelimit"] = limit_rate.strip()
    js_rt = _ytdlp_js_runtime()
    if js_rt:
        cfg: Dict[str, Any] = {}
        if js_rt == "deno":
            deno = Path.home() / ".deno" / "bin" / "deno"
            if deno.is_file():
                cfg["path"] = str(deno)
        opts["js_runtimes"] = _js_runtimes_param(js_rt, cfg)
    cookie_src = _resolve_cookie_source(use_private)
    if cookie_src:
        if cookie_src["kind"] == "file":
            opts["cookiefile"] = cookie_src["value"]
        else:
            opts["cookiesfrombrowser"] = (cookie_src["value"],)
    return opts


def _run_ytdlp_cli(
    args: List[str],
    on_line: Optional[Any] = None,
    *,
    job_id: Optional[int] = None,
    cancel_check: Optional[Any] = None,
) -> Dict[str, Any]:
    """Run yt-dlp CLI. Optionally register under job_id so cancel can terminate it."""
    GravityRateLimiter.acquire("yt-dlp")
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if job_id is not None:
        _register_ffmpeg_proc(int(job_id), proc)
    lines: List[str] = []
    last_line = ""
    cancelled = False
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            last_line = line
            lines.append(line)
            if on_line:
                on_line(line)
            if cancel_check and cancel_check():
                cancelled = True
                try:
                    proc.terminate()
                except Exception:
                    pass
                break
        rc = proc.wait(timeout=15) if cancelled else proc.wait()
    except Exception:
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass
        rc = proc.poll() if proc.poll() is not None else 1
    finally:
        if job_id is not None:
            _unregister_ffmpeg_proc(int(job_id))
    return {
        "exit_code": rc if rc is not None else 1,
        "last_line": last_line,
        "lines": lines,
        "cancelled": cancelled,
    }


def _parse_ytdlp_progress(line: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def _direct_dl_set(**kwargs: Any) -> None:
    with _direct_dl_lock:
        _direct_dl_state.update(kwargs)


def _vacuum_append(msg: str, detail: bool = False) -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"{ts}  {msg}"
    with _direct_dl_lock:
        log = list(_direct_dl_state.get("log") or [])
        log.append(line)
        _direct_dl_state["log"] = log[-100:]
        if detail:
            _direct_dl_state["message"] = msg[:120]
    try:
        VACUUM_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with VACUUM_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "msg": msg}) + "\n")
    except Exception:
        pass


def _vacuum_media_file(path: Path, detail: bool = False) -> str:
    """Strip JS/HTML polyglots and metadata from img/vid/gif (opt-in). TLS/JA3 is request-side."""
    if not path.is_file():
        return ""
    before = path.stat().st_size
    _vacuum_append(f"start {path.name} {before}B", detail)
    try:
        head = path.read_bytes()[:256]
        s = head.decode("latin-1", "replace").lstrip().lower()
        if s.startswith(("<!doctype html", "<html", "<script", "<?php")):
            _vacuum_append(
                "skip vacuum — file is HTML/JS (player page), not img/vid/gif; "
                "this is not yt-dlp js_runtimes",
                detail,
            )
            return " vacuum:skip-not-media"
        data = path.read_bytes()
        cut = None
        if len(data) > 16 and data[0:2] == b"\xff\xd8":
            for i in range(len(data) - 2, 1, -1):
                if data[i : i + 2] == b"\xff\xd9":
                    cut = i + 2
                    break
        elif len(data) > 6 and data[0:3] == b"GIF":
            for i in range(len(data) - 1, 5, -1):
                if data[i] == 0x3B:
                    cut = i + 1
                    break
        elif len(data) > 16 and data[0] == 0x89 and data[1:4] == b"PNG":
            iend = b"IEND\xaeB`\x82"
            idx = data.rfind(iend)
            if idx >= 8:
                cut = idx + 8
        if cut and 32 < cut < len(data):
            path.write_bytes(data[:cut])
            _vacuum_append(f"truncate trailer {len(data)} → {cut}B", detail)
        else:
            _vacuum_append("trailer ok (no polyglot tail)", detail)
        ffmpeg = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
        tmp = path.with_suffix(path.suffix + ".vac")
        name = path.name.lower()
        cmd = [
            ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-i", str(path), "-map_metadata", "-1", "-fflags", "+bitexact",
        ]
        if name.endswith(".gif"):
            cmd += ["-an", "-c:v", "gif", str(tmp)]
        else:
            cmd += ["-c", "copy", "-movflags", "+faststart", str(tmp)]
        _vacuum_append("ffmpeg -map_metadata -1 copy", detail)
        rc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300).returncode
        if rc != 0 or not tmp.is_file() or tmp.stat().st_size < 32:
            _vacuum_append(f"copy failed rc={rc} — re-encode fallback", detail)
            if tmp.exists():
                tmp.unlink()
            cmd = [
                ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                "-i", str(path), "-map_metadata", "-1",
            ]
            if name.endswith(".gif"):
                cmd += ["-an", str(tmp)]
            else:
                cmd += ["-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart", str(tmp)]
            rc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900).returncode
        if rc == 0 and tmp.is_file() and tmp.stat().st_size > 32:
            tmp.replace(path)
            _vacuum_append(f"replaced {path.name} ({path.stat().st_size}B)", detail)
        elif tmp.exists():
            tmp.unlink()
            _vacuum_append("ffmpeg produced nothing — kept original", detail)
        after = path.stat().st_size if path.is_file() else 0
        dropped = max(0, before - after)
        _vacuum_append(f"done dropped={dropped}B result={'stripped' if dropped else 'clean'}", detail)
        return f" vacuum:-{dropped}B" if dropped else " vacuum:clean"
    except Exception as e:
        _vacuum_append(f"skip: {e}", detail)
        return " vacuum:skip"


def api_vacuum_log(limit: int = 40) -> Dict[str, Any]:
    with _direct_dl_lock:
        live = list(_direct_dl_state.get("log") or [])
        flags = {
            "vacuum": bool(_direct_dl_state.get("vacuum")),
            "tls_ja3": bool(_direct_dl_state.get("tls_ja3")),
            "detail": bool(_direct_dl_state.get("detail")),
        }
    tail: List[str] = []
    if VACUUM_LOG_PATH.is_file():
        try:
            lines = VACUUM_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = lines[-limit:]
        except Exception:
            pass
    return {"ok": True, "log": live, "file_tail": tail, "file": str(VACUUM_LOG_PATH), **flags}


def api_vacuum_log_clear() -> Dict[str, Any]:
    with _direct_dl_lock:
        _direct_dl_state["log"] = []
        _direct_dl_state["message"] = "vacuum log cleared"
    try:
        if VACUUM_LOG_PATH.is_file():
            VACUUM_LOG_PATH.write_text("", encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "log": [], "file_tail": [], "file": str(VACUUM_LOG_PATH)}


def direct_download_status() -> Dict[str, Any]:
    with _direct_dl_lock:
        return dict(_direct_dl_state)


def _job_is_cancelled(job_id: int) -> bool:
    conn = get_db()
    job = load_job(conn, job_id)
    conn.close()
    return bool(job and job.status == "cancelled")


def _register_ffmpeg_proc(job_id: int, proc: subprocess.Popen) -> None:
    with _active_ffmpeg_lock:
        old = _active_ffmpeg_procs.get(job_id)
        if old and old.poll() is None:
            try:
                old.terminate()
            except Exception:
                pass
        _active_ffmpeg_procs[job_id] = proc


def _unregister_ffmpeg_proc(job_id: int) -> None:
    with _active_ffmpeg_lock:
        _active_ffmpeg_procs.pop(job_id, None)


def _stop_job_processes(job_id: int) -> None:
    with _active_ffmpeg_lock:
        proc = _active_ffmpeg_procs.pop(job_id, None)
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _as_local_media_path(url_or_path: str) -> Optional[Path]:
    """If url is an existing local media file (or file:// URI), return Path."""
    if not url_or_path or not str(url_or_path).strip():
        return None
    s = str(url_or_path).strip()
    if s.startswith("file://"):
        s = unquote(s[7:])
    # Reject obvious remote URLs
    if "://" in s and not s.startswith("file://"):
        return None
    p = Path(s).expanduser()
    try:
        p = p.resolve()
    except Exception:
        p = Path(s).expanduser()
    if not p.is_file():
        return None
    if p.suffix.lower() not in (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".gif", ".ts"):
        return None
    return p


# Pipeline download format: DASH by height, then H.264 convert (no 360p combined).
PIPELINE_YTDLP_FORMAT = ytdlp_format_for_height(2160) + "/" + YTDLP_H264_FORMAT + "/bestvideo*+bestaudio/best"


def run_download(job: Job, conn: sqlite3.Connection, cfg: dict) -> Path:
    """Download via bundled yt-dlp CLI (same path as direct H.264 / GravityDesktop).

    Uses CLI rather than the Python API so we pick up the bundled yt-dlp binary
    (newer extractors) + cookies/js-runtime flags that direct mode already uses.
    """
    ensure_js_runtime(interactive=False)
    from yt_dlp.utils import DownloadCancelled

    if _job_is_cancelled(job.id):
        raise DownloadCancelled("job cancelled before download")

    # Local path pasted as "URL" → treat as convert-only source
    local = _as_local_media_path(job.url or "")
    if local is not None:
        job.source_file = str(local)
        job.title = job.title if job.title and job.title != "Untitled" else local.stem
        job.status = "converting"
        job.stage = "convert"
        job.progress = 50.0
        save_job(conn, job)
        return local

    job.status = "downloading"
    job.stage = "download"
    job.progress = 0
    save_job(conn, job)

    out_dir = Path(job.output_path).parent if job.output_path else XDG_CACHE
    out_dir.mkdir(parents=True, exist_ok=True)

    base = sanitize_filename(job.title or f"video-{job.id}")
    # Unique per-job stem avoids collisions when title is still "Untitled"
    stem = f"{base}-{job.id}"
    outtmpl = str(out_dir / f"{stem}.%(ext)s")
    use_private = os.environ.get("GRAVITY_USE_COOKIES", "1") != "0"
    meta = job.metadata if isinstance(job.metadata, dict) else {}
    target_h = parse_target_height(meta.get("target_height") or preset_target_height(job.preset))
    fmt = ytdlp_format_for_height(target_h)

    def on_line(line: str) -> None:
        pct = _parse_ytdlp_progress(line)
        if pct is not None:
            job.progress = max(0.0, min(49.9, pct * 0.5))
            job.stage = "download"
            save_job(conn, job)

    def cancel_check() -> bool:
        return _job_is_cancelled(job.id)

    before = {p.resolve() for p in out_dir.glob(f"{stem}.*") if p.is_file()}

    list_args = _build_ytdlp_cli_base(job.url, use_private) + ["--list-formats", job.url]
    list_result = _run_ytdlp_cli(list_args, job_id=job.id, cancel_check=cancel_check)
    generic = not _is_youtube_url(job.url)
    picked = select_format_from_list(list_result.get("lines") or [], False, generic, target_h)
    if picked:
        fmt = picked
    job.metadata.setdefault("technical", {})["ytdlp_format"] = fmt
    job.metadata["target_height"] = target_h
    save_job(conn, job)

    dl_args = _build_ytdlp_cli_base(job.url, use_private)
    dl_args += [
        "-f", fmt,
        "--merge-output-format", "mp4",
        "--newline",
        "-o", outtmpl,
        job.url,
    ]

    max_retries = int(os.environ.get("GRAVITY_403_RETRIES", "2"))
    attempt = 0
    dl_result = _run_ytdlp_cli(dl_args, on_line=on_line, job_id=job.id, cancel_check=cancel_check)
    while (
        dl_result["exit_code"] != 0
        and not dl_result.get("cancelled")
        and _output_indicates_403(dl_result["lines"])
        and attempt < max_retries
    ):
        if _job_is_cancelled(job.id):
            break
        attempt += 1
        GravityRateLimiter.on_403()
        cool = GravityRateLimiter.cooldown_seconds_remaining()
        job.stage = f"cooldown {cool}s"
        save_job(conn, job)
        dl_result = _run_ytdlp_cli(dl_args, on_line=on_line, job_id=job.id, cancel_check=cancel_check)

    # Format fallback: retry with broader "best" if primary format unavailable
    if (
        dl_result["exit_code"] != 0
        and not dl_result.get("cancelled")
        and not _job_is_cancelled(job.id)
    ):
        joined = "\n".join(dl_result.get("lines") or [])
        if "format is not available" in joined.lower() or "requested format" in joined.lower():
            job.stage = "download-fallback"
            save_job(conn, job)
            fb_args = _build_ytdlp_cli_base(job.url, use_private)
            fb_args += [
                "-f", "bestvideo*+bestaudio/best/best",
                "--merge-output-format", "mp4",
                "--newline",
                "-o", outtmpl,
                job.url,
            ]
            dl_result = _run_ytdlp_cli(fb_args, on_line=on_line, job_id=job.id, cancel_check=cancel_check)

    if _job_is_cancelled(job.id) or dl_result.get("cancelled"):
        job.status = "cancelled"
        job.stage = "cancelled"
        job.finished = now_utc_iso()
        save_job(conn, job)
        raise DownloadCancelled("job cancelled during download")

    if dl_result["exit_code"] != 0:
        lines = dl_result.get("lines") or []
        if _output_indicates_403(lines):
            GravityRateLimiter.on_403()
            err = "HTTP 403 / IP restricted — try cookies (GRAVITY_COOKIES_BROWSER) or GRAVITY_PROXY"
        else:
            err = dl_result.get("last_line") or "yt-dlp failed"
            # Prefer the most informative error line
            for line in reversed(lines):
                if line and ("ERROR" in line or "error" in line.lower()):
                    err = line.strip()
                    break
        raise RuntimeError(err)

    GravityRateLimiter.on_success()

    # Resolve output file
    after = [p for p in out_dir.glob(f"{stem}.*") if p.is_file() and p.suffix.lower() in (
        ".mp4", ".mkv", ".webm", ".m4a"
    )]
    new_files = [p for p in after if p.resolve() not in before]
    candidates = new_files or after
    if not candidates:
        # last resort: newest media in out_dir matching stem prefix
        candidates = sorted(
            [p for p in out_dir.glob(f"{stem}*") if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    if not candidates:
        raise RuntimeError(f"Download finished but output not found under {out_dir} (stem={stem})")

    downloaded = max(candidates, key=lambda p: p.stat().st_mtime)

    # Best-effort title refresh via extract_info (no download)
    if not job.title or job.title == "Untitled":
        try:
            import yt_dlp
            with yt_dlp.YoutubeDL({"quiet": True, **_ytdlp_api_extra_opts(use_private)}) as ydl:
                info = ydl.extract_info(job.url, download=False)
            if info and info.get("title"):
                job.title = info["title"]
                job.metadata["source"] = {
                    "title": job.title,
                    "duration": info.get("duration"),
                    "uploader": info.get("uploader"),
                }
        except Exception:
            job.title = job.title or downloaded.stem

    job.progress = 50.0
    job.stage = "convert"
    save_job(conn, job)
    return downloaded


def _yt_progress_hook(d: dict, job: Job, conn: sqlite3.Connection):
    if d.get("status") == "downloading":
        pct = d.get("_percent_str", "0%").replace("%", "").strip()
        try:
            job.progress = float(pct) * 0.5  # download is first 50%
        except Exception:
            pass
        job.stage = "download"
        save_job(conn, job)


def generate_thumbnail(video_path: Path, thumb_path: Path, seek_time="00:01:30"):
    """Generate a thumbnail for NLS Visualist preview. Rule #2 no eval."""
    try:
        subprocess.check_call([
            "ffmpeg", "-y", "-ss", seek_time, "-i", str(video_path),
            "-vframes", "1", "-vf", "scale=320:-1", "-q:v", "3",
            str(thumb_path)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def prepare_for_noise_gravity(video_path: Path, output_h264: Optional[Path] = None) -> Path:
    """Prepare H.264 video for Noise Protocol transport (gravity mode).
    Analog to SCIS 'prepare-for-noise' for VP56: extract raw elementary stream
    so packets/NALs can be individually protected by Noise CipherState.
    Rule #1 no kill, Rule #2 no eval. Uses ffmpeg demux only.
    """
    if output_h264 is None:
        output_h264 = video_path.with_suffix(".h264")
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-c:v", "copy",
        "-f", "h264",
        str(output_h264)
    ]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_h264


def prepare_interstellar_nonlinear_gravity(video_path: Path) -> Path:
    """Use SCIS noiseprotocol-vcodec + FFMPEG for VP56 'origin form follows function' look
    for interstellar|nonlineari Visualist content (nonlinear time, space, hack reality aesthetics).
    Then prepare raw VP56 packets for Noise Protocol gravity transport (SCIS style).
    Integrates with the monitor pipeline for artistic NLS Visualist data.
    """
    vcodec_bin = "/home/nlsrecords/Downloads/SCIS/dist-newstyle/build/x86_64-linux/ghc-9.6.7/noiseprotocol-0.1.0.0/x/noiseprotocol-vcodec/build/noiseprotocol-vcodec/noiseprotocol-vcodec"
    vp56_out = video_path.with_suffix(".vp6f.interstellar.mov")
    raw_packets = video_path.with_suffix(".vp56-gravity-packets.bin")

    try:
        # Encode/transcode to VP56 origin look (legacy for visualist, nonlinear feel)
        # Using SCIS vcodec for encode-vp56 --variant vp6f (or transcodeOrigin style)
        subprocess.check_call([
            vcodec_bin, "encode-vp56", "--variant", "vp6f",
            str(video_path), str(vp56_out)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Prepare for noise gravity transport (extract raw like SCIS)
        subprocess.check_call([
            "ffmpeg", "-y", "-i", str(vp56_out),
            "-c:v", "copy", "-f", "rawvideo", str(raw_packets)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        return raw_packets
    except Exception as e:
        print(f"Interstellar/nonlineari gravity VP56 prep note: {e} (fallback to H264 gravity)")
        return prepare_for_noise_gravity(video_path)


def get_storage_memory_category(job: Job) -> dict:
    """Storage memory category for NLS Visualist data.
    Includes zone and memory|location|zone|V|Bandwidth.
    Different for interstellar|nonlineari vs default.
    """
    title_lower = (job.title or "").lower()
    is_inter = job.metadata.get("interstellar_nonlinear") or "interstellar" in title_lower or "nonlineari" in title_lower or job.preset == "interstellar-nonlinear"
    if is_inter:
        return {
            "zone": "interstellar-zone-alpha",
            "memory": "16GB",
            "location": "nls-visualist-dc-1",
            "zone": "interstellar-zone-alpha",  # repeated zone as per spec
            "V": "vp56-vol-1999",
            "Bandwidth": "10Gbps"
        }
    else:
        return {
            "zone": "default-zone",
            "memory": "8GB",
            "location": "local-dc",
            "zone": "default-zone",
            "V": "h264-vol",
            "Bandwidth": "1Gbps"
        }


def _verify_media_playable(path: Path, sample_sec: float = 2.0) -> Dict[str, Any]:
    """Headless decode probe — returns ok=False if ffmpeg cannot decode sample frames."""
    if not path.is_file() or path.stat().st_size < 1024:
        return {"ok": False, "error": f"missing or tiny file: {path}"}
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-v", "error",
                "-t", str(sample_sec),
                "-i", str(path),
                "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            timeout=max(30.0, sample_sec * 10),
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or f"ffmpeg exit {proc.returncode}").strip()
            # Keep last meaningful line
            lines = [ln for ln in err.splitlines() if ln.strip()]
            return {"ok": False, "error": (lines[-1] if lines else err)[:500], "rc": proc.returncode}
        return {"ok": True, "size": path.stat().st_size}
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}


def _remove_job_outputs(job: Job, *, keep_log: bool = True) -> None:
    """Delete incomplete/corrupt visualist outputs for a job before re-encode."""
    paths: List[Path] = []
    if job.output_path:
        p = Path(job.output_path)
        paths.extend([
            p,
            p.with_suffix(".partial.mp4"),
            Path(str(p) + ".partial"),
            p.with_suffix(".thumb.jpg"),
            Path(str(p) + ".thumb.jpg"),
            p.with_suffix(".nlsvis.json"),
            Path(str(p) + ".nlsvis.json"),
        ])
        # also common partial next to final
        paths.append(p.parent / (p.stem + ".partial.mp4"))
    for cand in paths:
        try:
            if cand.is_file():
                cand.unlink()
        except Exception:
            pass
    if not keep_log and job.log_path:
        try:
            Path(job.log_path).unlink(missing_ok=True)
        except Exception:
            pass


def probe_audio_info(path: Path) -> Dict[str, Any]:
    """Return first-audio channel count/layout. channels=0 means no audio stream."""
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=channels,channel_layout,codec_name",
                "-of", "json",
                str(path),
            ],
            text=True,
            timeout=20,
        )
        streams = (json.loads(out) or {}).get("streams") or []
        if not streams:
            return {"channels": 0, "channel_layout": None, "codec_name": None}
        s = streams[0]
        ch = s.get("channels")
        try:
            ch_n = int(ch) if ch is not None else 0
        except (TypeError, ValueError):
            ch_n = 0
        layout = s.get("channel_layout") or None
        if layout in ("", "unknown"):
            layout = None
        return {
            "channels": ch_n,
            "channel_layout": layout,
            "codec_name": s.get("codec_name"),
        }
    except Exception:
        return {"channels": None, "channel_layout": None, "codec_name": None}


def _nls_codec_bitrate_k(channels: int) -> int:
    """Bitrate follows channel function (φ-scaled stages, snapped to AAC rates)."""
    table = {1: 128, 2: 192, 3: 192, 4: 256, 5: 320, 6: 448, 7: 512, 8: 640}
    if channels <= 0:
        return 0
    return table.get(min(int(channels), 8), 192)


def _pan_identity(layout: str, n: int) -> str:
    maps = "|".join(f"c{i}=c{i}" for i in range(n))
    return f"pan={layout}|{maps}"


def nls_codec_plan(
    channels: Optional[int],
    layout: Optional[str] = None,
) -> Dict[str, Any]:
    """NLS Codec (nonlineari) — form follows function, scale follows φ.

    Keep stereo, quad, 5.1 (6ch), 7.1 (8ch / 8.1-style). Never stereo-downmix
    surround. Unlabeled 6/8ch (ffmpeg 6.1 AAC exit 234) get pan-identity onto
    a named layout so every discrete channel is kept.
    """
    try:
        ch_n = int(channels) if channels is not None else 0
    except (TypeError, ValueError):
        ch_n = 0
    src_layout = (layout or "").strip() or None
    if src_layout in ("unknown",):
        src_layout = None
    encode_ch = ch_n
    if encode_ch > 8:
        encode_ch = 8  # AAC LC has no 8.1 / 7.1.2 — keep first 8 as 7.1
    named = NLS_LAYOUT_BY_CHANNELS.get(encode_ch) if encode_ch else None
    need_pan = bool(
        encode_ch
        and named
        and (src_layout not in NLS_AAC_NAMED_LAYOUTS or encode_ch != ch_n)
    )
    bitrate = f"{_nls_codec_bitrate_k(encode_ch)}k" if encode_ch else None
    ffmpeg: List[str] = []
    if encode_ch:
        ffmpeg += ["-c:a", "aac", "-b:a", bitrate or "192k"]
        if need_pan and named:
            ffmpeg += ["-af", _pan_identity(named, encode_ch)]
        ffmpeg += [
            "-metadata:s:a:0",
            f"handler_name={NLS_CODEC_LABEL} ({NLS_CODEC_ALIAS})",
        ]
    return {
        "name": NLS_CODEC_NAME,
        "label": NLS_CODEC_LABEL,
        "alias": NLS_CODEC_ALIAS,
        "channels": encode_ch,
        "layout": named,
        "source_layout": src_layout,
        "bitrate": bitrate,
        "phi": PHI,
        "phi_inv": PHI_INV,
        "ffmpeg": ffmpeg,
    }


def gravity_channel_labels(channels: int) -> Tuple[str, ...]:
    """Discrete speaker labels for Gravity split. Form follows channel count."""
    try:
        n = int(channels)
    except (TypeError, ValueError):
        n = 0
    if n > 8:
        n = 8
    return GRAVITY_CHANNEL_LABELS.get(n, ())


def prepare_audio_gravity_channels(
    media_path: Path,
    dest_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Split discrete channels for Gravity/Noise transport, mix back for playback.

    Analog packets are WAV 48k/24 (same as WYHIWYREC). Unlabeled 6/8ch get
    pan-identity onto 5.1/7.1 first so ffmpeg channelsplit has a named layout.
    """
    src = Path(media_path)
    if not src.is_file():
        return {"ok": False, "reason": "missing", "path": str(src)}
    info = probe_audio_info(src)
    plan = nls_codec_plan(info.get("channels"), info.get("channel_layout"))
    n = int(plan.get("channels") or 0)
    layout = plan.get("layout")
    labels = gravity_channel_labels(n)
    if not n or not layout or not labels:
        return {"ok": False, "reason": "no_audio", "channels": n}
    out_dir = Path(dest_dir) if dest_dir else Path(str(src) + ".gravity")
    out_dir.mkdir(parents=True, exist_ok=True)
    split_paths = [out_dir / f"{lab}.wav" for lab in labels]
    pads = "".join(f"[{lab}]" for lab in labels)
    pan = _pan_identity(layout, n)
    fc = f"[0:a]{pan},channelsplit=channel_layout={layout}{pads}"
    split_cmd: List[str] = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src), "-filter_complex", fc,
    ]
    for lab, p in zip(labels, split_paths):
        split_cmd += ["-map", f"[{lab}]", "-c:a", "pcm_s24le", "-ar", "48000", str(p)]
    try:
        subprocess.check_call(split_cmd, timeout=120)
    except Exception as e:
        return {"ok": False, "reason": "split_failed", "error": str(e)}
    mix_path = out_dir / "mix.wav"
    mix_cmd: List[str] = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for p in split_paths:
        mix_cmd += ["-i", str(p)]
    ins = "".join(f"[{i}:a]" for i in range(n))
    mix_cmd += [
        "-filter_complex",
        f"{ins}amerge=inputs={n},aformat=channel_layouts={layout}[a]",
        "-map", "[a]", "-c:a", "pcm_s24le", "-ar", "48000", str(mix_path),
    ]
    try:
        subprocess.check_call(mix_cmd, timeout=120)
    except Exception as e:
        return {"ok": False, "reason": "mix_failed", "error": str(e), "split": [str(p) for p in split_paths]}
    sidecar = Path(str(src) + ".gravity.json")
    payload = {
        "ok": True,
        "name": NLS_CODEC_NAME,
        "label": NLS_CODEC_LABEL,
        "alias": NLS_CODEC_ALIAS,
        "layout": layout,
        "channels": n,
        "labels": list(labels),
        "split": [str(p) for p in split_paths],
        "mix": str(mix_path),
        "dir": str(out_dir),
        "source": str(src),
        "phi_inv": PHI_INV,
    }
    try:
        sidecar.write_text(json.dumps(payload, indent=2) + "\n")
        payload["sidecar"] = str(sidecar)
    except Exception:
        pass
    return payload


def _strip_audio_encoder_flags(args: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(args):
        if args[i] in _AUDIO_ENCODER_FLAGS:
            i += 2 if i + 1 < len(args) else 1
            continue
        out.append(args[i])
        i += 1
    return out


def build_convert_cmd(
    source: Path,
    partial_path: Path,
    preset: dict,
    audio_channels: Optional[int] = None,
    audio_layout: Optional[str] = None,
) -> List[str]:
    """ffmpeg argv for Visualist convert using NLS Codec (nonlineari) audio."""
    raw_extra = list(preset.get("ffmpeg_extra") or [])
    if audio_channels is None:
        extra = raw_extra
        plan_ffmpeg: List[str] = []
    else:
        extra = _strip_audio_encoder_flags(raw_extra)
        plan_ffmpeg = list(nls_codec_plan(audio_channels, audio_layout).get("ffmpeg") or [])
    cmd: List[str] = [
        "ffmpeg", "-y",
        "-i", str(source),
        "-map", "0:v:0",
        "-map", "0:a:0?",
        *extra,
    ]
    if preset.get("max_height"):
        cmd += ["-vf", f"scale=-2:{preset['max_height']}"]
    cmd += plan_ffmpeg
    cmd += ["-progress", "pipe:1", "-nostats", str(partial_path)]
    return cmd


def run_convert(source: Path, job: Job, conn: sqlite3.Connection, cfg: dict, preset: dict):
    """Run ffmpeg conversion with live progress parsing.

    Writes to a .partial.mp4 then renames atomically so a killed/requeued encode
    cannot leave a 'completed-looking' corrupt file at the final path.
    """
    job.status = "converting"
    job.stage = "convert"
    job.progress = 50.0
    # Clear prior requeue/retry noise so Jobs tab does not show false failure
    job.error = None
    save_job(conn, job)

    root = ensure_visualist_root(cfg)
    safe_title = sanitize_filename(job.title or f"job-{job.id}")
    final_name = f"{safe_title} [{job.id}].mp4"
    final_path = root / final_name
    final_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = final_path.with_suffix(".partial.mp4")

    # Never encode into a previous corrupt final; remove stale artifacts first
    for stale in (final_path, partial_path, final_path.with_suffix(".thumb.jpg"),
                  Path(str(final_path) + ".nlsvis.json")):
        try:
            if stale.is_file():
                stale.unlink()
        except Exception:
            pass

    job.output_path = str(final_path)
    job.log_path = str(LOG_DIR / f"job-{job.id}.log")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    save_job(conn, job)

    # Get duration for % calculation
    duration = None
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(source)],
            text=True
        ).strip()
        duration = float(out)
        job.metadata.setdefault("technical", {})["source_duration"] = duration
    except Exception:
        pass

    # Explicit stream map: first video + first audio (source may list audio before video).
    # NLS Codec (nonlineari): form follows source layout; never stereo-downmix surround.
    audio = probe_audio_info(source)
    plan = nls_codec_plan(audio.get("channels"), audio.get("channel_layout"))
    cmd = build_convert_cmd(
        source,
        partial_path,
        preset,
        audio_channels=audio.get("channels"),
        audio_layout=audio.get("channel_layout"),
    )
    tech = job.metadata.setdefault("technical", {})
    tech["audio_channels"] = plan.get("channels") or audio.get("channels")
    tech["audio_layout"] = plan.get("layout") or audio.get("channel_layout")
    tech["acodec"] = NLS_CODEC_NAME
    tech["codec_label"] = NLS_CODEC_LABEL
    tech["nonlineari"] = True
    tech["nls_codec_bitrate"] = plan.get("bitrate")
    tech["phi_inv"] = PHI_INV

    log_f = open(job.log_path, "a")
    log_f.write(f"\n--- convert start {now_utc_iso()} source={source} partial={partial_path}\n")
    log_f.flush()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log_f, text=True, bufsize=1)
    _register_ffmpeg_proc(job.id, proc)

    last_update = 0.0

    try:
        while True:
            if _job_is_cancelled(job.id):
                try:
                    proc.terminate()
                except Exception:
                    pass
                job.status = "cancelled"
                job.stage = "cancelled"
                job.finished = now_utc_iso()
                save_job(conn, job)
                try:
                    if partial_path.is_file():
                        partial_path.unlink()
                except Exception:
                    pass
                return

            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                if proc.poll() is not None:
                    break
                continue

            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                if k == "out_time_ms" and duration:
                    try:
                        secs = int(v) / 1_000_000
                        conv_pct = min(100.0, (secs / duration) * 100.0)
                        overall = 50.0 + (conv_pct * 0.5)
                        job.progress = round(overall, 1)
                        job.metadata.setdefault("technical", {})["encode_speed"] = None
                    except Exception:
                        pass
                elif k == "speed":
                    job.metadata.setdefault("technical", {})["encode_speed"] = v
                elif k == "fps":
                    job.metadata.setdefault("technical", {})["encode_fps"] = v

            now = time.time()
            if now - last_update > 1.5:
                save_job(conn, job)
                last_update = now

        proc.wait()
    finally:
        try:
            log_f.close()
        except Exception:
            pass
        _unregister_ffmpeg_proc(job.id)

    if _job_is_cancelled(job.id):
        job.status = "cancelled"
        job.stage = "cancelled"
        job.finished = now_utc_iso()
        save_job(conn, job)
        try:
            if partial_path.is_file():
                partial_path.unlink()
        except Exception:
            pass
        return

    if proc.returncode != 0:
        job.status = "failed"
        job.stage = "failed"
        job.error = f"ffmpeg exited with {proc.returncode}"
        job.finished = now_utc_iso()
        save_job(conn, job)
        try:
            if partial_path.is_file():
                partial_path.unlink()
        except Exception:
            pass
        return

    if not partial_path.is_file() or partial_path.stat().st_size < 1024:
        job.status = "failed"
        job.stage = "failed"
        job.error = "ffmpeg finished but partial output missing/empty"
        job.finished = now_utc_iso()
        save_job(conn, job)
        return

    # Atomic promote partial → final only after encode OK
    try:
        if final_path.is_file():
            final_path.unlink()
        partial_path.replace(final_path)
    except Exception as e:
        job.status = "failed"
        job.stage = "failed"
        job.error = f"failed to promote partial output: {e}"
        job.finished = now_utc_iso()
        save_job(conn, job)
        return

    # Headless decode check — never mark completed if file is unplayable
    verify = _verify_media_playable(final_path, sample_sec=2.0)
    if not verify.get("ok"):
        job.status = "failed"
        job.stage = "failed"
        job.error = f"convert produced unplayable output: {verify.get('error')}"
        job.finished = now_utc_iso()
        save_job(conn, job)
        # Keep bad file for inspection under .bad suffix
        try:
            bad = final_path.with_suffix(".bad.mp4")
            if bad.is_file():
                bad.unlink()
            final_path.rename(bad)
            job.output_path = str(bad)
            save_job(conn, job)
        except Exception:
            pass
        return

    # Success — clear any prior requeue/error note
    job.status = "completed"
    job.progress = 100.0
    job.stage = "done"
    job.error = None
    job.finished = now_utc_iso()
    job.metadata.setdefault("technical", {})["final_size"] = final_path.stat().st_size
    job.metadata["technical"]["verified_playable"] = True
    save_job(conn, job)

    # Generate thumbnail for Visualist interface
    thumb = final_path.with_suffix(".thumb.jpg")
    if generate_thumbnail(final_path, thumb):
        job.metadata["thumbnail"] = str(thumb)
        save_job(conn, job)

    # Gravity / Noise Protocol prep (using SCIS philosophy for secure transport of Visualist data)
    preset_def = DEFAULT_PRESETS.get(job.preset, {})
    do_gravity = job.metadata.get("gravity") or preset_def.get("gravity", False)
    if do_gravity:
        h264 = prepare_for_noise_gravity(final_path)
        job.metadata["gravity_prepared"] = True
        job.metadata["raw_h264_stream"] = str(h264)
        audio_g = prepare_audio_gravity_channels(final_path)
        if audio_g.get("ok"):
            job.metadata["gravity_audio"] = audio_g
            job.metadata["gravity_channels"] = audio_g.get("channels")
            job.metadata["gravity_layout"] = audio_g.get("layout")
            job.metadata["gravity_mix"] = audio_g.get("mix")
        save_job(conn, job)

    # Interstellar|nonlineari support: use SCIS noiseprotocol-vcodec + FFMPEG for VP56 origin form
    # (legacy visualist look for nonlinear/hack reality, space themes like Interstellar)
    # Then gravity prep for Noise transport
    do_vp56_gravity = preset_def.get("vp56", False) or job.metadata.get("gravity") or "interstellar" in (job.title or "").lower() or "nonlineari" in (job.title or "").lower()
    if do_vp56_gravity:
        vp56_gravity = prepare_interstellar_nonlinear_gravity(final_path)
        job.metadata["vp56_gravity_prepared"] = True
        job.metadata["vp56_raw_stream"] = str(vp56_gravity)
        job.metadata["interstellar_nonlinear"] = True
        save_job(conn, job)

    # Storage memory category (must have zone and memory|location|zone|V|Bandwidth)
    job.metadata["storage_memory_category"] = get_storage_memory_category(job)
    save_job(conn, job)

    # NLS Visualist data interface
    write_visualist_sidecar(final_path, job, cfg)

    if cfg.get("notify", True):
        desktop_notify("NLS Video Complete", f"{job.title} ready → {final_path.name}")

    # Optional: remove source download if it was a temp
    # (we keep it for now so user can re-encode with different preset)


def process_one_job(job_id: int):
    conn = get_db()
    job = load_job(conn, job_id)
    if not job or job.status not in ("pending",):
        return

    cfg = load_config()
    preset = DEFAULT_PRESETS.get(job.preset, DEFAULT_PRESETS["balanced-4k"])

    job.started = now_utc_iso()
    # Auto-promote local path URLs to source_file (convert-only)
    if not job.source_file:
        local = _as_local_media_path(job.url or "")
        if local is not None:
            job.source_file = str(local)
            if not job.title or job.title == "Untitled":
                job.title = local.stem
    save_job(conn, job)

    try:
        if job.source_file and Path(job.source_file).exists():
            downloaded = Path(job.source_file)
            job.progress = 50.0
            job.stage = "convert"
            job.status = "converting"
            save_job(conn, job)
        else:
            job.status = "downloading"
            save_job(conn, job)
            # Must stay inside try — otherwise yt-dlp failures leave zombie "downloading" rows
            downloaded = run_download(job, conn, cfg)

        if _job_is_cancelled(job_id):
            return
        run_convert(downloaded, job, conn, cfg, preset)

    except Exception as e:
        from yt_dlp.utils import DownloadCancelled
        job = load_job(conn, job_id) or job
        if isinstance(e, DownloadCancelled) or _job_is_cancelled(job_id):
            if job and job.status != "cancelled":
                job.status = "cancelled"
                job.stage = "cancelled"
                job.finished = now_utc_iso()
                save_job(conn, job)
            return
        job.status = "failed"
        job.stage = "failed"
        job.error = str(e)[:2000]
        job.finished = now_utc_iso()
        save_job(conn, job)
        if cfg.get("notify", True):
            desktop_notify("NLS Video Failed", f"{job.title}: {e}")
    finally:
        _stop_job_processes(job_id)
        conn.close()


# ----------------------------- Worker -----------------------------
def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_worker_pid_file() -> Optional[int]:
    try:
        if not WORKER_PID_PATH.is_file():
            return None
        return int(WORKER_PID_PATH.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _write_worker_pid_file() -> None:
    XDG_DATA.mkdir(parents=True, exist_ok=True)
    WORKER_PID_PATH.write_text(str(os.getpid()), encoding="utf-8")


def _clear_worker_pid_file() -> None:
    try:
        if WORKER_PID_PATH.is_file():
            existing = _read_worker_pid_file()
            if existing is None or existing == os.getpid():
                WORKER_PID_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def _job_has_live_process(job_id: int) -> bool:
    with _active_ffmpeg_lock:
        proc = _active_ffmpeg_procs.get(job_id)
        return bool(proc and proc.poll() is None)


def _parse_iso_ts(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        s = value.replace("Z", "+00:00")
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def recover_stale_jobs(
    reason: str = "worker restart",
    *,
    force: bool = False,
    max_age_sec: float = 180.0,
) -> Dict[str, Any]:
    """Requeue orphaned downloading/converting jobs so the worker can claim them again.

    Root cause of a frozen Gravity Jobs tab: worker dies mid-job → rows stay
    `downloading` forever, while the worker loop only selects `pending`.

    force=True: worker/serve startup — reclaim everything without a live process.
    force=False: skip the current job and recently-started rows (yt-dlp is not in
    _active_ffmpeg_procs during download).
    """
    requeued: List[int] = []
    skipped_live: List[int] = []
    with _worker_lock:
        current_id = _worker_state.get("current_job_id")
        worker_running = bool(_worker_state.get("running"))
    conn = get_db()
    rows = conn.execute(
        "SELECT id, status, stage, started FROM jobs WHERE status IN ('downloading', 'converting')"
    ).fetchall()
    now = now_utc_iso()
    now_ts = time.time()
    for row in rows:
        jid = int(row["id"])
        if current_id is not None and jid == int(current_id):
            skipped_live.append(jid)
            continue
        if _job_has_live_process(jid):
            skipped_live.append(jid)
            continue
        if not force and worker_running:
            started_ts = _parse_iso_ts(row["started"] if "started" in row.keys() else None)
            if started_ts is not None and (now_ts - started_ts) < max_age_sec:
                skipped_live.append(jid)
                continue
        job = load_job(conn, jid)
        if not job:
            continue
        prev = f"{job.status}/{job.stage or '?'}"
        # Kill any leftover encode and drop partial/corrupt outputs before requeue
        _stop_job_processes(jid)
        _remove_job_outputs(job, keep_log=True)
        job.status = "pending"
        job.stage = "queued"
        job.progress = 0.0
        job.started = None
        job.finished = None
        job.error = f"requeued after stale {prev} ({reason}) @ {now}"
        save_job(conn, job)
        requeued.append(jid)
    conn.close()
    with _worker_lock:
        _worker_state["recovered_ids"] = list(requeued)
    return {
        "ok": True,
        "requeued": requeued,
        "requeued_count": len(requeued),
        "skipped_live": skipped_live,
        "reason": reason,
        "force": force,
    }


def worker_status() -> Dict[str, Any]:
    """Live pipeline worker status for Gravity Jobs tab + /api/worker."""
    with _worker_lock:
        st = dict(_worker_state)
    pid_file = _read_worker_pid_file()
    external_alive = bool(pid_file and pid_file != os.getpid() and _pid_alive(pid_file))
    in_process = bool(st.get("running"))
    conn = get_db()
    pending = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'pending'").fetchone()[0]
    active = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status IN ('downloading', 'converting')"
    ).fetchone()[0]
    failed = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'failed'").fetchone()[0]
    conn.close()
    return {
        "ok": True,
        "running": in_process or external_alive,
        "in_process": in_process,
        "external": external_alive,
        "mode": st.get("mode") if in_process else ("external" if external_alive else None),
        "pid": os.getpid() if in_process else (pid_file if external_alive else None),
        "started_at": st.get("started_at"),
        "current_job_id": st.get("current_job_id"),
        "last_job_id": st.get("last_job_id"),
        "last_error": st.get("last_error"),
        "recovered_ids": st.get("recovered_ids") or [],
        "processed_count": st.get("processed_count") or 0,
        "pending_count": int(pending),
        "active_count": int(active),
        "failed_count": int(failed),
        "hint": (
            None
            if (in_process or external_alive)
            else "No worker — pipeline jobs stay pending. Start: nls-video worker  (or GRAVITY_WORKER_ENABLED=1 with gravity-serve)"
        ),
    }


def _worker_loop(mode: str = "standalone") -> None:
    """Claim pending jobs until stop flag (embedded) or forever (standalone)."""
    with _worker_lock:
        _worker_state.update(
            {
                "running": True,
                "mode": mode,
                "started_at": now_utc_iso(),
                "pid": os.getpid(),
                "stop": False,
                "last_error": None,
            }
        )
    recovered = recover_stale_jobs(reason=f"{mode} worker start", force=True)
    if recovered.get("requeued"):
        print(f"Recovered stale jobs → pending: {recovered['requeued']}")
    print(f"NLS Video worker started ({mode}). Press Ctrl-C to stop.")
    try:
        while True:
            with _worker_lock:
                if _worker_state.get("stop"):
                    break
            conn = get_db()
            pending = conn.execute(
                "SELECT id FROM jobs WHERE status = 'pending' ORDER BY id LIMIT 1"
            ).fetchall()
            conn.close()

            if pending:
                job_id = int(pending[0][0])
                with _worker_lock:
                    _worker_state["current_job_id"] = job_id
                print(f"Processing job {job_id}...")
                try:
                    process_one_job(job_id)
                    with _worker_lock:
                        _worker_state["processed_count"] = int(
                            _worker_state.get("processed_count") or 0
                        ) + 1
                        _worker_state["last_job_id"] = job_id
                        _worker_state["last_error"] = None
                except Exception as e:
                    with _worker_lock:
                        _worker_state["last_error"] = str(e)
                        _worker_state["last_job_id"] = job_id
                    print(f"Worker job {job_id} error: {e}", file=sys.stderr)
                finally:
                    with _worker_lock:
                        _worker_state["current_job_id"] = None
            else:
                time.sleep(2 if mode == "embedded" else 3)
    finally:
        with _worker_lock:
            _worker_state["running"] = False
            _worker_state["current_job_id"] = None
            _worker_state["mode"] = None
        _clear_worker_pid_file()
        print("NLS Video worker stopped.")


def start_worker_thread(mode: str = "embedded") -> Dict[str, Any]:
    """Start in-process pipeline worker if none is already running (this process or external)."""
    global _worker_thread
    with _worker_lock:
        if _worker_state.get("running") and _worker_thread and _worker_thread.is_alive():
            return {
                "ok": True,
                "started": False,
                "reason": "already_running",
                **{k: _worker_state.get(k) for k in ("mode", "current_job_id", "started_at")},
            }
    pid_file = _read_worker_pid_file()
    if pid_file and pid_file != os.getpid() and _pid_alive(pid_file):
        return {
            "ok": True,
            "started": False,
            "reason": "external_worker",
            "pid": pid_file,
            "hint": f"External worker pid {pid_file} is alive — not starting embedded",
        }
    _write_worker_pid_file()
    t = threading.Thread(target=_worker_loop, kwargs={"mode": mode}, daemon=True, name="nls-video-worker")
    _worker_thread = t
    t.start()
    return {"ok": True, "started": True, "mode": mode, "pid": os.getpid()}


def worker():
    """Foreground worker. Run in tmux or with & for background."""
    pid_file = _read_worker_pid_file()
    if pid_file and pid_file != os.getpid() and _pid_alive(pid_file):
        print(f"Another worker appears alive (pid {pid_file}). Aborting dual-worker start.")
        print("If stale, remove:", WORKER_PID_PATH)
        return
    _write_worker_pid_file()
    try:
        _worker_loop(mode="standalone")
    except KeyboardInterrupt:
        print("\nWorker interrupted.")
    finally:
        with _worker_lock:
            _worker_state["stop"] = True
            _worker_state["running"] = False
        _clear_worker_pid_file()


# ----------------------------- CLI -----------------------------
def cmd_add(args):
    conn = get_db()
    cfg = load_config()
    preset = args.preset or cfg.get("default_preset", "balanced-4k")
    if preset not in DEFAULT_PRESETS:
        print(f"Unknown preset. Available: {list(DEFAULT_PRESETS.keys())}")
        return

    source_file = getattr(args, 'source_file', None)
    url = args.url or ""

    # Get title early
    title = args.title
    if not title and url:
        try:
            import yt_dlp
            with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get("title", "Untitled")
        except Exception:
            title = "Untitled"
    elif not title and source_file:
        title = Path(source_file).stem

    now = now_utc_iso()
    metadata = {}
    if getattr(args, 'gravity', False):
        metadata["gravity"] = True
    if getattr(args, 'interstellar_nonlinear', False):
        metadata["interstellar_nonlinear"] = True
        metadata["gravity"] = True  # implies gravity for noise prep

    job = Job(
        id=0,
        url=url,
        title=title,
        preset=preset,
        status="pending",
        progress=0,
        stage="queued",
        output_path=None,
        log_path="",
        metadata=metadata,
        created=now,
        source_file=source_file,
    )
    conn.execute("""
        INSERT INTO jobs (url, title, preset, status, progress, stage, created, metadata, source_file)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (job.url, job.title, job.preset, job.status, job.progress, job.stage, job.created, json.dumps(job.metadata), job.source_file))
    job.id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()

    print(f"Added job #{job.id}: {job.title} ({preset})")
    if source_file:
        print(f"  (convert-only from {source_file})")
    if metadata.get("gravity"):
        print("  (gravity / Noise Protocol prep enabled - raw stream for secure transport)")
    print("Run `nls-video worker` (or in background) to process.")


def cmd_list(args):
    conn = get_db()
    jobs = list_jobs(conn, args.status)
    conn.close()

    if RICH_AVAILABLE:
        table = Table(title="NLS Video Jobs")
        table.add_column("ID", style="cyan")
        table.add_column("Title")
        table.add_column("Status", style="magenta")
        table.add_column("Progress")
        table.add_column("Preset")
        for j in jobs:
            table.add_row(str(j.id), j.title[:50], j.status, f"{j.progress:.1f}%", j.preset)
        Console().print(table)
    else:
        print(f"{'ID':<5} {'Title':<40} {'Status':<12} {'%':>6} Preset")
        for j in jobs:
            print(f"{j.id:<5} {j.title[:40]:<40} {j.status:<12} {j.progress:>5.1f}% {j.preset}")


def cmd_status(args):
    conn = get_db()
    job = load_job(conn, args.id)
    conn.close()
    if not job:
        print("Job not found")
        return
    print(json.dumps(job.to_dict(), indent=2, default=str))


def cmd_logs(args):
    conn = get_db()
    job = load_job(conn, args.id)
    conn.close()
    if not job or not job.log_path or not Path(job.log_path).exists():
        print("No log for this job (or still downloading)")
        return
    path = Path(job.log_path)
    with open(path) as f:
        for line in f:
            print(line, end="")
        if not args.follow:
            return
        # Follow new lines (tail -f style) until Ctrl+C
        try:
            while True:
                line = f.readline()
                if line:
                    print(line, end="")
                    sys.stdout.flush()
                else:
                    # job may still be writing; exit if terminal status is done
                    conn = get_db()
                    job2 = load_job(conn, args.id)
                    conn.close()
                    if job2 and job2.status in ("completed", "failed", "cancelled", "error"):
                        # drain any final bytes
                        rest = f.read()
                        if rest:
                            print(rest, end="")
                        break
                    time.sleep(0.5)
        except KeyboardInterrupt:
            print()


def cmd_cancel(args):
    result = api_cancel_job(args.id)
    if result.get("ok"):
        print(f"Job {args.id} cancelled.")
    else:
        print(result.get("error", "Job not cancelable or not found."))


def cmd_serve(args):
    """Web dashboard / full interface for NLS Visualist data + pipeline.
    Serves videos and thumbnails from the Visualist root under /visualist/
    for in-browser preview and playback (the "interface").
    """
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            cfg = load_config()
            vroot = Path(cfg.get("visualist_root", DEFAULT_VISUALIST_ROOT))

            if self.path == "/" or self.path == "/index.html":
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                html = self._dashboard_html()
                self.wfile.write(html.encode())
            elif self.path == "/api/jobs":
                self._json_response(self._get_jobs())
            elif self.path == "/api/catalog":
                self._json_response(self._get_catalog())
            elif self.path.startswith("/visualist/"):
                rel = self.path[len("/visualist/"):]
                full = _safe_file_under(vroot, rel)
                if full and _serve_media_file(self, full):
                    return
                self.send_error(404)
            else:
                self.send_error(404)

        def _json_response(self, data):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data, default=str).encode())

        def _get_jobs(self):
            conn = get_db()
            jobs = [j.to_dict() for j in list_jobs(conn)]
            conn.close()
            return {"jobs": jobs, "catalog_path": str(CATALOG_PATH)}

        def _get_catalog(self):
            catalog = []
            if CATALOG_PATH.exists():
                try:
                    catalog = json.loads(CATALOG_PATH.read_text())
                except Exception:
                    catalog = []
            return {"catalog": catalog}

        def _dashboard_html(self):
            return """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>NLS Visualist • Video Pipeline &amp; Media</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { background: #0a0a0a; color: #ddd; font-family: ui-monospace, monospace, system-ui; }
    .card { background:#111; border: 1px solid #222; }
    .nav-tab { padding: 0.5rem 1rem; cursor: pointer; border-bottom: 2px solid transparent; }
    .nav-tab.active { border-bottom-color: #10b981; color: #10b981; }
    .thumb { width:100%; height:120px; object-fit:cover; background:#222; }
    .asc-thumbnail { filter: contrast(1.15) saturate(0.85) sepia(0.15) hue-rotate(-8deg); /* ASC cinematic film look */ }
    .glitch {
      position: relative;
      display: inline-block;
    }
    .glitch::before, .glitch::after {
      content: attr(data-text);
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
    }
    .glitch::before {
      left: 2px;
      text-shadow: -2px 0 #ff00ff;
      clip: rect(24px, 9999px, 86px, 0);
      animation: glitch-anim 1.5s infinite linear alternate-reverse;
    }
    .glitch::after {
      left: -2px;
      text-shadow: 2px 0 #00ffff;
      clip: rect(86px, 9999px, 140px, 0);
      animation: glitch-anim2 1.5s infinite linear alternate-reverse;
    }
    @keyframes glitch-anim {
      0% { clip: rect(24px, 9999px, 86px, 0); }
      20% { clip: rect(140px, 9999px, 86px, 0); }
      40% { clip: rect(24px, 9999px, 140px, 0); }
      60% { clip: rect(86px, 9999px, 24px, 0); }
      80% { clip: rect(140px, 9999px, 140px, 0); }
      100% { clip: rect(24px, 9999px, 86px, 0); }
    }
    @keyframes glitch-anim2 {
      0% { clip: rect(86px, 9999px, 140px, 0); }
      20% { clip: rect(24px, 9999px, 24px, 0); }
      40% { clip: rect(140px, 9999px, 86px, 0); }
      60% { clip: rect(86px, 9999px, 140px, 0); }
      80% { clip: rect(24px, 9999px, 24px, 0); }
      100% { clip: rect(86px, 9999px, 140px, 0); }
    }
    .visualist-banner {
      font-size: 0.9rem;
      opacity: 0.7;
      letter-spacing: 2px;
      text-transform: uppercase;
    }
    video { max-width:100%; max-height:320px; }
  </style>
</head>
<body class="p-6 font-sans">
  <div class="max-w-7xl mx-auto">
    <div class="flex items-center justify-between mb-4">
      <div>
        <h1 class="text-3xl font-bold glitch" data-text="NLS Visualist • Video Pipeline &amp; Media">NLS Visualist • Video Pipeline &amp; Media</h1>
        <p class="visualist-banner">1000 years old nonlinear h@k reality</p>
        <p class="text-sm opacity-70">yt-dlp + ffmpeg H.264 • Live jobs + your Visualist catalog • noiseprotocol gravity</p>
      </div>
      <div class="text-xs opacity-60">Rules: #1 no kill • #2 no eval</div>
    </div>

    <div class="flex gap-2 border-b border-neutral-800 mb-4 text-sm">
      <div onclick="showTab('jobs')" id="tab-jobs" class="nav-tab active">Pipeline Jobs</div>
      <div onclick="showTab('visualist')" id="tab-visualist" class="nav-tab">NLS Visualist Data</div>
    </div>

    <div id="tab-jobs-content">
      <div id="stats" class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4"></div>
      <div class="card rounded-xl p-4">
        <h2 class="font-semibold mb-3">Jobs (auto-refresh every 1.5s)</h2>
        <div id="jobs" class="space-y-3"></div>
      </div>
    </div>

    <div id="tab-visualist-content" class="hidden">
      <div class="card rounded-xl p-4">
        <h2 class="font-semibold mb-3">NLS Visualist Media Catalog</h2>
        <div id="catalog" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 text-sm"></div>
        <div class="mt-3 text-xs opacity-60">Thumbnails generated automatically. Click Play to stream the H.264 in-browser.</div>
      </div>
    </div>
  </div>

  <script>
    let currentTab = 'jobs';
    function showTab(tab) {
      currentTab = tab;
      document.getElementById('tab-jobs-content').classList.toggle('hidden', tab !== 'jobs');
      document.getElementById('tab-visualist-content').classList.toggle('hidden', tab !== 'visualist');
      document.getElementById('tab-jobs').classList.toggle('active', tab === 'jobs');
      document.getElementById('tab-visualist').classList.toggle('active', tab === 'visualist');
      if (tab === 'visualist') refreshCatalog();
    }

    async function refreshJobs() {
      const res = await fetch('/api/jobs');
      const data = await res.json();
      const jobs = data.jobs || [];
      const active = jobs.filter(j => ['downloading','converting'].includes(j.status)).length;
      const done = jobs.filter(j => j.status === 'completed').length;
      document.getElementById('stats').innerHTML = `
        <div class="card p-3 rounded"><div class="text-xs opacity-60">Active</div><div class="text-2xl font-semibold">${active}</div></div>
        <div class="card p-3 rounded"><div class="text-xs opacity-60">Completed</div><div class="text-2xl font-semibold">${done}</div></div>
        <div class="card p-3 rounded"><div class="text-xs opacity-60">Total</div><div class="text-2xl font-semibold">${jobs.length}</div></div>
        <div class="card p-3 rounded text-xs">Catalog updated on completion</div>
      `;
      const c = document.getElementById('jobs'); c.innerHTML = '';
      jobs.forEach(j => {
        const pct = Math.max(0, Math.min(100, j.progress || 0));
        const d = document.createElement('div');
        d.className = 'card p-3 rounded';
        d.innerHTML = `
          <div class="flex justify-between">
            <div class="font-medium truncate">${j.title || j.url}</div>
            <div class="text-xs opacity-70">${j.preset}</div>
          </div>
          <div class="text-xs opacity-60">${j.status} • ${j.stage || ''}</div>
          <div class="h-2 bg-neutral-800 rounded mt-1 overflow-hidden"><div class="h-2 bg-emerald-500" style="width:${pct}%"></div></div>
          <div class="text-[10px] opacity-60 mt-0.5">${pct.toFixed(1)}% ${j.output_path ? '— ready in Visualist' : ''}</div>
        `;
        c.appendChild(d);
      });
    }

    async function refreshCatalog() {
      const res = await fetch('/api/catalog');
      const data = await res.json();
      const items = (data.catalog || []).slice().reverse();
      const c = document.getElementById('catalog'); c.innerHTML = '';
      if (items.length === 0) {
        c.innerHTML = '<div class="opacity-60">No items yet — completed jobs appear here automatically with thumbnails and metadata.</div>';
        return;
      }
      items.forEach(it => {
        const d = document.createElement('div');
        d.className = 'card rounded-xl overflow-hidden';
        const thumbClass = (it.gravity_prepared || it.raw_h264_stream) ? 'asc-thumbnail' : '';
        const t = it.thumbnail ? `<img src="/visualist/${it.thumbnail.split('/').pop()}" class="thumb ${thumbClass}">` : `<div class="thumb ${thumbClass} flex items-center justify-center text-xs opacity-50">ASC no thumb</div>`;
        const gravityBadge = (it.gravity_prepared || it.raw_h264_stream) ? `<span class="text-[10px] px-1 py-0.5 bg-purple-900 text-purple-300 rounded ml-1">GRAVITY / NOISEPROTOCOL</span>` : '';
        const smc = it.storage_memory_category || {};
        const storageInfo = smc.zone || smc.memory ? `Storage: zone=${smc.zone || ''} mem=${smc.memory || ''} loc=${smc.location || ''} V=${smc.V || ''} BW=${smc.Bandwidth || ''}` : '';
        d.innerHTML = `
          <div>${t}</div>
          <div class="p-3">
            <div class="font-medium truncate">${it.title || 'Untitled'} ${gravityBadge}</div>
            <div class="text-xs opacity-70 mt-1">
              ${it.technical && it.technical.duration ? Math.round(it.technical.duration)+'s' : ''}
              ${it.source_url ? '• ' + it.source_url.split('v=')[1] || '' : ''}
              ${storageInfo ? '<br>' + storageInfo : ''}
            </div>
            <div class="mt-2 flex gap-2 text-xs">
              ${it.output_path ? `<a href="/visualist/${encodeURIComponent(it.output_path.split('/').pop())}" target="_blank" class="px-2 py-px bg-neutral-800 rounded hover:bg-neutral-700">Play</a>` : ''}
              ${it.output_path ? `<a href="/visualist/${encodeURIComponent(it.output_path.split('/').pop().replace(/\\.mp4$/,'.nlsvis.json'))}" target="_blank" class="px-2 py-px bg-neutral-800 rounded hover:bg-neutral-700">JSON</a>` : ''}
              ${it.raw_h264_stream ? `<a href="/visualist/${encodeURIComponent(it.raw_h264_stream.split('/').pop())}" target="_blank" class="px-2 py-px bg-purple-800 rounded hover:bg-purple-700">Gravity Stream</a>` : ''}
            </div>
          </div>
        `;
        c.appendChild(d);
      });
    }

    function start() {
      setInterval(() => {
        if (currentTab === 'jobs') refreshJobs();
        if (currentTab === 'visualist') refreshCatalog();
      }, 1500);
      refreshJobs();
    }
    let currentTab = 'jobs';
    window.showTab = showTab;
    start();
  </script>
</body>
</html>"""

    import mimetypes  # ensure

    port = args.port
    print(f"Starting enhanced NLS Visualist interface on http://localhost:{port} (jobs + media gallery)")
    try:
        subprocess.run(["xdg-open", f"http://localhost:{port}"], check=False)
    except Exception:
        pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()


# ----------------------------- Gravity Serve (browser UI) -----------------------------

class RuntimeJsonLogger:
    """Append-only JSONL runtime log for gravity-serve / gravity-desktop parity."""

    def __init__(self, source: str, session_meta: Optional[Dict[str, Any]] = None):
        self.source = source
        self.started = time.time()
        self._lock = threading.Lock()
        RUNTIME_LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.live_path = RUNTIME_LOG_DIR / f"{source}-live.jsonl"
        self.session_path = RUNTIME_LOG_DIR / f"{source}-session.json"
        meta = {
            "source": source,
            "pid": os.getpid(),
            "started_at": now_utc_iso(),
            "live_log": str(self.live_path),
        }
        if session_meta:
            meta.update(session_meta)
        self._write_session(meta)
        self._rotate_if_huge()

    LIVE_MAX_BYTES = 32 * 1024 * 1024
    LIVE_KEEP_BYTES = 1 * 1024 * 1024

    def _rotate_if_huge(self) -> None:
        """Keep live JSONL bounded so /api/logs cannot OOM the serve process."""
        try:
            if not self.live_path.is_file():
                return
            size = self.live_path.stat().st_size
            if size <= self.LIVE_MAX_BYTES:
                return
            keep = min(self.LIVE_KEEP_BYTES, size)
            with self.live_path.open("rb") as f:
                f.seek(size - keep)
                data = f.read()
            nl = data.find(b"\n")
            if nl >= 0:
                data = data[nl + 1 :]
            self.live_path.write_bytes(data)
        except Exception:
            pass

    @staticmethod
    def enabled() -> bool:
        return os.environ.get("GRAVITY_RUNTIME_LOG", "1").lower() not in ("0", "false", "no", "off")

    def runtime_ms(self) -> int:
        return int((time.time() - self.started) * 1000)

    def _write_session(self, data: Dict[str, Any]) -> None:
        if not self.enabled():
            return
        try:
            self.session_path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def append(self, event: str, payload: Optional[Dict[str, Any]] = None) -> None:
        if not self.enabled():
            return
        row = {
            "ts": now_utc_iso(),
            "runtime_ms": self.runtime_ms(),
            "source": self.source,
            "event": event,
        }
        if payload:
            row.update(payload)
        line = json.dumps(row, default=str) + "\n"
        with self._lock:
            try:
                with self.live_path.open("a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                pass

    def tail(self, n: int = 20) -> List[Dict[str, Any]]:
        if not self.live_path.is_file() or n <= 0:
            return []
        try:
            chunk = 65536
            data = b""
            with self.live_path.open("rb") as f:
                f.seek(0, os.SEEK_END)
                pos = f.tell()
                while pos > 0 and data.count(b"\n") <= n:
                    step = min(chunk, pos)
                    pos -= step
                    f.seek(pos)
                    data = f.read(step) + data
            text = data.decode("utf-8", "replace")
            lines = [ln for ln in text.splitlines() if ln.strip()][-n:]
            out: List[Dict[str, Any]] = []
            for ln in lines:
                try:
                    out.append(json.loads(ln))
                except Exception:
                    pass
            return out
        except Exception:
            return []


class GravityBridge:
    """Background TCP client for gravity-server; caches latest gravity_update for HTTP."""

    def __init__(self, host: str = "127.0.0.1", port: int = 4242, logger: Optional[RuntimeJsonLogger] = None):
        self.host = host
        self.port = port
        self.logger = logger
        self._lock = threading.Lock()
        self._was_connected = False
        self.latest: Dict[str, Any] = {
            "type": "gravity_update",
            "jobs": [],
            "catalog": [],
            "connected": False,
            "timestamp": None,
            "error": None,
        }

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self.latest)

    def _set(self, **kwargs) -> None:
        with self._lock:
            self.latest.update(kwargs)
        self._maybe_log(kwargs)

    def _maybe_log(self, kwargs: Dict[str, Any]) -> None:
        if not self.logger:
            return
        connected = kwargs.get("connected", self.latest.get("connected"))
        if "connected" in kwargs and connected != self._was_connected:
            self._was_connected = bool(connected)
            self.logger.append(
                "gravity_connected" if connected else "gravity_disconnected",
                {"connected": connected, "error": kwargs.get("error")},
            )
        if kwargs.get("type") == "gravity_update" or "jobs" in kwargs:
            jobs = kwargs.get("jobs", self.latest.get("jobs", []))
            catalog = kwargs.get("catalog", self.latest.get("catalog", []))
            self.logger.append(
                "gravity_update",
                {
                    "connected": bool(connected),
                    "jobs_count": len(jobs) if isinstance(jobs, list) else 0,
                    "catalog_count": len(catalog) if isinstance(catalog, list) else 0,
                    "timestamp": kwargs.get("timestamp"),
                },
            )

    def _load_fallback(self) -> None:
        conn = get_db()
        jobs = [j.to_dict() for j in list_jobs(conn)]
        conn.close()
        catalog: List[Dict[str, Any]] = []
        if CATALOG_PATH.exists():
            try:
                catalog = json.loads(CATALOG_PATH.read_text())
            except Exception:
                catalog = []
        self._set(
            type="gravity_update",
            jobs=jobs,
            catalog=catalog,
            timestamp=now_utc_iso(),
        )

    def run_forever(self) -> None:
        while True:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(8.0)
                s.connect((self.host, self.port))
                s.settimeout(None)
                sig = _sigma9()
                sig.check_prologue(sig.read_sigma9(s, 9))
                s.send(b"\x42" * 32)
                sig.read_sigma9(s, 32)
                s.send(b"\x43" * 48)
                buf = b""
                self._set(connected=True, error=None)
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if not line.strip():
                            continue
                        try:
                            update = json.loads(line.decode("utf-8"))
                            update["connected"] = True
                            update["error"] = None
                            self._set(**update)
                        except Exception:
                            pass
            except Exception as e:
                self._load_fallback()
                self._set(connected=False, error=str(e))
                time.sleep(3.0)


def _media_content_type(path: Path) -> str:
    lower = str(path).lower()
    if lower.endswith(".mp4"):
        return "video/mp4"
    if lower.endswith(".webm"):
        return "video/webm"
    if lower.endswith(".gif"):
        return "image/gif"
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith(".h264"):
        return "video/mp4"  # elementary stream — not browser-playable; label only
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def _serve_media_file(handler: BaseHTTPRequestHandler, full: Path, head_only: bool = False) -> bool:
    """Serve media with HTTP Range support (required for in-browser MP4 playback)."""
    if not full.is_file():
        return False
    head_only = head_only or getattr(handler, "_head_request", False)
    ctype = _media_content_type(full)
    size = full.stat().st_size
    range_header = handler.headers.get("Range")
    if range_header and not head_only:
        m = re.match(r"bytes=(\d+)-(\d*)", range_header.strip())
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
            end = min(end, size - 1)
            if start >= size or start > end:
                handler.send_response(416)
                handler.send_header("Content-Range", f"bytes */{size}")
                handler.end_headers()
                return True
            length = end - start + 1
            handler.send_response(206)
            handler.send_header("Content-Type", ctype)
            handler.send_header("Content-Length", str(length))
            handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            handler.send_header("Accept-Ranges", "bytes")
            handler.end_headers()
            with open(full, "rb") as f:
                f.seek(start)
                handler.wfile.write(f.read(length))
            return True
    handler.send_response(200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(size))
    handler.send_header("Accept-Ranges", "bytes")
    handler.end_headers()
    if head_only:
        return True
    with open(full, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            handler.wfile.write(chunk)
    return True


def _safe_file_under(base: Path, name: str) -> Optional[Path]:
    if not name:
        return None
    name = unquote(name.split("?", 1)[0], encoding="utf-8", errors="strict")
    if ".." in name or name.startswith("/"):
        return None
    full = (base / name).resolve()
    try:
        full.relative_to(base.resolve())
    except ValueError:
        return None
    return full if full.is_file() else None


def _enrich_visualist_item(item: Dict[str, Any], vroot: Path) -> Dict[str, Any]:
    """Add browser-friendly play/thumb names for ASC FILMIC / GRAVITY catalog cards."""
    out = dict(item)
    op = item.get("output_path") or ""
    if op:
        p = Path(op)
        out["play_name"] = p.name
        thumb_path = item.get("thumbnail")
        if thumb_path:
            out["thumb_name"] = Path(thumb_path).name
        else:
            for cand in (p.with_suffix(".thumb.jpg"), Path(str(p) + ".thumb.jpg")):
                if cand.is_file():
                    out["thumb_name"] = cand.name
                    break
            else:
                out["thumb_name"] = None
    grav = bool(item.get("gravity_prepared") or item.get("raw_h264_stream"))
    out["asc_mode"] = "GRAVITY" if grav else "FILMIC"
    out["playable"] = bool(op and Path(op).suffix.lower() in (".mp4", ".webm", ".gif"))
    if item.get("raw_h264_stream"):
        out["h264_stream_name"] = Path(item["raw_h264_stream"]).name
    tech = item.get("technical") if isinstance(item.get("technical"), dict) else {}
    if tech.get("acodec") or tech.get("codec_label"):
        out["acodec"] = tech.get("codec_label") or tech.get("acodec")
        out["audio_layout"] = tech.get("audio_layout")
        out["audio_channels"] = tech.get("audio_channels")
    dur = tech.get("source_duration") or tech.get("duration") or tech.get("duration_sec")
    if dur:
        out["duration_sec"] = dur
        out["duration_label"] = _fmt_clock(dur)
    size = tech.get("final_size") or tech.get("size_bytes")
    if not size and op:
        try:
            size = Path(op).stat().st_size
        except OSError:
            size = None
    if size:
        out["size_bytes"] = size
        out["size_label"] = _fmt_bytes(size)
    smc = item.get("storage_memory_category") if isinstance(item.get("storage_memory_category"), dict) else {}
    out["zone"] = smc.get("zone")
    ytid = _youtube_id_from_name(out.get("play_name") or "")
    raw_title = out.get("title") or ""
    if _looks_like_id_title(raw_title, ytid) and (ytid or out.get("play_name")):
        resolved = _resolve_youtube_title(out.get("play_name") or "", raw_title, [1])
        if resolved:
            out["title"] = resolved
    if ytid and not out.get("source_url"):
        out["source_url"] = f"https://youtu.be/{ytid}"
    return out


def _nlsar_backend() -> Optional[Dict[str, Any]]:
    """Local NLSAR architecture snapshot. Never hit /api/comm (avoids pull loop)."""
    try:
        import nlsar_node

        return nlsar_node.fetch_backend()
    except Exception:
        pass
    base = os.environ.get("NLSAR_URL", "http://127.0.0.1:4212").rstrip("/")
    try:
        req = urllib.request.Request(
            base + "/api/backend",
            headers={"User-Agent": "gravity-serve/nlsar"},
        )
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _enrich_gravity_snapshot(snap: Dict[str, Any]) -> Dict[str, Any]:
    cfg = load_config()
    vroot = Path(cfg.get("visualist_root", DEFAULT_VISUALIST_ROOT))
    out = dict(snap)
    catalog = snap.get("catalog") or []
    if isinstance(catalog, list):
        out["catalog"] = [_enrich_visualist_item(it, vroot) for it in catalog]
    bridge_jobs = snap.get("jobs") or []
    bridge_by_id: Dict[int, Dict[str, Any]] = {}
    if isinstance(bridge_jobs, list):
        for j in bridge_jobs:
            if not isinstance(j, dict):
                continue
            try:
                bridge_by_id[int(j.get("id"))] = j
            except (TypeError, ValueError):
                continue
    conn = get_db()
    fresh = {j.id: j.to_dict() for j in list_jobs(conn)}
    conn.close()
    merged: List[Dict[str, Any]] = []
    for jid in sorted(fresh.keys(), reverse=True):
        db_job = fresh[jid]
        if jid in bridge_by_id:
            merged.append({**bridge_by_id[jid], **db_job})
        else:
            merged.append(db_job)
    out["jobs"] = merged
    out["worker"] = worker_status()
    nls = _nlsar_backend()
    if nls:
        out["nlsar"] = {
            "connected": True,
            "corpus": nls.get("corpus"),
            "signals": nls.get("signals"),
            "listen": nls.get("listen") or os.environ.get("NLSAR_URL", "http://127.0.0.1:4212") + "/",
            "inject": nls.get("inject") or {},
        }
        jobs = list(out.get("jobs") or [])
        jobs.extend(nls.get("jobs") or [])
        out["jobs"] = jobs
        cat = list(out.get("catalog") or [])
        cat.extend(nls.get("catalog") or [])
        out["catalog"] = cat
    else:
        out["nlsar"] = {"connected": False}
    return out


def _fmt_bytes(n: Any) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    if n < 1024:
        return f"{n} B"
    units = ["KB", "MB", "GB", "TB"]
    x = float(n)
    for u in units:
        x /= 1024.0
        if x < 1024.0:
            return f"{x:.1f} {u}" if x < 10 else f"{x:.0f} {u}"
    return f"{x:.0f} PB"


def _fmt_clock(sec: Any) -> str:
    try:
        s = float(sec)
    except (TypeError, ValueError):
        return ""
    if s < 0:
        return ""
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    ss = int(s % 60)
    if h:
        return f"{h}:{m:02d}:{ss:02d}"
    return f"{m}:{ss:02d}"


def _json_cache_load(path: Path) -> Dict[str, Any]:
    try:
        if path.is_file():
            data = json.loads(path.read_text())
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _json_cache_save(path: Path, data: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def _direct_id_from_name(name: str) -> str:
    m = _DIRECT_NAME_RE.match(name or "")
    if not m:
        return ""
    stem = m.group(1)
    stem = _DIRECT_SEQ_RE.sub("", stem)
    return stem


def _direct_seq_from_name(name: str) -> int:
    m = _DIRECT_NAME_RE.match(name or "")
    if not m:
        return 1
    sm = _DIRECT_SEQ_RE.search(m.group(1))
    return int(sm.group(1)) if sm else 1


def _cleanup_download_temps(dest: Path) -> int:
    """Remove yt-dlp/vacuum leftovers for dest (.part, .ytdl, Frag, .vac)."""
    if dest is None:
        return 0
    n = 0
    parent = dest.parent
    name = dest.name
    if not parent.is_dir() or not name:
        return 0
    for p in parent.iterdir():
        fn = p.name
        if not (fn == name or fn.startswith(name + ".") or fn.startswith(name + ".part")):
            continue
        if fn.endswith((".part", ".ytdl", ".vac")) or ".part-Frag" in fn:
            try:
                p.unlink()
                n += 1
            except Exception:
                pass
    return n


def next_direct_dest(media_id: str, gif: bool = False) -> Path:
    """direct-h264-{id}.mp4 then direct-h264-{id}-002.mp4 … (never overwrite)."""
    mid = (media_id or "file").strip() or "file"
    prefix = f"direct-gif-{mid}" if gif else f"direct-h264-{mid}"
    ext = "gif" if gif else "mp4"
    first = DOWNLOADS_DIR / f"{prefix}.{ext}"
    if not first.exists():
        return first
    n = 2
    while n < 1000:
        p = DOWNLOADS_DIR / f"{prefix}-{n:03d}.{ext}"
        if not p.exists():
            return p
        n += 1
    return DOWNLOADS_DIR / f"{prefix}-{int(time.time())}.{ext}"


def _youtube_id_from_name(name: str) -> str:
    did = _direct_id_from_name(name)
    return did if _YT_VIDEO_ID_RE.fullmatch(did or "") else ""


def _looks_like_id_title(title: str, ytid: str = "") -> bool:
    t = (title or "").strip()
    if not t or t.lower() in ("untitled", "unknown"):
        return True
    if ytid and t == ytid:
        return True
    low = t.lower()
    if low.startswith("direct-h264-") or low.startswith("direct-gif-"):
        return True
    if t.isdigit() and len(t) >= 15:
        return True
    return False


def _oembed_youtube_title(vid: str) -> str:
    if not vid:
        return ""
    url = "https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=" + vid + "&format=json"
    req = urllib.request.Request(url, headers={"User-Agent": "gravity-serve/catalog"})
    try:
        with urllib.request.urlopen(req, timeout=1.8) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        title = (data.get("title") or "").strip() if isinstance(data, dict) else ""
        return title
    except Exception:
        return ""


def _resolve_youtube_title(name: str, sidecar_title: str = "", budget: List[int] = None) -> str:
    ytid = _youtube_id_from_name(name)
    with _TITLE_CACHE_LOCK:
        cache = _json_cache_load(TITLE_CACHE_PATH)
        if ytid and cache.get(ytid):
            return str(cache[ytid])
    title = (sidecar_title or "").strip()
    if not _looks_like_id_title(title, ytid):
        if ytid:
            with _TITLE_CACHE_LOCK:
                cache = _json_cache_load(TITLE_CACHE_PATH)
                cache[ytid] = title
                _json_cache_save(TITLE_CACHE_PATH, cache)
        return title
    if ytid and budget is not None and budget[0] > 0:
        budget[0] -= 1
        fetched = _oembed_youtube_title(ytid)
        if fetched:
            with _TITLE_CACHE_LOCK:
                cache = _json_cache_load(TITLE_CACHE_PATH)
                cache[ytid] = fetched
                _json_cache_save(TITLE_CACHE_PATH, cache)
            return fetched
    if title:
        return title
    return ytid or name


def _read_sidecar(path: Path) -> Dict[str, Any]:
    sidecar = Path(str(path) + ".interlaterus.json")
    if not sidecar.is_file():
        return {}
    try:
        sc = json.loads(sidecar.read_text())
    except Exception:
        return {}
    nft = sc.get("nft") if isinstance(sc.get("nft"), dict) else {}
    meta = nft.get("metadata") if isinstance(nft.get("metadata"), dict) else {}
    probe = sc.get("probe") if isinstance(sc.get("probe"), dict) else {}
    if not probe and isinstance(meta.get("technical"), dict):
        probe = meta["technical"]
    out: Dict[str, Any] = {
        "pattern_code": sc.get("pattern_code") or nft.get("pattern_code"),
        "vertex": sc.get("vertex") or nft.get("vertex"),
        "title": meta.get("title") or sc.get("title"),
        "source_url": meta.get("source_url") or sc.get("source_url"),
        "duration_sec": probe.get("duration_sec"),
        "size_bytes": probe.get("size_bytes"),
        "width": probe.get("width"),
        "height": probe.get("height"),
        "vcodec": probe.get("vcodec"),
        "acodec": probe.get("acodec"),
        "bitrate": probe.get("bitrate"),
        "format": probe.get("format"),
        "sha256": probe.get("sha256") or meta.get("sha256"),
        "minted_at": sc.get("minted_at") or nft.get("created_at"),
    }
    return {k: v for k, v in out.items() if v not in (None, "", [])}


def _ffprobe_media(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    st = path.stat()
    key = f"{path}:{int(st.st_mtime)}:{st.st_size}"
    with _PROBE_CACHE_LOCK:
        cache = _json_cache_load(PROBE_CACHE_PATH)
        hit = cache.get(key)
        if isinstance(hit, dict):
            return hit
    ffprobe = shutil.which("ffprobe") or "/usr/bin/ffprobe"
    try:
        raw = subprocess.check_output(
            [
                ffprobe, "-v", "error",
                "-show_entries",
                "format=duration,size,bit_rate,format_name:stream=codec_name,codec_type,sample_rate,channels,width,height,bits_per_raw_sample",
                "-of", "json",
                str(path),
            ],
            stderr=subprocess.DEVNULL,
            timeout=12,
        )
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return {}
    fmt = data.get("format") if isinstance(data.get("format"), dict) else {}
    streams = data.get("streams") if isinstance(data.get("streams"), list) else []
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})
    try:
        dur = float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0
    try:
        size = int(fmt.get("size") or st.st_size)
    except (TypeError, ValueError):
        size = st.st_size
    out: Dict[str, Any] = {
        "duration_sec": dur or None,
        "size_bytes": size,
        "bitrate": int(fmt["bit_rate"]) if str(fmt.get("bit_rate") or "").isdigit() else fmt.get("bit_rate"),
        "format": fmt.get("format_name"),
        "vcodec": v.get("codec_name"),
        "acodec": a.get("codec_name"),
        "width": v.get("width"),
        "height": v.get("height"),
        "sample_rate": int(a["sample_rate"]) if str(a.get("sample_rate") or "").isdigit() else a.get("sample_rate"),
        "channels": a.get("channels"),
        "bit_depth": a.get("bits_per_raw_sample"),
    }
    out = {k: v for k, v in out.items() if v not in (None, "", [])}
    with _PROBE_CACHE_LOCK:
        cache = _json_cache_load(PROBE_CACHE_PATH)
        if len(cache) > 400:
            cache = dict(list(cache.items())[-200:])
        cache[key] = out
        _json_cache_save(PROBE_CACHE_PATH, cache)
    return out


def _human_rec_title(stem: str) -> str:
    key = (stem or "").strip().lower()
    if key in REC_STEM_TITLES:
        return REC_STEM_TITLES[key]
    with _TITLE_CACHE_LOCK:
        cache = _json_cache_load(TITLE_CACHE_PATH)
        if key in cache:
            return str(cache[key])
        if len(key) == 11 and cache.get(key):
            return str(cache[key])
    parts = [p for p in re.split(r"[-_]+", key) if p]
    if len(parts) >= 2 and parts[-1] in _HOST_TLDS:
        return ".".join(parts)
    pretty = re.sub(r"[-_]+", " ", stem or "").strip()
    return pretty[:48] if pretty else "ASC rec"


def _read_rec_sidecar(path: Path) -> Dict[str, Any]:
    sidecar = Path(str(path) + ".rec.json")
    if not sidecar.is_file():
        return {}
    try:
        data = json.loads(sidecar.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_rec_filename(name: str) -> Dict[str, str]:
    m = _REC_NAME_RE.match(name or "")
    if not m:
        return {"fn": "rec", "stem": "rec", "stamp": "", "ext": ""}
    wy, stem, stamp, ext = m.group(1), m.group(2), m.group(3), m.group(4)
    low = (stem or "").lower()
    if wy:
        fn = "WYHIWYREC"
    elif low in ("nts1", "nts2", "rinse-fm", "radio") or low.endswith("-fm"):
        fn = "net stream"
    else:
        fn = "catalog"
    return {"fn": fn, "stem": stem, "stamp": stamp, "ext": ext.lower()}


def _recent_downloads_list(limit: int = 40) -> List[Dict[str, Any]]:
    patterns = (
        re.compile(r"^direct-h264-.+\.mp4$"),
        re.compile(r"^direct-gif-.+\.gif$"),
        re.compile(r"^direct-h264-rot\d+-.+\.mp4$"),
    )
    items: List[Dict[str, Any]] = []
    if not DOWNLOADS_DIR.is_dir():
        return items
    files = [f for f in DOWNLOADS_DIR.iterdir() if f.is_file() and any(p.match(f.name) for p in patterns)]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    budget = [8]
    for f in files[:limit]:
        st = f.stat()
        sc = _read_sidecar(f)
        ytid = _youtube_id_from_name(f.name)
        did = _direct_id_from_name(f.name)
        seq = _direct_seq_from_name(f.name)
        title = _resolve_youtube_title(f.name, str(sc.get("title") or ""), budget)
        if isinstance(title, str) and (title.startswith("ERROR:") or "secretstorage" in title.lower()):
            title = did or f.stem
        if _looks_like_id_title(title, ytid) and did.isdigit() and len(did) >= 15:
            if budget[0] > 0:
                budget[0] -= 1
                xt = _oembed_x_title(did)
                if xt:
                    title = xt
                    with _TITLE_CACHE_LOCK:
                        cache = _json_cache_load(TITLE_CACHE_PATH)
                        cache[did] = xt
                        _json_cache_save(TITLE_CACHE_PATH, cache)
        elif _looks_like_id_title(title, ytid) and did:
            with _TITLE_CACHE_LOCK:
                cache = _json_cache_load(TITLE_CACHE_PATH)
                if cache.get(did):
                    title = str(cache[did])
        source_url = _guess_source_url(f.name, str(sc.get("source_url") or ""))
        kind = "gif" if f.suffix.lower() == ".gif" else "h264"
        host = _download_host(f.name, source_url, did)
        entry: Dict[str, Any] = {
            "kind": kind,
            "host": host,
            "name": f.name,
            "path": str(f),
            "title": title,
            "source_url": source_url,
            "media_id": did or None,
            "seq": seq,
            "youtube_id": ytid or None,
            "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "size_bytes": sc.get("size_bytes") or st.st_size,
            "duration_sec": sc.get("duration_sec"),
            "width": sc.get("width"),
            "height": sc.get("height"),
            "vcodec": sc.get("vcodec"),
            "acodec": sc.get("acodec"),
            "bitrate": sc.get("bitrate"),
            "pattern_code": sc.get("pattern_code"),
            "vertex": sc.get("vertex"),
            "sha256": sc.get("sha256"),
            "minted_at": sc.get("minted_at"),
        }
        if not entry.get("duration_sec"):
            probe = _ffprobe_media(f)
            for k in ("duration_sec", "size_bytes", "width", "height", "vcodec", "acodec", "bitrate"):
                if entry.get(k) in (None, "") and probe.get(k) not in (None, ""):
                    entry[k] = probe[k]
        entry["size_label"] = _fmt_bytes(entry.get("size_bytes"))
        entry["duration_label"] = _fmt_clock(entry.get("duration_sec"))
        if entry.get("width") and entry.get("height"):
            entry["res_label"] = f"{entry['width']}×{entry['height']}"
        items.append({k: v for k, v in entry.items() if v not in (None, "")})
    return items


def _rec_catalog_list(limit: int = 40) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not DOWNLOADS_DIR.is_dir():
        return items
    files = [
        f for f in DOWNLOADS_DIR.iterdir()
        if f.is_file() and f.name.startswith("asc-rec-")
        and f.suffix.lower() in (".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg", ".mp4")
    ]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files[:limit]:
        st = f.stat()
        parsed = _parse_rec_filename(f.name)
        probe = _ffprobe_media(f)
        meta = _read_rec_sidecar(f)
        title = (meta.get("title") or "").strip() or _human_rec_title(parsed["stem"])
        fn = (meta.get("fn") or parsed["fn"] or "rec")
        if "wyhiwyrec" in f.name.lower() or str(fn).upper() == "WYHIWYREC":
            fn = "WYHIWYREC"
        codec = probe.get("acodec") or parsed["ext"]
        is_video = parsed["ext"] == "mp4" or bool(probe.get("vcodec"))
        entry: Dict[str, Any] = {
            "kind": "rec-video" if is_video else "rec",
            "fn": fn,
            "name": f.name,
            "path": str(f),
            "title": title,
            "stem": parsed["stem"],
            "stamp": parsed["stamp"],
            "ext": parsed["ext"],
            "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "size_bytes": probe.get("size_bytes") or st.st_size,
            "duration_sec": probe.get("duration_sec"),
            "acodec": codec,
            "vcodec": probe.get("vcodec"),
            "width": probe.get("width"),
            "height": probe.get("height"),
            "sample_rate": probe.get("sample_rate"),
            "channels": probe.get("channels"),
            "bit_depth": probe.get("bit_depth"),
            "bitrate": probe.get("bitrate"),
            "format": probe.get("format"),
            "source_url": meta.get("source_url") or "",
            "rec_format": meta.get("format") or "",
            "norm": meta.get("norm") or "",
        }
        if entry.get("width") and entry.get("height"):
            entry["res_label"] = f"{entry['width']}×{entry['height']}"
        entry["size_label"] = _fmt_bytes(entry.get("size_bytes"))
        entry["duration_label"] = _fmt_clock(entry.get("duration_sec"))
        sr = entry.get("sample_rate")
        if sr:
            try:
                entry["rate_label"] = f"{int(sr) / 1000:g} kHz"
            except (TypeError, ValueError):
                entry["rate_label"] = str(sr)
        ch = entry.get("channels")
        if ch == 1:
            entry["ch_label"] = "mono"
        elif ch == 2:
            entry["ch_label"] = "stereo"
        elif ch:
            entry["ch_label"] = f"{ch}ch"
        items.append({k: v for k, v in entry.items() if v not in (None, "")})
    try:
        REC_INDEX_PATH.write_text(json.dumps({
            "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "count": len(items),
            "files": [
                {
                    "path": it["path"],
                    "name": it["name"],
                    "title": it.get("title"),
                    "fn": it.get("fn"),
                    "bytes": it.get("size_bytes"),
                    "mtime": it.get("modified"),
                    "duration_sec": it.get("duration_sec"),
                }
                for it in items
            ],
        }, indent=2))
    except Exception:
        pass
    return items


def api_downloads() -> Dict[str, Any]:
    items = _recent_downloads_list(limit=40)
    recs = _rec_catalog_list(limit=40)
    return {
        "items": items,
        "recs": recs,
        "counts": {
            "downloads": len(items),
            "recs": len(recs),
            "wyhiwyrec": sum(1 for r in recs if r.get("fn") == "WYHIWYREC"),
            "net_stream": sum(1 for r in recs if r.get("fn") == "net stream"),
            "catalog": sum(1 for r in recs if r.get("fn") == "catalog"),
        },
    }


def _resolve_locate_target(path: str = "", name: str = "") -> Optional[Path]:
    """Resolve a media path for locate/reveal. name = basename under Downloads or Visualist."""
    name = (name or "").strip()
    path = (path or "").strip()
    if name and not path:
        cand = _safe_file_under(DOWNLOADS_DIR, name)
        if cand:
            return cand
        cfg = load_config()
        vroot = Path(cfg.get("visualist_root", DEFAULT_VISUALIST_ROOT))
        return _safe_file_under(vroot, name)
    if not path:
        return None
    try:
        target = Path(path).expanduser().resolve()
    except Exception:
        return None
    if not target.exists():
        return None
    home = Path.home().resolve()
    try:
        target.relative_to(home)
    except ValueError:
        return None
    return target


def _open_in_file_manager(target: Path) -> None:
    """Reveal target in the desktop file manager (select file when possible)."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(target)])
        return
    if sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{target}"])
        return
    uri = target.as_uri()
    # FreeDesktop: select file in default file manager
    try:
        subprocess.Popen(
            [
                "dbus-send",
                "--session",
                "--dest=org.freedesktop.FileManager1",
                "--type=method_call",
                "/org/freedesktop/FileManager1",
                "org.freedesktop.FileManager1.ShowItems",
                f"array:string:{uri}",
                "string:",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    except Exception:
        pass
    folder = str(target.parent if target.is_file() else target)
    if shutil.which("thunar"):
        subprocess.Popen(["thunar", folder])
    else:
        subprocess.Popen(["xdg-open", folder])


def api_locate_file(path: str = "", name: str = "") -> Dict[str, Any]:
    """Open the desktop file manager at the file (or its parent) so the user can locate it."""
    target = _resolve_locate_target(path=path, name=name)
    if not target:
        return {"ok": False, "error": "File not found or path not allowed (must be under $HOME)"}
    try:
        _open_in_file_manager(target)
        return {"ok": True, "path": str(target), "name": target.name}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _interlaterus_catalog() -> List[Dict[str, Any]]:
    if not INTERLATERUS_CATALOG.is_file():
        return []
    try:
        data = json.loads(INTERLATERUS_CATALOG.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _load_visualist_catalog() -> List[Dict[str, Any]]:
    if not CATALOG_PATH.is_file():
        return []
    try:
        data = json.loads(CATALOG_PATH.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _vertex_key(vertex: Any) -> str:
    if isinstance(vertex, (list, tuple)) and len(vertex) == 4:
        return ",".join(str(int(v)) for v in vertex)
    return ""


def _blockcode_positions() -> Dict[str, Dict[str, Any]]:
    """Authoritative POS vertex map keyed by sha256."""
    if not BLOCKCODE_DB.is_file():
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    try:
        conn = sqlite3.connect(BLOCKCODE_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT pattern_code, vertex_x, vertex_y, vertex_z, vertex_t, "
            "media_path, source_url, sha256, created_at FROM blockcode_nft_records"
        ).fetchall()
        conn.close()
        for r in rows:
            sha = (r["sha256"] or "").strip()
            if not sha:
                continue
            out[sha] = {
                "pattern_code": r["pattern_code"],
                "vertex": [r["vertex_x"], r["vertex_y"], r["vertex_z"], r["vertex_t"]],
                "media_path": r["media_path"],
                "source_url": r["source_url"],
                "minted_at": r["created_at"],
            }
    except Exception:
        pass
    return out


def _visualist_by_basename() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for item in _load_visualist_catalog():
        op = item.get("output_path") or ""
        if not op:
            continue
        out[Path(op).name] = item
    return out


def _avd_entries() -> List[Dict[str, Any]]:
    """Analog Video Data (ASC filmic side) from ~/Downloads direct files."""
    entries: List[Dict[str, Any]] = []
    for item in _recent_downloads_list(limit=100):
        path = Path(item.get("path") or "")
        avd: Dict[str, Any] = {
            "path": str(path),
            "name": item.get("name"),
            "asc_mode": "FILMIC",
            "modified": item.get("modified"),
            "pattern_code": item.get("pattern_code"),
            "vertex": item.get("vertex"),
        }
        sidecar = Path(str(path) + ".interlaterus.json")
        if sidecar.is_file():
            try:
                sc = json.loads(sidecar.read_text())
                avd["sha256"] = (sc.get("probe") or {}).get("sha256") or sc.get("sha256")
                avd["pattern_code"] = avd.get("pattern_code") or sc.get("pattern_code")
                avd["vertex"] = avd.get("vertex") or sc.get("vertex")
            except Exception:
                pass
        entries.append(avd)
    return entries


def pos_reconcile(write: bool = True) -> Dict[str, Any]:
    """Merge AVD + POS across blockcode DB, interlaterus, visualist, Downloads."""
    blockcode = _blockcode_positions()
    interlaterus = {((it.get("sha256") or "").strip()): it for it in _interlaterus_catalog() if it.get("sha256")}
    visualist_names = _visualist_by_basename()
    avd_list = _avd_entries()

    by_id: Dict[str, Dict[str, Any]] = {}

    def ensure_entry(eid: str) -> Dict[str, Any]:
        if eid not in by_id:
            by_id[eid] = {"id": eid, "avd": None, "pos": None, "synced_at": now_utc_iso()}
        return by_id[eid]

    for sha, pos in blockcode.items():
        ent = ensure_entry(sha)
        mint = interlaterus.get(sha, {})
        smc = {}
        media_name = Path(pos.get("media_path") or "").name
        vis = visualist_names.get(media_name)
        if vis:
            smc = vis.get("storage_memory_category") or {}
        elif mint:
            title = (mint.get("title") or "").lower()
            is_inter = "interstellar" in title or "nonlineari" in title
            smc = {
                "zone": "interstellar-zone-alpha" if is_inter else "default-zone",
                "memory": "16GB" if is_inter else "8GB",
                "location": "nls-visualist-dc-1" if is_inter else "local-dc",
                "V": "vp56-vol-1999" if is_inter else "h264-vol",
                "Bandwidth": "10Gbps" if is_inter else "1Gbps",
            }
        ent["pos"] = {
            "vertex": pos["vertex"],
            "pattern_code": pos["pattern_code"],
            "storage_memory_category": smc,
            "media_path": pos.get("media_path"),
            "source_url": pos.get("source_url"),
            "minted_at": pos.get("minted_at"),
        }
        if media_name and Path(pos.get("media_path") or "").is_file():
            ent["avd"] = {
                "path": pos["media_path"],
                "name": media_name,
                "asc_mode": "GRAVITY" if vis and (vis.get("gravity_prepared") or vis.get("raw_h264_stream")) else "FILMIC",
                "sha256": sha,
            }

    for avd in avd_list:
        sha = (avd.get("sha256") or "").strip()
        eid = sha or f"avd:{avd.get('name') or 'unknown'}"
        ent = ensure_entry(eid)
        if ent.get("avd") is None:
            ent["avd"] = {k: v for k, v in avd.items() if k != "sha256"}
            if sha:
                ent["avd"]["sha256"] = sha
        if sha and sha in blockcode and ent.get("pos") is None:
            pos = blockcode[sha]
            ent["pos"] = {
                "vertex": pos["vertex"],
                "pattern_code": pos["pattern_code"],
                "storage_memory_category": {},
                "media_path": pos.get("media_path"),
            }

    for name, vis in visualist_names.items():
        eid = f"vis:{name}"
        if any((e.get("avd") or {}).get("name") == name or Path((e.get("pos") or {}).get("media_path") or "").name == name for e in by_id.values()):
            continue
        ent = ensure_entry(eid)
        ent["pos"] = {
            "vertex": None,
            "pattern_code": None,
            "storage_memory_category": vis.get("storage_memory_category") or {},
            "media_path": vis.get("output_path"),
            "visualist_only": True,
        }
        ent["avd"] = {
            "path": vis.get("output_path"),
            "name": name,
            "asc_mode": "GRAVITY" if vis.get("gravity_prepared") or vis.get("raw_h264_stream") else "FILMIC",
            "title": vis.get("title"),
        }

    entries = sorted(by_id.values(), key=lambda e: e.get("id", ""))
    orphans_avd = [e["id"] for e in entries if e.get("avd") and not e.get("pos")]
    orphans_pos = [e["id"] for e in entries if e.get("pos") and not e.get("avd")]
    paired = [e["id"] for e in entries if e.get("avd") and e.get("pos")]

    vertex_hist: Dict[str, int] = {}
    zone_hist: Dict[str, int] = {}
    for e in entries:
        v = e.get("pos") or {}
        vk = _vertex_key(v.get("vertex"))
        if vk:
            vertex_hist[vk] = vertex_hist.get(vk, 0) + 1
        zone = (v.get("storage_memory_category") or {}).get("zone")
        if zone:
            zone_hist[zone] = zone_hist.get(zone, 0) + 1

    payload = {
        "entries": entries,
        "summary": {
            "total": len(entries),
            "paired_avd_pos": len(paired),
            "orphans_avd_only": len(orphans_avd),
            "orphans_pos_only": len(orphans_pos),
            "vertices_occupied": len(vertex_hist),
            "vertex_histogram": vertex_hist,
            "zone_histogram": zone_hist,
        },
        "orphans": {
            "avd_only": orphans_avd[:50],
            "pos_only": orphans_pos[:50],
        },
    }

    if write:
        XDG_DATA.mkdir(parents=True, exist_ok=True)
        POSITION_INDEX_PATH.write_text(json.dumps(payload, indent=2, default=str))
        build_proof_of_spatio(payload)

    return payload


def build_proof_of_spatio(index: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Proof of Spatio (aka POS) — verifiable digest over position index."""
    if index is None:
        if POSITION_INDEX_PATH.is_file():
            try:
                index = json.loads(POSITION_INDEX_PATH.read_text())
            except Exception:
                index = pos_reconcile(write=True)
        else:
            index = pos_reconcile(write=True)

    entries = index.get("entries") or []
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    proof = {
        "proof_type": "proof_of_spatio",
        "aka": "POS",
        "generated_at": now_utc_iso(),
        "position_index": str(POSITION_INDEX_PATH),
        "summary": index.get("summary") or {},
        "orphans": index.get("orphans") or {},
        "entry_count": len(entries),
        "proof_digest": digest,
        "tesseract_capacity": 16,
    }
    XDG_DATA.mkdir(parents=True, exist_ok=True)
    PROOF_OF_SPATIO_PATH.write_text(json.dumps(proof, indent=2, default=str))
    return proof


def api_positioning(rebuild: bool = False) -> Dict[str, Any]:
    if rebuild or not POSITION_INDEX_PATH.is_file():
        index = pos_reconcile(write=True)
    else:
        try:
            index = json.loads(POSITION_INDEX_PATH.read_text())
        except Exception:
            index = pos_reconcile(write=True)
    proof = build_proof_of_spatio(index)
    return {
        "ok": True,
        "aka": "POS",
        "proof_type": "proof_of_spatio",
        "position_index": str(POSITION_INDEX_PATH),
        "proof_path": str(PROOF_OF_SPATIO_PATH),
        "summary": index.get("summary") or {},
        "orphans": index.get("orphans") or {},
        "entries": index.get("entries") or [],
        "proof_digest": proof.get("proof_digest"),
        "generated_at": proof.get("generated_at"),
    }


def api_positioning_orphans(rebuild: bool = False) -> Dict[str, Any]:
    data = api_positioning(rebuild=rebuild)
    entries = data.get("entries") or []
    by_id = {e.get("id"): e for e in entries if e.get("id")}
    orphans = data.get("orphans") or {}
    avd_only = [by_id[i] for i in (orphans.get("avd_only") or []) if i in by_id]
    pos_only = [by_id[i] for i in (orphans.get("pos_only") or []) if i in by_id]
    return {
        "ok": True,
        "summary": data.get("summary") or {},
        "orphans": orphans,
        "avd_only_entries": avd_only,
        "pos_only_entries": pos_only,
        "proof_digest": data.get("proof_digest"),
    }


# ----------------------------- Cron scheduler (AVD/POS) -----------------------------

def _cron_interval_sec(task_row: sqlite3.Row) -> int:
    try:
        cfg = json.loads(task_row["config_json"] or "{}")
        if isinstance(cfg.get("interval_sec"), (int, float)) and cfg["interval_sec"] > 0:
            return int(cfg["interval_sec"])
    except Exception:
        pass
    # Parse simple */N * * * * minute cadence
    schedule = (task_row["schedule_cron"] or "").strip()
    m = re.match(r"\*/(\d+)\s", schedule)
    if m:
        return max(60, int(m.group(1)) * 60)
    return 600


def _cron_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "task_type": row["task_type"],
        "schedule_cron": row["schedule_cron"],
        "enabled": bool(row["enabled"]),
        "last_run": row["last_run"],
        "next_run": row["next_run"],
        "last_status": row["last_status"],
        "last_error": row["last_error"],
        "config_json": row["config_json"],
        "interval_sec": _cron_interval_sec(row),
    }


def _parse_iso_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        s = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def cron_task_is_due(task_row: sqlite3.Row, now: Optional[datetime] = None) -> bool:
    if not task_row["enabled"]:
        return False
    now = now or now_utc()
    nxt = _parse_iso_dt(task_row["next_run"])
    if nxt is None:
        return True
    return nxt <= now


def task_mint_watch() -> Dict[str, Any]:
    """Idempotent mint for new ~/Downloads/direct-h264-* files."""
    try:
        import interlaterus_desktop as ild

        result = ild.run_watch_once()
        return {"ok": True, "task": "mint_watch", **result}
    except Exception as e:
        return {"ok": False, "task": "mint_watch", "error": str(e)}


def task_avd_scan() -> Dict[str, Any]:
    """Tag analog/direct downloads as AVD (FILMIC) and refresh position index."""
    avd_list = _avd_entries()
    filmic = 0
    with_sha = 0
    for a in avd_list:
        # Direct downloads are AVD filmic by default (_avd_entries sets asc_mode=FILMIC)
        if (a.get("asc_mode") or "FILMIC") == "FILMIC":
            filmic += 1
        if a.get("sha256"):
            with_sha += 1
    index = pos_reconcile(write=True)
    summary = index.get("summary") or {}
    return {
        "ok": True,
        "task": "avd_scan",
        "avd_files": len(avd_list),
        "filmic_tagged": filmic,
        "with_sha256": with_sha,
        "position_summary": {
            "total": summary.get("total"),
            "paired_avd_pos": summary.get("paired_avd_pos"),
            "orphans_avd_only": summary.get("orphans_avd_only"),
            "orphans_pos_only": summary.get("orphans_pos_only"),
        },
    }


def task_pos_reconcile_run() -> Dict[str, Any]:
    """Merge vertex + storage_memory_category into position_index.json."""
    index = pos_reconcile(write=True)
    summary = index.get("summary") or {}
    return {
        "ok": True,
        "task": "pos_reconcile",
        "summary": summary,
        "orphans": index.get("orphans") or {},
        "position_index": str(POSITION_INDEX_PATH),
    }


CRON_TASK_HANDLERS = {
    "mint_watch": task_mint_watch,
    "pos_reconcile": task_pos_reconcile_run,
    "avd_scan": task_avd_scan,
}


def run_cron_task(task_id: int, force: bool = True) -> Dict[str, Any]:
    """Execute one cron task by id; updates cron_tasks + cron_runs audit log."""
    conn = get_db()
    row = conn.execute("SELECT * FROM cron_tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": f"task_id {task_id} not found"}
    if not force and not row["enabled"]:
        conn.close()
        return {"ok": False, "error": f"task {row['name']} is disabled"}

    task_type = row["task_type"]
    handler = CRON_TASK_HANDLERS.get(task_type)
    started = now_utc_iso()
    run_id = conn.execute(
        "INSERT INTO cron_runs (task_id, started, finished, status, result_json) VALUES (?,?,?,?,?)",
        (task_id, started, None, "running", None),
    ).lastrowid
    conn.commit()

    try:
        if not handler:
            raise ValueError(f"unknown task_type: {task_type}")
        result = handler()
        status = "ok" if result.get("ok", True) else "error"
        err = result.get("error")
    except Exception as e:
        result = {"ok": False, "error": str(e)}
        status = "error"
        err = str(e)

    finished = now_utc_iso()
    interval = _cron_interval_sec(row)
    next_run = (now_utc().timestamp() + interval)
    next_iso = datetime.fromtimestamp(next_run, tz=timezone.utc).isoformat()

    conn.execute(
        """
        UPDATE cron_runs SET finished = ?, status = ?, result_json = ? WHERE id = ?
        """,
        (finished, status, json.dumps(result, default=str), run_id),
    )
    conn.execute(
        """
        UPDATE cron_tasks
        SET last_run = ?, next_run = ?, last_status = ?, last_error = ?
        WHERE id = ?
        """,
        (finished, next_iso, status, err, task_id),
    )
    conn.commit()
    conn.close()
    return {
        "ok": status == "ok",
        "run_id": run_id,
        "task_id": task_id,
        "name": row["name"],
        "task_type": task_type,
        "status": status,
        "result": result,
        "next_run": next_iso,
    }


def cron_tick(force_all: bool = False) -> Dict[str, Any]:
    """Run all due (or all enabled if force_all) cron tasks once."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM cron_tasks ORDER BY id").fetchall()
    conn.close()
    now = now_utc()
    ran: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for row in rows:
        if not row["enabled"] and not force_all:
            skipped.append({"id": row["id"], "name": row["name"], "reason": "disabled"})
            continue
        if force_all or cron_task_is_due(row, now):
            ran.append(run_cron_task(row["id"], force=True))
        else:
            skipped.append({"id": row["id"], "name": row["name"], "reason": "not_due", "next_run": row["next_run"]})
    return {
        "ok": True,
        "ticked_at": now_utc_iso(),
        "ran": ran,
        "skipped": skipped,
        "ran_count": len(ran),
    }


def api_cron_list() -> Dict[str, Any]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM cron_tasks ORDER BY id").fetchall()
    conn.close()
    return {
        "ok": True,
        "tasks": [_cron_row_to_dict(r) for r in rows],
        "handlers": list(CRON_TASK_HANDLERS.keys()),
    }


def api_cron_runs(limit: int = 50) -> Dict[str, Any]:
    limit = max(1, min(200, int(limit or 50)))
    conn = get_db()
    rows = conn.execute(
        """
        SELECT r.id, r.task_id, t.name AS task_name, t.task_type,
               r.started, r.finished, r.status, r.result_json
        FROM cron_runs r
        LEFT JOIN cron_tasks t ON t.id = r.task_id
        ORDER BY r.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    runs = []
    for r in rows:
        item = {
            "id": r["id"],
            "task_id": r["task_id"],
            "task_name": r["task_name"],
            "task_type": r["task_type"],
            "started": r["started"],
            "finished": r["finished"],
            "status": r["status"],
        }
        try:
            item["result"] = json.loads(r["result_json"] or "{}")
        except Exception:
            item["result"] = r["result_json"]
        runs.append(item)
    return {"ok": True, "runs": runs, "count": len(runs)}


def api_cron_toggle(task_id: int, enabled: Optional[bool] = None) -> Dict[str, Any]:
    conn = get_db()
    row = conn.execute("SELECT * FROM cron_tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": f"task_id {task_id} not found"}
    if enabled is None:
        new_enabled = 0 if row["enabled"] else 1
    else:
        new_enabled = 1 if enabled else 0
    conn.execute("UPDATE cron_tasks SET enabled = ? WHERE id = ?", (new_enabled, task_id))
    conn.commit()
    row = conn.execute("SELECT * FROM cron_tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return {"ok": True, "task": _cron_row_to_dict(row)}


def start_cron_runner_thread(poll_sec: float = 45.0) -> threading.Thread:
    """Background thread: poll due cron tasks every poll_sec (in-process scheduler)."""

    def _loop():
        # small delay so gravity-serve binds first
        time.sleep(2.0)
        while True:
            try:
                cron_tick(force_all=False)
            except Exception as e:
                print(f"[cron-runner] tick error: {e}", file=sys.stderr)
            time.sleep(max(15.0, float(poll_sec)))

    t = threading.Thread(target=_loop, name="nls-cron-runner", daemon=True)
    t.start()
    return t


def cmd_cron(args):
    """CLI: nls-video cron list|tick|run|runs|toggle|runner"""
    action = getattr(args, "cron_action", None) or "list"
    if action == "list":
        data = api_cron_list()
        if args.json:
            print(json.dumps(data, indent=2, default=str))
            return
        print(f"{'ID':>3}  {'NAME':<16}  {'SCHEDULE':<14}  {'EN':<3}  {'STATUS':<8}  NEXT")
        for t in data["tasks"]:
            en = "on" if t["enabled"] else "off"
            print(
                f"{t['id']:>3}  {t['name']:<16}  {t['schedule_cron']:<14}  {en:<3}  "
                f"{(t['last_status'] or '—'):<8}  {t['next_run'] or 'due'}"
            )
        return
    if action == "tick":
        data = cron_tick(force_all=bool(getattr(args, "all", False)))
        if args.json:
            print(json.dumps(data, indent=2, default=str))
            return
        print(f"cron tick @ {data['ticked_at']} — ran {data['ran_count']}")
        for r in data["ran"]:
            print(f"  ✓ {r.get('name')}: {r.get('status')} next={r.get('next_run')}")
        for s in data["skipped"]:
            print(f"  · skip {s.get('name')}: {s.get('reason')}")
        return
    if action == "run":
        tid = getattr(args, "id", None)
        if tid is None:
            print("usage: nls-video cron run --id N", file=sys.stderr)
            return
        data = run_cron_task(int(tid), force=True)
        if args.json:
            print(json.dumps(data, indent=2, default=str))
            return
        print(f"task {data.get('name')}: {data.get('status')}")
        if data.get("result"):
            print(json.dumps(data["result"], indent=2, default=str))
        return
    if action == "runs":
        data = api_cron_runs(limit=getattr(args, "limit", 50) or 50)
        if args.json:
            print(json.dumps(data, indent=2, default=str))
            return
        for r in data["runs"]:
            print(f"#{r['id']} task={r.get('task_name')} {r.get('status')} {r.get('started')}")
        return
    if action == "toggle":
        tid = getattr(args, "id", None)
        if tid is None:
            print("usage: nls-video cron toggle --id N [--enable|--disable]", file=sys.stderr)
            return
        enabled = None
        if getattr(args, "enable", False):
            enabled = True
        elif getattr(args, "disable", False):
            enabled = False
        data = api_cron_toggle(int(tid), enabled=enabled)
        if args.json:
            print(json.dumps(data, indent=2, default=str))
            return
        if not data.get("ok"):
            print(data.get("error", "toggle failed"), file=sys.stderr)
            return
        t = data["task"]
        print(f"task {t['name']}: enabled={t['enabled']}")
        return
    if action == "runner":
        poll = float(getattr(args, "interval", 45) or 45)
        print(f"nls-video cron-runner foreground (poll every {poll:.0f}s) — Ctrl+C to stop")
        print(f"  tasks DB: {DB_PATH}")
        try:
            while True:
                data = cron_tick(force_all=False)
                if data.get("ran_count"):
                    print(f"[{data['ticked_at']}] ran {data['ran_count']}: "
                          + ", ".join(r.get("name", "?") for r in data["ran"]))
                time.sleep(max(15.0, poll))
        except KeyboardInterrupt:
            print("\ncron-runner stopped")
        return
    print(f"unknown cron action: {action}", file=sys.stderr)


def cmd_spatio(args):
    if args.rebuild or not PROOF_OF_SPATIO_PATH.is_file():
        api_positioning(rebuild=True)
    proof = json.loads(PROOF_OF_SPATIO_PATH.read_text())
    if args.json:
        print(json.dumps(proof, indent=2))
        return
    print("Proof of Spatio (aka POS)")
    print(f"  digest: {proof.get('proof_digest')}")
    print(f"  entries: {proof.get('entry_count')}")
    s = proof.get("summary") or {}
    print(f"  paired AVD↔POS: {s.get('paired_avd_pos', 0)}")
    print(f"  orphans AVD-only: {s.get('orphans_avd_only', 0)}")
    print(f"  orphans POS-only: {s.get('orphans_pos_only', 0)}")
    print(f"  vertices occupied: {s.get('vertices_occupied', 0)}/16")
    print(f"  proof file: {PROOF_OF_SPATIO_PATH}")
    print(f"  index file: {POSITION_INDEX_PATH}")


def cmd_running_status(args):
    if args.json:
        print(json.dumps(api_running(), indent=2))
        return
    r = read_gravity_serve_running()
    if not r.get("running"):
        print("No gravity-serve running version on disk.")
        print(f"  mm notify: {MM_NOTIFY_PATH}")
        return
    live = api_running()
    print("gravity-serve running version (for mm)")
    print(f"  {r.get('for_mm')}")
    print(f"  live pid:  {live.get('live_pid')}")
    print(f"  file:      {GRAVITY_SERVE_RUNNING_PATH}")
    print(f"  mm notify: {MM_NOTIFY_PATH}")
    print(f"  poll:      {r.get('api_running')}")


def cmd_gravity_serve_archive(args):
    from archive_gravity_serve import archive_gravity_serve

    dest = Path(args.dest).expanduser() if args.dest else None
    result = archive_gravity_serve(dest, log_tail_lines=args.log_tail)
    running = read_gravity_serve_running()
    if running.get("running") and running.get("pid"):
        write_gravity_serve_running(
            pid=int(running["pid"]),
            http_port=int(running.get("http_port") or 8766),
            gravity_host=(running.get("gravity_bridge") or {}).get("host", "127.0.0.1"),
            gravity_port=int((running.get("gravity_bridge") or {}).get("port") or 4242),
            archive_dir=result.get("archive_dir"),
            event="archived",
        )
    if args.json:
        print(json.dumps(result, indent=2))
        return
    print("gravity-serve archived — live server kept running")
    print(f"  dir:   {result.get('archive_dir')}")
    print(f"  proof: {result.get('proof_digest')}")
    proc = result.get("live_server") or {}
    if proc.get("pid"):
        print(f"  pid:   {proc['pid']} (still running)")


def cmd_aoa_delta(args):
    from aoa_delta_compose import compose_aoa_delta, DEG_PER_SLICE, SLICES_PER_360

    report_dir = Path(args.report_dir).expanduser() if args.report_dir else None
    result = compose_aoa_delta(report_dir, write=not args.no_write)
    if args.json:
        print(json.dumps(result, indent=2))
        return
    if not result.get("ok"):
        print(result.get("error", "AOA delta compose failed"))
        return
    print("AOA | NLS Visualist — LIFO delta program")
    print(f"  {SLICES_PER_360} angular slices × {DEG_PER_SLICE}° = 360° + slice 0 axiom")
    print(f"  LIFO pop: {' → '.join(str(x) for x in result['lifo_pop_order'])}")
    print(f"  composite: {result.get('composite_sha256')}")
    print(f"  proof:     {result.get('proof_digest')}")
    if result.get("written"):
        print(f"  delta:     {result['written']}")


def write_gravity_serve_running(
    *,
    pid: int,
    http_port: int,
    gravity_host: str,
    gravity_port: int,
    archive_dir: Optional[str] = None,
    event: str = "started",
) -> Dict[str, Any]:
    """Persist live running version — mm polls this file or GET /api/running."""
    manifest = load_version_manifest()
    url = f"http://127.0.0.1:{http_port}/"
    archive_latest = str(ARCHIVE_LATEST_LINK.resolve()) if ARCHIVE_LATEST_LINK.is_symlink() else None
    payload: Dict[str, Any] = {
        "ok": True,
        "running": True,
        "event": event,
        "updated_at_utc": now_utc_iso(),
        "time_axiom": TIME_AXIOM,
        "pid": pid,
        "version": manifest.get("version", __version__),
        "tag": manifest.get("tag", f"v{__version__}"),
        "released": manifest.get("released"),
        "url": url,
        "api_running": f"{url}api/running",
        "api_version": f"{url}api/version",
        "app_root": str(_SCRIPT_DIR),
        "http_port": http_port,
        "gravity_bridge": {"host": gravity_host, "port": gravity_port},
        "archive_latest": archive_latest,
        "last_archive_dir": archive_dir,
        "for_mm": (
            f"gravity-serve {manifest.get('tag', 'v' + __version__)} running on :{http_port} "
            f"(pid {pid}) — poll {url}api/running"
        ),
    }
    XDG_DATA.mkdir(parents=True, exist_ok=True)
    GRAVITY_SERVE_RUNNING_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    MM_NOTIFY_PATH.write_text(
        json.dumps(
            {
                "to": "mm",
                "subject": "gravity-serve running",
                "message": payload["for_mm"],
                "at_utc": payload["updated_at_utc"],
                "running_version": payload,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return payload


def read_gravity_serve_running() -> Dict[str, Any]:
    if GRAVITY_SERVE_RUNNING_PATH.is_file():
        try:
            return json.loads(GRAVITY_SERVE_RUNNING_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"ok": False, "running": False, "error": "No running version file"}


def api_running(bridge_snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base = read_gravity_serve_running()
    if not base.get("running"):
        return {**base, "ok": False, "live_pid": None}
    pid = base.get("pid")
    live = False
    if pid:
        try:
            os.kill(int(pid), 0)
            live = True
        except (OSError, ValueError, TypeError):
            live = False
    out = dict(base)
    out["live_pid"] = live
    out["checked_at_utc"] = now_utc_iso()
    if bridge_snapshot is not None:
        out["gravity_connected"] = bool(bridge_snapshot.get("connected"))
        out["jobs_count"] = len(bridge_snapshot.get("jobs") or [])
    return out


def api_version() -> Dict[str, Any]:
    manifest = load_version_manifest()
    running = read_gravity_serve_running()
    return {
        "ok": True,
        "name": manifest.get("name", APP_NAME),
        "version": manifest.get("version", __version__),
        "tag": manifest.get("tag", f"v{__version__}"),
        "released": manifest.get("released"),
        "components": manifest.get("components", {}),
        "running": bool(running.get("running") and running.get("pid")),
        "running_pid": running.get("pid"),
        "running_url": running.get("url"),
    }


def api_cancel_job(job_id: int) -> Dict[str, Any]:
    conn = get_db()
    job = load_job(conn, int(job_id))
    if job and job.status in ("pending", "downloading", "converting"):
        job.status = "cancelled"
        job.stage = "cancelled"
        job.finished = now_utc_iso()
        save_job(conn, job)
        conn.close()
        _stop_job_processes(int(job_id))
        return {"ok": True, "job_id": job_id, "status": "cancelled"}
    conn.close()
    return {"ok": False, "error": "Job not cancelable or not found", "job_id": job_id}


def api_stop_jobs() -> Dict[str, Any]:
    """Abrupt cancel of every pending/downloading/converting job, then return a fresh jobs list."""
    conn = get_db()
    live = [j for j in list_jobs(conn) if j.status in ("pending", "downloading", "converting")]
    cancelled: List[int] = []
    for job in live:
        job.status = "cancelled"
        job.stage = "cancelled"
        job.finished = now_utc_iso()
        save_job(conn, job)
        cancelled.append(int(job.id))
    jobs = [j.to_dict() for j in list_jobs(conn)]
    conn.close()
    for jid in cancelled:
        _stop_job_processes(jid)
    return {
        "ok": True,
        "cancelled": cancelled,
        "cancelled_count": len(cancelled),
        "jobs": jobs,
        "worker": worker_status(),
    }


def _extract_x_status_id(url: str) -> str:
    m = _X_STATUS_RE.search(url or "")
    return m.group(1) if m else ""


def _extract_giphy_id(url: str) -> str:
    m = re.search(
        r"(?:media\d*\.giphy\.com/media/|i\.giphy\.com/)([A-Za-z0-9]+)",
        url or "",
        re.I,
    )
    if m:
        return m.group(1)
    m = re.search(r"giphy\.com/(?:gifs|media|embed)/([^/?#]+)", url or "", re.I)
    if not m:
        return ""
    slug = m.group(1)
    dash = slug.rfind("-")
    if dash >= 0 and dash < len(slug) - 4:
        return slug[dash + 1 :]
    return slug


def _extract_imgur_id(url: str) -> str:
    m = re.search(
        r"(?:i\.)?imgur\.com/(?:gallery/|a/)?([A-Za-z0-9]+)(?:\.(?:gifv|gif|mp4|webm|png|jpg|jpeg))?",
        url or "",
        re.I,
    )
    return m.group(1) if m else ""


def _resolve_ipfs_url(url: str) -> str:
    """ipfs://CID → HTTP gateway. Same as GravityDesktop.resolveDownloadUrl. Not a venv path."""
    u = (url or "").strip()
    if not u.lower().startswith("ipfs://"):
        return u
    gw = (os.environ.get("GRAVITY_IPFS_GATEWAY") or "https://ipfs.io/ipfs/").strip()
    if not gw.endswith("/"):
        gw += "/"
    path = u[7:]
    if path.lower().startswith("ipfs/"):
        path = path[5:]
    return gw + path


def _is_youtube_url(url: str) -> bool:
    u = (url or "").lower()
    return "youtube.com/" in u or "youtu.be/" in u or "youtube-nocookie.com/" in u


def _extract_query_id(url: str) -> str:
    """Form follows function: viewkey= / v= / id= — not the .php basename (view_video)."""
    m = re.search(
        r"[?&](?:viewkey|vkey|video_id|v|id|file|cid|hash|vk)=([A-Za-z0-9_-]{4,})",
        url or "",
        re.I,
    )
    if not m:
        return ""
    vid = m.group(1)
    return vid[:24]


def _extract_media_id(url: str) -> str:
    url = _resolve_ipfs_url((url or "").strip())
    qid = _extract_query_id(url)
    if qid:
        return qid
    if "youtu.be/" in url.lower():
        return url.rsplit("/", 1)[-1].split("?")[0][:20]
    xid = _extract_x_status_id(url)
    if xid:
        return xid
    gid = _extract_giphy_id(url)
    if gid:
        return gid
    iid = _extract_imgur_id(url)
    if iid:
        return iid
    m = re.search(r"/(\d{8,})", url)
    if m:
        return m.group(1)
    tail = url.split("?")[0].rsplit("/", 1)[-1]
    tail = re.sub(r"\.[^.]+$", "", tail)
    if tail:
        return tail[:20]
    return hex(abs(hash(url)))[2:10]


def _resolve_x_status_media_url(status_id: str) -> str:
    if not status_id:
        return ""
    twimg_gif = re.compile(r"https://video\.twimg\.com/tweet_video/[A-Za-z0-9_-]+\.mp4")
    twimg_any = re.compile(r"https://video\.twimg\.com/[A-Za-z0-9_./-]+\.mp4")
    for ep in (
        f"https://api.fxtwitter.com/status/{status_id}",
        f"https://api.vxtwitter.com/Twitter/status/{status_id}",
    ):
        try:
            req = urllib.request.Request(
                ep, headers={"User-Agent": HTTP_UA, "Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                body = resp.read().decode("utf-8", "replace")
            m = twimg_gif.search(body) or twimg_any.search(body)
            if m:
                return m.group(0)
        except Exception:
            continue
    return ""


def _resolve_gif_direct_url(url: str) -> str:
    xid = _extract_x_status_id(url)
    if xid:
        return _resolve_x_status_media_url(xid)
    gid = _extract_giphy_id(url)
    if gid:
        return f"https://i.giphy.com/{gid}.gif"
    iid = _extract_imgur_id(url)
    if iid:
        low = url.lower()
        if any(ext in low for ext in (".gifv", ".mp4", ".webm")):
            return f"https://i.imgur.com/{iid}.mp4"
        return f"https://i.imgur.com/{iid}.gif"
    return ""


def _file_starts_with(path: Path, magic: bytes) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(len(magic)) == magic
    except Exception:
        return False


def _file_is_gif(path: Path) -> bool:
    return _file_starts_with(path, b"GIF87a") or _file_starts_with(path, b"GIF89a")


def _file_looks_like_video(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            b = fh.read(12)
        if len(b) < 12:
            return False
        if b[4:8] == b"ftyp":
            return True
        if b[:3] == b"\x1aE\xdf":
            return True
        if b[:4] == b"RIFF":
            return True
    except Exception:
        return False
    return False


def _file_looks_like_html(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            s = fh.read(64).lstrip().lower()
        return s.startswith(b"<!doctype") or s.startswith(b"<html") or s.startswith(b"<?xml")
    except Exception:
        return False


def _extract_gif_candidates(html: str) -> List[str]:
    if not html:
        return []
    h = html.replace("\\/", "/").replace("\\u002F", "/")
    ranked: List[str] = []
    gifs: List[str] = []
    videos: List[str] = []
    seen = set()
    for m in re.finditer(r"https://[^\s\"'<>\\]+", h, re.I):
        u = m.group(0).replace("&amp;", "&")
        for i, ch in enumerate(u):
            if ch in "<>)]}\"":
                u = u[:i]
                break
        low = u.lower()
        path = low.split("?", 1)[0]
        if any(
            bad in low
            for bad in (
                "favicon", "sprite", "/static/", "pixel", "1x1", "analytics",
                "woff", ".svg", "pinterest.com", "facebook.com",
            )
        ):
            continue
        if u in seen:
            continue
        seen.add(u)
        is_gif = path.endswith(".gif") and not path.endswith(".gifv")
        tw_gif = "/tweet_video/" in path and path.endswith(".mp4")
        is_vid = path.endswith((".mp4", ".webm", ".gifv"))
        if is_gif or tw_gif:
            if any(k in low for k in ("giphy", "tenor", "imgur", "twimg")) or tw_gif:
                ranked.append(u)
            else:
                gifs.append(u)
        elif is_vid and any(k in low for k in ("twimg", "imgur", "giphy", "redgifs", "tenor")):
            videos.append(u)
    out = ranked + gifs + videos
    return out[:12]


def _http_download_file(url: str, dest: Path, referer: str = "", on_progress=None) -> bool:
    headers = {
        "User-Agent": HTTP_UA,
        "Accept": "image/gif,image/webp,image/*,video/mp4,video/webm,text/html,*/*",
    }
    if referer:
        headers["Referer"] = referer
    try:
        if dest.exists():
            dest.unlink()
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as fh:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    fh.write(chunk)
                    got += len(chunk)
                    if total and on_progress:
                        on_progress(min(99, int(got * 100 / total)))
        return dest.is_file() and dest.stat().st_size > 0
    except Exception:
        if dest.exists():
            try:
                dest.unlink()
            except Exception:
                pass
        return False


def _recode_video_to_gif(src: Path, dest: Path) -> bool:
    ffmpeg = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
    try:
        if dest.exists():
            dest.unlink()
        cmd = [
            ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-loglevel", "error",
            "-y", "-i", str(src), "-an",
            "-vf", r"fps=12,scale=min(480\,iw):-1:flags=lanczos",
            str(dest),
        ]
        rc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600).returncode
        if rc == 0 and _file_is_gif(dest):
            return True
        cmd = [
            ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-loglevel", "error",
            "-y", "-i", str(src), "-an", str(dest),
        ]
        rc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600).returncode
        return rc == 0 and _file_is_gif(dest)
    except Exception:
        return False


def _save_as_gif(url: str, dest: Path, on_progress=None, depth: int = 0, seen=None, referer: str = "") -> bool:
    """Native GIF over HTTP, host resolvers (X/Giphy/Tenor/Imgur), HTML scrape, or mp4 recode."""
    if not url or depth > 4:
        return False
    if seen is None:
        seen = set()
    key = url.split("#")[0]
    if key in seen:
        return False
    seen.add(key)
    resolved = _resolve_gif_direct_url(url)
    if resolved and resolved != url and _save_as_gif(resolved, dest, on_progress, depth + 1, seen, url):
        return True
    part = Path(str(dest) + ".part")
    got = _http_download_file(url, part, referer=referer or url, on_progress=on_progress)
    if got and _file_is_gif(part):
        if dest.exists():
            dest.unlink()
        part.replace(dest)
        return _file_is_gif(dest)
    if got and _file_looks_like_video(part):
        ok = _recode_video_to_gif(part, dest)
        try:
            part.unlink()
        except Exception:
            pass
        if ok:
            return True
    if got:
        html = ""
        try:
            html = part.read_text(errors="replace")
        except Exception:
            html = ""
        try:
            part.unlink()
        except Exception:
            pass
        if html:
            for cand in _extract_gif_candidates(html):
                if _save_as_gif(cand, dest, on_progress, depth + 1, seen, url):
                    return True
    elif part.exists():
        try:
            part.unlink()
        except Exception:
            pass
    iid = _extract_imgur_id(url)
    if iid and _save_as_gif(f"https://i.imgur.com/{iid}.mp4", dest, on_progress, depth + 1, seen, url):
        return True
    return dest.is_file() and _file_is_gif(dest)


def _oembed_x_title(status_id: str) -> str:
    if not status_id:
        return ""
    try:
        req = urllib.request.Request(
            f"https://api.fxtwitter.com/status/{status_id}",
            headers={"User-Agent": HTTP_UA, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        tweet = data.get("tweet") if isinstance(data, dict) else None
        if not isinstance(tweet, dict):
            return ""
        text = (tweet.get("text") or "").strip()
        user = ((tweet.get("author") or {}).get("screen_name") or "").strip()
        if text:
            return f"{text[:80]}" + (f" (@{user})" if user else "")
    except Exception:
        return ""
    return ""


def _download_host(name: str, source_url: str = "", did: str = "") -> str:
    u = (source_url or "").lower()
    n = (name or "").lower()
    if "x.com" in u or "twitter.com" in u or (did.isdigit() and len(did) >= 15):
        return "x"
    if "giphy" in u or "giphy" in n:
        return "giphy"
    if "tenor" in u or "tenor" in n:
        return "tenor"
    if "imgur" in u:
        return "imgur"
    if _youtube_id_from_name(name):
        return "youtube"
    if n.startswith("direct-gif-"):
        return "gif"
    return "h264"


def _guess_source_url(name: str, sidecar_url: str = "") -> str:
    did = _direct_id_from_name(name)
    if did.isdigit() and len(did) >= 15:
        return f"https://x.com/i/status/{did}"
    if sidecar_url:
        return sidecar_url
    ytid = _youtube_id_from_name(name)
    if ytid:
        return f"https://youtu.be/{ytid}"
    if _extract_giphy_id("https://giphy.com/gifs/" + did) == did and did and not did.isdigit():
        return f"https://giphy.com/gifs/{did}"
    return ""


# Peak and loudness match GravityDesktop: one programme gain, measured after the file exists.
NORM_PEAK_DBFS = -1.0
NORM_LOUDNESS_LUFS = -23.0
NORM_TRUE_PEAK_DBTP = -1.5
NORM_LRA = 11.0
_MAX_VOL_RE = re.compile(
    r"max_volume:\s*(-inf|inf|-?[0-9]+(?:\.[0-9]+)?)\s*dB",
    re.IGNORECASE,
)


def parse_max_volume_db(ffmpeg_text: str) -> Optional[float]:
    if not ffmpeg_text:
        return None
    last: Optional[float] = None
    for m in _MAX_VOL_RE.finditer(ffmpeg_text):
        v = m.group(1)
        if v.lower() in ("-inf", "inf"):
            last = float("-inf")
        else:
            try:
                last = float(v)
            except ValueError:
                last = None
    return last


def peak_volume_filter(max_volume_db: Optional[float]) -> Optional[str]:
    if max_volume_db is None or max_volume_db != max_volume_db or abs(max_volume_db) == float("inf"):
        return None
    gain = NORM_PEAK_DBFS - max_volume_db
    if abs(gain) < 0.05:
        return None
    return f"volume={gain:.3f}dB"


def norm_json_number(text: str, key: str) -> Optional[str]:
    if not text or not key:
        return None
    m = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]+)"', text)
    return m.group(1).strip() if m else None


def loudnorm_linear_filter(measured_text: str) -> Optional[str]:
    i = norm_json_number(measured_text, "input_i")
    tp = norm_json_number(measured_text, "input_tp")
    lra = norm_json_number(measured_text, "input_lra")
    thresh = norm_json_number(measured_text, "input_thresh")
    offset = norm_json_number(measured_text, "target_offset")
    if not all((i, tp, lra, thresh, offset)):
        return None
    if "inf" in i.lower() or "inf" in tp.lower():
        return None
    try:
        measured_i = float(i)
        measured_tp = float(tp)
    except ValueError:
        return None
    if abs(measured_i - NORM_LOUDNESS_LUFS) < 0.5 and measured_tp <= NORM_TRUE_PEAK_DBTP + 0.05:
        return None
    return (
        f"loudnorm=I={NORM_LOUDNESS_LUFS:.1f}:TP={NORM_TRUE_PEAK_DBTP:.1f}:LRA={NORM_LRA:.1f}"
        f":measured_I={i}:measured_TP={tp}:measured_LRA={lra}:measured_thresh={thresh}"
        f":offset={offset}:linear=true"
    )


def audio_norm_filter(mode: str, measured_text: str) -> Optional[str]:
    if mode == "peak":
        return peak_volume_filter(parse_max_volume_db(measured_text))
    if mode == "loudness":
        return loudnorm_linear_filter(measured_text)
    return None


def _ffmpeg_bin() -> str:
    return shutil.which("ffmpeg") or "/usr/bin/ffmpeg"


def _ffmpeg_text(args: List[str], timeout: int = 3600) -> str:
    proc = subprocess.run(
        [_ffmpeg_bin(), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    text = (proc.stderr or "") + "\n" + (proc.stdout or "")
    if proc.returncode != 0:
        tail = " ".join(text.split())[-240:]
        raise RuntimeError(f"ffmpeg exit {proc.returncode} {tail}")
    return text


def _measure_audio_norm(path: Path, mode: str) -> str:
    if mode == "loudness":
        af = (
            f"loudnorm=I={NORM_LOUDNESS_LUFS:.1f}:TP={NORM_TRUE_PEAK_DBTP:.1f}"
            f":LRA={NORM_LRA:.1f}:print_format=json"
        )
    else:
        af = "volumedetect"
    return _ffmpeg_text([
        "-hide_banner", "-nostdin", "-nostats",
        "-i", str(path), "-map", "0:a:0", "-af", af, "-f", "null", "-",
    ])


def _norm_codec_args(ext: str, fmt: str) -> List[str]:
    e = (ext or "").lower()
    f = fmt or ""
    if e in (".m4a", ".mp4", ".aac", ".mkv", ".webm", ".mov"):
        return ["-c:a", "aac", "-b:a", "256k", "-aac_coder", "twoloop", "-profile:a", "aac_low"]
    if e == ".mp3":
        return ["-c:a", "libmp3lame", "-b:a", "320k", "-compression_level", "0"]
    if e == ".flac":
        return ["-c:a", "flac", "-compression_level", "8", "-sample_fmt", "s32"]
    if e == ".ogg":
        return ["-c:a", "libvorbis", "-q:a", "6"]
    if "16" in f:
        return ["-c:a", "pcm_s16le"]
    return ["-c:a", "pcm_s24le"]


def _stamp_rec_norm(path: Path, mode: str) -> None:
    sidecar = Path(str(path) + ".rec.json")
    if not sidecar.is_file():
        return
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        data["norm"] = mode
        data["bytes"] = path.stat().st_size if path.is_file() else data.get("bytes")
        sidecar.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


def normalize_media_file(path: Path, mode: str) -> Dict[str, Any]:
    """Rewrite audio in place. Peak → −1 dBFS. Loudness → −23 LUFS, true peak −1.5 dBTP."""
    mode = (mode or "off").strip().lower()
    if mode not in ("peak", "loudness"):
        return {"ok": False, "error": "norm mode is peak or loudness"}
    path = path.expanduser().resolve()
    if not path.is_file():
        return {"ok": False, "error": f"file not found: {path}"}
    if path.suffix.lower() == ".gif":
        return {"ok": False, "error": "GIF has no programme audio to normalize"}
    try:
        measured = _measure_audio_norm(path, mode)
        filt = audio_norm_filter(mode, measured)
    except Exception as ex:
        return {"ok": False, "error": str(ex), "path": str(path)}
    if not filt:
        _stamp_rec_norm(path, mode)
        return {
            "ok": True,
            "skipped": True,
            "mode": mode,
            "path": str(path),
            "message": f"norm {mode} already at target — {path.name}",
        }
    ext = path.suffix or ".wav"
    tmp = path.with_name(path.stem + ".norm-tmp" + ext)
    meta = _read_rec_sidecar(path)
    probe = _ffprobe_media(path)
    audio_only = ext.lower() in (".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg")
    cmd = [
        _ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-i", str(path),
    ]
    if audio_only or not probe.get("vcodec"):
        cmd += ["-vn", "-map", "0:a:0"]
    else:
        cmd += ["-map", "0:v:0", "-c:v", "copy", "-map", "0:a:0"]
    cmd += ["-af", filt + ",aresample=48000:resampler=soxr:precision=28"]
    cmd += _norm_codec_args(ext, str(meta.get("format") or ""))
    if ext.lower() in (".m4a", ".mp4", ".mov"):
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(tmp))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except Exception as ex:
        if tmp.exists():
            tmp.unlink()
        return {"ok": False, "error": str(ex), "path": str(path)}
    if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size < 32:
        if tmp.exists():
            tmp.unlink()
        tail = " ".join(((proc.stderr or "") + (proc.stdout or "")).split())[-180:]
        return {
            "ok": False,
            "error": f"norm {mode} ffmpeg exit {proc.returncode} {tail}".strip(),
            "path": str(path),
            "message": f"norm {mode} ffmpeg exit {proc.returncode} — kept {path.name}",
        }
    os.replace(tmp, path)
    _stamp_rec_norm(path, mode)
    return {
        "ok": True,
        "skipped": False,
        "mode": mode,
        "path": str(path),
        "filter": filt,
        "message": f"norm {mode} → {path.name}",
    }


def _downloads_file(path: str) -> Optional[Path]:
    raw = str(path or "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    if not p.is_file():
        cand = DOWNLOADS_DIR / Path(raw).name
        p = cand if cand.is_file() else p
    try:
        p = p.resolve()
    except Exception:
        return None
    if not p.is_file():
        return None
    if p.parent != DOWNLOADS_DIR.resolve():
        return None
    return p


def api_normalize(path: str, mode: str) -> Dict[str, Any]:
    """Background peak or loudness rewrite of one file in ~/Downloads."""
    mode = (mode or "").strip().lower()
    if mode not in ("peak", "loudness"):
        return {"ok": False, "error": "norm mode is peak or loudness"}
    p = _downloads_file(path)
    if p is None:
        return {"ok": False, "error": "file must be in ~/Downloads"}
    with _direct_dl_lock:
        if _direct_dl_state.get("status") == "downloading":
            return {"ok": False, "error": "A download or convert is already running"}
    _direct_dl_set(
        status="downloading",
        progress=5.0,
        message=f"norm {mode} {p.name} …",
        error=None,
        url=None,
        path=str(p),
        log=[],
    )

    def _worker() -> None:
        result = normalize_media_file(p, mode)
        if result.get("ok"):
            _direct_dl_set(
                status="done",
                progress=100.0,
                message=result.get("message") or f"norm {mode} → {p.name}",
                error=None,
                path=str(p),
            )
        else:
            msg = result.get("message") or result.get("error") or f"norm {mode} failed"
            _direct_dl_set(status="error", error=msg, message=msg, progress=0.0, path=str(p))

    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True, "mode": mode, "path": str(p), "message": f"norm {mode} {p.name} …"}


def api_direct_download(
    url: str,
    gif: bool = False,
    mint: bool = True,
    vacuum: bool = False,
    tls_ja3: bool = True,
    detail: bool = False,
    height: Any = 2160,
    norm: str = "off",
) -> Dict[str, Any]:
    """Mirror GravityDesktop direct download → ~/Downloads/direct-h264-*.mp4 or direct-gif-*.gif."""
    if not url or not url.strip():
        return {"ok": False, "error": "URL required"}
    url = _resolve_ipfs_url(url.strip())

    with _direct_dl_lock:
        if _direct_dl_state.get("status") == "downloading":
            return {"ok": False, "error": "Another direct download is already running"}

    media_id = _extract_media_id(url)
    target_h = parse_target_height(height)
    start_msg = (
        "GIF trigger — any GIF (HTTP / X / Giphy / Tenor / recode)..."
        if gif
        else f"Starting yt-dlp direct {target_h}p to ~/Downloads/..."
    )
    _direct_dl_set(
        status="downloading",
        progress=0.0,
        message=start_msg,
        error=None,
        url=url,
        path=None,
        log=[],
        vacuum=bool(vacuum),
        tls_ja3=bool(tls_ja3),
        detail=bool(detail),
    )
    if detail:
        _vacuum_append(
            f"download start gif={gif} vacuum={vacuum} TLS/JA3={'chrome' if tls_ja3 else 'off'} {url[:80]}",
            True,
        )

    def _finish_ok(path: Path, title: str) -> None:
        vac_note = ""
        norm_note = ""
        if vacuum and path and Path(path).is_file():
            _direct_dl_set(message="Vacuum — TLS/JA3 on request; stripping JS/injection from file…")
            vac_note = _vacuum_media_file(Path(path), detail=detail)
        if norm in ("peak", "loudness") and path and Path(path).is_file() and not gif:
            _direct_dl_set(message=f"norm {norm} {Path(path).name} …", progress=96.0)
            result = normalize_media_file(Path(path), norm)
            norm_note = " · " + (result.get("message") or result.get("error") or f"norm {norm}")
        if mint and os.environ.get("INTERLATERUS_SKIP_MINT") != "1":
            script = Path(__file__).resolve().parent / "interlaterus_desktop.py"
            if script.is_file():
                _direct_dl_set(message="Minting interlaterus blockcode…", progress=100.0)
                subprocess.run(
                    ["/usr/bin/python3", str(script), "mint", "--file", str(path), "--url", url, "--title", title],
                    capture_output=True,
                    text=True,
                )
        _direct_dl_set(
            status="done",
            progress=100.0,
            message=f"✓ done → {path.name}{vac_note}{norm_note}",
            error=None,
            path=str(path),
        )

    def _worker() -> None:
        dest = next_direct_dest(media_id, gif=gif)
        cleared = _cleanup_download_temps(dest)
        if detail:
            _vacuum_append(f"dest {dest.name}" + (f" cleared {cleared} leftover part(s)" if cleared else ""), True)
        outtmpl = str(dest)
        fmt = YTDLP_GIF_FORMAT if gif else ytdlp_format_for_height(target_h)
        use_private = os.environ.get("GRAVITY_USE_COOKIES", "1") != "0"

        def on_line(line: str) -> None:
            pct = _parse_ytdlp_progress(line)
            if pct is not None:
                _direct_dl_set(progress=pct, message=f"Downloading… {pct:.0f}%")
                return
            low = line.lower()
            # Vacuum/detail must not surface yt-dlp JS-runtime API errors as the URL reason.
            if "js_runtimes" in low or ("impersonat" in low and "warning" in low):
                if detail:
                    _vacuum_append("yt-dlp: " + line.strip()[:160], True)
                return
            if line.strip():
                _direct_dl_set(message=line.strip()[:120])

        try:
            if gif:
                def on_pct(p: int) -> None:
                    _direct_dl_set(progress=float(p), message=f"GIF downloading… {p}%")

                _direct_dl_set(message="GIF — fetching (HTTP / host / recode)…")
                if _save_as_gif(url, dest, on_progress=on_pct):
                    title = dest.stem.replace("direct-gif-", "")
                    xid = _extract_x_status_id(url)
                    if xid:
                        title = _oembed_x_title(xid) or title
                    _finish_ok(dest, title)
                    return
                _direct_dl_set(message="GIF HTTP miss — yt-dlp fallback…")

            ensure_js_runtime(interactive=False)
            _direct_dl_set(message="Checking formats (yt-dlp --list-formats)...")
            list_args = _build_ytdlp_cli_base(
                url, use_private, impersonate="chrome" if tls_ja3 else "off"
            ) + ["--list-formats", url]
            list_result = _run_ytdlp_cli(list_args)
            if list_result["exit_code"] != 0 and _output_indicates_403(list_result["lines"]):
                GravityRateLimiter.on_403()
            if not gif:
                generic = not _is_youtube_url(url)
                picked = select_format_from_list(
                    list_result.get("lines") or [], False, generic, target_h
                )
                if picked:
                    fmt = picked
                _direct_dl_set(message=f"Selected {target_h}p {fmt} — downloading...")

            _direct_dl_set(message="Downloading…")
            dl_args = _build_ytdlp_cli_base(
                url, use_private, impersonate="chrome" if tls_ja3 else "off"
            )
            if gif:
                dl_args += ["-f", fmt, "--recode-video", "gif", "--newline", "-o", outtmpl, url]
            else:
                dl_args += ["-f", fmt, "--merge-output-format", "mp4", "--newline", "-o", outtmpl, url]

            max_retries = int(os.environ.get("GRAVITY_403_RETRIES", "2"))
            attempt = 0
            dl_result = _run_ytdlp_cli(dl_args, on_line=on_line)
            while (
                dl_result["exit_code"] != 0
                and _output_indicates_403(dl_result["lines"])
                and attempt < max_retries
            ):
                attempt += 1
                GravityRateLimiter.on_403()
                cool = GravityRateLimiter.cooldown_seconds_remaining()
                _direct_dl_set(
                    message=f"403/IP restricted — cooldown {cool}s, retry {attempt}/{max_retries}",
                    progress=0.0,
                )
                dl_result = _run_ytdlp_cli(dl_args, on_line=on_line)

            if dl_result["exit_code"] != 0:
                if _output_indicates_403(dl_result["lines"]):
                    GravityRateLimiter.on_403()
                    err = "HTTP 403 / IP restricted — try cookies (GRAVITY_COOKIES_BROWSER) or GRAVITY_PROXY"
                else:
                    err = dl_result["last_line"] or "yt-dlp failed"
                _cleanup_download_temps(dest)
                _direct_dl_set(status="error", error=err, message=err, progress=0.0)
                return

            GravityRateLimiter.on_success()
            # Do not call YoutubeDL Python API here — vacuum-on downloads used to
            # hit extract_info() with a list js_runtimes and report that as the URL error.
            path = dest if dest.is_file() else None
            info = None
            if path is None or not path.is_file():
                candidates = sorted(
                    DOWNLOADS_DIR.glob("direct-gif-*" if gif else "direct-h264-*"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                path = candidates[0] if candidates else None
            if path is None or not path.is_file():
                _direct_dl_set(status="error", error="Download finished but output file not found", progress=0.0)
                return

            title = (info or {}).get("title", path.stem)
            if not gif and path.is_file():
                probe = _ffprobe_media(path)
                if is_transcode_needed(str(probe.get("vcodec") or "")):
                    _direct_dl_set(
                        message=f"VP9 → H.264  {probe.get('height') or target_h}p same pixels…",
                        progress=90.0,
                    )

                    def _conv_pct(p: int) -> None:
                        _direct_dl_set(progress=float(p), message=f"VP9 → H.264 {p}%")

                    avc = transcode_vp9_to_h264(path, on_progress=_conv_pct)
                    if avc is not None and avc.is_file():
                        path = avc
            _finish_ok(path, title)
        except Exception as e:
            err = str(e)
            if _output_indicates_403([err]):
                err = "HTTP 403 / IP restricted — try cookies or GRAVITY_PROXY"
            _direct_dl_set(status="error", error=err, message=err, progress=0.0)
            print(f"direct download error: {e}", file=sys.stderr)

    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True, "mode": "direct", "gif": gif, "url": url, "height": target_h, "target": str(DOWNLOADS_DIR)}


def api_convert_h264(path: str) -> Dict[str, Any]:
    """Convert an existing VP9/AV1 file in ~/Downloads to H.264 at the same pixels."""
    if not path or not str(path).strip():
        return {"ok": False, "error": "path required"}
    p = Path(str(path).strip()).expanduser()
    if not p.is_file():
        cand = DOWNLOADS_DIR / Path(str(path).strip()).name
        if cand.is_file():
            p = cand
        else:
            return {"ok": False, "error": f"file not found: {path}"}
    probe = _ffprobe_media(p)
    if not is_transcode_needed(str(probe.get("vcodec") or "")):
        return {
            "ok": True,
            "skipped": True,
            "path": str(p),
            "vcodec": probe.get("vcodec"),
            "message": f"Already H.264 ({probe.get('vcodec') or '?'})",
        }
    with _direct_dl_lock:
        if _direct_dl_state.get("status") == "downloading":
            return {"ok": False, "error": "A download or convert is already running"}
    dest_name = Path(h264_sibling_path(str(p))).name
    _direct_dl_set(
        status="downloading",
        progress=0.0,
        message=f"VP9 → H.264 {probe.get('height') or ''}p same pixels…",
        error=None,
        url=str(p),
        path=None,
        log=[],
    )

    def _worker() -> None:
        def on_pct(pct: int) -> None:
            _direct_dl_set(progress=float(pct), message=f"VP9 → H.264 {pct}%")

        avc = transcode_vp9_to_h264(p, on_progress=on_pct)
        if avc is not None and avc.is_file():
            _direct_dl_set(
                status="done",
                progress=100.0,
                message=f"✓ H.264 → {avc.name}",
                error=None,
                path=str(avc),
            )
        else:
            _direct_dl_set(
                status="error",
                error="VP9 → H.264 failed",
                message="VP9 → H.264 failed — kept original",
                progress=0.0,
            )

    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True, "mode": "convert", "src": str(p), "dest": dest_name}


def api_add_job(
    url: str,
    preset: str = "balanced-4k",
    gravity: bool = False,
    height: Any = None,
) -> Dict[str, Any]:
    if not url or not url.strip():
        return {"ok": False, "error": "URL required"}
    cfg = load_config()
    if preset not in DEFAULT_PRESETS:
        preset = cfg.get("default_preset", "balanced-4k")
    raw = url.strip()
    local = _as_local_media_path(raw)
    source_file: Optional[str] = str(local) if local is not None else None
    title = "Untitled"
    if local is not None:
        title = local.stem
    else:
        try:
            ensure_js_runtime(interactive=False)
            import yt_dlp
            with yt_dlp.YoutubeDL({"quiet": True, **_ytdlp_api_extra_opts(True)}) as ydl:
                info = ydl.extract_info(raw, download=False)
                title = (info or {}).get("title", "Untitled") or "Untitled"
        except Exception:
            pass
    now = now_utc_iso()
    metadata: Dict[str, Any] = {}
    if gravity:
        metadata["gravity"] = True
    if local is not None:
        metadata["local_source"] = True
    metadata["target_height"] = parse_target_height(
        height if height is not None else preset_target_height(preset)
    )
    conn = get_db()
    conn.execute(
        """INSERT INTO jobs (url, title, preset, status, progress, stage, created, metadata, source_file)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            raw if local is None else str(local),
            title,
            preset,
            "pending",
            0,
            "queued",
            now,
            json.dumps(metadata),
            source_file,
        ),
    )
    job_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    wstat = worker_status()
    # Opportunistically start embedded worker if serve has it enabled and none is running
    if not wstat.get("running") and os.environ.get("GRAVITY_WORKER_ENABLED", "1").lower() in (
        "1", "true", "yes", "on",
    ):
        start_worker_thread(mode="embedded")
        wstat = worker_status()
    return {
        "ok": True,
        "job_id": job_id,
        "title": title,
        "preset": preset,
        "status": "pending",
        "stage": "queued",
        "source_file": source_file,
        "mode": "convert-only" if source_file else "download+convert",
        "worker": wstat,
        "hint": (
            None
            if wstat.get("running")
            else "Job queued — start worker: nls-video worker"
        ),
    }


def api_retry_job(job_id: int) -> Dict[str, Any]:
    """Requeue a failed/cancelled/(corrupt)completed job back to pending for the pipeline worker."""
    conn = get_db()
    job = load_job(conn, int(job_id))
    if not job:
        conn.close()
        return {"ok": False, "error": "Job not found", "job_id": job_id}
    if job.status not in ("failed", "cancelled", "completed"):
        conn.close()
        return {
            "ok": False,
            "error": f"Only failed/cancelled/completed jobs can be retried (status={job.status})",
            "job_id": job_id,
        }
    # Re-detect local source if URL is a path
    if not job.source_file:
        local = _as_local_media_path(job.url or "")
        if local is not None:
            job.source_file = str(local)
    # Also allow retry of "completed" jobs that left unplayable output
    _stop_job_processes(int(job_id))
    _remove_job_outputs(job, keep_log=True)
    job.status = "pending"
    job.stage = "queued"
    job.progress = 0.0
    job.started = None
    job.finished = None
    job.error = f"retried @ {now_utc_iso()}"
    save_job(conn, job)
    conn.close()
    if os.environ.get("GRAVITY_WORKER_ENABLED", "1").lower() in ("1", "true", "yes", "on"):
        start_worker_thread(mode="embedded")
    return {
        "ok": True,
        "job_id": job_id,
        "status": "pending",
        "worker": worker_status(),
    }


def cmd_gravity_serve(args):
    """Browser Gravity client — HTML dashboard proxying gravity-server live updates.
    Serves jobs, visualist catalog, interlaterus mints, and ~/Downloads direct files.
    """
    runtime_logger = RuntimeJsonLogger(
        "gravity-serve",
        {
            "http_port": args.port,
            "gravity_host": args.gravity_host,
            "gravity_port": args.gravity_port,
        },
    )
    runtime_logger.append("session_start", {"http_port": args.port})
    # Bind TCP gravity-server first so GravityBridge + Java handshake immediately.
    server_embedded = os.environ.get("GRAVITY_SERVER_EMBEDDED", "1").lower() in (
        "1", "true", "yes", "on",
    )
    if server_embedded:
        start_gravity_server_thread(
            host=args.gravity_host, port=args.gravity_port, mode="embedded"
        )
    bridge = GravityBridge(host=args.gravity_host, port=args.gravity_port, logger=runtime_logger)
    threading.Thread(target=bridge.run_forever, daemon=True).start()
    api_log_interval = float(os.environ.get("GRAVITY_API_LOG_INTERVAL_SEC", "60"))
    last_api_log: Dict[str, float] = {"gravity": 0.0, "downloads": 0.0}

    def _maybe_log_api(kind: str, payload: Dict[str, Any]) -> None:
        now = time.time()
        if now - last_api_log.get(kind, 0.0) < api_log_interval:
            return
        last_api_log[kind] = now
        runtime_logger.append(f"api_{kind}", payload)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *log_args):
            return  # quiet

        def _api_path(self) -> str:
            """Normalize path for routing (strip query, trailing slash)."""
            return urlparse(self.path).path.rstrip("/") or "/"

        def _json(self, data: Any, code: int = 200) -> None:
            body = json.dumps(data, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _read_json_body(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                return {}

        def do_HEAD(self):
            self._head_request = True
            try:
                self.do_GET()
            finally:
                self._head_request = False

        def do_GET(self):
            cfg = load_config()
            vroot = Path(cfg.get("visualist_root", DEFAULT_VISUALIST_ROOT))

            path = self._api_path()
            if path in ("/", "/index.html", "/gravity"):
                html_path = GRAVITY_SERVE_HTML
                if not html_path.is_file():
                    self.send_error(404, "gravity_serve.html missing")
                    return
                body = html_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path in ("/plan", "/plan.html"):
                if not PLAN_HTML.is_file():
                    self.send_error(404, "plan.html missing")
                    return
                body = PLAN_HTML.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/plan.md" and PLAN_MD.is_file():
                body = PLAN_MD.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/plan.original.md" and PLAN_ORIGINAL_MD.is_file():
                body = PLAN_ORIGINAL_MD.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/api/version":
                self._json(api_version())
            elif path == "/api/running":
                self._json(api_running(bridge.snapshot()))
            elif path == "/api/time":
                self._json(api_time())
            elif path == "/api/gravity":
                snap = _enrich_gravity_snapshot(bridge.snapshot())
                _maybe_log_api(
                    "gravity",
                    {
                        "connected": snap.get("connected"),
                        "jobs_count": len(snap.get("jobs") or []),
                        "catalog_count": len(snap.get("catalog") or []),
                    },
                )
                self._json(snap)
            elif path == "/api/interlaterus":
                self._json({"items": _interlaterus_catalog()})
            elif path == "/api/downloads":
                payload = api_downloads()
                _maybe_log_api(
                    "downloads",
                    {
                        "items_count": len(payload.get("items") or []),
                        "recs_count": len(payload.get("recs") or []),
                        "sample": [i.get("title") or i.get("name") for i in (payload.get("items") or [])[:3]],
                    },
                )
                self._json(payload)
            elif path == "/api/recs":
                recs = _rec_catalog_list()
                self._json({
                    "items": recs,
                    "counts": {
                        "recs": len(recs),
                        "wyhiwyrec": sum(1 for r in recs if r.get("fn") == "WYHIWYREC"),
                        "net_stream": sum(1 for r in recs if r.get("fn") == "net stream"),
                        "catalog": sum(1 for r in recs if r.get("fn") == "catalog"),
                    },
                })
            elif self.path == "/api/download/status":
                self._json(direct_download_status())
            elif path == "/api/vacuum/log":
                qs = parse_qs(urlparse(self.path).query)
                try:
                    limit = int((qs.get("limit") or ["40"])[0])
                except ValueError:
                    limit = 40
                self._json(api_vacuum_log(limit=limit))
            elif path in ("/api/positioning", "/api/spatio", "/api/spatio/proof"):
                qs = parse_qs(urlparse(self.path).query)
                rebuild = (qs.get("rebuild") or [""])[0].lower() in ("1", "true", "yes")
                self._json(api_positioning(rebuild=rebuild))
            elif path == "/api/positioning/orphans":
                qs = parse_qs(urlparse(self.path).query)
                rebuild = (qs.get("rebuild") or [""])[0].lower() in ("1", "true", "yes")
                self._json(api_positioning_orphans(rebuild=rebuild))
            elif path == "/api/cron":
                self._json(api_cron_list())
            elif path == "/api/cron/runs":
                qs = parse_qs(urlparse(self.path).query)
                try:
                    limit = int((qs.get("limit") or ["50"])[0])
                except ValueError:
                    limit = 50
                self._json(api_cron_runs(limit=limit))
            elif path == "/api/worker":
                self._json(worker_status())
            elif self.path == "/api/logs":
                self._json({
                    "session": json.loads(runtime_logger.session_path.read_text())
                    if runtime_logger.session_path.is_file() else {},
                    "runtime_ms": runtime_logger.runtime_ms(),
                    "live_log": str(runtime_logger.live_path),
                    "tail": runtime_logger.tail(30),
                })
            elif path.startswith("/docs/"):
                docs_root = Path.home() / "Downloads" / "GravityDesktop" / "docs"
                rel = unquote(path[len("/docs/"):].split("?", 1)[0])
                full = _safe_file_under(docs_root, rel)
                if not full:
                    self.send_error(404)
                    return
                kind = {
                    ".png": "image/png",
                    ".md": "text/markdown; charset=utf-8",
                    ".html": "text/html; charset=utf-8",
                }.get(full.suffix.lower(), "application/octet-stream")
                body = full.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/downloads/"):
                rel = self.path[len("/downloads/"):]
                full = _safe_file_under(DOWNLOADS_DIR, rel)
                if full and _serve_media_file(self, full):
                    return
                self.send_error(404)
            elif self.path.startswith("/visualist/"):
                rel = self.path[len("/visualist/"):]
                full = _safe_file_under(vroot, rel)
                if full and _serve_media_file(self, full):
                    return
                self.send_error(404)
            else:
                self.send_error(404)

        def do_POST(self):
            path = self._api_path()
            if path == "/api/add":
                data = self._read_json_body()
                result = api_add_job(
                    data.get("url", ""),
                    data.get("preset", "balanced-4k"),
                    bool(data.get("gravity")),
                    data.get("height"),
                )
                runtime_logger.append("api_add_job", result)
                self._json(result, 200 if result.get("ok") else 400)
            elif path == "/api/cancel":
                data = self._read_json_body()
                if data.get("all") or data.get("abrupt") or data.get("stop"):
                    result = api_stop_jobs()
                    runtime_logger.append("api_stop_jobs", {
                        "cancelled_count": result.get("cancelled_count"),
                        "via": "cancel",
                    })
                    self._json(result)
                else:
                    raw_id = data.get("id", data.get("job_id", 0))
                    try:
                        job_id = int(raw_id)
                    except (TypeError, ValueError):
                        job_id = 0
                    result = api_cancel_job(job_id)
                    runtime_logger.append("api_cancel_job", result)
                    self._json(result, 200 if result.get("ok") else 400)
            elif path == "/api/stop":
                result = api_stop_jobs()
                runtime_logger.append("api_stop_jobs", {
                    "cancelled_count": result.get("cancelled_count"),
                })
                self._json(result)
            elif path == "/api/retry":
                data = self._read_json_body()
                raw_id = data.get("id", data.get("job_id", 0))
                try:
                    job_id = int(raw_id)
                except (TypeError, ValueError):
                    job_id = 0
                result = api_retry_job(job_id)
                runtime_logger.append("api_retry_job", result)
                self._json(result, 200 if result.get("ok") else 400)
            elif path == "/api/vacuum/clear":
                self._json(api_vacuum_log_clear())
            elif path == "/api/download":
                data = self._read_json_body()
                result = api_direct_download(
                    data.get("url", ""),
                    bool(data.get("gif")),
                    data.get("mint", True) is not False,
                    vacuum=bool(data.get("vacuum")),
                    tls_ja3=data.get("tls_ja3", True) is not False,
                    detail=bool(data.get("detail")),
                    height=data.get("height", 2160),
                    norm=str(data.get("norm") or "off"),
                )
                runtime_logger.append("api_direct_download", result)
                self._json(result, 200 if result.get("ok") else 400)
            elif path == "/api/convert":
                data = self._read_json_body()
                result = api_convert_h264(str(data.get("path") or data.get("file") or ""))
                runtime_logger.append("api_convert_h264", result)
                self._json(result, 200 if result.get("ok") else 400)
            elif path == "/api/normalize":
                data = self._read_json_body()
                result = api_normalize(
                    str(data.get("path") or data.get("file") or ""),
                    str(data.get("mode") or data.get("norm") or ""),
                )
                runtime_logger.append("api_normalize", {
                    "ok": result.get("ok"),
                    "mode": result.get("mode"),
                    "path": result.get("path"),
                    "error": result.get("error"),
                })
                self._json(result, 200 if result.get("ok") else 400)
            elif path == "/api/open-downloads":
                try:
                    dl = str(DOWNLOADS_DIR)
                    if sys.platform == "darwin":
                        subprocess.Popen(["open", dl])
                    else:
                        subprocess.Popen(["xdg-open", dl])
                    self._json({"ok": True})
                except Exception as e:
                    self._json({"ok": False, "error": str(e)}, 500)
            elif path == "/api/locate":
                data = self._read_json_body()
                result = api_locate_file(
                    path=str(data.get("path") or ""),
                    name=str(data.get("name") or ""),
                )
                runtime_logger.append("api_locate", {
                    "ok": result.get("ok"),
                    "path": result.get("path"),
                    "name": result.get("name") or data.get("name"),
                })
                self._json(result, 200 if result.get("ok") else 400)
            elif path == "/api/cron/run":
                data = self._read_json_body()
                raw_id = data.get("task_id", data.get("id"))
                try:
                    task_id = int(raw_id)
                except (TypeError, ValueError):
                    self._json({"ok": False, "error": "task_id required"}, 400)
                    return
                result = run_cron_task(task_id, force=True)
                runtime_logger.append("api_cron_run", {"task_id": task_id, "status": result.get("status")})
                self._json(result, 200 if result.get("ok") or result.get("status") else 400)
            elif path == "/api/cron/toggle":
                data = self._read_json_body()
                raw_id = data.get("task_id", data.get("id"))
                try:
                    task_id = int(raw_id)
                except (TypeError, ValueError):
                    self._json({"ok": False, "error": "task_id required"}, 400)
                    return
                enabled = data.get("enabled")
                if enabled is not None:
                    enabled = bool(enabled)
                result = api_cron_toggle(task_id, enabled=enabled)
                runtime_logger.append("api_cron_toggle", result)
                self._json(result, 200 if result.get("ok") else 400)
            elif path == "/api/cron/tick":
                data = self._read_json_body()
                result = cron_tick(force_all=bool(data.get("all")))
                runtime_logger.append("api_cron_tick", {"ran_count": result.get("ran_count")})
                self._json(result)
            elif path == "/api/worker/start":
                result = start_worker_thread(mode="embedded")
                runtime_logger.append("api_worker_start", result)
                self._json({**result, "worker": worker_status()})
            elif path == "/api/worker/recover":
                result = recover_stale_jobs(reason="api recover", force=True)
                runtime_logger.append("api_worker_recover", result)
                # Ensure a worker exists to pick up requeued jobs
                if os.environ.get("GRAVITY_WORKER_ENABLED", "1").lower() in (
                    "1", "true", "yes", "on",
                ):
                    start_worker_thread(mode="embedded")
                self._json({**result, "worker": worker_status()})
            else:
                self._json({"ok": False, "error": "Not found", "path": path}, 404)

    class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
        daemon_threads = True

    port = args.port
    url = f"http://127.0.0.1:{port}/"
    running = write_gravity_serve_running(
        pid=os.getpid(),
        http_port=port,
        gravity_host=args.gravity_host,
        gravity_port=args.gravity_port,
        event="started",
    )
    cron_enabled = os.environ.get("GRAVITY_CRON_ENABLED", "0").lower() in ("1", "true", "yes", "on")
    if cron_enabled:
        poll = float(os.environ.get("GRAVITY_CRON_POLL_SEC", "45"))
        start_cron_runner_thread(poll_sec=poll)
        print(f"  Cron runner  → enabled (poll {poll:.0f}s)")
    else:
        print("  Cron runner  → off (set GRAVITY_CRON_ENABLED=1 to enable)")
    # Pipeline worker: default ON so Gravity Jobs → Pipeline Job (worker) actually processes.
    # Set GRAVITY_WORKER_ENABLED=0 to disable embedded worker (use standalone `nls-video worker`).
    worker_enabled = os.environ.get("GRAVITY_WORKER_ENABLED", "1").lower() in (
        "1", "true", "yes", "on",
    )
    if worker_enabled:
        wstart = start_worker_thread(mode="embedded")
        if wstart.get("started"):
            print(f"  Pipeline worker → embedded (pid {os.getpid()})")
            # Recovery runs inside worker loop (force=True) — avoid racing mid-download.
        elif wstart.get("reason") == "external_worker":
            print(f"  Pipeline worker → external pid {wstart.get('pid')}")
            recovered = recover_stale_jobs(reason="gravity-serve start (external worker)", force=True)
            if recovered.get("requeued"):
                print(f"  Recovered stale jobs → pending: {recovered['requeued']}")
        else:
            print(f"  Pipeline worker → {wstart.get('reason', 'running')}")
    else:
        print("  Pipeline worker → off (set GRAVITY_WORKER_ENABLED=1 or run: nls-video worker)")
        # Still recover so Jobs tab does not show zombie downloading forever
        recovered = recover_stale_jobs(reason="gravity-serve start (no worker)", force=True)
        if recovered.get("requeued"):
            print(f"  Requeued stale jobs (need worker): {recovered['requeued']}")
    # Embed gravity-server so Java GravityDesktop handshake works from this same process.
    # Set GRAVITY_SERVER_EMBEDDED=0 to keep a standalone `nls-video gravity-server`.
    server_embedded = os.environ.get("GRAVITY_SERVER_EMBEDDED", "1").lower() in (
        "1", "true", "yes", "on",
    )
    if server_embedded:
        sstart = start_gravity_server_thread(
            host=args.gravity_host, port=args.gravity_port, mode="embedded"
        )
        if sstart.get("started"):
            print(f"  Gravity server  → embedded {args.gravity_host}:{args.gravity_port}")
        elif sstart.get("reason") == "already_running":
            print(f"  Gravity server  → already running :{sstart.get('port')}")
        else:
            print(
                f"  Gravity server  → {sstart.get('reason', 'off')}"
                f" ({sstart.get('error') or 'external process on port?'})"
            )
    else:
        print("  Gravity server  → not embedded (run: nls-video gravity-server)")
    print(f"Gravity Serve HTML on {url}")
    print(f"  Version {__version__} ({load_version_manifest().get('tag', 'v' + __version__)})")
    print(f"  Running version → {GRAVITY_SERVE_RUNNING_PATH}")
    print(f"  mm notify       → {MM_NOTIFY_PATH}")
    print(f"  Poll            → {running.get('api_running')}")
    print(f"  Bridge → gravity-server {args.gravity_host}:{args.gravity_port}")
    print("  Tabs: jobs • visualist • interlaterus • downloads • WYHIWYREC • POS • Scheduled • ASC live")
    print(f"  Runtime log: {runtime_logger.live_path}")
    print(f"  Verify: {Path(__file__).resolve().parent / 'verify-gravity-api.sh'}")
    try:
        subprocess.run(["xdg-open", url], check=False)
    except Exception:
        pass
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()


def cmd_catalog(args):
    """Catalog an existing video file into NLS Visualist data.
    Rule #1: no kill. Rule #2: no eval.
    This just registers metadata without touching running processes.
    """
    cfg = load_config()
    video = Path(args.file)
    if not video.exists():
        print("File not found:", video)
        return
    title = args.title or video.stem
    now = now_utc_iso()
    sidecar = video.with_suffix(".nlsvis.json")
    data = {
        "title": title,
        "source_url": args.source_url or "external/manual",
        "preset": "external",
        "output_path": str(video),
        "processed_at": now,
        "tags": ["h264", "external"],
    }
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration,size,bit_rate",
             "-of", "json", str(video)],
            text=True
        )
        info = json.loads(out)
        data["technical"] = info.get("format", {})
    except Exception:
        pass
    # Generate thumbnail for Visualist interface
    thumb = video.with_suffix(".thumb.jpg")
    if generate_thumbnail(video, thumb):
        data["thumbnail"] = str(thumb)

    if getattr(args, 'gravity', False):
        h264 = prepare_for_noise_gravity(video)
        data["gravity_prepared"] = True
        data["raw_h264_stream"] = str(h264)
        try:
            keygen_bin = "/home/nlsrecords/Downloads/SCIS/dist-newstyle/build/x86_64-linux/ghc-9.6.7/noiseprotocol-0.1.0.0/x/noiseprotocol-keygen/build/noiseprotocol-keygen/noiseprotocol-keygen"
            if os.path.exists(keygen_bin):
                key_out = subprocess.check_output([keygen_bin], text=True)
                data["noise_gravity_keys"] = key_out.strip()
        except Exception:
            pass

    if getattr(args, 'interstellar_nonlinear', False):
        data["interstellar_nonlinear"] = True
        data["vp56_gravity_prepared"] = True
        vp56 = prepare_interstellar_nonlinear_gravity(video)
        data["vp56_raw_stream"] = str(vp56)

    # Always add storage memory category with zone and memory|location|zone|V|Bandwidth
    is_inter = getattr(args, 'interstellar_nonlinear', False) or "interstellar" in (title or "").lower() or "nonlineari" in (title or "").lower()
    data["storage_memory_category"] = {
        "zone": "interstellar-zone-alpha" if is_inter else "default-zone",
        "memory": "16GB" if is_inter else "8GB",
        "location": "nls-visualist-dc-1" if is_inter else "local-dc",
        "zone": "interstellar-zone-alpha" if is_inter else "default-zone",
        "V": "vp56-vol-1999" if is_inter else "h264-vol",
        "Bandwidth": "10Gbps" if is_inter else "1Gbps"
    }

    sidecar.write_text(json.dumps(data, indent=2))

    catalog = []
    if CATALOG_PATH.exists():
        try:
            catalog = json.loads(CATALOG_PATH.read_text())
        except Exception:
            catalog = []
    catalog.append(data)
    CATALOG_PATH.write_text(json.dumps(catalog, indent=2))

    print(f"Cataloged to NLS Visualist data: {sidecar}")
    print(f"Central catalog updated: {CATALOG_PATH}")


def cmd_list_catalog(args):
    """List the NLS Visualist catalog, highlighting gravity/noiseprotocol prepared items."""
    catalog = []
    if CATALOG_PATH.exists():
        try:
            catalog = json.loads(CATALOG_PATH.read_text())
        except Exception:
            catalog = []
    if not catalog:
        print("Catalog empty. Complete some jobs with --gravity or use nls-video catalog on finished files.")
        return
    if RICH_AVAILABLE:
        table = Table(title="NLS Visualist Data Catalog (Gravity/NoiseProtocol + Storage Memory Category)")
        table.add_column("Title")
        table.add_column("Gravity?", style="green")
        table.add_column("Interstellar?", style="cyan")
        table.add_column("Storage Mem (zone|mem|loc|V|BW)")
        table.add_column("Output")
        for item in catalog:
            grav = "YES" if item.get("gravity_prepared") or item.get("raw_h264_stream") else "no"
            inter = "YES" if item.get("interstellar_nonlinear") or "interstellar" in item.get("title","").lower() or "nonlineari" in item.get("title","").lower() else "no"
            smc = item.get("storage_memory_category", {})
            storage = f"{smc.get('zone','?')}|{smc.get('memory','?')}|{smc.get('location','?')}|{smc.get('V','?')}|{smc.get('Bandwidth','?')}"
            dur = item.get("technical", {}).get("duration", "?")
            out = item.get("output_path", "?")
            table.add_row(item.get("title", "?")[:30], grav, inter, storage, out.split("/")[-1][:25])
        Console().print(table)
    else:
        print("NLS Visualist Data Catalog:")
        for item in catalog:
            grav = "GRAVITY" if item.get("gravity_prepared") or item.get("raw_h264_stream") else ""
            inter = "INTER" if item.get("interstellar_nonlinear") or "interstellar" in item.get("title","").lower() or "nonlineari" in item.get("title","").lower() else ""
            smc = item.get("storage_memory_category", {})
            storage = f"zone={smc.get('zone','?')} mem={smc.get('memory','?')} loc={smc.get('location','?')} V={smc.get('V','?')} BW={smc.get('Bandwidth','?')}"
            print(f"  {item.get('title', '?')} {grav} {inter} {storage} -> {item.get('output_path','?')}")


def cmd_monitor(args):
    """Terminal TUI dashboard inside the terminal with the same idea as the web interface.
    Uses your Visualist aesthetics: glitch-style title, '1000 years old nonlinear h@k reality' banner,
    ASC cinematic thumbnails (styled panels with film-like borders and colors), gravity/noiseprotocol highlights.
    Live updating 'window' using rich panels and tables. No kill, no eval.
    Shows Pipeline Jobs (live from DB) and NLS Visualist Data (from catalog + current job integration).
    """
    if not RICH_AVAILABLE:
        print("rich not available, falling back to simple loop. Install rich for full TUI.")
        # simple fallback
        while True:
            os.system('clear' if os.name == 'posix' else 'cls')
            print("NLS Visualist Terminal Monitor (simple mode)")
            print("1000 years old nonlinear h@k reality")
            print("\nJobs:")
            conn = get_db()
            for j in list_jobs(conn):
                print(f"  #{j.id} {j.title[:40]} {j.status} {j.progress:.1f}% {j.preset}")
            conn.close()
            print("\nCatalog (last 5):")
            if CATALOG_PATH.exists():
                try:
                    cat = json.loads(CATALOG_PATH.read_text())[-5:]
                    for it in cat:
                        print(f"  {it.get('title','?')} gravity={bool(it.get('gravity_prepared'))}")
                except:
                    pass
            time.sleep(2)
        return

    console = Console()
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=5),
        Layout(name="body"),
    )
    layout["body"].split_row(
        Layout(name="jobs", ratio=1),
        Layout(name="visualist", ratio=1),
    )

    def make_header():
        title = Text("NLS Visualist • Terminal Monitor", style="bold cyan")
        banner = Text("\n1000 years old nonlinear h@k reality", style="magenta italic")
        glitch_note = Text("\n[glitch aesthetics + ASC thumbnails + noiseprotocol gravity]", style="dim")
        return Panel(title + banner + glitch_note, border_style="green", title="NLS Visualist Data Interface (Terminal)")

    def make_jobs_panel():
        conn = get_db()
        jobs = list_jobs(conn)
        conn.close()
        table = Table(title="Pipeline Jobs (live)", show_header=True, header_style="bold blue")
        table.add_column("ID", style="cyan", width=4)
        table.add_column("Title", style="white")
        table.add_column("Status", style="magenta")
        table.add_column("Progress", style="green")
        table.add_column("Preset")
        for j in jobs:
            prog = f"{j.progress:.1f}%"
            if j.status == "converting":
                prog += " [convert]"
            table.add_row(str(j.id), j.title[:35], j.status, prog, j.preset)
        return Panel(table, border_style="blue", title="Jobs Window")

    def make_visualist_panel():
        catalog = []
        if CATALOG_PATH.exists():
            try:
                catalog = json.loads(CATALOG_PATH.read_text())
            except:
                pass
        # Include current job as "live" item for Visualist integration
        conn = get_db()
        current_jobs = list_jobs(conn, status="converting")
        conn.close()
        items = catalog[-5:]  # last 5
        table = Table(title="NLS Visualist Data (ASC Thumbnails + Gravity)", show_header=True, header_style="bold purple")
        table.add_column("Item", style="white")
        table.add_column("ASC Thumb", style="yellow")
        table.add_column("Gravity?", style="green")
        table.add_column("Info")
        for it in items:
            grav = "YES (noiseprotocol)" if it.get("gravity_prepared") or it.get("raw_h264_stream") else "no"
            thumb = "[ASC filmic]"  # simulated ASC thumbnail
            dur = it.get("technical", {}).get("duration", "?")
            table.add_row(it.get("title", "?")[:25], thumb, grav, f"{dur}s")
        for j in current_jobs:
            table.add_row(f"[LIVE] {j.title[:20]}", "[ASC live]", "in progress", f"{j.progress:.1f}%")
        return Panel(table, border_style="purple", title="Visualist Data Window (from catalog + live jobs)")

    with Live(layout, refresh_per_second=1, screen=True, console=console) as live:
        while True:
            layout["header"].update(make_header())
            layout["jobs"].update(make_jobs_panel())
            layout["visualist"].update(make_visualist_panel())
            time.sleep(1.5)
            # user can Ctrl+C to exit; follows no kill rule (no process termination)


def _sigma9():
    """Load the shared sigma-9 greeting. The pipe file is often a symlink."""
    import sys
    from pathlib import Path
    candidates = [
        Path(__file__).parent,
        Path(__file__).resolve().parent,
        Path.home() / "Downloads" / "GravityDesktop",
    ]
    for c in candidates:
        if (c / "sigma9.py").is_file():
            p = str(c)
            if p not in sys.path:
                sys.path.insert(0, p)
            break
    import sigma9
    if sigma9.sigma() != 9 or len(sigma9.PROLOGUE) != 9:
        raise RuntimeError("sigma-9 greeting is not 9 bytes")
    return sigma9


def _recv_exact(conn: socket.socket, n: int) -> bytes:
    """Read n bytes. socket.recv may return a short slice and desync the handshake."""
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionResetError("gravity handshake closed")
        buf += chunk
    return bytes(buf)


def _gravity_client_handler(conn, addr) -> None:
    """Handshake + JSON gravity_update lines (same protocol as GravityDesktop.java).

    Fixed greeting, not Noise_XX: prologue GRAVITY\\x00\\x01, 32-byte 0x42 hello,
    32-byte server hello, 48-byte 0x43 finish, then newline JSON.
    A client that closes is a dropped caller (EPIPE), not a dead server.
    """
    try:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sig = _sigma9()
        conn.sendall(sig.PROLOGUE)
        sig.read_sigma9(conn, 32)
        conn.sendall(b"\x00" * 32)
        sig.read_sigma9(conn, 48)
        while True:
            conn_db = get_db()
            jobs = [j.to_dict() for j in list_jobs(conn_db)]
            conn_db.close()
            catalog = []
            if CATALOG_PATH.exists():
                try:
                    catalog = json.loads(CATALOG_PATH.read_text())
                except Exception:
                    catalog = []
            update = {
                "type": "gravity_update",
                "jobs": jobs,
                "catalog": catalog,
                "timestamp": now_utc_iso(),
                "worker": worker_status(),
            }
            try:
                conn.sendall((json.dumps(update) + "\n").encode("utf-8"))
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                break
            time.sleep(2.0)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        return
    except Exception as e:
        print(f"Gravity client {addr} error: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _gravity_accept_loop(server_sock: socket.socket, host: str, port: int, mode: str) -> None:
    global _gravity_server_sock
    with _gravity_server_lock:
        _gravity_server_state.update(
            {
                "running": True,
                "host": host,
                "port": port,
                "mode": mode,
                "error": None,
                "started_at": now_utc_iso(),
            }
        )
        _gravity_server_sock = server_sock
    try:
        while True:
            try:
                conn, addr = server_sock.accept()
            except OSError:
                break
            print(f"Gravity client connected from {addr}")
            threading.Thread(
                target=_gravity_client_handler,
                args=(conn, addr),
                daemon=True,
                name=f"gravity-client-{addr[1]}",
            ).start()
    finally:
        with _gravity_server_lock:
            _gravity_server_state["running"] = False
            if _gravity_server_sock is server_sock:
                _gravity_server_sock = None
        try:
            server_sock.close()
        except Exception:
            pass


def start_gravity_server_thread(
    host: str = "127.0.0.1",
    port: int = 4242,
    mode: str = "embedded",
) -> Dict[str, Any]:
    """Bind gravity-server in-process so Java + gravity-serve share one pipeline."""
    global _gravity_server_thread
    with _gravity_server_lock:
        if _gravity_server_state.get("running") and _gravity_server_thread and _gravity_server_thread.is_alive():
            return {
                "ok": True,
                "started": False,
                "reason": "already_running",
                "host": _gravity_server_state.get("host"),
                "port": _gravity_server_state.get("port"),
                "mode": _gravity_server_state.get("mode"),
            }
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_sock.bind((host, int(port)))
        server_sock.listen(5)
    except OSError as e:
        try:
            server_sock.close()
        except Exception:
            pass
        return {
            "ok": False,
            "started": False,
            "reason": "bind_failed",
            "host": host,
            "port": port,
            "error": str(e),
        }
    t = threading.Thread(
        target=_gravity_accept_loop,
        args=(server_sock, host, int(port), mode),
        daemon=True,
        name="gravity-server",
    )
    _gravity_server_thread = t
    t.start()
    return {"ok": True, "started": True, "host": host, "port": int(port), "mode": mode}


def _worker_enabled() -> bool:
    return os.environ.get("GRAVITY_WORKER_ENABLED", "1").lower() in ("1", "true", "yes", "on")


def _ensure_embedded_worker(reason: str = "pipeline") -> Dict[str, Any]:
    if not _worker_enabled():
        return {"ok": True, "started": False, "reason": "disabled"}
    wstat = worker_status()
    if wstat.get("running"):
        return {"ok": True, "started": False, "reason": "already_running", "worker": wstat}
    result = start_worker_thread(mode="embedded")
    result["reason_ctx"] = reason
    return result


def cmd_gravity_server(args):
    """Start Gravity protocol server (NoiseProtocol structure from SCIS, for 'gravity' secure transport of Visualist data).
    Clients (e.g. Java + Qt desktop app) connect, perform simple handshake (prologue GRAVITY, hello/finish with magic bytes like SCIS 0x42/0x43), then receive JSON updates of jobs + catalog.
    This allows the desktop window to act *as the protocol client* for the NLS Visualist interface.
    Rule #1 no kill, Rule #2 no eval. Pure sockets + JSON.

    Also starts the pipeline worker so queued jobs convert without a separate `nls-video worker`.
    """
    host = "127.0.0.1"
    port = args.port
    wstart = _ensure_embedded_worker(reason="gravity-server")
    if wstart.get("started"):
        print(f"  Pipeline worker → embedded (pid {os.getpid()})")
    elif wstart.get("reason") == "already_running":
        print("  Pipeline worker → already running")
    elif wstart.get("reason") == "disabled":
        print("  Pipeline worker → off (set GRAVITY_WORKER_ENABLED=1 or run: nls-video worker)")
    else:
        print(f"  Pipeline worker → {wstart.get('reason', wstart)}")
    print(f"Starting NoiseProtocol Gravity server on {host}:{port} (for Java/Qt desktop windows)...")
    result = start_gravity_server_thread(host=host, port=port, mode="standalone")
    if not result.get("ok"):
        print(f"gravity-server failed to bind {host}:{port}: {result.get('error')}")
        return
    if not result.get("started"):
        print(f"gravity-server already running ({result.get('reason')}) on {result.get('host')}:{result.get('port')}")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nGravity server interrupted.")


def cmd_gravity_client(args):
    """Terminal client for the Gravity protocol - the 'same' as the Java/Qt desktop window, but inside the terminal.
    Connects to gravity-server, handshake (SCIS-inspired), receives live JSON updates, renders a rich TUI 'window' with panels for:
    - Header with glitch aesthetics + "1000 years old nonlinear h@k reality" banner
    - Jobs table (live from protocol)
    - Visualist Data gallery (ASC thumbnails as styled panels, gravity highlights, links to streams)
    - NEW: URL drag & drop / copy & paste INPUT BAR (size 3) directly above the status bar for data downloading to ~/Downloads/
    Uses rich for 'built-in window' feel (panels as windows). Live updating. Follows no kill, no eval.
    Run this in a terminal to 'open the window' with the same idea as the Java desktop one.
    """
    if not RICH_AVAILABLE:
        print("rich required for TUI. pip install rich")
        return
    console = Console()
    host = "127.0.0.1"
    port = args.port
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host, port))
        # Handshake. Prologue is 9 bytes: derivatives 1+2+3+3.
        sig = _sigma9()
        sig.check_prologue(sig.read_sigma9(s, 9))
        s.send(b'\x42' * 32)  # client hello
        sig.read_sigma9(s, 32)  # server hello
        s.send(b'\x43' * 48)  # finish
        console.print("[green]Gravity handshake complete. Receiving protocol updates...[/green]")

        layout = Layout()
        layout.split_column(
            Layout(name="header", size=5),
            Layout(name="body"),
            Layout(name="input", size=3),
            Layout(name="status", size=3),
        )
        layout["body"].split_row(
            Layout(name="jobs", ratio=1),
            Layout(name="visualist", ratio=1),
        )

        def make_header():
            # KISS + visual_language_animation.svg (monospace, cyan, colored nodes for H.264 stages)
            title = Text("NLS Visualist • H.264", style="bold cyan")
            flow = Text(" ◐URL  ▦DL  ⌬H264  ▣GRAV  ◈CAT ", style="cyan")
            sub = Text("URL → yt-dlp → ffmpeg H.264 → (gravity) → catalog", style="dim")
            return Panel(title + "\n" + flow + "\n" + sub, border_style="cyan", title="KISS")

        def make_progress_bar(percent: float, width: int = 20, status: str = "converting") -> Text:
            """KISS progress. Block bar colored by H.264 pipeline stage."""
            pct = max(0.0, min(100.0, percent))
            filled = int(width * (pct / 100))
            bar = "█" * filled + "░" * (width - filled)
            color = "cyan" if status in ("downloading", "converting") else "green"
            if status == "failed":
                color = "red"
            text = Text()
            text.append(f"[{bar}] ", style=color)
            text.append(f"{pct:.1f}%", style="white")
            return text

        def make_status_bar(jobs_data, catalog_data):
            """KISS bottom bar."""
            active = sum(1 for j in jobs_data if j.get('status') in ['downloading', 'converting'])
            completed = sum(1 for j in jobs_data if j.get('status') == 'completed')
            status_text = Text()
            status_text.append("H.264 • ", style="bold cyan")
            status_text.append(f"{active} active / {completed} done  |  no kill • no eval", style="dim")
            return Panel(status_text, border_style="cyan", title="status")

        def make_jobs_panel(jobs_data):
            table = Table(title="H.264 Jobs (live)", show_header=True, header_style="bold cyan")
            table.add_column("#", style="cyan", width=3)
            table.add_column("Title", style="white")
            table.add_column("Stage", style="magenta")
            table.add_column("Progress", style="cyan")
            for j in jobs_data:
                prog_bar = make_progress_bar(j.get('progress', 0), width=16, status=j.get('status', ''))
                table.add_row(
                    str(j.get('id')),
                    j.get('title', '?')[:32],
                    j.get('status', '?'),
                    prog_bar
                )
            return Panel(table, border_style="cyan", title="jobs")

        def make_visualist_panel(catalog_data):
            text = Text("Visualist (H.264 + Gravity)\n", style="bold cyan")
            text.append("monospace • dark • simple\n", style="dim")
            for it in catalog_data[-4:]:
                grav = " g" if it.get("gravity_prepared") or it.get("raw_h264_stream") else ""
                text.append(f"• {it.get('title','?')[:28]}{grav}\n", style="white")
            return Panel(text, border_style="cyan", title="visualist")

        # Simple stage indicators row (KISS nodes from the SVG visual language)
        def make_stages_panel():
            txt = Text()
            stages = [
                ("◐", "cyan", "URL"),
                ("▦", "yellow", "DL"),
                ("⌬", "red", "H264"),
                ("▣", "green", "GRAV"),
                ("◈", "magenta", "CAT"),
            ]
            for sym, col, name in stages:
                txt.append(f" {sym} {name} ", style=f"bold {col}")
            return Panel(txt, border_style="cyan", title="H.264 flow (KISS)")

        # === URL drag & drop / copy & paste INPUT above status bar for direct download to ~/Downloads/ ===
        input_state = {
            "last_pasted": "",
            "direct_status": "Ready — drag URL or copy-paste + Enter (downloads direct to ~/Downloads/)",
            "direct_progress": 0.0,
            "direct_output": "",
        }

        def make_input_panel(st):
            """The drag & drop + copy-paste bar placed above the status bar.
            Captures pasted/dragged URLs via stdin thread and runs yt-dlp directly to ~/Downloads/.
            Shows live progress bar using the shared make_progress_bar. No feedback loops.
            """
            txt = Text()
            txt.append("▶ URL (H.264) → ~/Downloads/\n", style="bold cyan")
            txt.append("Type/paste + Enter (arrows, backspace via readline; mouse select + terminal copy/paste works before Enter). For full cursor/selection/Ctrl+V in a real input bar use the Java desktop app.\n", style="dim")
            if st.get("last_pasted"):
                txt.append(f"Last: {st['last_pasted'][:62]}\n", style="cyan")
            status_style = "green"
            ds = st.get("direct_status", "")
            if "err" in ds.lower() or "fail" in ds.lower():
                status_style = "red"
            elif "download" in ds.lower() or "start" in ds.lower():
                status_style = "cyan"
            txt.append("Status: ", style="bold")
            txt.append(ds, style=status_style)
            txt.append("\n")
            prog = st.get("direct_progress", 0.0)
            if prog > 0.5:
                bar = make_progress_bar(prog, width=42, status="downloading")
                txt.append(bar)
                txt.append("  direct\n")
            else:
                txt.append("[waiting for URL paste/drag...]\n", style="dim")
            return Panel(txt, border_style="yellow", title="Input Bar (URL to ~/Downloads/)")

        def run_direct_download(url, st):
            """Fire-and-manage direct yt-dlp (no shell, no eval) straight to ~/Downloads/.
            Updates input_state for live progress in the input panel. Independent of job queue.
            Ensures JS runtime (deno etc.) to avoid the "No supported JavaScript runtime" warning.
            """
            ensure_js_runtime(interactive=False)  # non-blocking check + optional auto in future
            downloads = Path.home() / "Downloads"
            downloads.mkdir(parents=True, exist_ok=True)
            outtmpl = str(downloads / "%(title)s [%(id)s].%(ext)s")
            rt = check_js_runtime()
            try:
                import yt_dlp
                def hook(d):
                    if d.get('status') == 'downloading':
                        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                        dl = d.get('downloaded_bytes', 0)
                        p = (dl / total * 100.0) if total > 0 else 0.0
                        st["direct_progress"] = max(0.0, min(100.0, p))
                        fn = d.get('filename') or d.get('_filename') or ''
                        st["direct_status"] = f"downloading: {os.path.basename(str(fn))[:38]}"
                    elif d.get('status') == 'finished':
                        st["direct_progress"] = 100.0
                        fn = d.get('filename') or d.get('_filename') or 'file'
                        base = os.path.basename(str(fn))
                        st["direct_status"] = f"✓ done → ~/Downloads/{base}"
                        st["direct_output"] = str(fn)
                opts = {
                    "outtmpl": outtmpl,
                    "progress_hooks": [hook],
                    "quiet": True,
                    "no_warnings": True,
                    "merge_output_format": "mp4",
                }
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])
            except ImportError:
                # Fallback: yt-dlp CLI (subprocess list, safe, no shell)
                st["direct_status"] = "yt-dlp py not found, using CLI..."
                try:
                    cli_args = ["yt-dlp", "--newline", "-o", outtmpl, url]
                    if rt:
                        cli_args = ["yt-dlp", "--js-runtimes", rt, "--newline", "-o", outtmpl, url]
                    proc = subprocess.Popen(
                        cli_args,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1
                    )
                    for line in iter(proc.stdout.readline, ""):
                        if not line:
                            break
                        line = line.strip()
                        if "[download]" in line and "%" in line:
                            m = re.search(r"(\d+\.?\d*)%", line)
                            if m:
                                st["direct_progress"] = float(m.group(1))
                            st["direct_status"] = line[:72]
                        elif line and ("Merging" in line or "Destination" in line or "has already" in line):
                            st["direct_status"] = line[:72]
                    proc.wait()
                    if proc.returncode == 0:
                        st["direct_progress"] = 100.0
                        st["direct_status"] = "✓ done (yt-dlp CLI) → ~/Downloads/"
                    else:
                        st["direct_status"] = f"CLI rc={proc.returncode}"
                        st["direct_progress"] = 0.0
                except Exception as e2:
                    st["direct_status"] = f"CLI error: {str(e2)[:60]}"
                    st["direct_progress"] = 0.0
            except Exception as e:
                st["direct_status"] = f"error: {str(e)[:68]}"
                st["direct_progress"] = 0.0

        # Start the paste/drag watcher thread (daemon, captures stdin lines for URLs)
        # This enables "drag and drop && copy & paste" into the gravity-client TUI window.
        def paste_watcher():
            while True:
                try:
                    line = sys.stdin.readline()
                    if not line:
                        time.sleep(0.15)
                        continue
                    url = line.strip()
                    if not url:
                        continue
                    if not (url.startswith("http://") or url.startswith("https://") or "youtu" in url.lower()):
                        input_state["direct_status"] = f"ignored (not http URL): {url[:45]}"
                        input_state["direct_progress"] = 0.0
                        continue
                    input_state["last_pasted"] = url
                    input_state["direct_progress"] = 0.0
                    input_state["direct_status"] = "starting direct yt-dlp to ~/Downloads/..."
                    threading.Thread(target=run_direct_download, args=(url, input_state), daemon=True).start()
                except Exception as ex:
                    input_state["direct_status"] = f"input err: {str(ex)[:55]}"
                    time.sleep(0.2)

        paste_thread = threading.Thread(target=paste_watcher, daemon=True)
        paste_thread.start()

        jobs_data = []
        catalog_data = []

        # KISS initial (SVG style + H.264 stages in header for simplicity)
        layout["header"].update(make_header())
        layout["jobs"].update(make_jobs_panel(jobs_data))
        layout["visualist"].update(make_visualist_panel(catalog_data))
        layout["status"].update(make_status_bar(jobs_data, catalog_data))
        layout["input"].update(make_input_panel(input_state))

        with Live(layout, refresh_per_second=4, screen=True, console=console) as live:
            buffer = b""
            while True:
                readable, _, _ = select.select([s], [], [], 0.25)
                if readable:
                    data = s.recv(4096)
                    if not data:
                        break
                    buffer += data
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        try:
                            update = json.loads(line.decode('utf-8', errors='ignore'))
                            if update.get("type") == "gravity_update":
                                jobs_data = update.get("jobs", [])
                                catalog_data = update.get("catalog", [])
                                layout["header"].update(make_header())
                                layout["jobs"].update(make_jobs_panel(jobs_data))
                                layout["visualist"].update(make_visualist_panel(catalog_data))
                                layout["status"].update(make_status_bar(jobs_data, catalog_data))
                        except Exception:
                            pass
                layout["input"].update(make_input_panel(input_state))
                time.sleep(0.03)
    except Exception as e:
        console.print(f"[red]Gravity client error: {e}[/red]")
        console.print("Make sure gravity-server is running: nls-video gravity-server --port 4242")


def cmd_hierarchy(args):
    """Launch the Enhanced Interactive 11-Dimensional Hierarchy Explorer.
    Fully integrated with NLS Visualist themes: gravity, H.264 pipeline stages,
    ASC filmic aesthetics, interstellar|nonlineari, noiseprotocol.
    Uses the provided multimedia (ANSI + ASCII) + rich if available.
    KISS interactive journey.
    """
    if HIERARCHY_AVAILABLE:
        try:
            hierarchy_interpreter.main()
        except Exception as e:
            print(f"Hierarchy explorer error: {e}")
            print("Falling back to basic mode...")
            # Fallback simple version if the module has issues
            print("11D Hierarchy (basic): 11 Pure Form → 1 The Way")
            for lvl in range(11, 0, -1):
                print(f"  Level {lvl}: {hierarchy_interpreter.describe_level(lvl)[:70]}...")
                time.sleep(0.3)
    else:
        print("hierarchy_interpreter.py not found or import failed.")
        print("Make sure the file exists in the same directory as nls_video_pipe.py")
        print("Basic hierarchy (manifestation path):")
        for lvl in range(11, 0, -1):
            print(f"  {lvl}: Pure Form ... DNA ... Waves ... Elements ... Human ... The Way")


def cmd_worker(args):
    worker()


def main():
    parser = argparse.ArgumentParser(description="NLS Video download + H.264 convert monitor")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="Queue a YouTube (or direct) video for download + convert. Use --source-file for convert-only on an existing downloaded file (e.g. the current AV1 source).")
    p.add_argument("url", nargs="?", help="YouTube URL (ignored if --source-file is used)")
    p.add_argument("--preset", choices=list(DEFAULT_PRESETS.keys()), default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--source-file", help="Existing local file to convert (skips download step). Useful to adopt the current running encode or re-encode with different preset.")
    p.add_argument("--gravity", action="store_true", help="After successful convert, prepare raw H.264 elementary stream for Noise Protocol transport (gravity mode, using SCIS philosophy for secure Visualist channels). Rule #1 no kill, Rule #2 no eval.")
    p.add_argument("--interstellar-nonlinear", action="store_true", help="Enable interstellar|nonlineari mode: use SCIS noiseprotocol-vcodec + FFMPEG for VP56 origin form (legacy visualist look) + gravity prep. For content with 1000 years old nonlinear h@k reality aesthetics, ASC cinematic thumbnails.")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="List jobs")
    p.add_argument("--status", default=None)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("status", help="Show detailed job info")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("logs", help="Show log for a job")
    p.add_argument("id", type=int)
    p.add_argument("--follow", action="store_true")
    p.set_defaults(func=cmd_logs)

    p = sub.add_parser("cancel", help="Cancel a pending/running job")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_cancel)

    p = sub.add_parser("worker", help="Run the background processor (recommended in tmux)")
    p.set_defaults(func=cmd_worker)

    p = sub.add_parser("serve", help="Start the web dashboard (NLS Visualist interface)")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("gravity-serve", help="Browser Gravity client — full HTML dashboard (jobs, catalog, interlaterus mint, ~/Downloads). Proxies gravity-server live updates.")
    p.add_argument("--port", type=int, default=8766, help="HTTP port (default 8766)")
    p.add_argument("--gravity-host", default="127.0.0.1", help="gravity-server host")
    p.add_argument("--gravity-port", type=int, default=4242, help="gravity-server port")
    p.set_defaults(func=cmd_gravity_serve)

    p = sub.add_parser("gravity-serve-archive", help="Archive gravity-serve assets + session + log tail (keeps live server running)")
    p.add_argument("--dest", default=None, help="Optional archive directory")
    p.add_argument("--log-tail", type=int, default=500, help="Lines of live JSONL to include")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_gravity_serve_archive)

    p = sub.add_parser("running-status", help="Show gravity-serve running version (for mm / monitors)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_running_status)

    p = sub.add_parser("catalog", help="Catalog an existing finished video into NLS Visualist data (no download/convert run, follows no-kill no-eval rules). Use --gravity to also prepare raw stream for Noise Protocol.")
    p.add_argument("file")
    p.add_argument("--title", default=None)
    p.add_argument("--source-url", default=None)
    p.add_argument("--gravity", action="store_true", help="Prepare raw H.264 for noiseprotocol gravity / secure transport (SCIS style).")
    p.add_argument("--interstellar-nonlinear", action="store_true", help="Tag as interstellar|nonlineari and prepare VP56 gravity via SCIS noiseprotocol-vcodec + FFMPEG.")
    p.set_defaults(func=cmd_catalog)

    p = sub.add_parser("list-catalog", help="List the NLS Visualist data catalog (gravity / noiseprotocol prepared items)")
    p.set_defaults(func=cmd_list_catalog)

    p = sub.add_parser("spatio", help="Proof of Spatio (aka POS) — reconcile AVD↔POS catalog positioning")
    p.add_argument("--rebuild", action="store_true", help="Force rebuild position_index.json")
    p.add_argument("--json", action="store_true", help="Print proof JSON")
    p.set_defaults(func=cmd_spatio)

    p = sub.add_parser("cron", help="AVD/POS catalog cron: list|tick|run|runs|toggle|runner")
    p.add_argument(
        "cron_action",
        nargs="?",
        default="list",
        choices=["list", "tick", "run", "runs", "toggle", "runner"],
        help="list (default) | tick | run | runs | toggle | runner",
    )
    p.add_argument("--id", type=int, default=None, help="Task id for run/toggle")
    p.add_argument("--all", action="store_true", help="tick: run all enabled even if not due")
    p.add_argument("--enable", action="store_true", help="toggle: force enable")
    p.add_argument("--disable", action="store_true", help="toggle: force disable")
    p.add_argument("--limit", type=int, default=50, help="runs: tail limit")
    p.add_argument("--interval", type=float, default=45.0, help="runner: poll seconds")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_cron)

    p = sub.add_parser("cron-runner", help="Foreground cron daemon (same as: cron runner)")
    p.add_argument("--interval", type=float, default=45.0, help="Poll seconds")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=lambda a: cmd_cron(argparse.Namespace(
        cron_action="runner", interval=a.interval, json=getattr(a, "json", False),
        id=None, all=False, enable=False, disable=False, limit=50,
    )))

    p = sub.add_parser("aoa-delta", help="AOA | NLS Visualist — LIFO 16→0 grok_report PDF delta compose (360°/16 slices)")
    p.add_argument("--report-dir", default=None, help="Directory with grok_report*.pdf (default ~/Downloads)")
    p.add_argument("--no-write", action="store_true", help="Dry run — do not write aoa-delta.json")
    p.add_argument("--json", action="store_true", help="Print full compose JSON")
    p.set_defaults(func=cmd_aoa_delta)

    p = sub.add_parser("monitor", help="Terminal TUI dashboard inside the terminal (same idea as web serve: jobs + NLS Visualist Data gallery with your aesthetics, ASC thumbnails, glitch, gravity. Live updating 'window' in terminal.)")
    p.set_defaults(func=cmd_monitor)

    p = sub.add_parser("gravity-server", help="Start the NoiseProtocol Gravity server (inspired by SCIS) as the protocol backend. Java + Qt (or Swing) desktop clients connect to open a window on the desktop as the NLS Visualist interface/protocol client. No kill, no eval.")
    p.add_argument("--port", type=int, default=4242)
    p.set_defaults(func=cmd_gravity_server)

    p = sub.add_parser("gravity-client", help="Terminal client for the Gravity protocol (same as Java desktop window, but inside terminal). Connects to gravity-server, does handshake, receives live updates, renders TUI with Visualist aesthetics, ASC thumbnails, glitch, gravity elements. The terminal acts as the 'window' for the NLS Visualist data interface/protocol.")
    p.add_argument("--port", type=int, default=4242)
    p.set_defaults(func=cmd_gravity_client)

    p = sub.add_parser("hierarchy", help="Interactive 11-Dimensional Hierarchy Explorer (NLS Visualist edition). Journey through levels 11 (Pure Form / Source) → 1 (The Way / Final Catalog). Ties gravity, H.264, ASC filmic, interstellar|nonlineari, noiseprotocol into an esoteric manifestation map. KISS interactive with ASCII, colors, explanations. Run standalone: python3 hierarchy_interpreter.py")
    p.set_defaults(func=cmd_hierarchy)

    p = sub.add_parser("check-js", help="Check for JS runtime (deno/node/etc.) needed by yt-dlp for YouTube. Deno and Node.js are similarly supported. Offers install (Deno recommended). pythonJava friendly (call from Java app too).")
    p.set_defaults(func=lambda args: print("JS runtime:", ensure_js_runtime(interactive=True) or "none found"))

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
