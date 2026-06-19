"""Деплой OTA API на backend (без загрузки .exe/.apk — это pc/android scripts)."""
from __future__ import annotations

import io
import os
from pathlib import Path

from _deploy_common import BACKEND_ROOT, CONTAINER, REMOTE, connect, run, upload_file, upload_dir

FILES = [
    "app/main.py",
    "app/api/admin.py",
    "app/api/updates.py",
    "app/services/update_service.py",
    "app/services/build_agent_service.py",
    "ai/release_build_scheduler.py",
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
docker cp admin-ui/dist/. {CONTAINER}:/app/admin-ui/dist/
docker exec {CONTAINER} mkdir -p /app/update/pc /app/update/android
docker compose restart api
sleep 8
curl -s http://localhost:8000/api/health
echo
"""
    sftp2 = client.open_sftp()
    sftp2.putfo(io.BytesIO(script.encode()), "/tmp/deploy_update_backend.sh")
    sftp2.close()
    run(client, "bash /tmp/deploy_update_backend.sh 2>&1", timeout=180)
    client.close()
    print("Done")


if __name__ == "__main__":
    main()
