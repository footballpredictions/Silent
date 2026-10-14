"""Architecture packages and installer resource guards through real tar/shell."""
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lib.silent_release import ARCHES, ELF_ABI, artifact_name, package_info, write_tarball
from test_path_runtime import SHELL


def fixture(root):
    root.mkdir(exist_ok=True)
    (root / "VERSION").write_text("1.0.169\n")
    for name in ("install.sh", "remote-install.sh"):
        (root / name).write_text("#!/bin/sh\necho installed\n")
    binaries = root / "files/usr/lib/silent-vpn/wdtt"
    binaries.mkdir(parents=True)
    for arch in ARCHES:
        elf_class, machine = ELF_ABI[arch]
        data = bytearray(64)
        data[:6] = b"\x7fELF" + bytes((elf_class, 1))
        data[18:20] = machine.to_bytes(2, "little")
        (binaries / f"wdtt-client.{arch}").write_bytes(data)


class ArchPackageTests(unittest.TestCase):
    def test_four_packages_contain_exactly_one_correct_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            fixture(base / "source")
            for arch in ARCHES:
                output = base / artifact_name("1.0.169", arch)
                write_tarball(base / "source", output, arch)
                with tarfile.open(output) as archive:
                    names = archive.getnames()
                    self.assertEqual([n for n in names if "/wdtt/" in n],
                                     [f"silent-vpn/files/usr/lib/silent-vpn/wdtt/wdtt-client.{arch}"])
                    self.assertEqual(archive.extractfile("silent-vpn/ARCH").read().strip(), arch.encode())
                info = package_info(output, arch, "1.0.169")
                self.assertEqual(info["size"], output.stat().st_size)
                self.assertGreater(info["unpacked_size"], 0)
                self.assertEqual(len(info["sha256"]), 64)

    def test_wrong_elf_cannot_be_packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root / "source")
            (root / "source/files/usr/lib/silent-vpn/wdtt/wdtt-client.arm").write_bytes(b"wrong")
            with self.assertRaises(ValueError):
                write_tarball(root / "source", root / "bad.tgz", "arm")

    def test_public_bootstrap_is_identical(self):
        mirror = ROOT.parent / "landing/openwrt-install.sh"
        if not mirror.is_file():
            self.skipTest("Landing checkout is optional in a standalone OpenWrt checkout")
        self.assertEqual((ROOT / "remote-install.sh").read_bytes(),
                         mirror.read_bytes())


