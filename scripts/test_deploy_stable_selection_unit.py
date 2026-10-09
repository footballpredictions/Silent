"""Selection cannot turn a narrow deployment into a whole-tree or outside-root upload."""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deploy_stable
from deploy_stable import _selected_python_paths


class SelectionTests(unittest.TestCase):
    def test_existing_payment_file_only_and_deduplicated(self):
        self.assertEqual(_selected_python_paths(["app/services/payment_service.py"] * 2), ["app/services/payment_service.py"])

    def test_reject_traversal_absolute_non_python_and_other_trees(self):
        for name in ("app/../scripts/deploy_stable.py", "/app/services/payment_service.py", "docker-compose.yml", "scripts/deploy_stable.py", "app/services", "app/missing.py"):
            with self.subTest(path=name), self.assertRaises(ValueError):
                _selected_python_paths([name])

    def test_ui_entrypoint_switches_last_and_keeps_old_assets(self):
        remote_root = deploy_stable.REMOTE + '/admin-ui/dist/'
        old_asset = remote_root + 'assets/old.js'
        remote_files = {old_asset: b'old-client', remote_root + 'index.html': b'old-index'}
        switches = []

        class Sftp:
            def put(self, local, remote):
                remote_files[remote] = Path(local).read_bytes()
            def chmod(self, remote, mode):
                assert mode == 0o644
            def posix_rename(self, source, target):
                if target.endswith('/index.html'):
                    assert remote_root + 'assets/new.js' in remote_files
                remote_files[target] = remote_files.pop(source)
                switches.append(target)

        with TemporaryDirectory() as folder, patch.object(deploy_stable, 'run') as run:
            dist = Path(folder)
            (dist/'assets').mkdir()
            (dist/'assets'/'new.js').write_bytes(b'new-client')
            (dist/'index.html').write_bytes(b'new-index')
            deploy_stable._upload_admin_ui(Sftp(), None, dist)
        self.assertTrue(switches[-1].endswith('/index.html'))
        self.assertEqual(remote_files[old_asset], b'old-client')
        self.assertEqual(remote_files[remote_root + 'index.html'], b'new-index')
        self.assertTrue(all('rm ' not in c.args[1] for c in run.call_args_list))


if __name__ == "__main__":
    unittest.main()
