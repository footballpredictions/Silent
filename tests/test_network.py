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
if [ "$name" = ipset ]; then case " $* " in *" list "*) exit 1 ;; esac; fi
exit 0
'''
        stub = stub.replace("exit 0\n", '''if [ "$name" = ip ]; then
    case " $* " in
        *" -o -4 addr show dev svkeen "*) echo '7: svkeen inet 10.66.66.2/32 scope global svkeen' ;;
        *" -4 route get 10.66.66.1 "*) echo '10.66.66.1 dev svkeen src 10.66.66.2' ;;
    esac
fi
exit 0
''')
        for name in ("ip", "iptables", "ip6tables", "ipset", "ping"):
            p = self.bin/name; p.write_text(stub, newline="\n"); p.chmod(0o755)
        self.env = os.environ.copy()
        self.env.update(SVK_RUN=posix(self.run), SVK_PATH=posix(self.bin)+":/usr/bin:/bin", SVK_TEST_LOG=posix(self.log), MSYS_NO_PATHCONV="1")
    def tearDown(self): self.tmp.cleanup()
    def invoke(self, op, *args, fail=False):
        env = dict(self.env); env["SVK_FAIL_DNAT"] = "1" if fail else "0"
        return subprocess.run([BASH, posix(ROOT/"files/network.sh"), op, "br0", "192.168.1.1", "192.168.1.0/24", "8787", *args], env=env, capture_output=True, text=True, encoding="utf-8")
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
        self.assertLess(log.index("--match-set svk_vpn dst"), log.index("--match-set svk_direct dst"))
    def test_start_failure_rolls_back_partial_dns_policy(self):
        result = self.invoke("up", fail=True); self.assertNotEqual(result.returncode, 0)
        log = self.commands()
        self.assertIn("ip rule del pref 51 fwmark 0x53000000/0xff000000 table 20513", log)
        self.assertIn("-t nat -F SVK_N", log)
        self.assertFalse((self.run/"active").exists())

    def test_direct_services_keep_native_wan_routing_instead_of_assuming_eth0(self):
        result = self.invoke('up')
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = self.commands().splitlines()
        direct = next(i for i, line in enumerate(lines) if '--match-set svk_direct dst -j RETURN' in line)
        fallback = next(i for i, line in enumerate(lines) if '-i br0 -s 192.168.1.0/24 -j MARK' in line)
        self.assertLess(direct, fallback)
        self.assertFalse(any('eth0' in line or 'wwan0' in line or 'table 162' in line for line in lines))
        self.assertFalse(any('route replace default' in line for line in lines))
    def test_stop_only_removes_owned_resources(self):
        (self.run/"address").write_text("10.66.66.2/32\n")
        result = self.invoke("down"); self.assertEqual(result.returncode, 0, result.stderr)
        log = self.commands()
        self.assertIn("ip rule del pref 52 from 10.66.66.2/32 table 20513", log)
        self.assertIn("ip route flush table 20513 dev svkeen", log)
        self.assertNotIn("iptables -F", log)
        self.assertNotIn("ip rule flush", log)
        self.assertNotIn("killall", log)
        self.assertIn("ipset destroy svk_vpn", log)
    def test_ensure_restores_routes_rules_and_sets_without_flushing_them(self):
        (self.run/"active").touch()
        (self.run/"address").write_text("10.66.66.2/32\n")
        result=self.invoke("ensure"); self.assertEqual(result.returncode,0,result.stderr)
        log=self.commands()
        self.assertIn("route replace default dev svkeen table 20513",log)
        self.assertIn("route replace 10.66.66.1/32 dev svkeen",log)
        self.assertIn("rule add pref 51",log)
        self.assertIn("rule add pref 52 from 10.66.66.2/32",log)
        self.assertIn("ipset create svk_vpn",log)
        self.assertNotIn("ipset flush",log)
        self.assertNotIn("route replace default dev svkeen\n",log)
    def test_disconnect_cannot_be_undone_by_background_or_ndm_hooks(self):
        result = self.invoke("up")
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.run/"address").write_text("10.66.66.2/32\n")
        result = self.invoke("down")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.run/"active").exists())
        self.log.unlink()
        for op in ("ensure", "restore"):
            result = self.invoke(op)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commands(), "")
    def test_api_ready_requires_active_tunnel(self):
        result=self.invoke("api-ready"); self.assertNotEqual(result.returncode,0)
        (self.run/"active").touch()
        result=self.invoke("api-ready"); self.assertEqual(result.returncode,0,result.stderr)
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
    def test_arch_packages_match_runtime_sources_and_compiled_build_identity(self):
        manifest=json.loads((ROOT/'dist/manifest.json').read_text())
        entries=json.loads((ROOT/'dist/release-entry.json').read_text())['keenetic']['arches']
        for slot in manifest['architectures']:
            archive=ROOT/'dist'/f"silent-vpn-keenetic-{manifest['version']}-{slot}.tar.gz"
            prefix=f"silent-vpn-keenetic-{manifest['version']}/"
            with tarfile.open(archive) as tf:
                metadata=json.load(tf.extractfile(prefix+'PACKAGE.json'))
                self.assertEqual(metadata,{'schema_version':1,'platform':'keenetic','arch':slot,'version':manifest['version'],'build_id':manifest['build_id']})
                self.assertEqual(tf.extractfile(prefix+'ARCH').read(),(slot+'\n').encode())
                self.assertEqual(tf.extractfile(prefix+'VERSION').read(),(ROOT/'VERSION').read_bytes())
                self.assertEqual(sum(m.size for m in tf.getmembers()),entries[slot]['unpacked_size'])
                for src in [ROOT/'install.sh',ROOT/'uninstall.sh',ROOT/'README.md',*sorted((ROOT/'files').glob('*'))]:
                    if src.is_file():self.assertEqual(tf.extractfile(prefix+src.relative_to(ROOT).as_posix()).read(),src.read_bytes(),str(src))
                for binary in ('silent-keenetic','spass'):
                    self.assertEqual(tf.extractfile(prefix+f'bin/{slot}/{binary}').read(),(ROOT/'build/bin'/slot/binary).read_bytes())
            result=subprocess.run(['go','version','-m',str(ROOT/'build/bin'/slot/'silent-keenetic')],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('GOOS=linux',result.stdout)
            self.assertIn('CGO_ENABLED=0',result.stdout)
            expected={'aarch64':'arm64','armv7':'arm','armv5':'arm','mipsel':'mipsle','mips':'mips','x86_64':'amd64','i386':'386'}[slot]
            self.assertIn('GOARCH='+expected,result.stdout)
            if slot in ('mips','mipsel'):self.assertIn('GOMIPS=softfloat',result.stdout)
            if slot in ('armv7','armv5'):self.assertIn('GOARM='+('7' if slot=='armv7' else '5'),result.stdout)
            # trimpath omits linker flags from Go build-info; check the linked ID itself.
            self.assertIn(manifest['build_id'].encode(),(ROOT/'build/bin'/slot/'silent-keenetic').read_bytes())

if __name__ == "__main__": unittest.main()
