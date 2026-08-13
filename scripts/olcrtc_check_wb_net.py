"""Check stream.wb.ru / telemost from VPS + set WB playwright proxy if available."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _deploy_common import connect, run  # noqa: E402


def main() -> None:
    client = connect()
    print(
        run(
            client,
            "echo TELEMOS; curl -sS -m 10 -o /dev/null -w '%{http_code}\\n' https://telemost.yandex.ru/ || echo fail; "
            "echo WB; curl -sS -m 10 -o /dev/null -w '%{http_code}\\n' https://stream.wb.ru/ || echo fail; "
            "grep -E '^(PROXY_HTTP_|OLCRTC_WB_PLAYWRIGHT)' /opt/silent-vpn/backend/.env 2>/dev/null | cut -c1-80 || true; "
            "systemctl show silent-olcrtc-host-provision -p Environment 2>/dev/null | tr ' ' '\\n' | grep -i proxy || true",
        )
    )
    client.close()


if __name__ == "__main__":
    main()
