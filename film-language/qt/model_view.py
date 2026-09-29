"""MODEL: ObserverStage — N–Z–N, φ rays, shots as particles. E_p = Σ w_i v_i."""

from __future__ import annotations

import math
from typing import Any, Dict

from theme import ACCENT, GOLD, INK, MAGENTA, MUTED
from tokens import PHI

try:
    from PySide6.QtGui import QColor, QPainter, QPen
    from PySide6.QtWidgets import QWidget
except ImportError:  # pragma: no cover
    from PyQt5.QtGui import QColor, QPainter, QPen
    from PyQt5.QtWidgets import QWidget


class ModelView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc: Dict[str, Any] = {}
        self.picked = 0
        self.setMinimumHeight(180)

    def set_doc(self, doc: Dict[str, Any]) -> None:
        self.doc = doc or {}
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#111214"))
        w, h = self.width(), self.height()
        ox, oy = int(w * 0.22), int(h * 0.72)
        p.setPen(QPen(QColor(ACCENT), 2))
        p.drawLine(20, oy, w - 20, oy)
        p.drawText(w - 28, oy - 6, "N")
        p.drawText(8, oy - 6, "N")
        p.drawText(ox - 8, 16, "Z")
        shots = self.doc.get("shots") or [{}] * 5
        n = max(3, len(shots))
        p.setPen(QPen(QColor(GOLD), 1))
        for i in range(n):
            ang = math.pi * 0.15 + i * (math.pi * 0.55 / max(1, n - 1))
            r = 40 + (i + 1) * 18 * PHI / 2
            x = ox + r * math.cos(ang)
            y = oy - r * math.sin(ang)
            p.drawLine(ox, oy, int(x), int(y))
            p.setBrush(QColor(INK if i != self.picked else MAGENTA))
            p.drawEllipse(int(x) - 6, int(y) - 6, 12, 12)
        p.setPen(QColor(MUTED))
        p.drawText(8, h - 10, "observer  ·  Fibonacci STAGE  ·  pick line before PLAY")
        p.end()
