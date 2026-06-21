"""Диагностика VPN/Hive на production."""
from __future__ import annotations

import json
import sys

from _deploy_common import connect, run

client = connect()

checks = [
    (
        "config",
        'docker exec backend-api-1 python -c "from app.config import settings; '
        'print(settings.VPN_SERVER_IP); print(settings.HIVE_WORKER_ROUTING_ENABLED); '
        'print(len(settings.WG_SERVER_PUBLIC_KEY or \'\')); print(bool(settings.WDTT_MASTER_PASSWORD))"',
    ),
    ("wdtt", "systemctl is-active wdtt 2>/dev/null; systemctl is-active silent-wdtt 2>/dev/null; true"),
    ("wg_key_host", "cat /etc/wdtt/wg_public.key 2>/dev/null | head -c 20; echo"),
    (
        "hive_cells",
        "docker exec backend-api-1 python <<'PY'\n"
        "import asyncio\n"
        "from app.database import AsyncSessionLocal\n"
        "from app.services.hive_service import list_cells_with_stats\n"
        "from sqlalchemy import select, func\n"
        "from app.models import Device, HiveCell\n"
        "async def main():\n"
        "    async with AsyncSessionLocal() as db:\n"
        "        cells = await list_cells_with_stats(db)\n"
        "        for c in cells:\n"
        "            print(c['name'], c['status'], c['public_ip'], 'assigned', c['assigned_devices'], 'wg', (c.get('wg_public_key') or '')[:20])\n"
        "        q = await db.execute(select(Device.cell_id, func.count(Device.id)).where(Device.is_active==True).group_by(Device.cell_id))\n"
        "        print('devices_by_cell:', list(q.all()))\n"
        "asyncio.run(main())\n"
        "PY",
    ),
    (
        "bootstrap",
        'curl -sf -X POST http://127.0.0.1:8000/api/vpn/bootstrap-config '
        '-H "Content-Type: application/json" '
        '-d \'{"bootstrap_hash":"6EJ_t4eeAb-wbJynEOE-gpHCuaZIYqCRzDB1HZamyxY","device_fingerprint":"diag-py","device_type":"android"}\' '
        "| python3 -c \"import sys,json; d=json.load(sys.stdin); print('server_ip', d.get('server_ip')); print('port', d.get('server_port')); print('wg_srv', (d.get('server_public_key') or '')[:24]); print('wg_addr', d.get('wg_address'))\"",
    ),
]

for name, cmd in checks:
    print(f"\n=== {name} ===")
    try:
        out = run(client, cmd)
        print(out[:4000] if out else "(empty)")
    except Exception as e:
        print("ERR", e)

print("\nDone.")
