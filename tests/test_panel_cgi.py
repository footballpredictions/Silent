"""Local panel reports the running tunnel and releases profile response files."""
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
SESSION = (ROOT / "files/usr/lib/silent-vpn/session.sh").read_text(encoding="utf-8")
CONNECTED = SESSION[SESSION.index("sv_session_connected()"):SESSION.index("sv_connect_abort()")]


@unittest.skipUnless(SHELL, "POSIX shell required for panel CGI scenarios")
class PanelCgiTests(unittest.TestCase):
    def test_exclusions_cgi_does_not_report_success_when_policy_fails(self):
        source = (ROOT / 'files/www/cgi-bin/silent-api').read_text(encoding='utf-8')
        source = source.replace('SV_LIB="/usr/lib/silent-vpn"', '')
        for name in ['common', 'hive', 'session']:
            source = source.replace(f'. "$SV_LIB/{name}.sh"', '')
        with tempfile.TemporaryDirectory() as directory:
            output = self.run_script(directory, r'''
sv_mkdir() { :; }
sv_http_allow_lan() { return 0; }
sv_session_active() { return 0; }
sv_session_connected() { return 1; }
sv_panel_logout() { :; }
jsonfilter() { cat >/dev/null; echo true; }
silent-vpn-ctl() { return 1; }
uci() { echo 1; }
PATH_INFO=/exclusions
REQUEST_METHOD=POST
''' + source)
            self.assertIn('Status: 503', output)
            self.assertNotIn('Status: 200', output)

    def run_script(self, directory, script):
        # Windows CreateProcess truncates long `sh -c` strings (~8k); run from a file.
        environment = os.environ.copy()
        environment.update(SV_RUN=Path(directory).as_posix(), SV_VAR=Path(directory).as_posix())
        path = Path(directory) / "panel-cgi.sh"
        path.write_text(script.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
        return subprocess.run([SHELL, str(path)], env=environment, capture_output=True,
                              text=True, encoding="utf-8", timeout=10, check=True).stdout

    def test_local_online_requires_live_process_and_applied_path(self):
        with tempfile.TemporaryDirectory() as directory:
            output = self.run_script(directory, CONNECTED + r'''
touch "$SV_RUN/connected" "$SV_RUN/path.up"
echo $$ > "$SV_RUN/cloak.pid"
sv_tunnel_api_ready() { return 0; }
sv_session_connected && echo LIVE
sv_tunnel_api_ready() { return 1; }
sv_session_connected || echo NO_ROUTE
sv_tunnel_api_ready() { return 0; }
rm "$SV_RUN/path.up"
sv_session_connected || echo NO_PATH
touch "$SV_RUN/path.up"
echo 99999999 > "$SV_RUN/cloak.pid"
sv_session_connected || echo DEAD
echo invalid > "$SV_RUN/cloak.pid"
sv_session_connected || echo INVALID
''')
            self.assertEqual(output.splitlines(), ["LIVE", "NO_ROUTE", "NO_PATH", "DEAD", "INVALID"])

    def test_profile_cgi_removes_its_response_without_clearing_session(self):
        # Run the actual CGI dispatch. The API boundary substitutes a profile file,
        # so cleanup is tested without accessing any real account or network.
        source = (ROOT / "files/www/cgi-bin/silent-api").read_text(encoding="utf-8")
        source = source.replace('SV_LIB="/usr/lib/silent-vpn"', '')
        for name in ["common", "hive", "session"]:
            source = source.replace(f'. "$SV_LIB/{name}.sh"', '')
        with tempfile.TemporaryDirectory() as directory:
            script = r'''
sv_mkdir() { mkdir -p "$SV_RUN"; }
sv_http_allow_lan() { return 0; }
sv_session_active() { return 0; }
sv_session_connected() { return 1; }
sv_panel_logout() { :; }
sv_hive_me() {
    printf '{"email":"fixture@example.test"}' > "$SV_RUN/profile.tmp"
    echo "$SV_RUN/profile.tmp"
}
printf '%s' 'fixture-token' > "$SV_VAR/access_token"
PATH_INFO=/profile
''' + source + r'''
[ ! -f "$SV_RUN/profile.tmp" ] && echo CLEANED
[ -s "$SV_VAR/access_token" ] && echo SESSION_PRESERVED
'''
            output = self.run_script(directory, script)
            self.assertIn('{"email":"fixture@example.test"}', output)
            self.assertIn("CLEANED", output)
            self.assertIn("SESSION_PRESERVED", output)


if __name__ == "__main__":
    unittest.main()
