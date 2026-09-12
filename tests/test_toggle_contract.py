"""Toggle CSS/JS must match PC/Android: glow scales, track does not; snake on thumb rim."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
JS = (ROOT / "web" / "js" / "toggle.js").read_text(encoding="utf-8")
APP = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")


class ToggleContractTests(unittest.TestCase):
    def test_glow_not_track_scales(self):
        self.assertIn(".toggle-glow", CSS)
        self.assertIn("vpn-track-pulse", CSS)
        self.assertNotRegex(CSS, r"\.toggle\.on[^{]*\{[^}]*animation:\s*track-pulse")

    def test_disabled_toggle_stays_opaque(self):
        self.assertIn("button:disabled:not(.toggle)", CSS)
        self.assertNotRegex(CSS, r"^button:disabled \{[^}]*opacity:\s*0\.4", re.M)

    def test_snake_radius_on_thumb_rim(self):
        self.assertIn("export function snakeRadius", JS)
        self.assertRegex(JS, r"return \(size - stroke\) / 2")
        self.assertIn("SNAKE_STROKE = 4", JS)
        self.assertIn("THUMB_SIZE = 48", JS)

    def test_app_uses_shared_toggle(self):
        self.assertIn("toggleMarkup", APP)
        self.assertIn("mountToggleSnake", APP)
        self.assertIn("SNAKE_MIN_VISIBLE_MS", APP)
        self.assertIn("dockKind", APP)
        self.assertIn("Оформить подписку", APP)
        self.assertNotIn("busy ? \"disabled\"", APP)


if __name__ == "__main__":
    unittest.main()
