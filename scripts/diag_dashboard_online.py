"""Read deployed source hashes and sample dashboard modes without exposing admin credentials."""
import hashlib
import json
import shlex
from pathlib import Path

from _deploy_common import BACKEND_ROOT, CONTAINER, REMOTE, connect

FILES = ('app/api/admin.py', 'app/services/hive_service.py', 'app/services/hive_slots.py', 'admin-ui/dist/index.html')
PROGRAM = r'''
import asyncio,json,time,urllib.request
from datetime import datetime,timedelta
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.admin_auth import AdminSession
from app.core.security import create_access_token
from app.config import settings

async def token():
    async with AsyncSessionLocal() as db:
        row=(await db.execute(select(AdminSession).where(AdminSession.revoked_at.is_(None),AdminSession.expires_at>datetime.utcnow()).order_by(AdminSession.created_at.desc()).limit(1))).scalar_one_or_none()
        return create_access_token('admin',expires_delta=timedelta(minutes=5),jti=row.token_jti) if row else None
t=asyncio.run(token())
with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/',headers={'Host':settings.ADMIN_PUBLIC_HOST}),timeout=10) as response:
    index=response.read().decode()
    print(json.dumps({'served_admin_index':response.status,'has_ui_assets':'/assets/index-' in index}),flush=True)
if not t:
    print('No active admin session; no sessions created')
else:
    for i in range(12):
        mode=('fast=1','compact=1','light=1')[i%3]
        request=urllib.request.Request('http://127.0.0.1:8000/api/admin/stats?'+mode,headers={'Authorization':'Bearer '+t,'Connection':'close','Host':settings.ADMIN_PUBLIC_HOST})
        started=time.monotonic()
        with urllib.request.urlopen(request,timeout=30) as response: data=json.load(response)
        print(json.dumps({'sample':i,'mode':mode,'online':data['users'].get('connected_devices'),'seconds':round(time.monotonic()-started,3)}),flush=True)
        time.sleep(0.3)
'''

if __name__ == '__main__':
    client = connect(attempts=2)
    try:
        with client.open_sftp() as sftp:
            for rel in FILES:
                with sftp.file(f'{REMOTE}/{rel}', 'rb') as source:
                    remote_hash = hashlib.sha256(source.read()).hexdigest()
                print(json.dumps({'file': rel, 'matches_local': remote_hash == hashlib.sha256((BACKEND_ROOT / rel).read_bytes()).hexdigest()}))
        _, stdout, _ = client.exec_command('systemctl show wdtt.service -p MainPID -p ActiveState')
        print(stdout.read().decode().strip(), flush=True)
        stdin, stdout, stderr = client.exec_command(f'docker exec -i {shlex.quote(CONTAINER)} python -',timeout=150)
        stdin.write(PROGRAM); stdin.flush(); stdin.channel.shutdown_write()
        for line in stdout: print(line.rstrip())
        status=stdout.channel.recv_exit_status()
        if status: print(stderr.read().decode(errors='replace')[-1000:])
        raise SystemExit(status)
    finally: client.close()
