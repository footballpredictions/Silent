"""Exercise actual removal/reinstallation in a disposable router filesystem."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "posix" and shutil.which("sh"), "Linux router fixture required")
class UninstallRuntimeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="silent-uninstall-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.env = dict(os.environ, FIXTURE=str(self.root), PATH=str(self.root / "commands") + ":/usr/bin:/bin")
        for name in ("id", "ip", "uci", "killall", "ifdown", "nft", "opkg"):
            body = "echo 0" if name == "id" else ("exit 1" if name == "ip" else ':')
            self.write("commands/" + name, "#!/bin/sh\n" + body + "\n", True)
        # Reject any accidental deletion outside the disposable filesystem.
        self.write("commands/rm", '''#!/bin/sh
for arg do
 case "$arg" in -*) ;; "$FIXTURE"/*) ;; *) exit 90 ;; esac
done
exec /bin/rm "$@"
''', True)
        self.saved = {
            "etc/config/silent-vpn": "config core 'main'\n option ru_direct '1'\n option dns_custom '9.9.9.9'\n",
            "etc/silent-vpn/access_token": "saved-access",
            "etc/silent-vpn/refresh_token": "saved-refresh",
            "etc/silent-vpn/email": "fixture@example.invalid",
            "etc/silent-vpn/fingerprint": "saved-device-id",
        }
        for path, value in self.saved.items():
            self.write(path, value)
        self.write("usr/lib/silent-vpn/update.sh", 'sv_update_busy() { [ "${FIXTURE_BUSY:-0}" = 1 ]; }\n')
        for path in ("usr/sbin/silent-vpn-ctl", "etc/init.d/silent-vpn", "etc/init.d/silent-vpn-policy",
                     "etc/init.d/silent-vpn-dns", "etc/init.d/firewall", "etc/init.d/dnsmasq", "etc/init.d/uhttpd"):
            self.write(path, '#!/bin/sh\nprintf "%s %s\\n" "$0" "$*" >> "$FIXTURE/actions"\n', True)
        for path in ("usr/bin/spass", "www/silent-vpn/index.html", "var/run/silent-vpn/connected",
                     "usr/sbin/silent-vpn-uninstall", "tmp/sv-rm.sh"):
            self.write(path, "installed")

    def write(self, path, value, executable=False):
        dest = self.root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(value, encoding="utf-8")
        if executable:
            dest.chmod(0o755)
        return dest

    def rooted(self, source):
        return re.sub(r"(?<![\w/])/(?:etc|usr|www|var|tmp|sbin|bin)(?=/)", lambda m: str(self.root) + m[0], source)

    def uninstall(self, *args):
        script = self.write("uninstall.sh", self.rooted((ROOT / "uninstall.sh").read_text()))
        return subprocess.run(["sh", str(script), *args], env=self.env, text=True, capture_output=True, timeout=10)

    def assert_saved(self):
        for path, value in self.saved.items():
            self.assertEqual((self.root / path).read_text(), value, path)

    def test_keep_data_removes_client_and_stops_services_but_keeps_credentials_and_preferences(self):
        result = self.uninstall("--keep-data")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_saved()
        for path in ("usr/lib/silent-vpn", "usr/bin/spass", "www/silent-vpn", "var/run/silent-vpn",
                     "etc/init.d/silent-vpn", "etc/init.d/silent-vpn-dns", "usr/sbin/silent-vpn-uninstall"):
            self.assertFalse((self.root / path).exists(), path)
        actions = (self.root / "actions").read_text()
        self.assertIn("silent-vpn-ctl disconnect", actions)
        self.assertIn("silent-vpn-dns stop", actions)

    def test_purge_and_legacy_no_argument_remove_saved_data(self):
        for args in (("--purge",), ()):
            with self.subTest(args=args):
                result = self.uninstall(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse((self.root / "etc/config/silent-vpn").exists())
                self.assertFalse((self.root / "etc/silent-vpn").exists())

    def test_unknown_or_conflicting_flags_do_not_start_removal(self):
        for args in (("--keep-dtaa",), ("--keep-data", "--purge")):
            result = self.uninstall(*args)
            self.assertEqual(result.returncode, 2)
            self.assert_saved()
            self.assertFalse((self.root / "actions").exists())
            self.assertTrue((self.root / "usr/bin/spass").exists())

    def test_update_in_progress_blocks_both_modes(self):
        self.env["FIXTURE_BUSY"] = "1"
        for mode in ("--keep-data", "--purge"):
            self.assertEqual(self.uninstall(mode).returncode, 1)
            self.assert_saved()
            self.assertFalse((self.root / "actions").exists())

    def install_fixture(self):
        package = self.root / "package"
        inputs = (
            "files/usr/sbin/silent-vpn-ctl", "files/usr/sbin/silent-vpn-policy", "files/usr/sbin/silent-vpn-update",
            "files/www/cgi-bin/silent-entry", "files/www/cgi-bin/silent-api", "web/index.html",
            "files/etc/init.d/silent-vpn", "files/etc/init.d/silent-vpn-policy", "files/etc/init.d/silent-vpn-dns",
            "files/etc/hotplug.d/iface/99-silent-vpn", "files/etc/uci-defaults/99-silent-vpn",
            "uninstall.sh", "remote-install.sh",
        )
        for name in inputs:
            self.write("package/" + name, "#!/bin/sh\nexit 0\n", True)
        self.write("package/files/etc/config/silent-vpn", "fresh-default-config\n")
        self.write("package/VERSION", "1.0.171\n")
        self.write("package/files/usr/lib/silent-vpn/lan-name.sh",
                   "sv_lan_apply_dns() { :; }\nsv_lan_ip() { echo 192.168.1.1; }\n")
        (self.root / "usr/bin").mkdir(parents=True, exist_ok=True)
        definitions = (ROOT / "install.sh").read_text().split('cmd="${1:-all}"')[0]
        source = self.rooted(definitions) + '\nROOT="' + str(package) + '"\n'
        source += 'require_arch() { SV_WDTT_SLOT=x86_64; }\ninstall_wdtt() { :; }\ninstall_files\n'
        script = self.write("install-fixture.sh", source)
        return subprocess.run(["sh", str(script)], env=self.env, text=True, capture_output=True, timeout=10)

    def test_keep_data_then_reinstall_preserves_login_and_custom_preferences(self):
        self.assertEqual(self.uninstall("--keep-data").returncode, 0)
        result = self.install_fixture()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_saved()
        self.assertTrue((self.root / "www/silent-vpn/index.html").is_file())

    def test_purge_then_fresh_install_uses_default_config(self):
        self.assertEqual(self.uninstall("--purge").returncode, 0)
        result = self.install_fixture()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "etc/config/silent-vpn").read_text(), "fresh-default-config\n")
        self.assertFalse((self.root / "etc/silent-vpn/access_token").exists())


if __name__ == "__main__":
    unittest.main()
