"""Автоматическая настройка VPN-соты по SSH (IP + root-пароль)."""
from __future__ import annotations

import io
import ipaddress
import json
import logging
import secrets
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
CELL_AGENT_MAIN = BACKEND_ROOT / "cell-agent" / "main.py"
MIN_WDTT_BYTES = 500_000
MIN_CELL_AGENT_BYTES = 500


def _read_file_from_docker_host(host_path: str, inner_path: str = "/f") -> bytes | None:
    """Читает файл с хоста Улья через docker.sock (из API-контейнера)."""
    try:
        r = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", f"{host_path}:{inner_path}:ro",
                "alpine:3.19",
                "cat", inner_path,
            ],
            capture_output=True,
            timeout=60,
        )
        if r.returncode == 0 and len(r.stdout) >= MIN_CELL_AGENT_BYTES:
            return r.stdout
    except Exception as e:
        logger.debug("docker read %s: %s", host_path, e)
    return None


def _load_cell_agent_py() -> str:
    """Исходник cell-agent для заливки на соту (контейнер или хост Улья)."""
    for p in (CELL_AGENT_MAIN, Path("/app/cell-agent/main.py")):
        if p.is_file():
            return p.read_text(encoding="utf-8")
    for host_path in (
        "/opt/silent-vpn/backend/cell-agent/main.py",
        f"{BACKEND_ROOT}/cell-agent/main.py",
    ):
        data = _read_file_from_docker_host(host_path)
        if data:
            logger.info("Hive cell-agent: host %s (%s bytes)", host_path, len(data))
            return data.decode("utf-8")
    raise RuntimeError(
        "cell-agent/main.py не найден на Улье. "
        "Запустите с ПК: cd backend && python scripts/deploy_stable.py"
    )


def _validate_wdtt_blob(data: bytes, source: str) -> bytes:
    if len(data) < MIN_WDTT_BYTES:
        raise RuntimeError(f"wdtt-server из {source} слишком мал ({len(data)} байт)")
    return data


def _read_wdtt_from_docker_host(host_path: str, inner_path: str) -> bytes | None:
    """Читает бинарник с хоста Улья через docker.sock (API-контейнер)."""
    try:
        r = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", f"{host_path}:{inner_path}:ro",
                "alpine:3.19",
                "cat", inner_path,
            ],
            capture_output=True,
            timeout=90,
        )
        if r.returncode == 0 and len(r.stdout) >= MIN_WDTT_BYTES:
            return r.stdout
    except Exception as e:
        logger.debug("docker read %s: %s", host_path, e)
    return None


def _load_wdtt_binary() -> bytes:
    """Бинарник wdtt-server с Улья — GitHub release больше не используем (404)."""
    custom = (settings.HIVE_WDTT_BINARY_PATH or "").strip()
    if custom:
        p = Path(custom)
        if p.is_file():
            return _validate_wdtt_blob(p.read_bytes(), str(p))

    local_candidates = [
        Path("/app/wdtt/wdtt-server"),
        BACKEND_ROOT / "wdtt" / "wdtt-server",
        Path("/usr/local/bin/wdtt-server"),
    ]
    for p in local_candidates:
        if p.is_file():
            data = p.read_bytes()
            if len(data) >= MIN_WDTT_BYTES:
                logger.info("Hive wdtt: local %s (%s bytes)", p, len(data))
                return data

    docker_candidates = [
        ("/usr/local/bin/wdtt-server", "/wdtt-server"),
        ("/opt/silent-vpn/backend/wdtt/wdtt-server", "/wdtt-server"),
        ("/opt/silent-vpn/backend/wdtt", "/wdtt"),
    ]
    for host_path, inner in docker_candidates:
        data = _read_wdtt_from_docker_host(host_path, inner)
        if data:
            logger.info("Hive wdtt: docker host %s (%s bytes)", host_path, len(data))
            return _validate_wdtt_blob(data, host_path)

    # shell glob via docker for wdtt dir
    try:
        r = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", "/opt/silent-vpn/backend/wdtt:/wdtt:ro",
                "alpine:3.19",
                "sh", "-c", "cat /wdtt/wdtt-server 2>/dev/null || ls -la /wdtt/",
            ],
            capture_output=True,
            timeout=60,
        )
        if r.returncode == 0 and len(r.stdout) >= MIN_WDTT_BYTES:
            return _validate_wdtt_blob(r.stdout, "/opt/silent-vpn/backend/wdtt")
    except Exception as e:
        logger.debug("docker wdtt dir: %s", e)

    raise RuntimeError(
        "wdtt-server не найден на Улье. Проверьте /usr/local/bin/wdtt-server "
        "(systemctl status wdtt) или /opt/silent-vpn/backend/wdtt/wdtt-server"
    )


