"""Dark VJ theme — SCIS magenta/cyan on Gravity graphite. φ frame 987×610."""

PHI = 1.6180339887
W, H = 987, 610
BG = "#0d0f12"
PANEL = "#161a20"
INK = "#e8ecf1"
MUTED = "#8b95a5"
ACCENT = "#5ad0c8"
MAGENTA = "#ff3dce"
GOLD = "#e6b84d"

STYLESHEET = f"""
QMainWindow, QWidget {{ background: {BG}; color: {INK}; }}
QGroupBox {{
  border: 1px solid {MAGENTA};
  margin-top: 12px;
  font: 11px "Monospace";
  color: {MAGENTA};
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}
QLineEdit, QPlainTextEdit, QTableWidget {{
  background: #0a0c10; color: {ACCENT}; border: 1px solid {ACCENT};
  font: 11px "Monospace";
}}
QPushButton {{
  background: #1a1e26; color: {INK}; border: 1px solid {ACCENT};
  padding: 4px 8px; font: 11px "Monospace";
}}
QPushButton:hover {{ background: #242a34; }}
QHeaderView::section {{ background: #12151a; color: {MUTED}; }}
QLabel {{ color: {INK}; font: 11px "Monospace"; }}
"""
