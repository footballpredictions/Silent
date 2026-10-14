"""Run the real installer in an isolated fake /opt. No router or host routes touched."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_network import ROOT, BASH, posix

class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.opt=self.base/'opt'; self.stage=self.base/'package'; self.stage.mkdir()
        self.dest=self.opt/'lib/silent-keenetic'; self.dest.mkdir(parents=True)
        self.config=self.opt/'etc/silent-keenetic'; self.config.mkdir(parents=True)
        self.service=self.opt/'etc/init.d/S99silent-keenetic'; self.service.parent.mkdir(parents=True)
        (self.opt/'etc/ndm/netfilter.d').mkdir(parents=True)
        self.bin=self.base/'stubs'; self.bin.mkdir()
        self.log=self.base/'commands'
        self.env=dict(os.environ,SVK_TEST_PATH=posix(self.bin)+':/usr/bin:/bin',MSYS_NO_PATHCONV='1',SVK_TEST_LOG=posix(self.log))
        self.secret=b'{"access_token":"kept","admin_password":"kept-local-password","reconnect":true}'
        (self.config/'config.json').write_bytes(self.secret)
        old='#!/bin/sh\nprintf "old-agent %s\\n" "$*" >> "$SVK_TEST_LOG"\n'
        (self.dest/'silent-keenetic').write_text(old,newline='\n')
        (self.dest/'spass').write_text('#!/bin/sh\n# old transport\n',newline='\n')
        self.service.write_text('#!/bin/sh\nprintf "service %s\\n" "$*" >> "$SVK_TEST_LOG"\n',newline='\n')
        files=self.stage/'files'; files.mkdir()
        for name in ('network.sh','guard.sh','100-silent-keenetic.sh','ru-direct.domains','ru-vpn.domains'):
            (files/name).write_text('# prepared runtime\n',newline='\n')
        (files/'S99silent-keenetic').write_text(self.service.read_text(),newline='\n')
        target=self.stage/'bin/aarch64'; target.mkdir(parents=True)
        (target/'silent-keenetic').write_text('#!/bin/sh\nprintf "new-agent %s\\n" "$*" >> "$SVK_TEST_LOG"\nif [ "$1" = --check ] && [ "${SVK_TEST_BAD_CHECK:-0}" = 1 ]; then exit 42; fi\n',newline='\n')
        (target/'spass').write_text('#!/bin/sh\n# new transport\n',newline='\n')
        (self.stage/'ARCH').write_text('aarch64\n')
        (self.stage/'VERSION').write_text('1.0.169\n')
        (self.stage/'PACKAGE.json').write_text('{}\n')
        (self.stage/'uninstall.sh').write_text('#!/bin/sh\n',newline='\n')
        (self.opt/'bin').mkdir()
        (self.opt/'bin/opkg').write_text('#!/bin/sh\nexit 0\n',newline='\n')
        (self.bin/'id').write_text('#!/bin/sh\necho 0\n',newline='\n')
        (self.bin/'uname').write_text('#!/bin/sh\ncase "$1" in -m) echo aarch64 ;; *) echo 5.15.0 ;; esac\n',newline='\n')
        (self.bin/'df').write_text('#!/bin/sh\necho "Filesystem 1024-blocks Used Available Capacity Mounted"\necho "test 1000000 0 ${SVK_TEST_FREE:-1000000} 0% /opt"\n',newline='\n')
        for file in [*self.bin.iterdir(),self.opt/'bin/opkg',self.dest/'silent-keenetic',self.service,target/'silent-keenetic',target/'spass']:
            file.chmod(0o755)
        text=(ROOT/'install.sh').read_text().replace('/opt',posix(self.opt))
        text=text.replace('export PATH='+posix(self.opt)+'/sbin:'+posix(self.opt)+'/bin:/usr/sbin:/usr/bin:/sbin:/bin','export PATH="$SVK_TEST_PATH"')
        self.installer=self.stage/'install.sh'; self.installer.write_text(text,newline='\n')
    def tearDown(self): self.tmp.cleanup()
    def invoke(self,*args,**extra):
        # Git Bash prepends its own commands at startup; set the stub PATH inside it.
        return subprocess.run([BASH,'-c','export PATH="$SVK_TEST_PATH"\nexec /bin/bash "$@"','installer',posix(self.installer),*args],env={**self.env,**extra},capture_output=True,text=True,encoding='utf-8')
    def commands(self): return self.log.read_text() if self.log.exists() else ''
    def test_manual_upgrade_preserves_account_password_and_reconnect(self):
        result=self.invoke('--no-deps');self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual((self.config/'config.json').read_bytes(),self.secret)
        self.assertEqual((self.dest/'spass').read_text(),'#!/bin/sh\n# new transport\n')
        self.assertIn('service stop',self.commands());self.assertIn('service start',self.commands())
        self.assertEqual((self.dest/'ARCH').read_text(),'aarch64\n')
    def test_failed_new_runtime_restores_old_files_and_restarts(self):
        old=(self.dest/'silent-keenetic').read_bytes()
        result=self.invoke('--no-deps',SVK_TEST_BAD_CHECK='1');self.assertNotEqual(result.returncode,0)
        self.assertEqual((self.dest/'silent-keenetic').read_bytes(),old)
        self.assertEqual((self.dest/'spass').read_text(),'#!/bin/sh\n# old transport\n')
        self.assertEqual((self.config/'config.json').read_bytes(),self.secret)
        self.assertIn('service start',self.commands())
    def test_ota_defers_restart_and_places_backup_with_payload(self):
        result=self.invoke('--ota');self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertNotIn('service start',self.commands());self.assertNotIn('service stop',self.commands())
        self.assertTrue((self.stage/'.rollback/runtime/spass').exists())
        self.assertFalse((self.opt/'var/backups').exists())
    def test_space_failure_does_not_stop_or_modify_old_client(self):
        old=(self.dest/'silent-keenetic').read_bytes()
        result=self.invoke('--no-deps',SVK_TEST_FREE='1');self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.commands(),'')
        self.assertEqual((self.dest/'silent-keenetic').read_bytes(),old)
        self.assertEqual((self.config/'config.json').read_bytes(),self.secret)

if __name__=='__main__': unittest.main()
