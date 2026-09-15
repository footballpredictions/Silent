"""Общие настройки SSH/VPS для deploy-скриптов backend."""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

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


def ssh_hosts(primary: str | None = None) -> list[str]:
    """Сначала публичный Улей, при TCP-блоке из РФ — шлюз туннеля 10.66.66.1:22."""
    load_env()
    first = (primary or os.environ.get("DEPLOY_HOST") or "132.243.234.162").strip()
    tunnel = (os.environ.get("DEPLOY_TUNNEL_HOST") or "10.66.66.1").strip()
    out: list[str] = []
    for host in (first, tunnel):
        if host and host not in out:
            out.append(host)
    return out


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
    import socket

    import paramiko

    hosts = ssh_hosts()
    _, user, password = ssh_config()
    last_err: BaseException | None = None
    for host in hosts:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(host, username=user, password=password, timeout=timeout)
            if host != hosts[0]:
                print(f"SSH via tunnel host {host} (public hive TCP blocked)")
            return client
        except (TimeoutError, socket.timeout, OSError) as e:
            last_err = e
            print(f"SSH {host}:22 failed: {type(e).__name__}")
            try:
                client.close()
            except Exception:
                pass
    if last_err:
        raise last_err
    raise SystemExit("SSH: no hosts")


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
    # После volume ./app и ./ai docker cp пишет в хост (no-op, если файл уже залит).
    # DNAT — bash, не python3 на VPS (там нет рабочего _deploy_common.ssh).
    from fix_tunnel_dnat import FIX_SH

    files_sh = " ".join(f'"{f}"' for f in rel_paths)
    restart_cmd = f"docker compose restart api\nsleep {sleep_s}\n" if restart else ""
    tunnel_fix = "bash /tmp/fix_tunnel_dnat.sh\n" if restart else ""
    script = f"""#!/bin/bash
set -e
cd {REMOTE}
for f in {files_sh}; do
  docker cp "$f" {CONTAINER}:/app/"$f"
done
{restart_cmd}{tunnel_fix}curl -s http://localhost:8000/api/health
echo
"""
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(FIX_SH.encode()), "/tmp/fix_tunnel_dnat.sh")
    sftp.putfo(io.BytesIO(script.encode()), "/tmp/deploy_docker_cp.sh")
    sftp.close()
    run(client, "bash /tmp/deploy_docker_cp.sh 2>&1", timeout=180)
