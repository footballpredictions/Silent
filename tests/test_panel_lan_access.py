"""Run the shipped CGI doors with the actual local-access guard."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which("sh")
if not SHELL and os.name == "nt":
    candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/sh.exe"
    if candidate.is_file():
        SHELL = str(candidate)

BOUNDARIES = r'''
uci() {
    case "$*" in
        '-q get network.lan.device') echo "${FIXTURE_LAN_DEV:-br-lan}" ;;
        *) return 1 ;;
    esac
}
ip() {
    case "$*" in
        '-4 neigh show 192.168.1.173') echo '192.168.1.173 dev br-lan lladdr 32:4f:a9:40:e8:63 REACHABLE' ;;
        '-4 route get 192.168.1.173'|'-4 route get 192.168.1.195') echo "$REMOTE_ADDR dev ${FIXTURE_LAN_DEV:-br-lan} src 192.168.1.1" ;;
        '-4 route get 192.168.3.9') echo '192.168.3.9 dev br-guest src 192.168.3.1' ;;
        '-4 route get 79.111.32.7'|'-4 route get 10.0.0.7') echo "$REMOTE_ADDR dev wan src 79.111.37.132" ;;
        '-4 route get 1.1.1.1') echo '1.1.1.1 via 79.111.32.1 dev wan src 79.111.37.132' ;;
        '-4 route get 192.168.8.9') echo '192.168.8.9 via 192.168.1.2 dev br-lan src 192.168.1.1' ;;
        '-4 route get 10.66.0.3') echo '10.66.0.3 dev svpath src 10.66.0.9' ;;
        '-6 route get fd92:8ac2:23b8::42'|'-6 route get fe80::42%br-lan') echo "$REMOTE_ADDR dev br-lan src fd92:8ac2:23b8::1" ;;
        '-6 route get 2001:db8:ffff::7') echo '2001:db8:ffff::7 dev wan src 2001:db8:ffff::1' ;;
        *) return 1 ;;
    esac
}
iw() {
    case "$*" in
        dev) echo 'Interface wl0-ap0' ;;
        'dev wl0-ap0 station get 32:4f:a9:40:e8:63') return 0 ;;
        *) return 1 ;;
    esac
}
silent-vpn-ctl() { echo '{"session":false,"fixture":true}'; }
sv_mkdir() { :; }
'''


@unittest.skipUnless(SHELL, "POSIX shell required for CGI LAN access scenarios")
class PanelLanAccessTests(unittest.TestCase):
    def assert_access(self, address, allowed, lan_device="br-lan"):
        common = (ROOT / "files/usr/lib/silent-vpn/common.sh").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "index.html"
            index.write_text("PANEL_FIXTURE", encoding="utf-8")
            for door in ["silent-entry", "silent-api"]:
                with self.subTest(door=door, address=address):
                    source = (ROOT / f"files/www/cgi-bin/{door}").read_text(encoding="utf-8")
                    source = source.replace('SV_LIB="/usr/lib/silent-vpn"', '')
                    for library in ["common", "hive", "session"]:
                        source = source.replace(f'. "$SV_LIB/{library}.sh"', '')
                    source = source.replace('INDEX="/www/silent-vpn/index.html"', f'INDEX="{index.as_posix()}"')
                    source = source.replace('if [ -f "$SV_LIB/common.sh" ]; then', 'if true; then')
                    env = dict(os.environ, REMOTE_ADDR=address, HTTP_HOST="192.168.1.1.silent.vpn",
                               PATH_INFO="/status", CONTENT_LENGTH="0", FIXTURE_LAN_DEV=lan_device)
                    script = Path(directory) / "request.sh"
                    script.write_bytes((common + BOUNDARIES + source).encode("utf-8"))
                    result = subprocess.run([SHELL, script.as_posix()],
                                            env=env, capture_output=True, text=True,
                                            encoding="utf-8", timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("Status: 200" if allowed else "Status: 403", result.stdout)
                    if allowed:
                        self.assertIn("PANEL_FIXTURE" if door == "silent-entry" else '"fixture":true', result.stdout)

    def test_wifi_phone_in_lan_allowed(self):
        self.assert_access("192.168.1.173", True)

    def test_wired_pc_in_lan_allowed(self):
        self.assert_access("192.168.1.195", True)

    def test_configured_lan_device_allowed(self):
        self.assert_access("192.168.1.195", True, "br-home")

    def test_ipv6_lan_and_mapped_ipv4_allowed(self):
        for address in ["fd92:8ac2:23b8::42", "fe80::42", "::ffff:192.168.1.173"]:
            self.assert_access(address, True)

    def test_loopback_allowed(self):
        for address in ["127.0.0.1", "::1", "::ffff:127.0.0.1"]:
            self.assert_access(address, True)

    def test_wan_guest_vpn_and_routed_networks_denied(self):
        for address in ["79.111.32.7", "10.0.0.7", "1.1.1.1", "192.168.3.9",
                        "10.66.0.3", "192.168.8.9", "2001:db8:ffff::7"]:
            self.assert_access(address, False)

    def test_missing_unknown_and_invalid_address_denied(self):
        for address in ["", "192.168.1.250", "router.test", "127.invalid", "192.168.1.1 extra"]:
            self.assert_access(address, False)


if __name__ == "__main__":
    unittest.main()
