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
    first = (primary or os.environ.get("DEPLOY_HOST") or "89.125.188.100").strip()
    tunnel = (os.environ.get("DEPLOY_TUNNEL_HOST") or "10.66.66.1").strip()
    out: list[str] = []
    for host in (first, tunnel):
        if host and host not in out:
            out.append(host)
    return out


DEFAULT_JUMP_HOSTS = ("87.58.213.193", "78.17.74.27")


def jump_hosts(raw: str | None = None) -> list[str]:
    """Публичные :22 сот для ProxyJump, когда Улей :22 с РФ режут.

    С соты 22/443 Улья обычно живы. :9100 сюда не подходит — это HTTP API, не SSH.
    Соту 3 (ИИ) в дефолт не берём.
    """
    load_env()
    text = (raw if raw is not None else os.environ.get("DEPLOY_JUMP_HOSTS", "")).strip()
    if not text:
        text = ",".join(DEFAULT_JUMP_HOSTS)
    out: list[str] = []
    for part in text.split(","):
        host = part.strip()
        if host and host not in out:
            out.append(host)
    return out


def jump_auth() -> tuple[str, str]:
    """SSH на соту-прыжок. DEPLOY_JUMP_PASS, иначе тот же DEPLOY_PASS что у Улья."""
    load_env()
    user = (os.environ.get("DEPLOY_JUMP_USER") or os.environ.get("DEPLOY_USER") or "root").strip()
    password = (os.environ.get("DEPLOY_JUMP_PASS") or os.environ.get("DEPLOY_PASS") or "").strip()
    return user, password


def ssh_config() -> tuple[str, str, str]:
    load_env()
    host = os.environ.get("DEPLOY_HOST", "89.125.188.100")
    user = os.environ.get("DEPLOY_USER", "root")
    password = os.environ.get("DEPLOY_PASS", "")
    if not password:
        raise SystemExit(
            "Задайте DEPLOY_PASS в Silent-Project/.env.deploy или backend/.env.deploy "
            "(см. backend/scripts/.env.deploy.example)"
        )
    return host, user, password


def _as_int_env(name: str, default: int) -> int:
    load_env()
    try:
        return max(1, int(str(os.environ.get(name, "")).strip()))
    except (TypeError, ValueError):
        return default


def connect(timeout: int = 30, attempts: int | None = None, pause: float | None = None):
    """SSH к Улью: оба хоста и несколько попыток.

    Блок 443/22 из РФ плавает по соединениям (2026-09-16): TCP встаёт, а баннер
    SSH теряется — paramiko отдаёт `SSHException`, а не таймаут. Без повторов и
    без этого исключения деплой падал на первой же неудаче.

    `attempts`/`pause` из аргументов сильнее env: скрипт, который просил 40 попыток,
    знает про свой сценарий больше, чем `DEPLOY_SSH_ATTEMPTS` в окружении.
    """
    import socket
    import time

    import paramiko

    hosts = ssh_hosts()
    _, user, password = ssh_config()
    # Плавающий блок иногда закрывает окно на минуты: DEPLOY_SSH_ATTEMPTS=60 ждёт его.
    attempts = int(attempts) if attempts is not None else _as_int_env("DEPLOY_SSH_ATTEMPTS", 4)
    pause = float(pause) if pause is not None else float(_as_int_env("DEPLOY_SSH_PAUSE_SEC", 6))
    last_err: BaseException | None = None
    for attempt in range(1, max(1, attempts) + 1):
        for host in hosts:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(
                    host,
                    username=user,
                    password=password,
                    timeout=timeout,
                    banner_timeout=max(12, timeout),
                    auth_timeout=max(12, timeout),
                )
                if host != hosts[0]:
                    print(f"SSH via tunnel host {host} (public hive TCP blocked)")
                if attempt > 1:
                    print(f"SSH поднялся с попытки {attempt}")
                return client
            except (TimeoutError, socket.timeout, OSError, paramiko.SSHException) as e:
                last_err = e
                print(f"SSH {host}:22 failed: {type(e).__name__}")
                try:
                    client.close()
                except Exception:
                    pass
        jumped = _connect_via_cell_jump(user, password, timeout)
        if jumped is not None:
            if attempt > 1:
                print(f"SSH поднялся с попытки {attempt}")
            return jumped
        if attempt < max(1, attempts):
            time.sleep(max(0.0, pause))
    if last_err:
        raise last_err
    raise SystemExit("SSH: no hosts")


def _connect_via_cell_jump(hive_user: str, hive_password: str, timeout: int):
    """ПК → сота:22 → Улей:22. С соты вход Улья не в ТСПУ РФ."""
    import paramiko

    jump_user, jump_password = jump_auth()
    if not jump_password:
        print("SSH jump skipped: no DEPLOY_JUMP_PASS / DEPLOY_PASS")
        return None
    hive_ip = ssh_hosts()[0]
    if hive_ip.startswith("10."):
        hive_ip = (os.environ.get("DEPLOY_HOST") or "89.125.188.100").strip()
    last: BaseException | None = None
    for jump_ip in jump_hosts():
        jump = paramiko.SSHClient()
        jump.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            jump.connect(
                jump_ip,
                username=jump_user,
                password=jump_password,
                timeout=timeout,
                banner_timeout=max(12, timeout),
                auth_timeout=max(12, timeout),
            )
            print(f"SSH jump login {jump_ip}:22 ok")
            transport = jump.get_transport()
            if transport is None:
                raise OSError("jump transport missing")
            channel = transport.open_channel(
                "direct-tcpip",
                (hive_ip, 22),
                ("127.0.0.1", 0),
            )
            hive = paramiko.SSHClient()
            hive.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            hive.connect(
                hive_ip,
                username=hive_user,
                password=hive_password,
                timeout=timeout,
                banner_timeout=max(12, timeout),
                auth_timeout=max(12, timeout),
                sock=channel,
            )
            hive._silent_jump = jump  # noqa: SLF001 — канал жив, пока жив hive-клиент
            print(f"SSH jump {jump_ip}:22 -> {hive_ip}:22")
            return hive
        except (TimeoutError, OSError, paramiko.SSHException) as e:
            last = e
            print(f"SSH jump {jump_ip}:22 -> {hive_ip}:22 failed: {type(e).__name__}")
            try:
                jump.close()
            except Exception:
                pass
    if last:
        print(f"SSH jump exhausted: {type(last).__name__}")
    return None


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
