import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.silent_theme import palette, resolve_app_name, resolve_asset_url


class ThemeMapTests(unittest.TestCase):
    def test_light_defaults_match_theme_response(self):
        p = palette({}, "light")
        self.assertEqual(p["bg"], "#FFFFFF")
        self.assertEqual(p["fg"], "#000000")
        self.assertEqual(p["appTitle"], "SILENT VPN")
        self.assertFalse(p["dark"])

    def test_live_hive_fields(self):
        theme = {
            "background_color": "#FFFFFF",
            "text_color": "#000000",
            "font_family": "Inter",
            "app_name": "Silent VPN",
            "logo_url": "/static/logo.png",
            "login_link_color": "#4680C2",
        }
        p = palette(theme, "light")
        self.assertIn("Inter", p["fontFamily"])
        self.assertEqual(p["link"], "#4680C2")
        self.assertTrue(p["logoUrl"].endswith("/static/logo.png"))

    def test_dark_fallback_without_dark_keys(self):
        p = palette({"background_color": "#FFFFFF", "text_color": "#000000"}, "dark")
        self.assertTrue(p["dark"])
        self.assertEqual(p["bg"], "#0B0B0F")
        self.assertEqual(p["primaryBtnBg"], "#FFFFFF")

    def test_legacy_app_name(self):
        self.assertEqual(resolve_app_name("silent"), "Silent VPN")
        self.assertEqual(resolve_app_name(""), "Silent VPN")

    def test_asset_url(self):
        self.assertEqual(
            resolve_asset_url("/static/logo.png"),
            "https://132-243-234-162.nip.io/static/logo.png",
        )


if __name__ == "__main__":
    unittest.main()
