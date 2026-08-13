"""Verify olcrtc dead + API disabled + admin dist."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402


def main() -> None:
    c = connect()
    try:
        run(c, "systemctl list-units 'olcrtc@*' --state=running --no-legend | wc -l")
        run(c, "systemctl is-active silent-olcrtc-host-provision silent-olcrtc-proxy 2>/dev/null; true")
        run(c, "ps -eo comm | grep -E 'olcrtc|chrom' | head -10 || true")
        run(
            c,
            "docker exec backend-api-1 python -c "
            "\"import inspect; from app.services.olcrtc_assign import assign_public_config; "
            "print('disabled' if 'olcrtc disabled' in inspect.getsource(assign_public_config) else 'OLD')\"",
        )
        run(c, "grep -l OlcrtcManagePanel /opt/silent-vpn/backend/admin-ui/dist/assets/*.js 2>/dev/null || echo 'admin: no OlcrtcManagePanel'")
        run(c, "ps -eo pid,pcpu,comm --sort=-pcpu | head -8")
    finally:
        c.close()


if __name__ == "__main__":
    main()
