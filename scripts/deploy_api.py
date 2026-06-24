"""Деплой выбранных API-файлов + admin-ui/dist."""
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
    "app/services/vpn_service.py",
    "app/models/user.py",
    "app/services/subscription_service.py",
    "app/services/test_mode_settings.py",
    "app/services/vk_agent_auth.py",
    "app/models/__init__.py",
    "app/models/vk_link_session.py",
    "ai/vk_manager.py",
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
