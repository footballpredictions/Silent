"""Selection cannot turn a narrow deployment into a whole-tree or outside-root upload."""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deploy_stable
from deploy_stable import _selected_python_paths


class SelectionTests(unittest.TestCase):
    def test_admin_ui_only_never_restarts_or_uploads_backend(self):
        client=MagicMock()
        with patch.object(sys,'argv',['deploy_stable.py','--admin-ui-only']), patch.object(deploy_stable,'connect',return_value=client), patch.object(deploy_stable,'_upload_admin_ui') as upload, patch.object(deploy_stable,'_verify_admin_ui') as verify, patch.object(deploy_stable,'_restart_and_verify') as restart, patch.object(deploy_stable,'_upload_py_tree') as tree:
            deploy_stable.main()
        upload.assert_called_once();verify.assert_called_once();restart.assert_not_called();tree.assert_not_called();client.close.assert_called_once()

    def test_selected_deploy_can_add_new_module_without_backing_up_missing_file(self):
        client = MagicMock()
        sftp = client.open_sftp.return_value.__enter__.return_value
        sftp.stat.side_effect = FileNotFoundError(2, 'not found')
        with patch.object(deploy_stable, '_preflight'), patch.object(deploy_stable, 'connect', return_value=client), \
             patch.object(deploy_stable, '_restart_and_verify'):
            deploy_stable._deploy_selected_python(['app/services/routing_policy.py'])
        sftp.file.assert_not_called()
        self.assertEqual(sftp.chmod.call_args.args[1], 0o644)
        self.assertEqual(sftp.posix_rename.call_args.args[1], deploy_stable.REMOTE + '/app/services/routing_policy.py')

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
