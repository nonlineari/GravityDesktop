import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qt"))


class QtEnv(unittest.TestCase):
    def test_portal_themes_become_gtk3(self):
        import importlib
        import qt_env
        os.environ["QT_QPA_PLATFORMTHEME"] = "xdgdesktopportal"
        importlib.reload(qt_env)
        self.assertEqual(os.environ["QT_QPA_PLATFORMTHEME"], "gtk3")
        self.assertIn("qt.qpa.theme.gnome=false", os.environ.get("QT_LOGGING_RULES", ""))

    def test_keeps_explicit_nonportal_theme(self):
        import importlib
        import qt_env
        os.environ["QT_QPA_PLATFORMTHEME"] = "gtk3"
        importlib.reload(qt_env)
        self.assertEqual(os.environ["QT_QPA_PLATFORMTHEME"], "gtk3")


if __name__ == "__main__":
    unittest.main()
