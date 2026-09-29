"""ELEVATION: audio vs visual FFT + DualLattice residual ε."""

from __future__ import annotations

from typing import Any, Dict, List

from theme import ACCENT, GOLD, MUTED

try:
    from PySide6.QtGui import QColor, QPainter, QPen
    from PySide6.QtWidgets import QWidget
except ImportError:  # pragma: no cover
    from PyQt5.QtGui import QColor, QPainter, QPen
    from PyQt5.QtWidgets import QWidget


class ElevationView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc: Dict[str, Any] = {}
        self.setMinimumHeight(180)

    def set_doc(self, doc: Dict[str, Any]) -> None:
        self.doc = doc or {}
        self.update()

    def _bars(self, p: QPainter, mag: List[float], y0: int, h: int, color: str) -> None:
        if not mag:
            return
        w = self.width() - 16
        bw = max(1.0, w / len(mag) - 1)
        p.setPen(QPen(QColor(color), 1))
        p.setBrush(QColor(color))
        for i, v in enumerate(mag):
            bh = int(max(0.0, min(1.0, float(v))) * (h - 8))
            p.drawRect(int(8 + i * (bw + 1)), y0 + h - 4 - bh, int(bw), bh)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0a0c10"))
        lat = self.doc.get("lattice") or {}
        inn = lat.get("fft_in") or []
        out = lat.get("fft_out") or inn
        mid = self.height() // 2
        p.setPen(QColor(MUTED))
        p.drawText(8, 14, "AUDIO IN  α")
        self._bars(p, inn, 16, mid - 24, ACCENT)
        p.setPen(QColor(MUTED))
        p.drawText(8, mid + 14, "AUDIO OUT  β")
        self._bars(p, out, mid + 16, mid - 24, GOLD)
        eps = float(lat.get("epsilon_sec") or 0.0)
        p.setPen(QColor(ACCENT))
        p.drawText(8, self.height() - 8, f"ε {eps * 1000:.3f} ms   DualLattice")
        p.end()
