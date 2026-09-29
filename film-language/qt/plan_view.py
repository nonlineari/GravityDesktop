"""PLAN: 6-track FFT timeline (Form Follows Timeline)."""

from __future__ import annotations

from typing import Any, Dict, List

from theme import ACCENT, GOLD, MAGENTA, MUTED

try:
    from PySide6.QtGui import QColor, QPainter, QPen
    from PySide6.QtWidgets import QWidget
except ImportError:  # pragma: no cover
    from PyQt5.QtGui import QColor, QPainter, QPen
    from PyQt5.QtWidgets import QWidget


class PlanView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc: Dict[str, Any] = {}
        self.setMinimumHeight(180)

    def set_doc(self, doc: Dict[str, Any]) -> None:
        self.doc = doc or {}
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0a0c10"))
        seq = self.doc.get("sequences") or []
        fft = (self.doc.get("lattice") or {}).get("fft_in") or []
        verts = self.doc.get("vertices") or []
        n = max(len(seq), 6)
        h = self.height() / n
        w = self.width()
        T = seq[-1]["t1"] if seq else 1.0
        T = T or 1.0
        for i in range(n):
            y = int(i * h)
            p.setPen(QPen(QColor(MAGENTA), 1))
            p.drawRect(0, y, w - 1, int(h) - 2)
            role = (seq[i]["role"] if i < len(seq) else "") or f"T{i}"
            p.setPen(QColor(MUTED))
            p.drawText(6, y + 14, role)
            if fft:
                p.setPen(QPen(QColor(ACCENT), 1))
                prev = None
                for x, mag in enumerate(fft):
                    px = 60 + x / max(1, len(fft) - 1) * (w - 70)
                    py = y + h - 4 - mag * (h - 16)
                    pt = (px, py)
                    if prev:
                        p.drawLine(int(prev[0]), int(prev[1]), int(pt[0]), int(pt[1]))
                    prev = pt
        p.setPen(QPen(QColor(GOLD), 2))
        for v in verts:
            x = 60 + float(v.get("t", 0)) / T * (w - 70)
            p.drawLine(int(x), 2, int(x), self.height() - 2)
        p.end()
