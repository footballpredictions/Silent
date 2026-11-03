"""Installer emits executable host artifacts; no host/network operations."""
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import deploy_vps_cleanup as installer


class InstallerTests(unittest.TestCase):
    def test_tick_script_has_executable_shebang(self):
        files={}
        client=MagicMock()
        client.exec_command.return_value=(MagicMock(),MagicMock(),MagicMock())
        def putfo(stream,path):files[path]=stream.read()
        sftp=client.open_sftp.return_value.__enter__.return_value
        sftp.putfo.side_effect=putfo
        sftp.posix_rename.side_effect=lambda source,target:files.update({target:files.pop(source)})
        with patch.object(installer,'connect',return_value=client),patch.object(installer,'run'):
            installer.main()
        script=files[installer.SYNC]
        self.assertTrue(script.startswith(b'#!/'),repr(script.splitlines()[0]))
        self.assertNotIn(b'\r\n',script)


if __name__=='__main__':unittest.main()