@unittest.skipUnless(SHELL, "POSIX shell required")
class InstallerGuardTests(unittest.TestCase):
    def setUp(self):
        self.definitions = (ROOT / "remote-install.sh").read_text(encoding="utf-8").split('if [ "$(id -u')[0]

    def shell(self, code, cwd=None):
        return subprocess.run([SHELL, "-c", self.definitions + "\n" + code], cwd=cwd,
                              capture_output=True, text=True, encoding="utf-8", timeout=15)

    def test_flash_and_tmp_exhaustion_fail_before_download(self):
        for low_path in ("/tmp", "/usr"):
            result = self.shell('df() { if [ "$2" = "' + low_path + '" ]; then echo "dev 100 99 1 99% /"; else echo "dev 999999 0 999999 0% /"; fi; }\nsv_preflight 4000000 13000000')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Недостаточно места", result.stderr)

    def test_invalid_sizes_fail_closed(self):
        for sizes in ('0 1', '12 nope', '"" 1', '1 -1'):
            self.assertNotEqual(self.shell("sv_preflight " + sizes).returncode, 0)

    def test_flash_backup_is_included_in_free_space_guard(self):
        limits='df() { if [ "$2" = /usr ]; then echo "dev 999999 0 30000 0% /"; else echo "dev 999999 0 999999 0% /"; fi; }\n'
        self.assertEqual(self.shell(limits+'sv_preflight 4000000 13000000').returncode,0)
        result=self.shell(limits+'sv_preflight 4000000 13000000 0 13000000')
        self.assertNotEqual(result.returncode,0)
        self.assertIn("Недостаточно места",result.stderr)

    def test_arch_detection_rejects_armv6_big_endian_and_mips64(self):
        for machine, endian, expected in (("aarch64", "1", "aarch64"), ("armv7l", "1", "arm"),
                ("armv6l", "1", ""), ("mips", "1", "mipsel"), ("mips", "2", ""),
                ("mips64", "1", ""), ("x86_64", "1", "x86_64")):
            code = f'uname() {{ echo {machine}; }}\nod() {{ echo {endian}; }}\nsv_slot'
            result = self.shell(code)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), expected)

    def run_installer(self, base, arch, *, bad_hash=False, install_result=0, low_space=False):
        source = base / "source"
        fixture(source)
        (source / "install.sh").write_text('#!/bin/sh\nset -e\n[ ! -f "$(dirname "$0")/../package.tgz" ]\n[ "$(cat "$(dirname "$0")/ARCH")" = "$EXPECTED_ARCH" ]\ntouch "$TEST_TMP/installed"\nexit ' + str(install_result) + '\n')
        archive = base / "source.tgz"
        write_tarball(source, archive, arch)
        info = package_info(archive, arch, "1.0.169")
        script = (ROOT / "remote-install.sh").read_text(encoding="utf-8")
        entry = 'if [ "$(id -u' + script.split('if [ "$(id -u', 1)[1]
        entry = entry.replace('cd /tmp', 'cd "$TEST_TMP"').replace('/tmp/sv-install.', '$TEST_TMP/sv-install.').replace('exec rm -f /tmp/sv.sh', 'exec rm -f "$TEST_TMP/sv.sh"')
        (base / "sv.sh").write_text("downloaded installer")
        values = {"download_url": f"https://github.com/test/repo/releases/download/v1.0.169/only-{arch}.tar.gz",
                  "size": str(info["size"]), "unpacked_size": str(info["unpacked_size"]),
                  "sha256": "0" * 64 if bad_hash else info["sha256"]}
        overrides = '''
TEST_TMP="$(pwd)"
id() { echo 0; }
sv_slot() { echo "$EXPECTED_ARCH"; }
sv_pkg_update() { :; }
sv_pkg_add() { :; }
sv_json() { case "$1" in
''' + '\n'.join(f'{key}) echo "{value}" ;;' for key, value in values.items()) + '''
esac; }
df() { echo "dev 99999999 0 ''' + ('1' if low_space else '99999999') + ''' 0% /"; }
awk() { if [ "$2" = /proc/meminfo ]; then echo 99999999; else command awk "$@"; fi; }
sv_fetch() {
  echo "$1" >> "$TEST_TMP/downloads"
  case "$1" in
    *releases.json*) echo '{}' > "$2" ;;
    */only-"$EXPECTED_ARCH".tar.gz) cp "$TEST_TMP/source.tgz" "$2" ;;
    *) exit 97 ;;
  esac
}
'''
        result = subprocess.run([SHELL, "-c", self.definitions + overrides + entry], cwd=base,
            env={**os.environ, "TEST_TMP": base.as_posix(), "EXPECTED_ARCH": arch},
            capture_output=True, text=True, encoding="utf-8", timeout=20)
        return result, (base / "downloads").read_text().splitlines()

    def test_full_install_downloads_only_selected_arch_and_cleans_stage(self):
        for arch in ARCHES:
            with tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                result, downloads = self.run_installer(base, arch)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(len(downloads), 2)
                self.assertTrue(downloads[1].endswith(f"only-{arch}.tar.gz"))
                self.assertTrue((base / "installed").exists())
                self.assertEqual(list(base.glob("sv-install.*")), [])
                self.assertFalse((base / "sv.sh").exists())

    def test_failed_checksum_never_runs_installer_and_cleans_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            result, _ = self.run_installer(base, "aarch64", bad_hash=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((base / "installed").exists())
            self.assertEqual(list(base.glob("sv-install.*")), [])

    def test_insufficient_space_never_downloads_package(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            result, downloads = self.run_installer(base, "arm", low_space=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(downloads), 1)
            self.assertFalse((base / "installed").exists())
            self.assertEqual(list(base.glob("sv-install.*")), [])

    def test_failed_install_removes_unpacked_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            result, _ = self.run_installer(base, "x86_64", install_result=42)
            self.assertEqual(result.returncode, 42, result.stdout + result.stderr)
            self.assertEqual(list(base.glob("sv-install.*")), [])


if __name__ == "__main__":
    unittest.main()
