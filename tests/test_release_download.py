"""Replay a router whose Pages work but direct GitHub downloads time out."""
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from test_path_runtime import SHELL

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://github.com/silentvpn3/silentvpn3.github.io/releases/download/v1.0.172/silent-vpn-openwrt-1.0.172-aarch64.tar.gz'


@unittest.skipUnless(SHELL, 'POSIX shell required')
class ReleaseDownloadTests(unittest.TestCase):
    def run_download(self, corrupt=False):
        definitions = (ROOT/'remote-install.sh').read_text(encoding='utf-8').split('if [ "$(id -u')[0]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            payload = b'verified architecture package from the existing OTA API\n'
            (base/'payload').write_bytes(b'corrupted mirror' if corrupt else payload)
            code = definitions + r'''
slot=aarch64
VERSION=1.0.172
SHA256="$TEST_SHA"
SIZE="$TEST_SIZE"
wget() {
    local arg url out previous
    for arg in "$@"; do
        [ "$previous" != '-O' ] || out="$arg"
        case "$arg" in http://*|https://*) url="$arg" ;; esac
        previous="$arg"
    done
    printf '%s\n' "$url" >> attempts
    case "$url" in
        https://github.com/*) return 1 ;;
        */api/updates/download/openwrt\?arch=aarch64|*/update/openwrt/*)
            cp payload "$out"; return 0 ;;
        *) return 1 ;;
    esac
}
sv_fetch "$TEST_URL" package.tgz
printf '%s  package.tgz\n' "$SHA256" | sha256sum -c -
'''
            env = {**os.environ, 'TEST_SHA':hashlib.sha256(payload).hexdigest(),
                   'TEST_SIZE':str(len(payload)), 'TEST_URL':URL}
            (base/'run.sh').write_text(code,encoding='utf-8',newline='\n')
            result = subprocess.run([SHELL,'run.sh'],cwd=base,env=env,capture_output=True,
                                    text=True,encoding='utf-8',timeout=10)
            attempts=(base/'attempts').read_text().splitlines()
            return result, attempts

    def test_github_timeout_uses_verified_existing_api_mirror(self):
        result, attempts=self.run_download()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertTrue(any('/api/updates/download/openwrt?' in url or '/update/openwrt/' in url
                            for url in attempts))

    def test_corrupt_mirror_cannot_be_installed(self):
        result, _=self.run_download(corrupt=True)
        self.assertNotEqual(result.returncode,0)

    def test_panel_update_can_download_when_api_and_github_are_blocked(self):
        installer=(ROOT/'remote-install.sh').read_text(encoding='utf-8').split('if [ "$(id -u')[0]
        updater=(ROOT/'files/usr/lib/silent-vpn/update.sh').read_text(encoding='utf-8')
        payload=b'OTA copy matching the Pages metadata\n'
        sha=hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            (base/'payload').write_bytes(payload)
            code=installer+'\n'+updater+r'''
sv_api_bases() { echo http://87.58.213.193:9100; }
sv_json_get() {
 case "$2" in
  version) echo 1.0.172;; size) echo "$TEST_SIZE";;
  sha256) echo "$TEST_SHA";; download_url) echo "$TEST_URL";;
 esac
}
wget() {
 local arg url out previous
 for arg in "$@"; do
  case "$previous" in -O|-qO) out="$arg";; esac
  case "$arg" in http://*|https://*) url="$arg";; esac
  previous="$arg"
 done
 case "$url" in
  https://89-125-188-100.nip.io:2083/update/openwrt/*) cp payload "$out"; return 0;;
  *) return 1;;
 esac
}
sv_update_download ignored.json package.tgz aarch64
'''
            (base/'run.sh').write_text(code,encoding='utf-8',newline='\n')
            result=subprocess.run([SHELL,'run.sh'],cwd=base,env={**os.environ,'TEST_SHA':sha,
                'TEST_SIZE':str(len(payload)),'TEST_URL':URL},capture_output=True,text=True,encoding='utf-8',timeout=10)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(hashlib.sha256((base/'package.tgz').read_bytes()).hexdigest(),sha)


if __name__=='__main__':
    unittest.main()
