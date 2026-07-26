"""Деплой host Playwright provision на Улей (systemd, вне Docker).

  cd backend
  python scripts/deploy_olcrtc_host_provision.py

Ставит:
  /opt/silent-vpn/olcrtc/host-provision/  (venv + server)
  /opt/silent-vpn/olcrtc/agent_states/    (cookies)
  systemd silent-olcrtc-host-provision.service → 127.0.0.1:9101
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from _deploy_common import BACKEND_ROOT, connect, run

REMOTE_BASE = "/opt/silent-vpn/olcrtc"
REMOTE_HP = f"{REMOTE_BASE}/host-provision"
REMOTE_STATES = f"{REMOTE_BASE}/agent_states"
UNIT = "/etc/systemd/system/silent-olcrtc-host-provision.service"
LOCAL_SERVER = BACKEND_ROOT / "scripts" / "olcrtc_host_provision_server.py"
LOCAL_PROVISION = BACKEND_ROOT / "ai" / "olcrtc_room_provision.py"


def _unit() -> str:
    return textwrap.dedent(
        f"""\
        [Unit]
        Description=Silent VPN olcrtc host Playwright provision (Telemost/WB)
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=simple
        WorkingDirectory={REMOTE_HP}
        # Docker bridge → host; снаружи режет UFW (только 172.16.0.0/12).
        Environment=OLCRTC_HOST_PROVISION_BIND=0.0.0.0
        Environment=OLCRTC_HOST_PROVISION_PORT=9101
        Environment=OLCRTC_HOST_PROVISION_STATE_DIR={REMOTE_STATES}
        Environment=OLCRTC_BACKEND_ROOT={REMOTE_HP}
        # X-Internal-Secret для /v1/*
        EnvironmentFile=-/opt/silent-vpn/backend/.env
        ExecStart={REMOTE_HP}/venv/bin/python {REMOTE_HP}/olcrtc_host_provision_server.py
        Restart=on-failure
        RestartSec=5

        [Install]
        WantedBy=multi-user.target
        """
    )


def main() -> None:
    if not LOCAL_SERVER.is_file():
        raise SystemExit(f"missing {LOCAL_SERVER}")
    if not LOCAL_PROVISION.is_file():
        raise SystemExit(f"missing {LOCAL_PROVISION}")

    client = connect()
    try:
        run(client, f"mkdir -p {REMOTE_HP}/ai {REMOTE_STATES}")
        sftp = client.open_sftp()
        try:
            sftp.put(str(LOCAL_SERVER), f"{REMOTE_HP}/olcrtc_host_provision_server.py")
            sftp.put(str(LOCAL_PROVISION), f"{REMOTE_HP}/ai/olcrtc_room_provision.py")
            # package marker
            with sftp.file(f"{REMOTE_HP}/ai/__init__.py", "w") as f:
                f.write("# host-provision ai stub\n")
        finally:
            sftp.close()

        run(
            client,
            f"""set -e
apt-get install -y -qq python3-venv python3-pip >/dev/null 2>&1 || true
cd {REMOTE_HP}
if [ ! -x venv/bin/python ]; then
  rm -rf venv
  python3 -m venv venv
fi
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q 'playwright>=1.40' httpx
./venv/bin/playwright install-deps chromium || true
./venv/bin/playwright install chromium
cat > {UNIT} <<'EOF'
{_unit()}
EOF
systemctl daemon-reload
systemctl enable silent-olcrtc-host-provision
systemctl restart silent-olcrtc-host-provision
# Docker bridge → host :9101
ufw allow from 172.16.0.0/12 to any port 9101 proto tcp comment 'olcrtc-host-provision' || true
iptables -C INPUT -s 172.16.0.0/12 -p tcp --dport 9101 -j ACCEPT 2>/dev/null || \
  iptables -I INPUT -s 172.16.0.0/12 -p tcp --dport 9101 -j ACCEPT
# Лишний UDP (ничего не слушает)
ufw delete allow 56002/udp >/dev/null 2>&1 || true
ufw delete allow 56002/udp >/dev/null 2>&1 || true
sleep 2
systemctl is-active silent-olcrtc-host-provision
SECRET=$(grep -E '^INTERNAL_API_SECRET=' /opt/silent-vpn/backend/.env | head -1 | cut -d= -f2- | tr -d '\\r' | tr -d '"' | tr -d "'")
curl -sS -H "X-Internal-Secret: $SECRET" http://127.0.0.1:9101/v1/status || true
echo
curl -sS -o /dev/null -w 'noauth_status=%{{http_code}}\\n' http://127.0.0.1:9101/v1/status || true
""",
        )
        print("OK: silent-olcrtc-host-provision :9101 (UFW docker + X-Internal-Secret)")
        print(f"States: {REMOTE_STATES}/telemost_state.json , wbstream_state.json")
        print("One-time login (Windows): python scripts/olcrtc_room_provision_host.py login telemost")
        print("Then upload JSON via admin «Агент комнат» or scp to agent_states/")
    finally:
        client.close()


if __name__ == "__main__":
    main()
