"""Mac OTA: два DMG (x64 и arm64) не затирают друг друга."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import update_service as us
from app.services.github_release_service import github_asset_filename


class MacUpdateArchesUnit(unittest.TestCase):
    def setUp(self) -> None:
        self._base = us._BASE
        self.tmp = tempfile.TemporaryDirectory()
        us._BASE = self.tmp.name

    def tearDown(self) -> None:
        us._BASE = self._base
        self.tmp.cleanup()

    def _touch(self, name: str) -> str:
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as fh:
            fh.write(b"dmg")
        return path

    def test_second_arch_keeps_the_first(self) -> None:
        us.publish_file("mac", "Silent VPN Setup 1.0.168-x64.dmg", self._touch("a.dmg"), arch="x64")
        us.publish_file("mac", "Silent VPN Setup 1.0.168-arm64.dmg", self._touch("b.dmg"), arch="arm64")
        latest = us.get_latest("mac")
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest["filename"], "Silent VPN Setup 1.0.168-x64.dmg")
        arches = {item["arch"] for item in us.mac_binaries(latest)}
        self.assertEqual(arches, {"x64", "arm64"})
        arm = us.get_latest("mac", arch="arm64")
        self.assertIsNotNone(arm)
        assert arm is not None
        self.assertIn("arm64", arm["filename"])

    def test_github_names_differ_by_arch(self) -> None:
        self.assertEqual(
            github_asset_filename("mac", "Silent VPN Setup 1.0.168-x64.dmg", "1.0.168"),
            "Silent.VPN.Setup.1.0.168-x64.dmg",
        )
        self.assertEqual(
            github_asset_filename("mac", "Silent VPN Setup 1.0.168-arm64.dmg", "1.0.168"),
            "Silent.VPN.Setup.1.0.168-arm64.dmg",
        )


if __name__ == "__main__":
    unittest.main()
