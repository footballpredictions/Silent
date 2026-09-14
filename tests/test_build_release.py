import tarfile
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.silent_release import artifact_name, iter_release_files, read_version, write_tarball


class ReleasePackTests(unittest.TestCase):
    def test_artifact_name(self):
        self.assertEqual(artifact_name("1.0.165"), "silent-vpn-openwrt-1.0.165.tar.gz")

    def test_pack_is_arch_independent(self):
        root = Path(__file__).resolve().parents[1]
        names = [arc for _, arc in iter_release_files(root)]
        self.assertIn("silent-vpn/install.sh", names)
        self.assertIn("silent-vpn/files/usr/sbin/silent-vpn-ctl", names)
        self.assertIn("silent-vpn/web/index.html", names)
        self.assertNotIn("silent-vpn/web/toggle-demo.html", names)
        self.assertTrue(all(".so" not in n and ".ipk" not in n for n in names))
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / artifact_name(read_version(root))
            write_tarball(root, dest)
            self.assertGreater(dest.stat().st_size, 1000)
            with tarfile.open(dest, "r:gz") as tar:
                members = tar.getnames()
            self.assertIn("silent-vpn/install.sh", members)
            self.assertTrue(any(n.startswith("silent-vpn/files/") for n in members))
            self.assertTrue(any(n.startswith("silent-vpn/web/") for n in members))

    def test_install_sh_has_two_steps(self):
        text = (Path(__file__).resolve().parents[1] / "install.sh").read_text(encoding="utf-8")
        self.assertIn("sh install.sh [deps|install|all]", text)
        self.assertIn("opkg install $DEPS", text)
        self.assertIn("rm -f /www/silent-vpn/toggle-demo.html", text)


if __name__ == "__main__":
    unittest.main()
