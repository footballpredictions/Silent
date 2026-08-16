"""Установка DNS-фильтра угроз на Улье: dnsmasq + HaGeZi TIF + sync с админ-тумблером."""
from __future__ import annotations

import io
import textwrap

from _deploy_common import connect, run

REMOTE_ROOT = "/opt/silent-vpn"
LIB_DIR = f"{REMOTE_ROOT}/threat-filter"
ETC_DIR = "/etc/silent-vpn"
BIN_UPDATE = "/usr/local/sbin/silent-threat-dns-update.sh"
BIN_SYNC = "/usr/local/sbin/silent-threat-dns-sync.sh"
META_JSON = f"{LIB_DIR}/meta.json"
BLOCK_CONF = f"{LIB_DIR}/50-block.conf"
ALLOW_CONF = f"{LIB_DIR}/00-allow.conf"
DNSMASQ_CONF = f"{ETC_DIR}/dnsmasq-threat.conf"
HAGEZI_URL = (
    "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/dnsmasq/tif.txt"
)


def main() -> None:
    client = connect()

    update_sh = textwrap.dedent(
        f"""\
        #!/bin/bash
        set -euo pipefail
        LIB="{LIB_DIR}"
        BLOCK="{BLOCK_CONF}"
        META="{META_JSON}"
        URL="{HAGEZI_URL}"
        ENV_FILE="/opt/silent-vpn/backend/.env"
        TMP="$(mktemp)"
        TMP2="$(mktemp)"
        cleanup() {{ rm -f "$TMP" "$TMP2"; }}
        trap cleanup EXIT

        mkdir -p "$LIB"
        curl -fsSL --connect-timeout 30 --max-time 180 "$URL" -o "$TMP"

        # HaGeZi TIF dnsmasq syntax: local=/bad.domain/  (NXDOMAIN)
        grep -E '^local=/[^/]+/' "$TMP" > "$TMP2" || true
        COUNT=$(wc -l < "$TMP2" | tr -d ' ')
        if [ "${{COUNT:-0}}" -lt 1000 ]; then
          echo "[threat-dns] refuse update: too few lines ($COUNT)" >&2
          exit 1
        fi
        install -m 644 "$TMP2" "$BLOCK"
        NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
        printf '{{"domains_count":%s,"list_updated_at":"%s","source":"hagezi-tif"}}\\n' \\
          "$COUNT" "$NOW" > "$META"

        if systemctl is-active --quiet silent-threat-dns 2>/dev/null; then
          systemctl kill -s HUP silent-threat-dns || systemctl reload silent-threat-dns || true
        fi

        SECRET=""
        if [ -f "$ENV_FILE" ]; then
          SECRET=$(grep -E '^INTERNAL_API_SECRET=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\\r' | tr -d '"' | tr -d "'")
        fi
        if [ -n "$SECRET" ]; then
          curl -fsS --connect-timeout 5 --max-time 15 \\
            -X POST "http://127.0.0.1:8000/api/vpn/internal/threat-filter/meta" \\
            -H "Content-Type: application/json" \\
            -H "X-Internal-Secret: $SECRET" \\
            -d "{{\\"domains_count\\":$COUNT,\\"list_updated_at\\":\\"$NOW\\"}}" \\
            >/dev/null || echo "[threat-dns] meta push failed (api down?)" >&2
        fi
        echo "[threat-dns] updated domains=$COUNT at $NOW"
        """
    )

    sync_sh = textwrap.dedent(
        f"""\
        #!/bin/bash
        set -euo pipefail
        ENV_FILE="/opt/silent-vpn/backend/.env"
        COMMENT="SILENT_THREAT_DNS"
        GW="10.66.66.1"
        SUBNET="10.66.0.0/16"

        SECRET=""
        if [ -f "$ENV_FILE" ]; then
          SECRET=$(grep -E '^INTERNAL_API_SECRET=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\\r' | tr -d '"' | tr -d "'")
        fi
        if [ -z "$SECRET" ]; then
          echo "[threat-dns-sync] no INTERNAL_API_SECRET" >&2
          exit 0
        fi

        RESP=$(curl -fsS --connect-timeout 3 --max-time 8 \\
          -H "X-Internal-Secret: $SECRET" \\
          "http://127.0.0.1:8000/api/vpn/internal/threat-filter" || echo '{{"enabled":false}}')
        ENABLED=$(echo "$RESP" | sed -n 's/.*"enabled"[[:space:]]*:[[:space:]]*\\(true\\|false\\).*/\\1/p' | head -1)
        [ -n "$ENABLED" ] || ENABLED=false

        # Ensure tunnel gateway IP exists (same as Telegram proxy)
        ip addr show lo | grep -q "$GW" || ip addr add "$GW/32" dev lo 2>/dev/null || true

        del_rules() {{
          while iptables -t nat -C PREROUTING -s "$SUBNET" -p udp --dport 53 \\
              -j DNAT --to-destination "$GW:53" -m comment --comment "$COMMENT" 2>/dev/null; do
            iptables -t nat -D PREROUTING -s "$SUBNET" -p udp --dport 53 \\
              -j DNAT --to-destination "$GW:53" -m comment --comment "$COMMENT" || break
          done
          while iptables -t nat -C PREROUTING -s "$SUBNET" -p tcp --dport 53 \\
              -j DNAT --to-destination "$GW:53" -m comment --comment "$COMMENT" 2>/dev/null; do
            iptables -t nat -D PREROUTING -s "$SUBNET" -p tcp --dport 53 \\
              -j DNAT --to-destination "$GW:53" -m comment --comment "$COMMENT" || break
          done
        }}

        add_rules() {{
          iptables -t nat -C PREROUTING -s "$SUBNET" -p udp --dport 53 \\
            -j DNAT --to-destination "$GW:53" -m comment --comment "$COMMENT" 2>/dev/null || \\
            iptables -t nat -A PREROUTING -s "$SUBNET" -p udp --dport 53 \\
              -j DNAT --to-destination "$GW:53" -m comment --comment "$COMMENT"
          iptables -t nat -C PREROUTING -s "$SUBNET" -p tcp --dport 53 \\
            -j DNAT --to-destination "$GW:53" -m comment --comment "$COMMENT" 2>/dev/null || \\
            iptables -t nat -A PREROUTING -s "$SUBNET" -p tcp --dport 53 \\
              -j DNAT --to-destination "$GW:53" -m comment --comment "$COMMENT"
        }}

        if [ "$ENABLED" = "true" ]; then
          systemctl start silent-threat-dns 2>/dev/null || true
          add_rules
          echo "[threat-dns-sync] enabled=true DNAT on"
        else
          del_rules
          echo "[threat-dns-sync] enabled=false DNAT off"
        fi
        """
    )

    allow_conf = textwrap.dedent(
        """\
        # Critical allowlist — must load before block (dnsmasq first-match)
        server=/nip.io/77.88.8.8
        server=/vk.com/77.88.8.8
        server=/userapi.com/77.88.8.8
        server=/vk.ru/77.88.8.8
        server=/vk.me/77.88.8.8
        server=/yandex.ru/77.88.8.8
        server=/yandex.net/77.88.8.8
        server=/ya.ru/77.88.8.8
        server=/mail.ru/77.88.8.8
        server=/google.com/77.88.8.8
        server=/googleapis.com/77.88.8.8
        server=/gstatic.com/77.88.8.8
        server=/youtube.com/77.88.8.8
        server=/ytimg.com/77.88.8.8
        server=/googlevideo.com/77.88.8.8
        server=/telegram.org/77.88.8.8
        server=/t.me/77.88.8.8
        server=/discord.com/77.88.8.8
        server=/discord.gg/77.88.8.8
        server=/discordapp.com/77.88.8.8
        server=/discord.media/77.88.8.8
        server=/discordapp.net/77.88.8.8
        server=/discordcdn.com/77.88.8.8
        server=/discordsays.com/77.88.8.8
        server=/discordstatus.com/77.88.8.8
        server=/github.com/77.88.8.8
        server=/githubusercontent.com/77.88.8.8
        """
    )

    dnsmasq_conf = textwrap.dedent(
        f"""\
        # Silent VPN threat filter — dedicated instance (not system dnsmasq)
        port=53
        listen-address=10.66.66.1
        bind-interfaces
        no-resolv
        no-hosts
        cache-size=4000
        domain-needed
        bogus-priv
        server=77.88.8.8
        server=1.1.1.1
        conf-file={ALLOW_CONF}
        conf-file={BLOCK_CONF}
        """
    )

    service_unit = textwrap.dedent(
        f"""\
        [Unit]
        Description=Silent VPN threat DNS (dnsmasq HaGeZi TIF)
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=simple
        ExecStartPre=/bin/bash -c 'ip addr show lo | grep -q 10.66.66.1 || ip addr add 10.66.66.1/32 dev lo'
        ExecStart=/usr/sbin/dnsmasq -k --conf-file={DNSMASQ_CONF} --pid-file=/run/silent-threat-dns.pid
        ExecReload=/bin/kill -HUP $MAINPID
        Restart=on-failure
        RestartSec=3

        [Install]
        WantedBy=multi-user.target
        """
    )

    update_service = textwrap.dedent(
        f"""\
        [Unit]
        Description=Silent VPN threat DNS list update (HaGeZi TIF)
        After=network-online.target

        [Service]
        Type=oneshot
        ExecStart={BIN_UPDATE}
        """
    )

    update_timer = textwrap.dedent(
        """\
        [Unit]
        Description=Update Silent threat DNS lists every 6h

        [Timer]
        OnBootSec=2min
        OnUnitActiveSec=6h
        RandomizedDelaySec=5min
        Persistent=true

        [Install]
        WantedBy=timers.target
        """
    )

    sync_service = textwrap.dedent(
        f"""\
        [Unit]
        Description=Silent VPN threat DNS DNAT sync with admin toggle
        After=network-online.target docker.service

        [Service]
        Type=oneshot
        ExecStart={BIN_SYNC}
        """
    )

    sync_timer = textwrap.dedent(
        """\
        [Unit]
        Description=Sync threat DNS DNAT every minute

        [Timer]
        OnBootSec=30s
        OnUnitActiveSec=1min
        AccuracySec=15s
        Persistent=true

        [Install]
        WantedBy=timers.target
        """
    )

    install_sh = textwrap.dedent(
        f"""\
        #!/bin/bash
        set -euo pipefail
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq
        apt-get install -y -qq dnsmasq curl iptables >/dev/null
        # Dedicated systemd unit — disable stock dnsmasq if it fights for :53 on all interfaces
        systemctl disable --now dnsmasq 2>/dev/null || true

        mkdir -p "{LIB_DIR}" "{ETC_DIR}"
        # placeholder block until first update
        if [ ! -s "{BLOCK_CONF}" ]; then
          echo "# pending first HaGeZi download" > "{BLOCK_CONF}"
        fi

        systemctl daemon-reload
        systemctl enable silent-threat-dns
        systemctl restart silent-threat-dns
        # DNS from WG clients to 10.66.66.1 (lo) — do not open :53 to the world
        ufw allow from 10.66.0.0/16 to any port 53 proto udp comment 'silent-threat-dns' 2>/dev/null || true
        ufw allow from 10.66.0.0/16 to any port 53 proto tcp comment 'silent-threat-dns' 2>/dev/null || true
        iptables -C INPUT -s 10.66.0.0/16 -p udp --dport 53 -j ACCEPT 2>/dev/null || \\
          iptables -I INPUT -s 10.66.0.0/16 -p udp --dport 53 -j ACCEPT
        iptables -C INPUT -s 10.66.0.0/16 -p tcp --dport 53 -j ACCEPT 2>/dev/null || \\
          iptables -I INPUT -s 10.66.0.0/16 -p tcp --dport 53 -j ACCEPT

        systemctl enable --now silent-threat-dns-update.timer
        systemctl enable --now silent-threat-dns-sync.timer

        # First list pull (may take a bit; large file)
        {BIN_UPDATE} || echo "[threat-dns] initial update deferred"
        {BIN_SYNC} || true

        echo "--- status ---"
        systemctl is-active silent-threat-dns || true
        systemctl list-timers 'silent-threat-dns-*' --no-pager || true
        ss -ulnp | grep -E ':53\\b' || true
        test -f "{META_JSON}" && cat "{META_JSON}" || true
        """
    )

    sftp = client.open_sftp()
    files = {
        BIN_UPDATE: update_sh,
        BIN_SYNC: sync_sh,
        ALLOW_CONF: allow_conf,
        DNSMASQ_CONF: dnsmasq_conf,
        "/etc/systemd/system/silent-threat-dns.service": service_unit,
        "/etc/systemd/system/silent-threat-dns-update.service": update_service,
        "/etc/systemd/system/silent-threat-dns-update.timer": update_timer,
        "/etc/systemd/system/silent-threat-dns-sync.service": sync_service,
        "/etc/systemd/system/silent-threat-dns-sync.timer": sync_timer,
        "/tmp/install_threat_dns.sh": install_sh,
    }
    # ensure dirs for allow/meta via remote mkdir in install; upload allow after mkdir
    run(client, f"mkdir -p {LIB_DIR} {ETC_DIR}", timeout=30)
    for path, content in files.items():
        print(f"upload {path}")
        sftp.putfo(io.BytesIO(content.encode("utf-8")), path)
    sftp.close()

    run(client, f"chmod +x {BIN_UPDATE} {BIN_SYNC} /tmp/install_threat_dns.sh", timeout=15)
    run(client, "bash /tmp/install_threat_dns.sh 2>&1", timeout=300)
    client.close()
    print("Done — threat DNS filter installed on hive host")


if __name__ == "__main__":
    main()
