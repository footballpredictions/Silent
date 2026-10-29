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
    def test_connection_stays_open_through_final_source_verification(self):
        client = MagicMock()
        closed = False
        def close():
            nonlocal closed
            closed = True
        def verify(*args, **kwargs):
            self.assertFalse(closed, 'SSH closed before final source verification')
            return {}
        client.close.side_effect = close
        with patch.object(deploy_stable, '_preflight'), \
             patch.object(deploy_stable, 'connect', return_value=client), \
             patch.object(deploy_stable, 'run'), \
             patch.object(deploy_stable, '_verify_admin_ui'), \
             patch.object(deploy_stable, '_verify_registered_cell_allowlist'), \
             patch.object(deploy_stable, '_record_deploy_manifest'), \
             patch.object(deploy_stable, '_verify_deploy_sources', side_effect=verify):
            deploy_stable._deploy_selected_python(['ai/availability_classifier.py'])
        client.close.assert_called_once()

    def test_source_comparison_ignores_line_endings_and_final_empty_lines(self):
        original = b'def run():\n    return True\n'
        self.assertEqual(deploy_stable._source_hash(original), deploy_stable._source_hash(b'def run():\r\n    return True\r\n\r\n'))
        self.assertNotEqual(deploy_stable._source_hash(original), deploy_stable._source_hash(b'def run():\n    return False\n'))

    def test_source_drift_blocks_selected_deploy_before_upload(self):
        client = MagicMock()
        with patch.object(deploy_stable, '_preflight'), patch.object(deploy_stable, 'connect', return_value=client), \
             patch.object(deploy_stable, '_verify_deploy_sources', create=True, side_effect=SystemExit('source drift')), \
             patch.object(deploy_stable, '_restart_and_verify') as restart:
            with self.assertRaises(SystemExit):
                deploy_stable._deploy_selected_python(['app/services/routing_policy.py'])
        client.open_sftp.assert_not_called()
        restart.assert_not_called()

    def test_admin_ui_only_never_restarts_or_uploads_backend(self):
        client=MagicMock()
        with patch.object(sys,'argv',['deploy_stable.py','--admin-ui-only']), patch.object(deploy_stable,'connect',return_value=client), patch.object(deploy_stable,'_upload_admin_ui') as upload, patch.object(deploy_stable,'_verify_admin_ui') as verify, patch.object(deploy_stable,'_restart_and_verify') as restart, patch.object(deploy_stable,'_upload_py_tree') as tree, patch.object(deploy_stable,'_verify_deploy_sources',return_value={}) as sources, patch.object(deploy_stable,'_record_deploy_manifest'):
            deploy_stable.main()
        upload.assert_called_once();verify.assert_called_once();restart.assert_not_called();tree.assert_not_called();client.close.assert_called_once()
        self.assertEqual(sources.call_count, 2)

    def test_selected_deploy_can_add_new_module_without_backing_up_missing_file(self):
        client = MagicMock()
        sftp = client.open_sftp.return_value.__enter__.return_value
        sftp.stat.side_effect = FileNotFoundError(2, 'not found')
        with patch.object(deploy_stable, '_preflight'), patch.object(deploy_stable, 'connect', return_value=client), \
             patch.object(deploy_stable, '_restart_and_verify'), \
             patch.object(deploy_stable, '_verify_deploy_sources', return_value={}), \
             patch.object(deploy_stable, '_record_deploy_manifest'):
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

    def test_running_source_guards_mounts_duplicates_and_unselected_drift(self):
        import copy
        hashes = deploy_stable._expected_source_hashes()
        baseline = {'apis': [deploy_stable.CONTAINER], 'hashes': hashes,
                    'mounts': [{'Destination': '/app/' + sub, 'Source': deploy_stable.REMOTE + '/' + sub,
                                'RW': False} for sub in ('app', 'ai')]}
        with patch.object(deploy_stable, '_remote_release_snapshot', return_value=baseline):
            self.assertEqual(deploy_stable._verify_deploy_sources(None)['source_hashes'], hashes)
        stopped = copy.deepcopy(baseline)
        stopped.update(container_running=False, apis=[])
        with patch.object(deploy_stable, '_remote_release_snapshot', return_value=stopped):
            self.assertEqual(deploy_stable._verify_deploy_sources(None)['source_hashes'], hashes,
                             'a verified stopped API must remain repairable')
        drift = copy.deepcopy(baseline)
        drift['hashes']['app/services/hive_service.py'] = 'old-online-implementation'
        with patch.object(deploy_stable, '_remote_release_snapshot', return_value=drift):
            with self.assertRaisesRegex(SystemExit, 'hive_service.py'):
                deploy_stable._verify_deploy_sources(None)
            # An explicitly selected change is allowed before upload, but must
            # match after upload/restart.
            deploy_stable._verify_deploy_sources(None, pending_paths=['app/services/hive_service.py'])
            with self.assertRaises(SystemExit):
                deploy_stable._verify_deploy_sources(None, verify_paths=['app/services/hive_service.py'])
        for change in ('mount', 'duplicate'):
            bad = copy.deepcopy(baseline)
            if change == 'mount': bad['mounts'][0]['Source'] = '/obsolete/app'
            else: bad['apis'].append('obsolete-api')
            with patch.object(deploy_stable, '_remote_release_snapshot', return_value=bad), self.assertRaises(SystemExit):
                deploy_stable._verify_deploy_sources(None)


if __name__ == "__main__":
    unittest.main()
