"""SSH-провижен прокси-флота. НЕ трогает VPN/Улей.

Роли:
- dedicated — чистый proxy-VPS: HTTP + SOCKS5 + MTProto + agent
- attached — сайт/VPS с другими сервисами: снести только старый proxy (whitelist),
  прописать env на **primary** HTTP/SOCKS (не на Улей), перезапустить PM2 при наличии.
  На attached НЕ ставим sing-box/exit — только клиентская привязка к primary.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import time
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

PROXY_SYSTEMD_UNITS = (
    "3proxy",
    "sockd",
    "danted",
    "dante",
    "xray",
    "v2ray",
    "sing-box",
    "mtg",
    "shadowsocks",
    "shadowsocks-libev",
    "ss-server",
    "outline-ss-server",
    "gost",
    "hysteria",
    "hysteria2",
    "silent-socks",
    "silent-mtproto",
    "silent-proxy-agent",
)
PROXY_APT_PACKAGES = (
    "dante-server",
    "3proxy",
    "squid",
    "shadowsocks-libev",
)
PROXY_DIRS_SAFE_REMOVE = (
    "/opt/silent-proxy",
    "/etc/silent-proxy",
    "/usr/local/3proxy",
    "/etc/3proxy",
    "/etc/xray",
    "/usr/local/etc/xray",
    "/etc/v2ray",
    "/etc/sing-box",
    "/opt/sing-box",
)

SINGBOX_VERSION = "1.11.7"
MTG_VERSION = "2.2.8"
AGENT_PORT_DEFAULT = 9101

# Ключи env, которые переписываем на primary HTTP при attach сайта
SITE_HTTP_PROXY_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "http_proxy",
    "https_proxy",
    "ALL_PROXY",
    "all_proxy",
    "API_FOOTBALL_PROXY_URL",
    "GITHUB_HTTPS_PROXY",
    "PROXY_URL",
    "PROXY",
)


def generate_agent_secret() -> str:
    return secrets.token_urlsafe(32)


def generate_socks_password() -> str:
    return secrets.token_urlsafe(18)


def _format_exc(e: BaseException) -> str:
    msg = str(e).strip() or repr(e)
    return f"{type(e).__name__}: {msg}"[:2000]


def _ssh_connect(
    host: str,
    password: str,
    *,
    port: int = 22,
    username: str | None = None,
    timeout: int | None = None,
    allow_port_fallback: bool = False,
):
    """SSH. По умолчанию — только указанный порт (для Jino :49452 fallback на 22 ломает подключение)."""
    import paramiko

    user = (username or settings.PROXY_PROVISION_SSH_USER or "root").strip()
    t = timeout or settings.PROXY_PROVISION_SSH_TIMEOUT_SEC
    ports_to_try = [int(port)]
    if allow_port_fallback and int(port) != 22:
        ports_to_try.append(22)

    last_err: BaseException | None = None
    for p in ports_to_try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            logger.info("proxy-ssh connect %s:%s", host, p)
            client.connect(
                host,
                port=int(p),
                username=user,
                password=password,
                timeout=t,
                banner_timeout=t,
                auth_timeout=t,
                allow_agent=False,
                look_for_keys=False,
            )
            client._silent_ssh_port = int(p)  # type: ignore[attr-defined]
            return client
        except BaseException as e:
            last_err = e
            logger.warning("proxy-ssh %s:%s failed: %s", host, p, e)
            try:
                client.close()
            except Exception:
                pass
    raise RuntimeError(
        f"SSH недоступен на {host}:{ports_to_try[0]} "
        f"(указанный порт без автосмены). "
        f"Проверьте host/порт/пароль. Последняя ошибка: "
        f"{_format_exc(last_err) if last_err else 'unknown'}"
    )


def _resolve_host_ip(host: str) -> str:
    import socket

    h = host.strip()
    try:
        return socket.gethostbyname(h)
    except OSError:
        return h


def _run(client, cmd: str, timeout: int = 300) -> str:
    logger.info("proxy-ssh: %s", cmd[:200])
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout, get_pty=True)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    if err.strip():
        logger.debug("proxy-ssh stderr: %s", err[:500])
    return out


def _sftp_write(client, remote_path: str, content: str | bytes, mode: int = 0o644) -> None:
    data = content.encode("utf-8") if isinstance(content, str) else content
    sftp = client.open_sftp()
    try:
        with sftp.file(remote_path, "wb") as f:
            f.write(data)
        sftp.chmod(remote_path, mode)
    finally:
        sftp.close()


def _sftp_read(client, remote_path: str) -> str | None:
    sftp = client.open_sftp()
    try:
        with sftp.file(remote_path, "rb") as f:
            return f.read().decode("utf-8", "replace")
    except OSError:
        return None
    finally:
        sftp.close()


def _load_proxy_agent_py() -> str:
    from pathlib import Path

    for p in (
        Path(__file__).resolve().parent.parent.parent / "proxy-agent" / "main.py",
        Path("/app/proxy-agent/main.py"),
    ):
        if p.is_file():
            return p.read_text(encoding="utf-8")
    raise RuntimeError("proxy-agent/main.py не найден")


def _remove_old_proxy_only(client) -> None:
    """Снести только whitelist proxy — сайт/nginx/docker/pm2 не трогаем."""
    stop_list = " ".join(PROXY_SYSTEMD_UNITS)
    _run(
        client,
        f"""
