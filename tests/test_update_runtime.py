"""Run the real OTA worker against real archives and a sandbox router filesystem."""
import hashlib
import io
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

from test_path_runtime import SHELL, ROOT


@unittest.skipUnless(SHELL, "POSIX shell required")
class UpdateRuntimeTests(unittest.TestCase):
    def test_lock_blocks_parallel_start_and_detects_dead_worker(self):
        source = (ROOT / "files/usr/lib/silent-vpn/update.sh").read_text(encoding="utf-8")
        definitions = source.split('sv_update_status()')[0]
        with tempfile.TemporaryDirectory() as directory:
            code = definitions + r'''
SV_RUN="$(pwd)"
mkdir update.lock
sv_update_busy || exit 21
echo $$ > update.lock/pid
sv_update_busy || exit 22
echo 29999999 > update.lock/pid
sv_update_busy && exit 23
exit 0
'''
            result = subprocess.run([SHELL, "-c", code], cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_metadata_fails_over_and_uses_pages_with_old_server(self):
        for mode in ("second_api", "pages"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                info = {"available": True, "version": "1.0.171", "arch": "aarch64",
                        "sha256": "a" * 64, "size": 1234, "unpacked_size": 9999}
                (base / "api.json").write_text(json.dumps(info))
                pages_info = {key: value for key, value in info.items() if key not in ("arch", "available")}
                (base / "pages.json").write_text(json.dumps({"openwrt": {"arches": {"aarch64": pages_info}}}))
                (base / "read_field.py").write_text('''import json,sys
value=json.load(open(sys.argv[1]))
for key in sys.argv[2].removeprefix('@.').split('.'):
    value=value.get(key, '') if isinstance(value,dict) else ''
print(json.dumps(value) if isinstance(value,(dict,bool)) else value)
''')
                code = (ROOT / "files/usr/lib/silent-vpn/update.sh").read_text(encoding="utf-8") + r'''
SV_RUN="$(pwd)"
sv_json_get() { "$TEST_PYTHON" "$SV_RUN/read_field.py" "$1" "$2"; }
jsonfilter() { "$TEST_PYTHON" "$SV_RUN/read_field.py" "$2" "$4"; }
sv_api_bases() { printf '%s\n' https://bad.test https://good.test; }
sv_hive_wget() {
    echo "$2" >> "$SV_RUN/calls"
    if [ "$TEST_MODE" = second_api ] && [ "${2#https://good.test}" != "$2" ]; then
        cp "$SV_RUN/api.json" "$4"; echo 200
    else
        echo '{"detail":"offline"}' > "$4"; echo 503
    fi
}
wget() { cp "$SV_RUN/pages.json" "$2"; }
sv_update_info aarch64 "$SV_RUN/result.json"
'''
                (base / "run.sh").write_text(code, encoding="utf-8", newline="\n")
                result = subprocess.run([SHELL, "run.sh"], cwd=base, capture_output=True,
                    text=True, encoding="utf-8", timeout=20,
                    env={**os.environ, "SV_VERSION":"1.0.170", "TEST_MODE":mode,
                         "TEST_PYTHON":Path(sys.executable).as_posix()})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads((base / "result.json").read_text()), info)
                self.assertEqual(len((base / "calls").read_text().splitlines()), 2)
                self.assertEqual(list(base.glob("update-check.*")) + list(base.glob("update-pages.*")), [])

    def worker(self, arch="aarch64", mode="ok"):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            router = base / "router"
            for directory_name in ("usr/lib/silent-vpn", "usr/bin", "usr/sbin", "www/silent-vpn",
                                   "www/cgi-bin", "etc/config", "etc/init.d", "etc/hotplug.d/iface", "etc/uci-defaults"):
                (router / directory_name).mkdir(parents=True, exist_ok=True)
            old_files = ["usr/lib/silent-vpn/VERSION", "usr/bin/spass", "usr/sbin/silent-vpn-ctl",
                         "usr/sbin/silent-vpn-policy", "usr/sbin/silent-vpn-update", "usr/sbin/silent-vpn-uninstall",
                         "www/silent-vpn/index.html", "www/cgi-bin/silent-api", "www/cgi-bin/silent-entry",
                         "etc/config/silent-vpn", "etc/hotplug.d/iface/99-silent-vpn", "etc/uci-defaults/99-silent-vpn"]
            for name in old_files:
                (router / name).write_text("old-" + name, encoding="utf-8")
            (router / "usr/lib/silent-vpn/VERSION").write_text("1.0.170")
            for service in ("silent-vpn", "silent-vpn-policy"):
                path = router / "etc/init.d" / service
                path.write_text('#!/bin/sh\necho service-"$1" >> "$SV_RUN/events"\n')
                path.chmod(0o755)
            run = base / "run"
            (run / "update.lock").mkdir(parents=True)
            (base / "read_field.py").write_text(
                'import json,sys\nv=json.load(open(sys.argv[1])).get(sys.argv[2], "")\n'
                'print(str(v).lower() if isinstance(v,bool) else v)\n')
            archive = base / "package.tgz"
            install = '''#!/bin/sh
echo install >> "$SV_RUN/events"
[ "$SILENT_OPENWRT_UPDATE" = 1 ] || exit 99
echo '1.0.171' > "$SV_TEST_ROOT/usr/lib/silent-vpn/VERSION"
echo new-binary > "$SV_TEST_ROOT/usr/bin/spass"
echo replaced-config > "$SV_TEST_ROOT/etc/config/silent-vpn"
[ "$TEST_MODE" != install_failure ]
'''
            payload = {"VERSION": b"1.0.171", "ARCH": arch.encode(), "install.sh": install.encode(),
                       f"files/usr/lib/silent-vpn/wdtt/wdtt-client.{arch}": b"fake transport"}
            if mode == "wrong_arch":
                payload["ARCH"] = b"wrong"
            if mode == "wrong_version":
                payload["VERSION"] = b"1.0.169"
            with tarfile.open(archive, "w:gz") as output:
                for name, content in payload.items():
                    member = tarfile.TarInfo("silent-vpn/" + name)
                    member.size = len(content)
                    output.addfile(member, io.BytesIO(content))
            sha = hashlib.sha256(archive.read_bytes()).hexdigest()
            info = {"available": True, "version": "1.0.171", "arch": arch,
                    "size": archive.stat().st_size, "unpacked_size": 100000,
                    "sha256": "0" * 64 if mode == "bad_hash" else sha}
            (base / "info.json").write_text(json.dumps(info))
            definitions = (ROOT / "remote-install.sh").read_text(encoding="utf-8").split('if [ "$(id -u')[0]
            source = (ROOT / "files/usr/lib/silent-vpn/update.sh").read_text(encoding="utf-8")
            source = re.sub(r'(?<![a-zA-Z0-9])/(usr|etc|www)/', r'${SV_TEST_ROOT}/\1/', source)
            source = source.replace('cd / &&', 'cd "$SV_TEST_ROOT" &&').replace('-C / ', '-C "$SV_TEST_ROOT" ')
            source = source.replace('/tmp/sv-update.', '$SV_TEST_TMP/sv-update.')
            code = definitions + '\nset +e\n' + source + r'''
SV_TEST_TMP="$(pwd)"
SV_TEST_ROOT="$SV_TEST_TMP/router"
SV_RUN="$SV_TEST_TMP/run"
sv_json_get() { "$TEST_PYTHON" "$SV_TEST_TMP/read_field.py" "$1" "$2"; }
sv_update_info() { cp "$SV_TEST_TMP/info.json" "$2"; }
sv_api_bases() { echo https://fixture.test; }
sv_slot() { echo "$TEST_ARCH"; }
sv_preflight() { [ "$TEST_MODE" != no_space ]; }
sv_session_connected() { return 0; }
wget() { cp "$SV_TEST_TMP/package.tgz" "$2"; }
silent-vpn-ctl() { echo "$1" >> "$SV_RUN/events"; }
uci() { :; }
sv_update_run
'''
            env = {**os.environ, "SV_TEST_ROOT": router.as_posix(), "SV_TEST_TMP": base.as_posix(),
                   "SV_RUN": run.as_posix(), "SV_VERSION": "1.0.170", "TEST_ARCH": arch,
                   "TEST_MODE": mode, "TEST_PYTHON": Path(sys.executable).as_posix()}
            (base / "run.sh").write_text(code, encoding="utf-8", newline="\n")
            result = subprocess.run([SHELL, "run.sh"], env=env, cwd=base, capture_output=True,
                                    text=True, encoding="utf-8", timeout=30)
            self.assertTrue((run / "update-state.json").exists(), result.stdout + result.stderr)
            state = json.loads((run / "update-state.json").read_text(encoding="utf-8"))
            events = (run / "events").read_text().splitlines() if (run / "events").exists() else []
            snapshot = {name: (router / name).read_text() for name in old_files}
            self.assertEqual(list(base.glob("sv-update.*")), [], result.stderr)
            self.assertFalse((run / "update.lock").exists())
            return result, state, events, snapshot

    def test_all_architectures_install_reconnect_preserve_config_and_cleanup(self):
        for arch in ("aarch64", "arm", "mipsel", "x86_64"):
            with self.subTest(arch=arch):
                result, state, events, snapshot = self.worker(arch)
                self.assertEqual(result.returncode, 0, str(state) + result.stdout + result.stderr)
                self.assertEqual(state["phase"], "done")
                self.assertEqual(snapshot["usr/lib/silent-vpn/VERSION"].strip(), "1.0.171")
                self.assertEqual(snapshot["etc/config/silent-vpn"], "old-etc/config/silent-vpn")
                self.assertLess(events.index("disconnect"), events.index("install"))
                self.assertLess(events.index("install"), events.index("connect"))

    def test_bad_hash_arch_version_or_space_never_interrupt_vpn(self):
        for mode in ("bad_hash", "wrong_arch", "wrong_version", "no_space"):
            with self.subTest(mode=mode):
                result, state, events, snapshot = self.worker(mode=mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(state["phase"], "error")
                self.assertNotIn("disconnect", events)
                self.assertEqual(snapshot["usr/lib/silent-vpn/VERSION"], "1.0.170")

    def test_install_failure_restores_real_backup_and_reconnects(self):
        result, state, events, snapshot = self.worker(mode="install_failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state["phase"], "error")
        self.assertEqual(snapshot["usr/lib/silent-vpn/VERSION"], "1.0.170")
        self.assertEqual(snapshot["usr/bin/spass"], "old-usr/bin/spass")
        self.assertEqual(snapshot["etc/config/silent-vpn"], "old-etc/config/silent-vpn")
        self.assertIn("connect", events, str(state) + result.stdout + result.stderr)