def _validate_host(host: str) -> str:
    host = host.strip()
    if not host:
        raise ValueError("Укажите IP или хост соты")
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            raise ValueError("Приватный IP соты не поддерживается — нужен публичный адрес VPS")
    except ValueError as e:
        if "does not appear to be an IPv4 or IPv6 address" not in str(e):
            raise
    return host


def _ssh_connect(host: str, password: str, *, username: str | None = None, timeout: int | None = None):
    import paramiko

    user = (username or settings.HIVE_PROVISION_SSH_USER or "root").strip()
    t = timeout or settings.HIVE_PROVISION_SSH_TIMEOUT_SEC
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            host,
            port=22,
            username=user,
            password=password,
            timeout=t,
            banner_timeout=t,
            auth_timeout=t,
            allow_agent=False,
            look_for_keys=False,
        )
    except paramiko.AuthenticationException as e:
        raise ValueError("SSH: неверный логин или пароль root") from e
    except paramiko.SSHException as e:
        raise ValueError(f"SSH: {e}") from e
    except OSError as e:
        raise ValueError(
            f"SSH: не удалось подключиться к {host}:22 — проверьте IP, firewall и что sshd запущен"
        ) from e
    return client


def _run(client, cmd: str, timeout: int = 600) -> tuple[int, str, str]:
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout, get_pty=True)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def _ensure_remote_dir(client, remote_dir: str) -> None:
    _run(client, f"mkdir -p {shlex.quote(remote_dir)}", timeout=30)


def _read_wg_public_key(client, *, wait_sec: int = 40) -> str:
    deadline = time.monotonic() + wait_sec
    while time.monotonic() < deadline:
        for cmd in (
            "wg show all public-key 2>/dev/null | head -1",
            "wg show wdtt0 public-key 2>/dev/null",
            "cat /etc/wdtt/wg_public.key 2>/dev/null",
            "cat /etc/wdtt/server_public.key 2>/dev/null",
            "grep -rEl '[A-Za-z0-9+/]{40,}=' /etc/wdtt 2>/dev/null | head -1 | xargs cat 2>/dev/null",
        ):
            _, out, _ = _run(client, cmd, timeout=15)
            key = (out or "").strip().splitlines()[0].strip() if out.strip() else ""
            if len(key) >= 40 and " " not in key:
                return key
        time.sleep(2)
    _, wdtt_log, _ = _run(client, "journalctl -u wdtt -n 30 --no-pager 2>/dev/null", timeout=20)
    raise RuntimeError(
        "wdtt запущен, но WG public key не появился за "
        f"{wait_sec}с. Лог wdtt:\n{(wdtt_log or '')[-600:]}"
    )


