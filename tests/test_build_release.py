import tarfile
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.silent_arch import slot_from_uname
from lib.silent_release import artifact_name, iter_release_files, read_version, write_tarball


class ReleasePackTests(unittest.TestCase):
    def test_artifact_name(self):
        self.assertEqual(artifact_name("1.0.165"), "silent-vpn-openwrt-1.0.165.tar.gz")

    def test_pack_is_arch_independent(self):
        root = Path(__file__).resolve().parents[1]
        names = [arc for _, arc in iter_release_files(root)]
        self.assertIn("silent-vpn/install.sh", names)
        self.assertIn("silent-vpn/uninstall.sh", names)
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

    def test_uname_to_wdtt_slot(self):
        self.assertEqual(slot_from_uname("aarch64"), "aarch64")
        self.assertEqual(slot_from_uname("armv7l"), "arm")
        self.assertEqual(slot_from_uname("mips"), "mipsel")
        self.assertEqual(slot_from_uname("x86_64"), "x86_64")
        self.assertIsNone(slot_from_uname("ppc"))

    def test_windows_checkout_packages_runnable_shell_without_changing_binaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            (root / "VERSION").write_bytes(b"1.0.168\r\n")
            script = b"#!/bin/sh\r\nprintf 'ready\\n'\r\n"
            (root / "install.sh").write_bytes(script)
            library = root / "files/usr/lib/silent-vpn"
            library.mkdir(parents=True)
            helper = library / "common.sh"
            helper.write_bytes(b"# sourced helper\r\nready() { echo ready; }\r\n")
            binary = library / "wdtt-client.x86_64"
            binary_data = b"\x7fELF\r\n\x00\xff"
            binary.write_bytes(binary_data)
            cgi = root / "files/www/cgi-bin/silent-api"
            cgi.parent.mkdir(parents=True)
            cgi.write_bytes(script)
            dest = Path(tmp) / "release.tar.gz"
            write_tarball(root, dest)
            with tarfile.open(dest, "r:gz") as tar:
                for name in ("install.sh", "files/usr/lib/silent-vpn/common.sh", "files/www/cgi-bin/silent-api"):
                    member = tar.getmember("silent-vpn/" + name)
                    data = tar.extractfile(member).read()
                    self.assertNotIn(b"\r\n", data, name)
                    self.assertEqual(member.size, len(data))
                self.assertEqual(tar.getmember("silent-vpn/install.sh").mode, 0o755)
                self.assertEqual(tar.extractfile("silent-vpn/files/usr/lib/silent-vpn/wdtt-client.x86_64").read(), binary_data)
            self.assertEqual((root / "install.sh").read_bytes(), script)

    def test_install_sh_checks_arch_before_copy(self):
        text = (Path(__file__).resolve().parents[1] / "install.sh").read_text(encoding="utf-8")
        start = text.find("install_files()")
        self.assertGreater(start, 0)
        self.assertLess(
            text.find("require_arch", start),
            text.find('cp -a "$ROOT/files/usr/lib/silent-vpn/."', start),
        )
        self.assertIn("/usr/bin/spass", text)
        self.assertIn("silent-vpn-uninstall", text)
        self.assertIn("не поддерживается", text)

    def test_remote_install_arch_then_cleanup(self):
        text = (Path(__file__).resolve().parents[1] / "remote-install.sh").read_text(encoding="utf-8")
        self.assertLess(text.find("sv_slot"), text.find("sv_fetch"))
        self.assertIn("rm -rf silent-vpn Silent-openwrt silent-vpn-openwrt.tgz", text)
        self.assertIn("id -u", text)
        self.assertIn("exec rm -f /tmp/sv.sh", text)
        self.assertIn("uclient-fetch", text)


if __name__ == "__main__":
    unittest.main()
