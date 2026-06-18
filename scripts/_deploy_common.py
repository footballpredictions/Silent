"""Общие настройки SSH/VPS для deploy-скриптов backend."""
from __future__ import annotations

import io
import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REMOTE = os.environ.get("DEPLOY_REMOTE", "/opt/silent-vpn/backend")
CONTAINER = os.environ.get("DEPLOY_CONTAINER", "backend-api-1")


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
    candidates = [
        BACKEND_ROOT / ".env.deploy",
        BACKEND_ROOT.parent / ".env.deploy",
        Path.home() / ".silent-vpn-deploy.env",
    ]
    for path in candidates:
        _load_dotenv(path)


def ssh_config() -> tuple[str, str, str]:
    load_env()
    host = os.environ.get("DEPLOY_HOST", "132.243.234.162")
    user = os.environ.get("DEPLOY_USER", "root")
    password = os.environ.get("DEPLOY_PASS", "")
    if not password:
        raise SystemExit(
            "Задайте DEPLOY_PASS в Silent-Project/.env.deploy или backend/.env.deploy "
            "(см. backend/scripts/.env.deploy.example)"
        )
    return host, user, password


def connect(timeout: int = 30):
    import paramiko

    host, user, password = ssh_config()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=timeout)
    return client


def run(client, cmd: str, timeout: int = 300) -> str:
    print(f"\n$ {cmd}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout, get_pty=True)
    out = ""
    while True:
        line = stdout.readline()
        if not line:
            break
        print(line, end="")
        out += line
    err = stderr.read().decode()
    if err:
        print("[stderr]", err)
    return out


def upload_file(sftp, client, rel: str) -> None:
    local = BACKEND_ROOT / rel.replace("/", os.sep)
    if not local.is_file():
        raise FileNotFoundError(local)
    remote = f"{REMOTE}/{rel}"
    parent = os.path.dirname(remote).replace("\\", "/")
    if parent:
        client.exec_command(f"mkdir -p {parent}")
    sftp.put(str(local), remote)
    print(f"uploaded {rel}")


def upload_dir(sftp, client, local_dir: Path, remote_dir: str) -> None:
    for root, _, names in os.walk(local_dir):
        for name in names:
            lp = Path(root) / name
            rel = lp.relative_to(local_dir).as_posix()
            rp = f"{remote_dir}/{rel}"
            client.exec_command(f"mkdir -p {os.path.dirname(rp)}")
            sftp.put(str(lp), rp)
            print(f"uploaded {remote_dir}/{rel}")


def docker_cp_and_restart(client, rel_paths: list[str], restart: bool = True, sleep_s: int = 12) -> None:
  files_sh = " ".join(f'"{f}"' for f in rel_paths)
  restart_cmd = f"docker compose restart api\nsleep {sleep_s}\n" if restart else ""
  script = f"""#!/bin/bash
set -e
cd {REMOTE}
for f in {files_sh}; do
  docker cp "$f" {CONTAINER}:/app/"$f"
done
{restart_cmd}curl -s http://localhost:8000/api/health
echo
"""
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(script.encode()), "/tmp/deploy_docker_cp.sh")
    sftp.close()
    run(client, "bash /tmp/deploy_docker_cp.sh 2>&1", timeout=180)
