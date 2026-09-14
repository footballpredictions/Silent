import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.silent_pkg import pkg_kind


class PkgKindTests(unittest.TestCase):
    def test_23_and_24_use_opkg(self):
        self.assertEqual(pkg_kind("23.05.5", has_apk=False, has_opkg=True), "opkg")
        self.assertEqual(pkg_kind("24.10.2", has_apk=False, has_opkg=True), "opkg")

    def test_25_and_newer_use_apk(self):
        self.assertEqual(pkg_kind("25.12.0", has_apk=True, has_opkg=False), "apk")
        self.assertEqual(pkg_kind("26.0.0", has_apk=True, has_opkg=False), "apk")

    def test_falls_back_if_preferred_missing(self):
        self.assertEqual(pkg_kind("25.12.0", has_apk=False, has_opkg=True), "opkg")
        self.assertEqual(pkg_kind("23.05.5", has_apk=True, has_opkg=False), "apk")

    def test_snapshot_prefers_apk_db(self):
        self.assertEqual(
            pkg_kind("SNAPSHOT", has_apk=True, has_opkg=True, has_apk_db=True),
            "apk",
        )
        self.assertEqual(
            pkg_kind("SNAPSHOT", has_apk=True, has_opkg=True, has_apk_db=False),
            "opkg",
        )

    def test_unknown_uses_available_manager(self):
        self.assertEqual(pkg_kind("", has_apk=False, has_opkg=True), "opkg")
        self.assertEqual(pkg_kind("", has_apk=True, has_opkg=False), "apk")
        self.assertIsNone(pkg_kind("", has_apk=False, has_opkg=False))


class InstallerPkgContractTests(unittest.TestCase):
    def test_install_sh_uses_pkg_helper(self):
        text = (Path(__file__).resolve().parents[1] / "install.sh").read_text(encoding="utf-8")
        self.assertIn("sv_pkg_kind", text)
        self.assertIn("sv_pkg_add", text)
        self.assertIn("apk add", text)
        self.assertIn("opkg install", text)
        self.assertIn("или apk (25+).", text)
        self.assertNotIn("&& has_apk=1", text)

    def test_remote_install_uses_pkg_helper(self):
        text = (Path(__file__).resolve().parents[1] / "remote-install.sh").read_text(encoding="utf-8")
        self.assertIn("sv_pkg_kind", text)
        self.assertIn("apk add", text)
        self.assertIn("opkg install", text)
        self.assertIn("или apk (25+).", text)
        self.assertNotIn("&& has_apk=1", text)

    def test_uninstall_cleans_uci_and_packages(self):
        text = (Path(__file__).resolve().parents[1] / "uninstall.sh").read_text(encoding="utf-8")
        self.assertIn("network.svpath", text)
        self.assertIn("firewall.svpath", text)
        self.assertIn("silent-entry", text)
        self.assertIn("uci-defaults/99-silent-vpn", text)
        self.assertIn("apk del", text)
        self.assertIn("opkg remove", text)
        self.assertIn("id -u", text)


if __name__ == "__main__":
    unittest.main()
