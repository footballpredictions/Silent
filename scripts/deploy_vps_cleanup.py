"""Install the host cleaner; backend publication invokes this via deploy_stable."""
from __future__ import annotations
import hashlib
import io
from pathlib import Path
import shlex
from _deploy_common import connect

BIN='/usr/local/sbin/silent-vps-cleanup.sh'
SYNC='/usr/local/sbin/silent-vps-cleanup-tick.sh'
RUNNER='/usr/local/lib/silent-vpn/vps_cleanup.py'


def run(client,command,*,timeout=30):
    _,out,err=client.exec_command(command,timeout=timeout)
    output=out.read().decode('utf-8',errors='replace')
    error=err.read().decode('utf-8',errors='replace')
    if out.channel.recv_exit_status():raise RuntimeError('Host cleanup installation failed: '+(error or output)[-400:])
    if output.strip():print(output.strip())
    return output


def artifacts():
    return {
        RUNNER:Path(__file__).with_name('vps_cleanup_runner.py').read_text(encoding='utf-8'),
        BIN:f'#!/bin/sh\nexec /usr/bin/python3 {RUNNER} --disk-only --journal-mb "${{1:-200}}"\n',
        SYNC:f'#!/bin/sh\nexec /usr/bin/python3 {RUNNER}\n',
        '/etc/systemd/system/silent-vps-cleanup.service':
            '[Unit]\nDescription=Silent VPN safe host cleanup\nAfter=network-online.target docker.service\n\n'
            f'[Service]\nType=oneshot\nExecStart=/usr/bin/python3 {RUNNER}\nTimeoutStartSec=10min\nNice=10\nIOSchedulingClass=idle\n',
        '/etc/systemd/system/silent-vps-cleanup.timer':
            '[Unit]\nDescription=Silent VPN cleanup schedule poll\n\n[Timer]\nOnBootSec=2min\n'
            'OnUnitActiveSec=1min\nRandomizedDelaySec=5sec\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n',
    }


def install(client):
    run(client,'systemctl stop silent-vps-cleanup.timer 2>/dev/null || true',timeout=15)
    _,out,_=client.exec_command('systemctl is-active silent-vps-cleanup.service',timeout=10)
    if out.read().decode().strip() in ('active','activating','deactivating'):
        run(client,'systemctl start silent-vps-cleanup.timer',timeout=15)
        raise RuntimeError('Текущая очистка ещё выполняется; установка отложена')
    run(client,'install -d -m 755 /usr/local/lib/silent-vpn',timeout=15)
    files=artifacts()
    with client.open_sftp() as sftp:
        for target,content in files.items():
            data=content.encode('utf-8')
            if target.endswith('.sh'):assert data.startswith(b'#!/') and b'\r\n' not in data
            temp=target+'.installing'
            sftp.putfo(io.BytesIO(data),temp)
            sftp.chmod(temp,0o755 if target.endswith('.sh') else 0o644)
            sftp.posix_rename(temp,target)
    run(client,f'/usr/bin/python3 -m py_compile {RUNNER}',timeout=15)
    expected={name:hashlib.sha256(content.encode()).hexdigest() for name,content in files.items()}
    check='import hashlib,pathlib; expected='+repr(expected)+'; assert all(hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()==h for p,h in expected.items()); print("PASS cleanup host artifacts: "+str(len(expected)))'
    run(client,'python3 -c '+shlex.quote(check),timeout=15)
    run(client,'systemctl daemon-reload && systemctl reset-failed silent-vps-cleanup.service && systemctl enable --now silent-vps-cleanup.timer && systemctl start --no-block silent-vps-cleanup.service',timeout=25)
    return {'host_cleanup_files':expected}


def main():
    client=connect()
    try:install(client)
    finally:client.close()


if __name__=='__main__':main()
