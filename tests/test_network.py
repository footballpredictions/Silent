"""Execute the actual POSIX network adapter with command doubles; no host routes change."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
if os.name == "nt":
    BASH = "C:/Program Files/Git/bin/bash.exe"

def posix(path):
    s = str(path).replace("\\", "/")
    return "/"+s[0].lower()+s[2:] if len(s)>2 and s[1]==":" else s

class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.bin = self.base/"bin"; self.bin.mkdir()
        self.log = self.base/"commands.log"
        self.run = self.base/"run"; self.run.mkdir()
        stub = '''#!/bin/sh
name=${0##*/}
printf '%s %s\\n' "$name" "$*" >> "$SVK_TEST_LOG"
if [ "$name" = iptables ] || [ "$name" = ip6tables ]; then
    case " $* " in *" -C "*) exit 1 ;; esac
    if [ "${SVK_FAIL_DNAT:-0}" = 1 ]; then case " $* " in *" --to-destination "*) exit 42 ;; esac; fi
fi
exit 0
'''
        for name in ("ip", "iptables", "ip6tables", "ipset", "ping"):
            p = self.bin/name; p.write_text(stub, newline="\n"); p.chmod(0o755)
        self.env = os.environ.copy()
        self.env.update(SVK_RUN=posix(self.run), SVK_PATH=posix(self.bin)+":/usr/bin:/bin", SVK_TEST_LOG=posix(self.log), MSYS_NO_PATHCONV="1")
    def tearDown(self): self.tmp.cleanup()
    def invoke(self, op, *args, fail=False):
        env = dict(self.env); env["SVK_FAIL_DNAT"] = "1" if fail else "0"
        return subprocess.run([BASH, posix(ROOT/"files/network.sh"), op, "br0", "192.168.1.1", "192.168.1.0/24", "8787", *args], env=env, capture_output=True, text=True)
    def commands(self): return self.log.read_text() if self.log.exists() else ""
    def test_lan_only_policy_and_ipv6_guard(self):
        result = self.invoke("up"); self.assertEqual(result.returncode, 0, result.stderr)
        log = self.commands()
        self.assertIn("-i br0 -s 192.168.1.0/24 -j MARK --set-xmark 0x53000000/0xff000000", log)
        self.assertIn("ip rule add pref 51 fwmark 0x53000000/0xff000000 table 20513", log)
        self.assertIn("ip6tables -w 2 -A SVK_V6 -i br0 -j REJECT", log)
        self.assertNotIn("route replace default", log)
        self.assertNotIn("-t mangle -F PREROUTING", log)
        self.assertTrue((self.run/"active").exists())
    def test_start_failure_rolls_back_partial_dns_policy(self):
        result = self.invoke("up", fail=True); self.assertNotEqual(result.returncode, 0)
        log = self.commands()
        self.assertIn("ip rule del pref 51 fwmark 0x53000000/0xff000000 table 20513", log)
        self.assertIn("-t nat -F SVK_N", log)
        self.assertFalse((self.run/"active").exists())
    def test_stop_only_removes_owned_resources(self):
        (self.run/"address").write_text("10.66.66.2/32\n")
        result = self.invoke("down"); self.assertEqual(result.returncode, 0, result.stderr)
        log = self.commands()
        self.assertIn("ip rule del pref 52 from 10.66.66.2/32 table 20513", log)
        self.assertIn("ip route flush table 20513 dev svkeen", log)
        self.assertNotIn("iptables -F", log)
        self.assertNotIn("ip rule flush", log)
        self.assertNotIn("killall", log)
    def test_ndm_hook_is_scoped_to_changed_table(self):
        (self.run/"active").touch()
        result = self.invoke("restore", "nat"); self.assertEqual(result.returncode, 0, result.stderr)
        log = self.commands(); self.assertIn("-t nat", log); self.assertNotIn("-t mangle", log); self.assertNotIn("rule add", log)
    def test_hook_does_not_block_if_transition_holds_lock(self):
        lock = self.run/"lock"; lock.mkdir(); (lock/"pid").write_text(str(os.getpid()))
        result = self.invoke("restore", "nat"); self.assertEqual(result.returncode, 0, result.stderr); self.assertEqual(self.commands(), "")
    def test_shell_syntax(self):
        for p in [*ROOT.glob("*.sh"), *ROOT.glob("files/*.sh"), ROOT/"files/S99silent-keenetic"]:
            r = subprocess.run([BASH, "-n", posix(p)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{p}: {r.stderr}")

class ArtifactTests(unittest.TestCase):
    def test_all_architectures_and_lf_in_release(self):
        manifest = json.loads((ROOT/"dist/manifest.json").read_text())
        self.assertEqual(set(manifest["architectures"]), {"aarch64","armv7","armv5","mipsel","mips","x86_64","i386"})
        archive = ROOT/"dist"/f"silent-vpn-keenetic-{manifest['version']}.tar.gz"
        with tarfile.open(archive) as tf:
            for slot in manifest["architectures"]:
                for binary in ("silent-keenetic","spass"):
                    name=f"silent-vpn-keenetic-{manifest['version']}/bin/{slot}/{binary}"
                    member=tf.getmember(name); self.assertEqual(member.mode,0o755); self.assertEqual(tf.extractfile(member).read(4),b"\x7fELF")
            for member in tf.getmembers():
                if member.name.endswith((".sh",".domains")) or member.name.endswith("S99silent-keenetic"):
                    b=tf.extractfile(member).read(); self.assertNotIn(b"\r",b); self.assertFalse(b.startswith(b"\xef\xbb\xbf"))
    def test_manifest_checksums(self):
        import hashlib
        manifest = json.loads((ROOT/"dist/manifest.json").read_text())
        for artifact in manifest["artifacts"]:
            path=ROOT/"dist"/artifact["file"]
            self.assertEqual(path.stat().st_size,artifact["size"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),artifact["sha256"])

if __name__ == "__main__": unittest.main()
