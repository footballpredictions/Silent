"""SSH/VPS для deploy PC-клиента (OTA .exe на backend VPS)."""
from __future__ import annotations

import os
from pathlib import Path

REMOTE_BACKEND = os.environ.get("DEPLOY_REMOTE", "/opt/silent-vpn/backend")
CONTAINER = os.environ.get("DEPLOY_CONTAINER", "backend-api-1")
PC_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def load_env() -> None:
    for path in (
        PC_ROOT / ".env.deploy",
        PC_ROOT.parent / ".env.deploy",
        Path.home() / ".silent-vpn-deploy.env",
    ):
        _load_dotenv(path)


def connect(timeout: int = 30):
    import paramiko

    load_env()
    password = os.environ.get("DEPLOY_PASS", "")
    if not password:
        raise SystemExit("Задайте DEPLOY_PASS в Silent/.env.deploy (см. backend/scripts/.env.deploy.example)")
    host = os.environ.get("DEPLOY_HOST", "132.243.234.162")
    user = os.environ.get("DEPLOY_USER", "root")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=timeout)
    return client
