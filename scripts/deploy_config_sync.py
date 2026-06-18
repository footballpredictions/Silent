"""Деплой ConfigSync API (sync-state)."""
from __future__ import annotations

import io

from _deploy_common import CONTAINER, REMOTE, connect, run, upload_file, upload_dir

FILES = [
    "app/services/config_sync_service.py",
    "app/api/vpn.py",
    "app/schemas/vpn.py",
    "app/api/admin.py",
]


def main() -> None:
    client = connect()
    sftp = client.open_sftp()
    for rel in FILES:
        upload_file(sftp, client, rel)
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
    sftp2.putfo(io.BytesIO(script.encode()), "/tmp/deploy_config_sync.sh")
    sftp2.close()
    run(client, "bash /tmp/deploy_config_sync.sh 2>&1", timeout=180)
    client.close()
    print("Done")


if __name__ == "__main__":
    main()
