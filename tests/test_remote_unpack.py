import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from test_path_runtime import SHELL

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(SHELL, 'POSIX shell required')
class RemoteUnpackTests(unittest.TestCase):
    def test_failed_run_cleans_its_private_stage(self):
        definitions = (ROOT / 'remote-install.sh').read_text(encoding='utf-8').split('if [ "$(id -u')[0]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'stage').mkdir()
            (base / 'stage/partial').write_text('partial unpack')
            result = subprocess.run([SHELL, '-c', definitions + '\nSTAGE=stage\ntrap sv_remote_cleanup EXIT\nfalse'],
                cwd=base, capture_output=True, text=True, encoding='utf-8', timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((base / 'stage').exists())

    def test_only_requested_binary_is_unpacked(self):
        definitions = (ROOT / 'remote-install.sh').read_text(encoding='utf-8').split('if [ "$(id -u')[0]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / 'source/silent-vpn/files/usr/lib/silent-vpn/wdtt'
            source.mkdir(parents=True)
            for arch in ('aarch64', 'arm', 'mipsel', 'x86_64'):
                (source / ('wdtt-client.' + arch)).write_text(arch)
            (base / 'source/silent-vpn/install.sh').write_text('#!/bin/sh\n')
            archive = base / 'package.tgz'
            with tarfile.open(archive, 'w:gz') as handle:
                handle.add(base / 'source/silent-vpn', arcname='silent-vpn')
            target = base / 'target'
            target.mkdir()
            result = subprocess.run([SHELL, '-c', definitions + '\nslot=aarch64\nsv_unpack "$TEST_ARCHIVE" "$TEST_TARGET"'],
                cwd=base, env={**os.environ, 'TEST_ARCHIVE': 'package.tgz', 'TEST_TARGET': 'target'},
                capture_output=True, text=True, encoding='utf-8', timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(sorted(p.name for p in (target / 'silent-vpn/files/usr/lib/silent-vpn/wdtt').iterdir()), ['wdtt-client.aarch64'])
            self.assertTrue((target / 'silent-vpn/install.sh').is_file())
