"""Diagnose specific olcrtc2 rooms + pool + cell journals."""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

ROOMS = sys.argv[1:] or ["svpn_3b36c7dc04fd", "26512770556451"]

INNER = r'''
import asyncio, json, sys
from collections import Counter
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models.olcrtc2_room import Olcrtc2Room, Olcrtc2Sticky
from app.services.olcrtc2_cell_units import probe_olcrtc2_unit, apply_olcrtc2_unit
from app.services.olcrtc2_assign import pool_stats, ensure_warm_pool
from app.services.olcrtc2_settings import load_olcrtc2_settings

want = sys.argv[1:]

async def main():
    async with AsyncSessionLocal() as db:
        settings = await load_olcrtc2_settings(db)
        print("SETTINGS", json.dumps({
            "enabled": settings.get("enabled"),
            "agent": settings.get("agent_enabled"),
            "warm": settings.get("warm_pool_per_dt"),
            "providers": settings.get("providers_enabled"),
            "cells": settings.get("cells"),
        }, ensure_ascii=False))
        print("POOL", json.dumps(await pool_stats(db), ensure_ascii=False))
        rows = (await db.execute(select(Olcrtc2Room))).scalars().all()
        print("COUNTS", json.dumps(dict(Counter(f"{r.provider}:{r.device_type}:{r.status}" for r in rows))))
        for w in want:
            found = (await db.execute(select(Olcrtc2Room).where(Olcrtc2Room.room_url.like(f"%{w}%")))).scalars().all()
            out = []
            for r in found:
                st = int((await db.execute(select(func.count()).select_from(Olcrtc2Sticky).where(Olcrtc2Sticky.room_id==r.id))).scalar() or 0)
                probe = await probe_olcrtc2_unit(db, r)
                out.append({
                    "unit": r.unit_name, "provider": r.provider, "dt": r.device_type,
                    "status": r.status, "room": r.room_url, "stickies": st,
                    "tok": (r.auth_token or "").startswith("eyJ"),
                    "tok_len": len(r.auth_token or ""),
                    "probe": probe,
                })
            print("LOOKUP", w, json.dumps(out, ensure_ascii=False, default=str))
        # sample recent android warm
        for prov in ("wbstream", "telemost"):
            warm = (await db.execute(
                select(Olcrtc2Room).where(
                    Olcrtc2Room.provider==prov,
                    Olcrtc2Room.device_type=="android",
                    Olcrtc2Room.status=="active",
                ).order_by(Olcrtc2Room.created_at.desc()).limit(5)
            )).scalars().all()
            sample=[]
            for r in warm:
                st=int((await db.execute(select(func.count()).select_from(Olcrtc2Sticky).where(Olcrtc2Sticky.room_id==r.id))).scalar() or 0)
                probe=await probe_olcrtc2_unit(db, r)
                sample.append({
                    "unit": r.unit_name, "room": (r.room_url or "")[:40], "stickies": st,
                    "tok": (r.auth_token or "").startswith("eyJ"),
                    "active": probe.get("active"), "state": probe.get("state") or probe.get("message"),
                })
            print("SAMPLE", prov, json.dumps(sample, ensure_ascii=False))

asyncio.run(main())
'''

CREDS = r'''
import asyncio, json
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.hive_cell import HiveCell
from app.services.hive_service import resolve_ssh_password
async def main():
    async with AsyncSessionLocal() as db:
        out={}
        for ip in ("78.17.74.27","87.58.213.193"):
            r=(await db.execute(select(HiveCell).where(HiveCell.public_ip==ip))).scalar_one()
            out[ip]=resolve_ssh_password(r) or ""
        print(json.dumps(out))
asyncio.run(main())
'''


