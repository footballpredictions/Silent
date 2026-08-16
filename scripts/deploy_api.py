"""Точечный деплой выбранных API-файлов + admin-ui/dist.

НЕ ИСПОЛЬЗОВАТЬ для прода-фиксов backend. Список FILES неполный:
файл не в списке = старый код в контейнере (вход 500, 2026-08-16: не попал device.py).
Канон: python scripts/deploy_stable.py (все app/**/*.py + ai/**/*.py).
"""
from __future__ import annotations

import io
from pathlib import Path

from _deploy_common import BACKEND_ROOT, CONTAINER, REMOTE, connect, run, upload_dir, upload_file
from fix_tunnel_dnat import FIX_SH

FILES = [
    "app/main.py",
    "app/config.py",
    "app/api/admin.py",
    "app/api/vk_auth.py",
    "app/services/vk_id_service.py",
    "app/api/users.py",
    "app/api/auth.py",
    "app/api/vpn.py",
    "app/schemas/vpn.py",
    "app/services/vpn_service.py",
    "app/models/user.py",
    "app/models/device.py",
    "app/services/subscription_service.py",
    "app/services/vpn_kick.py",
    "app/services/test_mode_settings.py",
    "app/services/registration_settings.py",
    "app/services/threat_filter_settings.py",
    "app/services/vps_cleanup_settings.py",
    "app/services/vk_agent_auth.py",
    "app/services/email_validation.py",
    "app/services/rate_limiter.py",
    "app/services/olcrtc_settings.py",
    "app/services/olcrtc_room_accounts.py",
    "app/services/olcrtc_rooms_db.py",
    "app/services/olcrtc_assign.py",
    "app/services/olcrtc_cell_push.py",
    "app/services/olcrtc2_settings.py",
    "app/services/olcrtc2_cell.py",
    "app/services/olcrtc2_assign.py",
    "app/services/olcrtc2_cell_units.py",
    "app/services/olcrtc2_create.py",
    "ai/olcrtc2_room_agent.py",
    "app/models/hive_cell.py",
    "app/schemas/hive.py",
    "app/api/hive.py",
    "app/services/hive_service.py",
    "app/services/hive_cell_sync.py",
    "app/services/hive_rebalance_loop.py",
    "app/services/hive_cell_maintenance_loop.py",
    "app/services/hive_capacity.py",
    "app/services/hive_cell_agent_auto.py",
    "app/services/hive_vpnbase_export.py",
    "app/services/hive_incidents.py",
    "app/models/olcrtc2_room.py",
    "app/models/__init__.py",
    "app/models/olcrtc_room.py",
    "app/models/vk_link_session.py",
    "app/middleware/admin_host_guard.py",
    "ai/vk_manager.py",
    "ai/olcrtc_room_agent.py",
    "ai/olcrtc_room_provision.py",
    "ai/olcrtc_room_liveness.py",
    "ai/olcrtc_host_provision_client.py",
    "app/services/agent_leader.py",
    "app/services/olcrtc_pool_loop.py",
    "static/vk-agent-oauth.html",
]

client = connect()
sftp = client.open_sftp()
for rel in FILES:
    upload_file(sftp, client, rel)

dist = BACKEND_ROOT / "admin-ui" / "dist"
if not dist.is_dir():
    raise SystemExit("cd admin-ui && npm run build")
upload_dir(sftp, client, dist, f"{REMOTE}/admin-ui/dist")
sftp.close()

files_sh = " ".join(f'"{f}"' for f in FILES)
script = f"""#!/bin/bash
set -e
cd {REMOTE}
docker compose up -d api
sleep 4
for f in {files_sh}; do docker cp "$f" {CONTAINER}:/app/$f; done
docker exec {CONTAINER} pip install -q redis disposable-email-domains 2>/dev/null || true
docker compose restart api
sleep 12
curl -s http://localhost:8000/api/health
echo
"""
sftp2 = client.open_sftp()
sftp2.putfo(io.BytesIO(FIX_SH.encode()), "/tmp/fix_tunnel_dnat.sh")
sftp2.putfo(io.BytesIO(script.encode()), "/tmp/deploy_api.sh")
sftp2.close()
run(client, "bash /tmp/deploy_api.sh 2>&1 && bash /tmp/fix_tunnel_dnat.sh 2>&1", timeout=120)
client.close()
print("Done")
