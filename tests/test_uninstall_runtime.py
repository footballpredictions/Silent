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

    def install_fixture(self, upgrade=False, staging=False):
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
        if upgrade:
            helper = self.rooted((ROOT / "files/usr/lib/silent-vpn/install-upgrade.sh").read_text())
            helper = helper.replace('cd / &&', 'cd "$FIXTURE" &&').replace('-C /', '-C "$FIXTURE"')
            helper = helper.replace('"/$path"', '"$FIXTURE/$path"')
            self.write("package/files/usr/lib/silent-vpn/install-upgrade.sh", helper)
            self.write("package/files/usr/lib/silent-vpn/update.sh",
                       (ROOT / "files/usr/lib/silent-vpn/update.sh").read_text())
        (self.root / "usr/bin").mkdir(parents=True, exist_ok=True)
        if staging:
            stage = self.root / "tmp/sv-install.fixture"
            stage.mkdir(parents=True)
            shutil.move(str(package), str(stage / "silent-vpn"))
            package = stage / "silent-vpn"
            self.env["SILENT_OPENWRT_STAGE"] = str(stage)
        definitions = (ROOT / "install.sh").read_text().split('cmd="${1:-all}"')[0]
        source = self.rooted(definitions) + '\nROOT="' + str(package) + '"\n'
        source += 'require_arch() { SV_WDTT_SLOT=x86_64; [ "${FIXTURE_BAD_ARCH:-0}" != 1 ]; }\n'
        source += 'install_wdtt() { :; }\ninstall_deps() { :; }\n'
        source += 'install_client 0\n' if upgrade else 'install_files\n'
        script = self.write("install-fixture.sh", source)
        return subprocess.run(["sh", str(script)], env=self.env, text=True, capture_output=True, timeout=10)

    def test_keep_data_then_reinstall_preserves_login_and_custom_preferences(self):
        self.assertEqual(self.uninstall("--keep-data").returncode, 0)
        result = self.install_fixture(upgrade=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_saved()
        self.assertTrue((self.root / "www/silent-vpn/index.html").is_file())

    def test_purge_then_fresh_install_uses_default_config(self):
        self.assertEqual(self.uninstall("--purge").returncode, 0)
        result = self.install_fixture(upgrade=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "etc/config/silent-vpn").read_text(), "fresh-default-config\n")
        self.assertFalse((self.root / "etc/silent-vpn/access_token").exists())

    def test_manual_upgrade_preserves_data_and_reconnects_after_backup_is_freed(self):
        self.write("usr/sbin/silent-vpn-ctl", '''#!/bin/sh
printf '%s\n' "$*" >> "$FIXTURE/control-actions"
case "$1" in
 disconnect) rm -f "$FIXTURE/var/run/silent-vpn/connected" ;;
 connect)
  test -z "$(find "$FIXTURE/tmp" -name rollback.tar)" || exit 77
  test ! -d "$FIXTURE/tmp/sv-install.fixture/silent-vpn" || exit 78
  echo resumed > "$FIXTURE/resumed" ;;
esac
''', True)
        # Keep the actual old controller in the fake new package so reconnect is observable.
        original_write = self.write
        def write(path, value, executable=False):
            if path == "package/files/usr/sbin/silent-vpn-ctl":
                value = (self.root / "usr/sbin/silent-vpn-ctl").read_text()
            return original_write(path, value, executable)
        self.write = write
        result = self.install_fixture(upgrade=True, staging=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_saved()
        self.assertEqual((self.root / "control-actions").read_text().splitlines(), ["disconnect", "connect"])
        self.assertEqual((self.root / "resumed").read_text().strip(), "resumed")
        self.assertFalse((self.root / "var/run/silent-vpn/update.lock").exists())
        self.assertFalse(list((self.root / "tmp").glob("sv-upgrade.*")))

    def test_manual_upgrade_does_not_connect_previously_disconnected_vpn(self):
        (self.root / "var/run/silent-vpn/connected").unlink()
        result = self.install_fixture(upgrade=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_saved()
        self.assertNotIn(" connect\n", (self.root / "actions").read_text())

    def test_failed_manual_upgrade_restores_old_program_and_config(self):
        before = (self.root / "usr/sbin/silent-vpn-ctl").read_bytes()
        self.write("commands/cp", '''#!/bin/sh
case "$*" in *files/www/cgi-bin/*) exit 23 ;; esac
exec /bin/cp "$@"
''', True)
        result = self.install_fixture(upgrade=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Предыдущая сборка восстановлена", result.stderr)
        self.assert_saved()
        self.assertEqual((self.root / "usr/sbin/silent-vpn-ctl").read_bytes(), before)
        self.assertFalse((self.root / "usr/lib/silent-vpn/lan-name.sh").exists())
        self.assertIn("silent-vpn-ctl connect", (self.root / "actions").read_text())
        self.assertFalse((self.root / "var/run/silent-vpn/update.lock").exists())

    def test_manual_upgrade_blocks_live_ota_before_stopping_anything(self):
        self.write("var/run/silent-vpn/update.lock/pid", str(os.getpid()))
        result = self.install_fixture(upgrade=True)
        self.assertNotEqual(result.returncode, 0)
        self.assert_saved()
        self.assertFalse((self.root / "actions").exists())
        self.assertEqual((self.root / "var/run/silent-vpn/update.lock/pid").read_text(), str(os.getpid()))

    def test_existing_ota_worker_bypasses_manual_upgrade_lock(self):
        self.write("var/run/silent-vpn/update.lock/pid", str(os.getpid()))
        self.env["SILENT_OPENWRT_UPDATE"] = "1"
        result = self.install_fixture(upgrade=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_saved()
        self.assertEqual((self.root / "var/run/silent-vpn/update.lock/pid").read_text(), str(os.getpid()))

    def test_manual_upgrade_reclaims_dead_worker_lock(self):
        self.write("var/run/silent-vpn/update.lock/pid", "29999999")
        result = self.install_fixture(upgrade=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_saved()
        self.assertFalse((self.root / "var/run/silent-vpn/update.lock").exists())

    def test_wrong_architecture_does_not_pause_existing_client(self):
        self.env["FIXTURE_BAD_ARCH"] = "1"
        result = self.install_fixture(upgrade=True)
        self.assertNotEqual(result.returncode, 0)
        self.assert_saved()
        self.assertFalse((self.root / "actions").exists())

    def test_backup_space_failure_does_not_pause_existing_client(self):
        self.write("commands/df", "#!/bin/sh\necho 'fixture 100 99 1 99% /tmp'\n", True)
        result = self.install_fixture(upgrade=True)
        self.assertNotEqual(result.returncode, 0)
        self.assert_saved()
        self.assertFalse((self.root / "actions").exists())
        self.assertFalse((self.root / "var/run/silent-vpn/update.lock").exists())

    def test_executable_replacement_is_atomic_even_if_old_process_is_running(self):
        binary = self.root / "old-sleep"
        shutil.copy2("/bin/sleep", binary)
        process = subprocess.Popen([str(binary), "10"])
        try:
            replacement = self.write("replacement", "#!/bin/sh\necho updated\n")
            definitions = (ROOT / "install.sh").read_text().split('cmd="${1:-all}"')[0]
            script = self.write("atomic.sh", definitions + '\ninstall_binary "' + str(replacement) + '" "' + str(binary) + '"\n')
            result = subprocess.run(["sh", str(script)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(binary.read_text(), replacement.read_text())
            self.assertIsNone(process.poll())
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_generic_bootstrap_dispatches_keenetic_before_openwrt_code(self):
        self.write("opt/bin/opkg", "#!/bin/sh\nexit 0\n", True)
        (self.root / "opt/etc/ndm").mkdir(parents=True)
        self.write("commands/wget", '''#!/bin/sh
test "$1" = -O || exit 88
test "$3" = https://silentvpn3.github.io/keenetic-install.sh || exit 89
printf '#!/bin/sh\necho keenetic > "$FIXTURE/selected"\n' > "$2"
''', True)
        source = (ROOT / "remote-install.sh").read_text()
        source = self.rooted(source).replace("/opt/", str(self.root) + "/opt/")
        script = self.write("router-install.sh", source)
        result = subprocess.run(["sh", str(script)], env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "selected").read_text().strip(), "keenetic")
        self.assertFalse(list((self.root / "tmp").glob("svk-bootstrap.*")))


if __name__ == "__main__":
    unittest.main()
