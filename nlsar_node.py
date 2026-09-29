"""NLSAR connection node for GravityDesktop.

Talks to the NLSAR architecture backend (CODE BUS :4212):

    handshake → gravity_update → signal → chat → inject

gravity-serve merges fetch_backend() into /api/gravity. The Java client
seeds remote-nav.tsv (assetClass=nlsar viewer=bot|news|station) and polls
/api/comm when the TCP gravity-server is offline.

Loop rule: this module calls NLSAR /api/backend (local snapshot), never
/api/comm, so NLSAR's optional pull of gravity-serve cannot recurse.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

NLSAR = os.environ.get("NLSAR_URL", "http://127.0.0.1:4212").rstrip("/")
NAV = Path.home() / ".config" / "gravity-desktop" / "remote-nav.tsv"


def fetch_backend(timeout: float = 1.0) -> Optional[Dict[str, Any]]:
    req = urllib.request.Request(
        NLSAR + "/api/backend",
        headers={"User-Agent": "GravityDesktop/nlsar-node"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return data if isinstance(data, dict) else None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def handshake(timeout: float = 1.0) -> Optional[Dict[str, Any]]:
    req = urllib.request.Request(
        NLSAR + "/api/comm?op=handshake",
        headers={"User-Agent": "GravityDesktop/nlsar-node"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return data if isinstance(data, dict) else None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def attach_nav(base: Optional[str] = None) -> str:
    base = (base or NLSAR).rstrip("/")
    NAV.parent.mkdir(parents=True, exist_ok=True)
    wanted = [
        f"nlsar\t{base}\t1\tbot\n",
        f"nlsar-news\t{base}\t2\tnews\n",
        f"nlsar-station\t{base}\t3\tstation\n",
    ]
    existing = NAV.read_text(encoding="utf-8") if NAV.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    if "# assetClass" not in existing:
        existing = "# assetClass\tbaseUrl\tmenuIndex\tviewer\n" + existing
    for line in wanted:
        key = line.split("\t", 1)[0] + "\t"
        if key not in existing:
            existing += line
    NAV.write_text(existing, encoding="utf-8")
    return str(NAV)


def merge_into(snap: Dict[str, Any], nls: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fold NLSAR jobs/catalog into a gravity_update snapshot."""
    nls = nls if nls is not None else fetch_backend()
    out = dict(snap)
    if not nls:
        out["nlsar"] = {"connected": False}
        return out
    out["nlsar"] = {
        "connected": True,
        "corpus": nls.get("corpus"),
        "signals": nls.get("signals"),
        "listen": nls.get("listen") or NLSAR + "/",
        "inject": nls.get("inject") or {},
    }
    jobs = list(out.get("jobs") or [])
    jobs.extend(nls.get("jobs") or [])
    out["jobs"] = jobs
    catalog = list(out.get("catalog") or [])
    catalog.extend(nls.get("catalog") or [])
    out["catalog"] = catalog
    return out


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = (argv[0] if argv else "status").lower()
    if cmd == "attach":
        path = attach_nav()
        print(f"OK gravity remote-nav {path}")
        print(f"  assetClass=nlsar viewer=bot  →  {NLSAR}/bot")
        return 0
    if cmd == "handshake":
        blob = handshake()
        if not blob:
            print("ERR NLSAR not listening on", NLSAR, file=sys.stderr)
            return 1
        json.dump(blob, sys.stdout, indent=2)
        print()
        return 0
    blob = fetch_backend()
    if not blob:
        print("ERR NLSAR not listening on", NLSAR, file=sys.stderr)
        return 1
    json.dump(blob, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
