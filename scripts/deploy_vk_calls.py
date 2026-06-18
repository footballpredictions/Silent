"""Деплой VK Calls auth + связанные сервисы + admin-ui."""
from __future__ import annotations

import io
from pathlib import Path

from _deploy_common import BACKEND_ROOT, CONTAINER, REMOTE, connect, run, upload_file, upload_dir

FILES = [
    "app/services/vk_calls_auth.py",
    "app/services/vk_agent_auth.py",
    "app/api/admin.py",
    "app/config.py",
    "app/services/subscription_service.py",
    "app/api/vk_auth.py",
    "app/services/vk_id_service.py",
    "ai/vk_manager.py",
    "ai/tunnel_monitor.py",
    "app/services/user_hash_service.py",
]


def main() -> None:
    dist = BACKEND_ROOT / "admin-ui" / "dist"
    if not dist.is_dir():
        raise SystemExit("cd admin-ui && npm run build")

    client = connect()
    sftp = client.open_sftp()
    for rel in FILES:
        upload_file(sftp, client, rel)
    upload_dir(sftp, client, dist, f"{REMOTE}/admin-ui/dist")
    sftp.close()

    files_sh = " ".join(f'"{f}"' for f in FILES)
    script = f"""#!/bin/bash
set -e
cd {REMOTE}
for f in {files_sh}; do docker cp "$f" {CONTAINER}:/app/"$f"; done
docker compose restart api
sleep 12
curl -s http://localhost:8000/api/health
echo
"""
    sftp2 = client.open_sftp()
    sftp2.putfo(io.BytesIO(script.encode()), "/tmp/deploy_vk_calls.sh")
    sftp2.close()
    run(client, "bash /tmp/deploy_vk_calls.sh 2>&1", timeout=180)
    client.close()
    print("Done")


if __name__ == "__main__":
    main()
