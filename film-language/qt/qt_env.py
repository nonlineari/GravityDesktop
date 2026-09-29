"""Set Qt platform theme before any PySide/PyQt import.

Qt's GNOME theme talks to org.freedesktop.portal.Settings. This machine's
xdg-desktop-portal has no Settings interface, which logs:
  qt.qpa.theme.gnome: dbus reply error ... UnknownMethod
Force gtk3 (plugin ships with PySide6) and mute that category.
"""

from __future__ import annotations

import os

_PORTAL_THEMES = {"", "gnome", "xdgdesktopportal", "flatpak", "snap"}


def apply() -> None:
    theme = os.environ.get("QT_QPA_PLATFORMTHEME", "")
    if theme.lower() in _PORTAL_THEMES:
        os.environ["QT_QPA_PLATFORMTHEME"] = "gtk3"
    os.environ.setdefault("GTK_USE_PORTAL", "0")
    rules = os.environ.get("QT_LOGGING_RULES", "")
    mute = "qt.qpa.theme.gnome=false"
    if "qt.qpa.theme.gnome" not in rules:
        os.environ["QT_LOGGING_RULES"] = f"{rules};{mute}" if rules else mute


apply()
