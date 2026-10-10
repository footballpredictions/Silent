"""Production diagnostics must not write logs or expose older diagnostics."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from test_path_runtime import ROOT, SHELL


@unittest.skipUnless(SHELL, 'POSIX shell required')
class LoggingTests(unittest.TestCase):
    def test_agent_log_is_silent_and_does_not_write_files_or_syslog(self):
        common = (ROOT / 'files/usr/lib/silent-vpn/common.sh').read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory() as directory:
            logs = Path(directory) / 'logs'
            logs.mkdir()
            script = common.replace('/var/log', './logs') + '''
logger() { echo syslog-called; }
sv_log 'connection diagnostics'
'''
            result = subprocess.run([SHELL, '-c', script], cwd=directory, capture_output=True,
                                    text=True, encoding='utf-8', timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertEqual(result.stderr, '')
            self.assertEqual(list(logs.iterdir()), [])

    def test_old_log_endpoints_do_not_return_or_modify_saved_logs(self):
        cgi = (ROOT / 'files/www/cgi-bin/silent-api').read_text(encoding='utf-8')
        routes = cgi[cgi.index('case "$OP" in'):].replace('/var/log', './logs')
        with tempfile.TemporaryDirectory() as directory:
            logs = Path(directory) / 'logs'
            logs.mkdir()
            saved = logs / 'silent-vpn.log'
            saved.write_text('old private diagnostics', encoding='utf-8')
            for op in ('log', 'log-clear'):
                with self.subTest(op=op):
                    script = 'OP=' + op + '\nsv_status_dump() { echo private-snapshot; }\n' + routes
                    result = subprocess.run([SHELL, '-c', script], cwd=directory, capture_output=True,
                                            text=True, encoding='utf-8', timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('Лог отключён', result.stdout)
                    self.assertNotIn('private', result.stdout)
                    self.assertEqual(saved.read_text(encoding='utf-8'), 'old private diagnostics')
