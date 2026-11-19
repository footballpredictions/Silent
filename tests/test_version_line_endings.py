"""Replay Windows VERSION metadata through the actual install/update gates."""
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

from test_path_runtime import ROOT, SHELL
from test_arch_packages import fixture
from lib.silent_release import write_tarball


@unittest.skipUnless(SHELL, 'POSIX shell required')
class VersionLineEndingTests(unittest.TestCase):
    def run_gate(self, version=b'1.0.172\r\n', updater=False, archive=None):
        source = (ROOT / 'remote-install.sh').read_text(encoding='utf-8')
        definitions = source.split('if [ "$(id -u')[0]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'stage').mkdir()
            package = base / 'stage/package.tgz'
            if archive:
                package.write_bytes(Path(archive).read_bytes())
            else:
                payload = {'VERSION': version, 'ARCH': b'aarch64\n', 'install.sh': b'#!/bin/sh\n',
                           'files/usr/lib/silent-vpn/wdtt/wdtt-client.aarch64': b'transport'}
                with tarfile.open(package, 'w:gz') as tar:
                    for name, content in payload.items():
                        entry = tarfile.TarInfo('silent-vpn/' + name)
                        entry.size = len(content)
                        tar.addfile(entry, io.BytesIO(content))
            code = definitions + '\nslot=aarch64\nSTAGE=stage\nVERSION=1.0.172\n'
            if updater:
                code += (ROOT / 'files/usr/lib/silent-vpn/update.sh').read_text(encoding='utf-8')
                code += '\nsv_update_archive stage/package.tgz stage aarch64 1.0.172 || exit 1\n'
                code += 'WORKDIR=stage/silent-vpn\n'
            else:
                code += source.split('sv_unpack "$STAGE/package.tgz" "$STAGE"', 1)[1].split('SILENT_OPENWRT_STAGE=', 1)[0]
                code = code.replace('\nrm -f "$STAGE/package.tgz"', '\nsv_unpack "$STAGE/package.tgz" "$STAGE"\nrm -f "$STAGE/package.tgz"', 1)
            code += '\ncp "$WORKDIR/VERSION" installed-version\n'
            (base / 'run.sh').write_text(code, encoding='utf-8', newline='\n')
            result = subprocess.run([SHELL, 'run.sh'], cwd=base, capture_output=True,
                                    text=True, encoding='utf-8', timeout=20)
            installed = (base / 'installed-version').read_bytes() if (base / 'installed-version').exists() else None
            return result, installed

    def test_bootstrap_accepts_crlf_and_installs_lf_version(self):
        result, installed = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(installed, b'1.0.172\n')

    def test_bootstrap_still_rejects_wrong_version(self):
        result, installed = self.run_gate(b'1.0.171\r\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(installed)

    def test_updater_accepts_crlf_and_installs_lf_version(self):
        result, installed = self.run_gate(updater=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(installed, b'1.0.172\n')

    def test_updater_still_rejects_wrong_version(self):
        result, installed = self.run_gate(b'1.0.171\r\n', updater=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(installed)

    def test_published_package_passes_bootstrap(self):
        archive = os.environ.get('SILENT_TEST_PUBLISHED_PACKAGE')
        if not archive:
            self.skipTest('Set SILENT_TEST_PUBLISHED_PACKAGE for the released archive replay')
        result, installed = self.run_gate(archive=archive)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(installed, b'1.0.172\n')


class PackageVersionTests(unittest.TestCase):
    def test_builder_normalizes_windows_version(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            fixture(base)
            (base / 'VERSION').write_bytes(b'1.0.172\r\n')
            package = write_tarball(base, base / 'package.tgz', 'aarch64')
            with tarfile.open(package) as tar:
                self.assertEqual(tar.extractfile('silent-vpn/VERSION').read(), b'1.0.172\n')
                windows_metadata = tar.extractfile('silent-vpn/PACKAGE.json').read()
            (base / 'VERSION').write_bytes(b'1.0.172\n')
            write_tarball(base, package, 'aarch64')
            with tarfile.open(package) as tar:
                self.assertEqual(tar.extractfile('silent-vpn/PACKAGE.json').read(), windows_metadata)


if __name__ == '__main__':
    unittest.main()
