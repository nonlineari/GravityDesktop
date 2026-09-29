#!/usr/bin/env python3
"""ELEVATION | MODEL | PLAN — Qt armature. Form follows function rows."""

from __future__ import annotations

import json
import sys
from pathlib import Path

QT = Path(__file__).resolve().parent
ROOT = QT.parent
sys.path.insert(0, str(QT))
sys.path.insert(0, str(ROOT / "py"))

import qt_env  # noqa: E402  # before any PySide import
from theme import H, STYLESHEET, W  # noqa: E402
from plan_view import PlanView  # noqa: E402
from elevation_view import ElevationView  # noqa: E402
from model_view import ModelView  # noqa: E402

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
        QLabel, QLineEdit, QMainWindow, QPushButton, QTableWidget,
        QTableWidgetItem, QVBoxLayout, QWidget,
    )
except ImportError:
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import (
        QApplication, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
        QLabel, QLineEdit, QMainWindow, QPushButton, QTableWidget,
        QTableWidgetItem, QVBoxLayout, QWidget,
    )


class EmpWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GravityDesktop Film | ELEVATION · MODEL · PLAN | FFF+FFT | max-6 tracks")
        self.resize(W + 200, H + 180)
        self.setStyleSheet(STYLESHEET)
        self.doc = {}

        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)

        fn = QHBoxLayout()
        for name, slot in (
            ("Index", self.do_index),
            ("Search", self.do_search),
            ("Compile", self.do_compile),
            ("Splice", self.do_splice),
            ("Preview", self.do_preview),
        ):
            b = QPushButton(name)
            b.clicked.connect(slot)
            fn.addWidget(b)
        v.addLayout(fn)

        grid = QGridLayout()
        self.plan = PlanView()
        self.elev = ElevationView()
        self.model = ModelView()
        for i, (title, w) in enumerate((("PLAN", self.plan), ("ELEVATION", self.elev), ("MODEL", self.model))):
            box = QGroupBox(title)
            lay = QVBoxLayout(box)
            lay.addWidget(w)
            grid.addWidget(box, 0, i)
        v.addLayout(grid, 1)

        row = QHBoxLayout()
        self.live = QLineEdit()
        self.live.setPlaceholderText("search /θ/ glyph=helix_cut class=POV_IMAGE   ·   vj_mode=tesseract")
        exec_btn = QPushButton("Exec")
        exec_btn.clicked.connect(self.do_search)
        row.addWidget(QLabel("livecode"))
        row.addWidget(self.live)
        row.addWidget(exec_btn)
        v.addLayout(row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["t", "path", "IPA", "YOLO", "OCR", "score"])
        self.table.setMaximumHeight(160)
        v.addWidget(self.table)
        self.status = QLabel("AVD in  ·  pick Index  ·  local search only")
        v.addWidget(self.status)

    def _set_doc(self, doc: dict) -> None:
        self.doc = doc
        self.plan.set_doc(doc)
        self.elev.set_doc(doc)
        self.model.set_doc(doc)

    def do_index(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Index AVD", str(Path.home() / "Downloads"))
        if not path:
            return
        from indexer import index_file
        side = index_file(Path(path))
        self._set_doc(json.loads(side.read_text()))
        self.status.setText(f"indexed {side}")

    def do_search(self) -> None:
        q = self.live.text().strip()
        if not q or not self.doc:
            self.status.setText("index first, then livecode search")
            return
        from search import search_doc
        hits = search_doc(self.doc, q)
        self.table.setRowCount(0)
        for h in hits[:10]:
            r = self.table.rowCount()
            self.table.insertRow(r)
            shot = h.get("shot") or {}
            yolo = ",".join(d.get("class", "") for d in (shot.get("yolo") or []) if isinstance(d, dict))
            vals = [
                f"{h['t0']:.2f}-{h['t1']:.2f}",
                str(h.get("source") or "")[-48:],
                " ".join(shot.get("ipa") or []),
                yolo,
                " ".join(shot.get("ocr") or [])[:40],
                f"{h['score']:.3f}",
            ]
            for c, val in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(val))
        self.status.setText(f"{len(hits)} hits")

    def do_compile(self) -> None:
        if not self.doc:
            return
        from prompt_compiler import compile_edl
        edl = compile_edl(self.live.text() or "cut POV", [self.doc])
        self.status.setText(f"EDL {edl.get('edl_path')}  clips={len(edl.get('clips') or [])}")

    def do_splice(self) -> None:
        from paths import EDL_DIR
        files = sorted(EDL_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            self.status.setText("no EDL — Compile first")
            return
        from splice import splice_edl
        edl = json.loads(files[0].read_text())
        try:
            out = splice_edl(edl)
            self.status.setText(f"splice {out}")
        except Exception as ex:
            self.status.setText(f"splice: {ex}")

    def do_preview(self) -> None:
        import shutil, subprocess
        from paths import CUTS_DIR
        ffplay = shutil.which("ffplay")
        clips = sorted(CUTS_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not ffplay or not clips:
            self.status.setText("ffplay/cut missing")
            return
        subprocess.Popen([ffplay, "-autoexit", str(clips[0])])


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = EmpWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
