import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = (ROOT / "files/usr/lib/silent-vpn/common.sh").read_text(encoding="utf-8")
SHELL = shutil.which("sh")
if not SHELL and os.name == "nt":
    git_shell = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/sh.exe"
    if git_shell.is_file():
        SHELL = str(git_shell)


class ApiFailoverTests(unittest.TestCase):
    def test_public_bases_cells_then_hive(self):
        start = COMMON.index("sv_api_bases()")
        chunk = COMMON[start : start + 900]
        hive = chunk.index("SV_PUBLIC_API")
        cell1 = chunk.index("87.58.213.193:9100")
        cell2 = chunk.index("78.17.74.27:9100")
        self.assertLess(cell1, cell2)
        self.assertLess(cell1, hive)
        self.assertIn("sv_hive_timeout_for", COMMON)

    def test_old_hive_override_is_ignored(self):
        self.assertIn("*132.243.234.162*", COMMON)


@unittest.skipUnless(SHELL, "POSIX shell required for API transport scenarios")
class ApiTransportTests(unittest.TestCase):
    def request(self, successful_base, tunnel_up=False):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            if tunnel_up:
                (run / "path.up").touch()
            environment = os.environ.copy()
            environment.update(
                SV_LIB=(ROOT / "files/usr/lib/silent-vpn").as_posix(),
                SV_VAR=(run / "state").as_posix(),
                SV_RUN=run.as_posix(),
                SV_API_OVERRIDE="",
                SV_PUBLIC_API="https://89-125-188-100.nip.io",
                SV_TUNNEL_API="http://10.66.66.1:8000",
                SV_TEST_SUCCESS=successful_base + "/api/users/me",
            )
            # Exercise the real shell request loop. The stub records attempted
            # URLs and returns a response only for the selected reachable API.
            script = '''
. "$SV_LIB/hive.sh"
wget() {
    local out="" timeout="" url=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
            -qO|-O) out="$2"; shift ;;
            --timeout=*) timeout="${1#--timeout=}" ;;
            http://*|https://*) url="$1" ;;
        esac
        shift
    done
    printf '%s %s\\n' "$url" "$timeout" >> "$SV_RUN/attempts"
    [ "$url" = "$SV_TEST_SUCCESS" ] || return 1
    printf '{"ok":true}' > "$out"
}
response="$(sv_hive_get /api/users/me)"
cat "$response"
'''
            result = subprocess.run(
                [SHELL, "-c", script], env=environment, text=True,
                capture_output=True, timeout=10, check=True,
            )
            self.assertEqual(result.stdout, '{"ok":true}')
            self.assertEqual((run / "http.code").read_text().strip(), "200")
            return (run / "attempts").read_text().splitlines()

    def test_reachable_cell_does_not_wait_for_public_hive(self):
        self.assertEqual(self.request("http://87.58.213.193:9100"), [
            "http://87.58.213.193:9100/api/users/me 8",
        ])

    def test_failed_first_cell_uses_second_before_public_hive(self):
        self.assertEqual(self.request("http://78.17.74.27:9100"), [
            "http://87.58.213.193:9100/api/users/me 8",
            "http://78.17.74.27:9100/api/users/me 8",
        ])

    def test_active_vpn_uses_only_its_tunnel_gateway(self):
        self.assertEqual(self.request("http://10.66.66.1:8000", tunnel_up=True), [
            "http://10.66.66.1:8000/api/users/me 8",
        ])

    def test_bearer_token_stays_one_header(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            environment = os.environ.copy()
            environment.update(
                SV_LIB=(ROOT / "files/usr/lib/silent-vpn").as_posix(),
                SV_VAR=(run / "state").as_posix(),
                SV_RUN=run.as_posix(),
                SV_API_OVERRIDE="",
                SV_PUBLIC_API="https://89-125-188-100.nip.io",
                SV_TUNNEL_API="http://10.66.66.1:8000",
                SV_TEST_SUCCESS="http://87.58.213.193:9100/api/users/me",
            )
            script = r'''
. "$SV_LIB/hive.sh"
mkdir -p "$SV_VAR"
printf '%s\n' 'abc.def.ghi' > "$SV_VAR/access_token"
wget() {
    local out="" url=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --header=Authorization:*) printf '%s\n' "$1" >> "$SV_RUN/headers" ;;
            -qO|-O) out="$2"; shift ;;
            http://*|https://*) url="$1" ;;
        esac
        shift
    done
    [ "$url" = "$SV_TEST_SUCCESS" ] || return 1
    printf '{"ok":true}' > "$out"
}
sv_hive_get /api/users/me >/dev/null
'''
            subprocess.run(
                [SHELL, "-c", script], env=environment, text=True,
                capture_output=True, timeout=10, check=True,
            )
            headers = (run / "headers").read_text().splitlines()
            self.assertEqual(headers, ["--header=Authorization: Bearer abc.def.ghi"])


if __name__ == "__main__":
    unittest.main()
