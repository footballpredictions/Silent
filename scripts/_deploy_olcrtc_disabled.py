"""Deploy assign stub + note: build admin-ui separately."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    c = connect()
    sftp = c.open_sftp()
    try:
        local = ROOT / "app/services/olcrtc_assign.py"
        sftp.put(str(local), "/tmp/olcrtc_assign.py")
        run(c, "docker cp /tmp/olcrtc_assign.py backend-api-1:/app/app/services/olcrtc_assign.py")
        run(c, "docker compose -f /opt/silent-vpn/backend/docker-compose.yml restart api")
        print("ok assign stub deployed")
    finally:
        sftp.close()
        c.close()


if __name__ == "__main__":
    main()