set +e
echo '=== remove old proxy (whitelist only) ==='
for u in {stop_list}; do
  systemctl stop "$u" 2>/dev/null
  systemctl stop "$u.service" 2>/dev/null
  systemctl disable "$u" 2>/dev/null
  systemctl disable "$u.service" 2>/dev/null
done
DEBIAN_FRONTEND=noninteractive apt-get remove -y -qq {' '.join(PROXY_APT_PACKAGES)} 2>/dev/null || true
for d in {' '.join(PROXY_DIRS_SAFE_REMOVE)}; do
  rm -rf "$d" 2>/dev/null
done
for b in xray v2ray sing-box mtg 3proxy microsocks gost; do
  rm -f "/usr/local/bin/$b" 2>/dev/null
done
true
""",
        timeout=180,
    )


def detect_existing_proxy(client) -> dict[str, Any]:
    units = " ".join(PROXY_SYSTEMD_UNITS)
    script = f"""
set +e
echo 'UNITS:'
for u in {units}; do
  systemctl is-active "$u" 2>/dev/null | grep -q active && echo "active:$u"
done
echo 'ENV_PROXY:'
grep -RIlE 'PROXY|proxy_url|3128|1080' /root --include='.env' --include='*.env' 2>/dev/null | head -40
echo 'LISTEN:'
ss -lntp 2>/dev/null | awk 'NR>1{{print}}' | head -40
echo 'END'
"""
    out = _run(client, script, timeout=60)
    active = []
    env_files = []
    section = None
    for line in out.splitlines():
        if line.startswith("UNITS:"):
            section = "units"
            continue
        if line.startswith("ENV_PROXY:"):
            section = "env"
            continue
        if line.startswith("LISTEN:"):
            section = "listen"
            continue
        if line.startswith("END"):
            break
        if section == "units" and line.startswith("active:"):
            active.append(line.split(":", 1)[1].strip())
        elif section == "env" and line.strip().startswith("/"):
            env_files.append(line.strip())
    return {
        "active_units": active,
        "env_files": env_files,
        "ss_raw": out,
        "detected_at": int(time.time()),
    }


def _upsert_env_line(content: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    line = f"{key}={value}"
    if pattern.search(content):
        return pattern.sub(line, content)
    if content and not content.endswith("\n"):
        content += "\n"
    return content + line + "\n"


def _wire_site_env_to_primary(
    client,
    *,
    http_url: str,
    socks_url: str,
    env_files: list[str] | None = None,
) -> list[str]:
    """Переписать proxy-ключи в .env сайта на primary. Сайт/код не трогаем."""
    updated: list[str] = []
    files = list(env_files or [])
    if not files:
        # типичные места
        found = _run(
            client,
            "grep -RIlE 'PROXY|proxy_url|3128|1080' /root --include='.env' --include='*.env' 2>/dev/null | head -40 || true",
            timeout=60,
        )
        files = [ln.strip() for ln in found.splitlines() if ln.strip().startswith("/")]
    # всегда проверим известные пути
    for extra in ("/root/server_f/.env", "/root/.env", "/opt/app/.env"):
        if extra not in files:
            files.append(extra)

    for path in files:
        raw = _sftp_read(client, path)
        if raw is None:
            continue
        # если в файле нет ни одного proxy-ключа и это не server_f — пропуск
        has_proxy = any(k in raw for k in SITE_HTTP_PROXY_KEYS) or "PROXY" in raw.upper()
        is_known = path in ("/root/server_f/.env",)
        if not has_proxy and not is_known:
            continue
        new = raw
        for key in SITE_HTTP_PROXY_KEYS:
            if key in raw or is_known:
                # Для сайтов основной канал — HTTP CONNECT (как API_FOOTBALL_PROXY_URL).
                # ALL_PROXY тоже HTTP, чтобы не ломать Node/axios SOCKS-диалектами.
                new = _upsert_env_line(new, key, http_url)
        # явные silent markers
        new = _upsert_env_line(new, "SILENT_PROXY_HTTP", http_url)
        new = _upsert_env_line(new, "SILENT_PROXY_SOCKS", socks_url)
        if new != raw:
            _sftp_write(client, path, new, 0o600)
            updated.append(path)
    return updated


def attach_site_to_primary(
    *,
    host: str,
    password: str,
    ssh_port: int = 22,
    primary: dict[str, Any],
) -> dict[str, Any]:
    """Привязать сайт-VPS к primary proxy: удалить старый proxy, прописать env, pm2 reload."""
    http_url = (primary.get("http_url") or "").strip()
    socks_url = (primary.get("socks_url") or "").strip()
    if not http_url and not socks_url:
        raise RuntimeError("Нет primary proxy endpoint (сначала подключите чистый proxy-VPS)")

    client = _ssh_connect(host, password, port=ssh_port, allow_port_fallback=False)
    used_ssh_port = int(getattr(client, "_silent_ssh_port", ssh_port) or ssh_port)
    try:
        previous = detect_existing_proxy(client)
        previous["ssh_port_used"] = used_ssh_port
        previous["resolved_ip"] = _resolve_host_ip(host)

        # 1) только старый proxy
        _remove_old_proxy_only(client)

        # 2) env → primary (не Улей)
        updated = _wire_site_env_to_primary(
            client,
            http_url=http_url or socks_url,
            socks_url=socks_url or http_url,
            env_files=previous.get("env_files") or [],
        )
        previous["env_updated"] = updated

        # 3) pm2: мягкий reload; если зависло в stopping — не блокируем attach
        pm2 = _run(
            client,
            """