def provision_cell_via_ssh(
    host: str,
    ssh_password: str,
    *,
    cell_agent_secret: str,
    hive_public_ip: str,
    hive_api_base: str,
    wdtt_master_password: str,
    cell_id: str,
) -> dict[str, Any]:
    host = _validate_host(host)
    if not ssh_password or len(ssh_password) < 4:
        raise ValueError("Укажите SSH-пароль root на соте")
    if not wdtt_master_password:
        raise ValueError("WDTT_MASTER_PASSWORD не задан на Улье — задайте в .env")
    if not hive_public_ip:
        raise ValueError("VPN_SERVER_IP не задан на Улье")

    agent_port = settings.HIVE_CELL_AGENT_PORT
    hive_ip = hive_public_ip.strip()
    hive_api = hive_api_base.rstrip("/")

    wdtt_binary = _load_wdtt_binary()
    logger.info("Hive provision: wdtt binary %s bytes → cell %s", len(wdtt_binary), host)
    agent_py = _load_cell_agent_py()
    passwords_json = json.dumps({"master": wdtt_master_password, "users": []})
    hive_meta = json.dumps({"hive_api_url": hive_api, "hive_cell_id": cell_id})

    remote_script = f"""#!/bin/bash
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
echo "[hive] apt..."
apt-get update -qq || true
apt-get install -y -qq -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" \\
    curl ca-certificates wireguard wireguard-tools python3 python3-venv ufw iptables 2>&1 || \\
    apt-get install -y -qq curl ca-certificates wireguard-tools python3 python3-venv ufw iptables 2>&1 || true

echo "[hive] wdtt binary (from Улей)..."
if [ ! -f /tmp/hive_wdtt_server_bin ] || [ $(stat -c%s /tmp/hive_wdtt_server_bin 2>/dev/null || echo 0) -lt {MIN_WDTT_BYTES} ]; then
  echo "FAIL: бинарник wdtt не передан с Улья"
  exit 1
fi
install -m 755 /tmp/hive_wdtt_server_bin /usr/local/bin/wdtt-server
mkdir -p /etc/wdtt /opt/silent-vpn/cell-agent
install -m 600 /tmp/hive_wdtt_passwords.json /etc/wdtt/passwords.json
install -m 600 /tmp/hive_meta.json /etc/wdtt/hive.json
WDTT_PASS=$(python3 -c "import json; print(json.load(open('/etc/wdtt/passwords.json'))['master'])")

cat > /etc/systemd/system/wdtt.service << SVCEOF
[Unit]
Description=WDTT VPN Server (Hive Cell)
After=network.target

[Service]
Type=simple
ExecStartPre=-/bin/sh -c "ip link show wdtt0 >/dev/null 2>&1 && ip link del wdtt0 2>/dev/null || true"
ExecStart=/usr/local/bin/wdtt-server -listen 0.0.0.0:56000 -wg-port 56001 -config-dir /etc/wdtt -password $WDTT_PASS
Restart=always
RestartSec=3
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
SVCEOF

echo "[hive] net..."
sysctl -w net.ipv4.ip_forward=1 || true
ETH=$(ip route get 8.8.8.8 2>/dev/null | awk '{{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1); exit}}')
if [ -n "$ETH" ]; then
  iptables -t nat -C POSTROUTING -s 10.66.66.0/24 -o "$ETH" -j MASQUERADE 2>/dev/null || \\
      iptables -t nat -A POSTROUTING -s 10.66.66.0/24 -o "$ETH" -j MASQUERADE
  iptables -t nat -C PREROUTING -d 10.66.66.1 -p tcp --dport 8000 -j DNAT --to-destination {hive_ip}:8000 2>/dev/null || \\
      iptables -t nat -A PREROUTING -d 10.66.66.1 -p tcp --dport 8000 -j DNAT --to-destination {hive_ip}:8000
  iptables -t nat -C POSTROUTING -d {hive_ip} -p tcp --dport 8000 -j MASQUERADE 2>/dev/null || \\
      iptables -t nat -A POSTROUTING -d {hive_ip} -p tcp --dport 8000 -j MASQUERADE
fi

ufw allow 22/tcp 2>/dev/null || true
ufw allow 56000/udp 2>/dev/null || true
ufw allow 56001/udp 2>/dev/null || true
ufw allow {agent_port}/tcp 2>/dev/null || true

systemctl daemon-reload
systemctl enable wdtt
systemctl restart wdtt

echo "[hive] wait wg key..."
WG_PUB=""
for i in $(seq 1 25); do
  WG_PUB=$(wg show all public-key 2>/dev/null | head -1)
  if [ -n "$WG_PUB" ]; then break; fi
  sleep 2
done
if [ -z "$WG_PUB" ]; then
  echo "FAIL: wg public key timeout"
  journalctl -u wdtt -n 20 --no-pager 2>/dev/null || true
  exit 1
fi
echo "$WG_PUB" > /etc/wdtt/wg_public.key
chmod 600 /etc/wdtt/wg_public.key

echo "[hive] cell-agent..."
python3 -m venv /opt/silent-vpn/cell-agent/venv
/opt/silent-vpn/cell-agent/venv/bin/pip install -q fastapi 'uvicorn[standard]' psutil

AGENT_SECRET=$(cat /tmp/hive_agent_secret.txt)
cat > /etc/systemd/system/silent-cell-agent.service << AGEOF
[Unit]
Description=Silent VPN Cell Agent
After=network.target wdtt.service

[Service]
Type=simple
WorkingDirectory=/opt/silent-vpn/cell-agent
Environment=CELL_AGENT_SECRET=$AGENT_SECRET
Environment=CELL_PUBLIC_IP={host}
Environment=WG_SERVER_PUBLIC_KEY=$WG_PUB
Environment=HIVE_API_URL={hive_api}
Environment=CELL_LINK_CAPACITY_MBPS={int(settings.HIVE_CELL_DEFAULT_LINK_CAPACITY_MBPS)}
Environment=TUNNEL_API_URL=http://10.66.66.1:8000
ExecStart=/opt/silent-vpn/cell-agent/venv/bin/uvicorn main:app --host 0.0.0.0 --port {agent_port}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
AGEOF

systemctl daemon-reload
systemctl enable silent-cell-agent
systemctl restart silent-cell-agent
sleep 2
rm -f /tmp/hive_wdtt_passwords.json /tmp/hive_agent_secret.txt /tmp/hive_meta.json /tmp/hive_wdtt_server_bin
curl -sf http://127.0.0.1:{agent_port}/health && echo " agent_ok"
systemctl is-active wdtt && echo " wdtt_ok"
echo "WG_PUB=$WG_PUB"
"""

    client = _ssh_connect(host, ssh_password)
    try:
        _ensure_remote_dir(client, "/opt/silent-vpn/cell-agent")
        sftp = client.open_sftp()
        sftp.putfo(io.BytesIO(agent_py.encode()), "/opt/silent-vpn/cell-agent/main.py")
        sftp.putfo(io.BytesIO(wdtt_binary), "/tmp/hive_wdtt_server_bin")
        sftp.putfo(io.BytesIO(passwords_json.encode()), "/tmp/hive_wdtt_passwords.json")
        sftp.putfo(io.BytesIO(hive_meta.encode()), "/tmp/hive_meta.json")
        sftp.putfo(io.BytesIO(cell_agent_secret.encode()), "/tmp/hive_agent_secret.txt")
        sftp.putfo(io.BytesIO(remote_script.encode()), "/tmp/hive_provision.sh")
        sftp.close()

        code, out, err = _run(client, "bash /tmp/hive_provision.sh 2>&1", timeout=600)
        log_tail = (out + err)[-4000:]
        logger.info("Hive provision %s: exit=%s\n%s", host, code, log_tail)
        if code != 0:
            raise RuntimeError(f"Настройка соты не завершилась:\n{log_tail[-1200:]}")

        wg_key = ""
        for line in out.splitlines():
            if line.startswith("WG_PUB="):
                wg_key = line.split("=", 1)[1].strip()
                break
        if len(wg_key) < 40:
            wg_key = _read_wg_public_key(client, wait_sec=10)

        return {
            "public_ip": host,
            "wg_public_key": wg_key,
            "wdtt_port": settings.VPN_SERVER_PORT,
            "wg_port": settings.WG_PORT,
            "tunnel_api_url": "http://10.66.66.1:8000",
            "api_url": f"http://{host}:{agent_port}",
            "provision_log_tail": log_tail[-1200:],
        }
    finally:
        client.close()