def main() -> None:
    queen = connect()
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(INNER.encode()), "/tmp/diag_rooms.py")
    sftp.putfo(io.BytesIO(CREDS.encode()), "/tmp/cell_pwds.py")
    sftp.close()
    run(queen, "docker cp /tmp/diag_rooms.py backend-api-1:/tmp/diag_rooms.py")
    run(queen, "docker cp /tmp/cell_pwds.py backend-api-1:/tmp/cell_pwds.py")
    args = " ".join(ROOMS)
    print(run(queen, f"docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/diag_rooms.py {args}", timeout=180))
    pwd_raw = run(queen, "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/cell_pwds.py")
    queen.close()
    pwds = json.loads([ln for ln in pwd_raw.splitlines() if ln.strip().startswith("{")][-1])

    # Find units for wanted rooms from a quick SSH grep
    for ip, pwd in pwds.items():
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(ip, username="root", password=pwd, timeout=25)
        rooms_pat = "|".join(re.escape(r) for r in ROOMS)
        cmd = f"""
python3 - <<'PY'
import re, subprocess
from pathlib import Path
want = {ROOMS!r}
envd = Path('/opt/silent-vpn/olcrtc2/env.d')
print('CELL', open('/etc/hostname').read().strip(), 'envs', len(list(envd.glob('*.env'))))
for p in sorted(envd.glob('*.env')):
    t = p.read_text()
    if not any(w in t for w in want):
        continue
    u = p.stem
    print('====', u, '====')
    for ln in t.splitlines():
        if ln.startswith('OLCRTC2_'):
            if ln.startswith('OLCRTC2_AUTH_TOKEN='):
                print('OLCRTC2_AUTH_TOKEN=len', len(ln.split('=',1)[1]))
            else:
                print(ln[:100])
    st = subprocess.run(['systemctl','is-active', f'olcrtc2@{{u}}.service'], capture_output=True, text=True)
    print('state', (st.stdout or '').strip())
    j = subprocess.run(['journalctl','-u', f'olcrtc2@{{u}}.service', '-n', '20', '--no-pager'], capture_output=True, text=True)
    print(re.sub(r'eyJ[A-Za-z0-9_.=-]+', '<JWT>', j.stdout or ''))
# recent failures
jall = subprocess.run(['journalctl','-u','olcrtc2@*','--since','30 min ago','--no-pager'], capture_output=True, text=True)
text = jall.stdout or ''
print('--- 30m ---')
print('Link connected', text.count('Link connected'))
print('not found', text.lower().count('not found'))
print('failed to create', text.lower().count('failed to create'))
print('ConferenceNotFound', text.count('ConferenceNotFound'))
PY
""".replace("{u}", "{u}")
        # fix the broken f-string for systemctl
        cmd = f"""
python3 - <<'PY'
import re, subprocess
from pathlib import Path
want = {ROOMS!r}
envd = Path('/opt/silent-vpn/olcrtc2/env.d')
print('CELL', open('/etc/hostname').read().strip(), 'envs', len(list(envd.glob('*.env'))))
matched = 0
for p in sorted(envd.glob('*.env')):
    t = p.read_text()
    if not any(w in t for w in want):
        continue
    matched += 1
    u = p.stem
    print('====', u, '====')
    for ln in t.splitlines():
        if ln.startswith('OLCRTC2_'):
            if ln.startswith('OLCRTC2_AUTH_TOKEN='):
                print('OLCRTC2_AUTH_TOKEN=len', len(ln.split('=',1)[1]))
            else:
                print(ln[:120])
    st = subprocess.run(['systemctl','is-active', f'olcrtc2@'+u+'.service'], capture_output=True, text=True)
    print('state', (st.stdout or '').strip())
    j = subprocess.run(['journalctl','-u', f'olcrtc2@'+u+'.service', '-n', '25', '--no-pager'], capture_output=True, text=True)
    print(re.sub(r'eyJ[A-Za-z0-9_.=-]+', '<JWT>', j.stdout or ''))
print('matched_envs', matched)
jall = subprocess.run(['journalctl','-u','olcrtc2@*','--since','30 min ago','--no-pager'], capture_output=True, text=True)
text = jall.stdout or ''
print('--- 30m ---')
print('Link connected', text.count('Link connected'))
print('not found', text.lower().count('not found'))
print('failed to create', text.lower().count('failed to create'))
print('ConferenceNotFound', text.count('ConferenceNotFound'))
PY
"""
        _, o, e = c.exec_command(cmd, timeout=60)
        print(f"\n######## {ip} ########")
        print(re.sub(r"eyJ[A-Za-z0-9_\-.=]+", "<JWT>", (o.read() + e.read()).decode("utf-8", "replace")))
        c.close()


if __name__ == "__main__":
    main()
