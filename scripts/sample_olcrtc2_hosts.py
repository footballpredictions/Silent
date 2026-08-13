"""Sample olcrtc2 host health on Cell1/2."""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

CREDS = r"""
import asyncio, json
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.hive_cell import HiveCell
from app.services.hive_service import resolve_ssh_password
async def main():
    async with AsyncSessionLocal() as db:
        out = {}
        for ip in ("78.17.74.27", "87.58.213.193"):
            r = (await db.execute(select(HiveCell).where(HiveCell.public_ip == ip))).scalar_one()
            out[ip] = resolve_ssh_password(r) or ""
        print(json.dumps(out))
asyncio.run(main())
"""

REMOTE_SH = r"""
python3 - <<'PY'
import subprocess
from pathlib import Path
print("CELL", open('/etc/hostname').read().strip())
envs = sorted(Path('/opt/silent-vpn/olcrtc2/env.d').glob('*.env'))
print('env_count', len(envs))
for p in envs[:3]:
    u = p.stem
    print('=====', u, '=====')
    st = subprocess.run(['systemctl','is-active',f'olcrtc2@{u}.service'], capture_output=True, text=True)
    print('state', (st.stdout or '').strip())
    for ln in p.read_text().splitlines():
        if ln.startswith('OLCRTC2_MODE=') or ln.startswith('OLCRTC2_ROOM='):
            print(ln[:80])
    j = subprocess.run(['journalctl','-u',f'olcrtc2@{u}.service','-n','10','--no-pager'], capture_output=True, text=True)
    import re
    print(re.sub(r'eyJ[A-Za-z0-9_\-.=]+','<JWT>', j.stdout or ''))
# summary
jall = subprocess.run(['journalctl','-u','olcrtc2@*','--since','2 hours ago','--no-pager'], capture_output=True, text=True)
text = jall.stdout or ''
print('--- summary 2h ---')
print('Link connected', text.count('Link connected'))
print('failed create', text.lower().count('failed to create'))
print('not found', text.lower().count('not found'))
print('ConferenceNotFound', text.count('ConferenceNotFound'))
ss = subprocess.run(['ss','-lntp'], capture_output=True, text=True)
for ln in (ss.stdout or '').splitlines():
    if ':5678' in ln or ':8808' in ln:
        print('LISTEN', ln)
PY
"""


def main() -> None:
    queen = connect()
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(CREDS.encode()), "/tmp/cell_pwds.py")
    sftp.close()
    run(queen, "docker cp /tmp/cell_pwds.py backend-api-1:/tmp/cell_pwds.py")
    raw = run(queen, "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/cell_pwds.py")
    queen.close()
    pwds = json.loads([ln for ln in raw.splitlines() if ln.strip().startswith("{")][-1])
    for ip, pwd in pwds.items():
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(ip, username="root", password=pwd, timeout=25)
        _, o, e = c.exec_command(REMOTE_SH, timeout=60)
        out = (o.read() + e.read()).decode("utf-8", "replace")
        print(f"\n######## {ip} ########")
        print(re.sub(r"eyJ[A-Za-z0-9_\-.=]+", "<JWT>", out))
        c.close()


if __name__ == "__main__":
    main()