def upgrade_cell_agent_via_ssh(
    host: str,
    ssh_password: str,
    *,
    link_capacity_mbps: float | None = None,
) -> None:
    """Обновить cell-agent на соте (мониторинг CPU/RAM/канал) без полной переустановки."""
    host = _validate_host(host)
    link_mbps = int(link_capacity_mbps or settings.HIVE_CELL_DEFAULT_LINK_CAPACITY_MBPS)
    agent_py = _load_cell_agent_py()
    agent_port = settings.HIVE_CELL_AGENT_PORT

    client = _ssh_connect(host, ssh_password)
    try:
        _ensure_remote_dir(client, "/opt/silent-vpn/cell-agent")
        sftp = client.open_sftp()
        sftp.putfo(io.BytesIO(agent_py.encode("utf-8")), "/opt/silent-vpn/cell-agent/main.py")
        sftp.close()
        code, out, err = _run(
            client,
            f"LINK={link_mbps}; "
            f"if grep -q CELL_LINK_CAPACITY_MBPS /etc/systemd/system/silent-cell-agent.service 2>/dev/null; then "
            f"sed -i \"s/Environment=CELL_LINK_CAPACITY_MBPS=.*/Environment=CELL_LINK_CAPACITY_MBPS=$LINK/\" "
            f"/etc/systemd/system/silent-cell-agent.service; "
            f"else sed -i \"/Environment=HIVE_API_URL/a Environment=CELL_LINK_CAPACITY_MBPS=$LINK\" "
            f"/etc/systemd/system/silent-cell-agent.service; fi; "
            f"systemctl daemon-reload; "
            f"/opt/silent-vpn/cell-agent/venv/bin/pip install -q psutil 2>/dev/null; "
            f"systemctl restart silent-cell-agent; sleep 2; "
            f"curl -sf http://127.0.0.1:{agent_port}/health",
            timeout=90,
        )
        if code != 0:
            raise RuntimeError(f"Не удалось перезапустить cell-agent:\n{(err or out)[-800:]}")
    finally:
        client.close()


def generate_cell_agent_secret() -> str:
    return secrets.token_urlsafe(32)