set +e
if command -v pm2 >/dev/null 2>&1; then
  echo PM2_PRESENT
  pm2 list
  # update-env без долгого wait: restart по одному имени с timeout через timeout(1)
  for app in $(pm2 jlist 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(' '.join(x['name'] for x in d))" 2>/dev/null); do
    timeout 25 pm2 restart "$app" --update-env || true
  done
  pm2 save 2>/dev/null || true
  echo PM2_DONE
else
  echo PM2_ABSENT
fi
""",
            timeout=90,
        )
        previous["pm2"] = pm2[-1500:]

        # sanity: сайт-процессы живы если были
        listen = _run(client, "ss -lntp 2>/dev/null | head -30 || true", timeout=30)

        return {
            "public_ip": _resolve_host_ip(host) or host,
            "ssh_port_used": used_ssh_port,
            "previous_proxy": previous,
            "env_updated": updated,
            "http_url": http_url,
            "socks_url": socks_url,
            "role": "attached",
            "bound_to": primary.get("public_ip"),
            "listen_sample": listen[-800:],
            # attached не имеет своего SOCKS — копируем primary для отображения в UI
            "socks_port": int(primary.get("socks_port") or 1080),
            "socks_user": primary.get("socks_user") or "",
            "agent_url": None,
            "agent_port": None,
        }
    finally:
        client.close()


def provision_dedicated_proxy(
    *,
    host: str,
    password: str,
    ssh_port: int = 22,
    socks_port: int = 1080,
    socks_user: str = "silent",
    socks_pass: str,
    agent_secret: str,
    http_port: int = 3128,
    http_user: str = "top10proxy",
    http_pass: str,
    mtproto_port: int = 8443,
    public_ip: str | None = None,
) -> dict[str, Any]:
    """Полная установка на чистом proxy-VPS: HTTP + SOCKS5 + MTProto + agent."""
    agent_port = int(settings.PROXY_AGENT_PORT or AGENT_PORT_DEFAULT)
    resolved = _resolve_host_ip(host)
    pub = (public_ip or resolved or host).strip()
    if pub and not pub[0].isdigit():
        pub = resolved or pub

    client = _ssh_connect(host, password, port=ssh_port, allow_port_fallback=False)
    used_ssh_port = int(getattr(client, "_silent_ssh_port", ssh_port) or ssh_port)
    try:
        previous = detect_existing_proxy(client)
        previous["ssh_port_used"] = used_ssh_port
        previous["resolved_ip"] = resolved

        _remove_old_proxy_only(client)

        _run(
            client,
            "export DEBIAN_FRONTEND=noninteractive; "
            "apt-get update -qq && apt-get install -y -qq curl ca-certificates "
            "python3 python3-venv python3-pip ufw tar >/dev/null",
            timeout=600,
        )
        _run(client, "mkdir -p /opt/silent-proxy/bin /opt/silent-proxy/agent /etc/silent-proxy")

        ver = SINGBOX_VERSION
        _run(
            client,
            f"""
set -e
BIN=/opt/silent-proxy/bin/sing-box
if [ -x "$BIN" ] && "$BIN" version 2>/dev/null | grep -q '{ver}'; then
  echo sing-box-ok
  exit 0
fi
cd /tmp
URL=https://github.com/SagerNet/sing-box/releases/download/v{ver}/sing-box-{ver}-linux-amd64.tar.gz
curl -fsSL -o sb.tgz "$URL"
tar -xzf sb.tgz
install -m 755 sing-box-{ver}-linux-amd64/sing-box "$BIN"
rm -rf sb.tgz sing-box-{ver}-linux-amd64
"$BIN" version
""",
            timeout=180,
        )

        # mtg
        mtg_ver = MTG_VERSION
        _run(
            client,
            f"""
set -e
BIN=/opt/silent-proxy/bin/mtg
if [ -x "$BIN" ]; then
  echo mtg-ok
  exit 0
fi
cd /tmp
curl -fsSL -o mtg.tgz https://github.com/9seconds/mtg/releases/download/v{mtg_ver}/mtg-{mtg_ver}-linux-amd64.tar.gz
tar -xzf mtg.tgz
FOUND=$(find . -name mtg -type f | head -1)
install -m 755 "$FOUND" "$BIN"
rm -rf mtg.tgz mtg-*
"$BIN" --version || true
""",
            timeout=180,
        )
        mtg_out = _run(client, "/opt/silent-proxy/bin/mtg generate-secret --hex google.com", timeout=30)
        mtproto_secret = (mtg_out or "").strip().splitlines()[-1].strip()
        if not mtproto_secret or len(mtproto_secret) < 16:
            mtproto_secret = "ee" + secrets.token_hex(16)

        sb_cfg = {
            "log": {"level": "warn"},
            "inbounds": [
                {
                    "type": "http",
                    "tag": "http-in",
                    "listen": "0.0.0.0",
                    "listen_port": int(http_port),
                    "users": [{"username": http_user, "password": http_pass}],
                },
                {
                    "type": "socks",
                    "tag": "socks-in",
                    "listen": "0.0.0.0",
                    "listen_port": int(socks_port),
                    "users": [{"username": socks_user, "password": socks_pass}],
                },
            ],
            "outbounds": [{"type": "direct", "tag": "direct"}],
        }
        _sftp_write(client, "/etc/silent-proxy/sing-box.json", json.dumps(sb_cfg, indent=2), 0o600)

        env_file = (
            f"PROXY_AGENT_SECRET={agent_secret}\n"
            f"PROXY_PUBLIC_IP={pub}\n"
            f"PROXY_SOCKS_PORT={socks_port}\n"
            f"PROXY_SOCKS_USER={socks_user}\n"
            f"PROXY_SOCKS_PASS={socks_pass}\n"
            f"PROXY_HTTP_PORT={http_port}\n"
            f"PROXY_HTTP_USER={http_user}\n"
            f"PROXY_HTTP_PASS={http_pass}\n"
            f"PROXY_MTPROTO_PORT={mtproto_port}\n"
            f"PROXY_MTPROTO_SECRET={mtproto_secret}\n"
        )
        _sftp_write(client, "/etc/silent-proxy/agent.env", env_file, 0o600)
        _sftp_write(client, "/opt/silent-proxy/agent/main.py", _load_proxy_agent_py(), 0o644)

        _run(
            client,
            "python3 -m venv /opt/silent-proxy/agent/.venv && "
            "/opt/silent-proxy/agent/.venv/bin/pip install -q fastapi 'uvicorn[standard]'",
            timeout=300,
        )

        socks_unit = """[Unit]
Description=Silent Proxy Exit (sing-box HTTP+SOCKS)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/opt/silent-proxy/bin/sing-box run -c /etc/silent-proxy/sing-box.json
Restart=always
RestartSec=3
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
"""
        mtg_unit = f"""[Unit]
Description=Silent MTProto (mtg)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/opt/silent-proxy/bin/mtg simple-run -i prefer-ipv4 -n 1.1.1.1 0.0.0.0:{int(mtproto_port)} {mtproto_secret}
Restart=always
RestartSec=3
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
"""
        agent_unit = f"""[Unit]
Description=Silent Proxy Agent
After=network-online.target silent-socks.service
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/silent-proxy/agent.env
WorkingDirectory=/opt/silent-proxy/agent
ExecStart=/opt/silent-proxy/agent/.venv/bin/uvicorn main:app --host 0.0.0.0 --port {agent_port}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""
        _sftp_write(client, "/etc/systemd/system/silent-socks.service", socks_unit)
        _sftp_write(client, "/etc/systemd/system/silent-mtproto.service", mtg_unit)
        _sftp_write(client, "/etc/systemd/system/silent-proxy-agent.service", agent_unit)
        _run(client, "systemctl daemon-reload")
        _run(
            client,
            f"""
set +e
fuser -k {int(socks_port)}/tcp 2>/dev/null || true
fuser -k {int(http_port)}/tcp 2>/dev/null || true
sleep 1
systemctl enable silent-socks.service silent-mtproto.service silent-proxy-agent.service
systemctl restart silent-socks.service
systemctl restart silent-mtproto.service
systemctl restart silent-proxy-agent.service
sleep 2
systemctl is-active silent-socks.service
systemctl is-active silent-mtproto.service
systemctl is-active silent-proxy-agent.service
""",
            timeout=120,
        )
        active = _run(
            client,
            "systemctl is-active silent-socks.service; "
            "systemctl is-active silent-mtproto.service; "
            "systemctl is-active silent-proxy-agent.service",
        )
        if active.count("active") < 3:
            raise RuntimeError(f"сервисы прокси не активны: {active}")

        _run(
            client,
            f"ufw allow 22/tcp; ufw allow {int(socks_port)}/tcp; "
            f"ufw allow {int(http_port)}/tcp; ufw allow {int(mtproto_port)}/tcp; "
            f"ufw allow {agent_port}/tcp; ufw --force enable || true",
            timeout=60,
        )

        listen = _run(
            client,
            f"ss -lntp | grep -E ':{socks_port}|:{http_port}|:{mtproto_port}|:{agent_port}' || true",
        )
        if f":{socks_port}" not in listen:
            raise RuntimeError(f"SOCKS порт {socks_port} не слушает: {listen}")
        if f":{http_port}" not in listen:
            raise RuntimeError(f"HTTP порт {http_port} не слушает: {listen}")

        http_url = f"http://{http_user}:{http_pass}@{pub}:{http_port}"
        socks_url = f"socks5://{socks_user}:{socks_pass}@{pub}:{socks_port}"
        tg_link = f"tg://proxy?server={pub}&port={mtproto_port}&secret={mtproto_secret}"

        return {
            "public_ip": pub,
            "socks_port": int(socks_port),
            "socks_user": socks_user,
            "http_port": int(http_port),
            "http_user": http_user,
            "http_pass": http_pass,
            "http_url": http_url,
            "socks_url": socks_url,
            "mtproto_port": int(mtproto_port),
            "mtproto_secret": mtproto_secret,
            "telegram_link": tg_link,
            "agent_url": f"http://{pub}:{agent_port}",
            "agent_port": agent_port,
            "ssh_port_used": used_ssh_port,
            "previous_proxy": previous,
            "role": "dedicated",
        }
    finally:
        client.close()


def provision_proxy_node(
    *,
    host: str,
    password: str,
    ssh_port: int = 22,
    role: str = "attached",
    socks_port: int = 1080,
    socks_user: str = "silent",
    socks_pass: str,
    agent_secret: str,
    public_ip: str | None = None,
    primary: dict[str, Any] | None = None,
    http_user: str | None = None,
    http_pass: str | None = None,
) -> dict[str, Any]:
    """Точка входа: dedicated = exit-прокси; attached = привязка сайта к primary."""
    role = (role or "attached").strip().lower()
    if role == "attached":
        if not primary:
            raise RuntimeError(
                "Сначала подключите чистый proxy-VPS (role=dedicated) — "
                "сайты цепляются к нему, не к Улью"
            )
        return attach_site_to_primary(
            host=host,
            password=password,
            ssh_port=ssh_port,
            primary=primary,
        )

    hp = (http_pass or getattr(settings, "PROXY_HTTP_PASS", None) or "").strip()
    if not hp:
        raise RuntimeError(
            "Задайте PROXY_HTTP_PASS в .env Улья (пароль HTTP-прокси на dedicated VPS)"
        )
    return provision_dedicated_proxy(
        host=host,
        password=password,
        ssh_port=ssh_port,
        socks_port=socks_port,
        socks_user=socks_user,
        socks_pass=socks_pass,
        agent_secret=agent_secret,
        http_user=(http_user or getattr(settings, "PROXY_HTTP_USER", None) or "top10proxy"),
        http_pass=hp,
        public_ip=public_ip,
    )
