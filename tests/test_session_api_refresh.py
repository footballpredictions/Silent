"""Run shipped session HTTP helpers with a blocked WAN and expired access token."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which('sh') or str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Git/bin/sh.exe')

class SessionRefreshTests(unittest.TestCase):
    def run_request(self, command, refresh_down=False, rejection='401', logout_during_refresh=False):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            env = dict(os.environ, SV_LIB=(ROOT / 'files/usr/lib/silent-vpn').as_posix(),
                       SV_VAR=(run / 'state').as_posix(), SV_RUN=run.as_posix(),
                       SV_TUNNEL_API='http://10.66.66.1:8000', REFRESH_DOWN=str(int(refresh_down)), REJECTION=rejection,
                       LOGOUT_DURING_REFRESH=str(int(logout_during_refresh)))
            script = r'''
. "$SV_LIB/hive.sh"
sv_mkdir
touch "$SV_RUN/path.up"
printf old.token.value > "$SV_VAR/access_token"
printf refresh.token.value > "$SV_VAR/refresh_token"
sv_tunnel_api_ready() { return 0; }
jsonfilter() {
  case "$*" in
    *access_token*) printf new.token.value ;;
    *refresh_token*) printf refresh.token.value ;;
  esac
}
wget() {
  local out="" url="" auth=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      -O) out="$2"; shift ;;
      --header=Authorization:*) auth="$1" ;;
      http://*|https://*) url="$1" ;;
    esac
    shift
  done
  printf '%s\n' "$url" >> "$SV_RUN/visited"
  case "$url" in
    */api/auth/refresh)
      [ "$REFRESH_DOWN" = 0 ] || return 1
      printf '{"access_token":"new.token.value","refresh_token":"refresh.token.value"}' > "$out"
      [ "$LOGOUT_DURING_REFRESH" = 0 ] || rm -f "$SV_VAR/access_token" "$SV_VAR/refresh_token" ;;
    *)
      case "$auth" in
        *new.token.value) printf '{"ok":true}' > "$out" ;;
        *) printf '{"detail":"expired"}' > "$out"; echo "HTTP error $REJECTION" >&2; return 8 ;;
      esac ;;
  esac
}
''' + command + r''' >/dev/null
'''
            result = subprocess.run([SHELL, '-c', script], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            return ((run / 'http.code').read_text().strip(), (run / 'visited').read_text().splitlines(),
                    (run / 'state/access_token').read_text() if (run / 'state/access_token').exists() else '',
                    (run / 'state/refresh_token').read_text() if (run / 'state/refresh_token').exists() else '')

    def test_all_session_requests_refresh_and_retry_through_the_existing_vpn(self):
        for command in ['sv_hive_me', 'sv_hive_rename_device other TV', 'sv_hive_delete_device other']:
            with self.subTest(command=command):
                code, visited, token, _ = self.run_request(command)
                self.assertEqual(code, '200')
                self.assertEqual(token, 'new.token.value')
                self.assertEqual(len(visited), 3)
                self.assertEqual(visited[1], 'http://10.66.66.1:8000/api/auth/refresh')
                self.assertTrue(all(url.startswith('http://10.66.66.1:8000/') for url in visited))

    def test_refresh_network_failure_preserves_saved_login(self):
        code, _, token, refresh = self.run_request('sv_hive_me', refresh_down=True)
        self.assertEqual(code, '503')
        self.assertEqual((token, refresh), ('old.token.value', 'refresh.token.value'))

    def test_forbidden_is_authoritative_without_refresh_or_replay(self):
        code, visited, _, _ = self.run_request('sv_hive_me', rejection='403')
        self.assertEqual(code, '403')
        self.assertEqual(len(visited), 1)

    def test_pending_refresh_does_not_restore_explicitly_closed_login(self):
        code, _, token, refresh = self.run_request('sv_hive_me', logout_during_refresh=True)
        self.assertEqual(code, '401')
        self.assertEqual((token, refresh), ('', ''))

if __name__ == '__main__':
    unittest.main()
