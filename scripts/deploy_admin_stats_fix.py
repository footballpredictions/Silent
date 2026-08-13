"""Точечный деплой app/api/admin.py (фикс NameError в /stats)."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import BACKEND_ROOT, CONTAINER, REMOTE, load_env, run, ssh_config  # noqa: E402


def connect_long() -> paramiko.SSHClient:
    load_env()
    host, user, password = ssh_config()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        username=user,
        password=password,
        timeout=90,
        banner_timeout=90,
        auth_timeout=90,
    )
    return client


def main() -> None:
    rel = "app/api/admin.py"
    local = BACKEND_ROOT / rel
    if not local.is_file():
        raise SystemExit(f"missing {local}")
    print(f"deploy {rel} …")
    client = connect_long()
    sftp = client.open_sftp()
    remote = f"{REMOTE}/{rel}"
    sftp.putfo(io.BytesIO(local.read_bytes()), remote)
    print(f"uploaded {rel}")
    sftp.close()
    run(client, f"docker cp {REMOTE}/{rel} {CONTAINER}:/app/{rel}")
    run(client, f"docker compose -f {REMOTE}/docker-compose.yml restart api")
    run(client, "sleep 8; curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/health; echo")
    run(
        client,
        "docker exec backend-api-1 python -c \"from app.api import admin; print('admin import ok')\"",
    )
    client.close()
    print("OK")


if __name__ == "__main__":
    main()
