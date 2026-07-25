"""Установка автоочистки Улья: journal / unused Docker / tmp + timer (опрос API)."""
from __future__ import annotations

import io
import textwrap

from _deploy_common import connect, run

BIN = "/usr/local/sbin/silent-vps-cleanup.sh"
SYNC = "/usr/local/sbin/silent-vps-cleanup-tick.sh"


def main() -> None:
    client = connect()

    cleanup_sh = textwrap.dedent(
        f"""\
        #!/bin/bash
        # Safe hive cleanup — never touches docker volumes / .env / OTA update/
        set -euo pipefail
        JOURNAL_MB="${{1:-200}}"
        BEFORE=$(df -B1 / | awk 'NR==2{{print $4}}')
        journalctl --vacuum-size="${{JOURNAL_MB}}M" >/dev/null 2>&1 || true
        apt-get clean >/dev/null 2>&1 || true
        rm -rf /var/cache/apt/archives/*.deb 2>/dev/null || true
        rm -f /tmp/deploy_*.sh /tmp/fix_*.sh /tmp/install_*.sh /tmp/remove_*.sh \\
          /tmp/silent_*.sh /tmp/_*.py /tmp/check_*.py /tmp/hotfix_*.py 2>/dev/null || true
        find /var/log -type f \\( -name '*.gz' -o -name '*.1' -o -name '*.old' \\) -mtime +14 -delete 2>/dev/null || true
        find /var/log -type f -name '*.log' -size +200M -exec truncate -s 0 {{}} \\; 2>/dev/null || true
        find /var/lib/docker/containers -name '*-json.log' -size +200M -exec truncate -s 50M {{}} \\; 2>/dev/null || true
        docker container prune -f >/dev/null 2>&1 || true
        docker image prune -af >/dev/null 2>&1 || true
        docker builder prune -af >/dev/null 2>&1 || true
        AFTER=$(df -B1 / | awk 'NR==2{{print $4}}')
        FREED=$(( AFTER - BEFORE ))
        FREED_MB=$(( FREED / 1024 / 1024 ))
        AVAIL=$(df -h / | awk 'NR==2{{print $4}}')
        echo "freed_approx_mb=${{FREED_MB}} avail=${{AVAIL}} journal_mb=${{JOURNAL_MB}}"
        """
    )

    tick_sh = textwrap.dedent(
        f"""\
        #!/bin/bash
        set -euo pipefail
        ENV_FILE="/opt/silent-vpn/backend/.env"
        SECRET=""
        if [ -f "$ENV_FILE" ]; then
          SECRET=$(grep -E '^INTERNAL_API_SECRET=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\\r' | tr -d '"' | tr -d "'")
        fi
        [ -n "$SECRET" ] || {{ echo "[vps-cleanup] no INTERNAL_API_SECRET"; exit 0; }}

        RESP=$(curl -fsS --connect-timeout 5 --max-time 15 \\
          -H "X-Internal-Secret: $SECRET" \\
          "http://127.0.0.1:8000/api/vpn/internal/vps-cleanup" || echo '{{}}')

        ENABLED=$(echo "$RESP" | sed -n 's/.*"enabled"[[:space:]]*:[[:space:]]*\\(true\\|false\\).*/\\1/p' | head -1)
        RUN_NOW=$(echo "$RESP" | sed -n 's/.*"run_now"[[:space:]]*:[[:space:]]*\\(true\\|false\\).*/\\1/p' | head -1)
        INTERVAL=$(echo "$RESP" | sed -n 's/.*"interval_days"[[:space:]]*:[[:space:]]*\\([0-9][0-9]*\\).*/\\1/p' | head -1)
        JOURNAL=$(echo "$RESP" | sed -n 's/.*"journal_max_mb"[[:space:]]*:[[:space:]]*\\([0-9][0-9]*\\).*/\\1/p' | head -1)
        LAST=$(echo "$RESP" | sed -n 's/.*"last_run_at"[[:space:]]*:[[:space:]]*"\\([^"]*\\)".*/\\1/p' | head -1)
        INTERVAL=${{INTERVAL:-7}}
        JOURNAL=${{JOURNAL:-200}}

        if [ "$ENABLED" != "true" ]; then
          echo "[vps-cleanup] disabled"
          exit 0
        fi

        NEED=0
        if [ "$RUN_NOW" = "true" ]; then
          NEED=1
        else
          if [ -z "$LAST" ] || [ "$LAST" = "null" ]; then
            NEED=1
          else
            # last_run older than interval_days?
            LAST_EPOCH=$(date -u -d "$LAST" +%s 2>/dev/null || echo 0)
            NOW_EPOCH=$(date -u +%s)
            AGE_DAYS=$(( (NOW_EPOCH - LAST_EPOCH) / 86400 ))
            if [ "$LAST_EPOCH" -eq 0 ] || [ "$AGE_DAYS" -ge "$INTERVAL" ]; then
              NEED=1
            fi
          fi
        fi

        if [ "$NEED" -ne 1 ]; then
          echo "[vps-cleanup] skip (next in <=${{INTERVAL}}d, last=$LAST)"
          exit 0
        fi

        echo "[vps-cleanup] running journal=${{JOURNAL}}M interval=${{INTERVAL}}d"
        SUMMARY=$({BIN} "$JOURNAL" 2>&1 | tail -1)
        BODY=$(SUMMARY="$SUMMARY" python3 - <<'PY'
import json, os
print(json.dumps({{"summary": os.environ.get("SUMMARY", "")}}))
PY
)
        curl -fsS --connect-timeout 5 --max-time 20 \\
          -X POST "http://127.0.0.1:8000/api/vpn/internal/vps-cleanup/meta" \\
          -H "Content-Type: application/json" \\
          -H "X-Internal-Secret: $SECRET" \\
          -d "$BODY" \\
          >/dev/null || echo "[vps-cleanup] meta push failed"
        echo "[vps-cleanup] done: $SUMMARY"
        """
    )

    service = textwrap.dedent(
        f"""\
        [Unit]
        Description=Silent VPN VPS cleanup tick (poll API)
        After=network-online.target docker.service

        [Service]
        Type=oneshot
        ExecStart={SYNC}
        """
    )

    timer = textwrap.dedent(
        """\
        [Unit]
        Description=Silent VPN VPS cleanup poll (API schedule)

        [Timer]
        OnBootSec=2min
        OnUnitActiveSec=15min
        RandomizedDelaySec=1min
        Persistent=true

        [Install]
        WantedBy=timers.target
        """
    )

    install = textwrap.dedent(
        f"""\
        #!/bin/bash
        set -euo pipefail
        systemctl daemon-reload
        systemctl enable --now silent-vps-cleanup.timer
        {SYNC} || echo "[vps-cleanup] initial tick deferred"
        systemctl list-timers 'silent-vps-cleanup*' --no-pager || true
        """
    )

    sftp = client.open_sftp()
    for path, content in {
        BIN: cleanup_sh,
        SYNC: tick_sh,
        "/etc/systemd/system/silent-vps-cleanup.service": service,
        "/etc/systemd/system/silent-vps-cleanup.timer": timer,
        "/tmp/install_vps_cleanup.sh": install,
    }.items():
        print(f"upload {path}")
        sftp.putfo(io.BytesIO(content.encode("utf-8")), path)
    sftp.close()
    run(client, f"chmod +x {BIN} {SYNC} /tmp/install_vps_cleanup.sh", timeout=15)
    run(client, "bash /tmp/install_vps_cleanup.sh 2>&1", timeout=180)
    client.close()
    print("Done — VPS cleanup timer installed")


if __name__ == "__main__":
    main()
