"""Деплой build-agent (скрипты + secrets) на VPS хост."""
from __future__ import annotations

import io
import os
from pathlib import Path

from _deploy_common import connect, run

BACKEND_ROOT = Path(__file__).resolve().parent.parent
BUILD_AGENT = BACKEND_ROOT / "build-agent"
REMOTE = os.environ.get("DEPLOY_BUILD_AGENT_REMOTE", "/opt/silent-vpn/backend/build-agent")


def main() -> None:
    if not BUILD_AGENT.is_dir():
        raise SystemExit(f"Missing {BUILD_AGENT}")

    client = connect()
    sftp = client.open_sftp()
    client.exec_command(f"mkdir -p {REMOTE}/secrets {REMOTE}/workspace")

    for root, dirs, names in os.walk(BUILD_AGENT):
        dirs[:] = [d for d in dirs if d not in ("workspace", "__pycache__")]
        for name in names:
            lp = Path(root) / name
            rel = lp.relative_to(BUILD_AGENT).as_posix()
            rp = f"{REMOTE}/{rel}"
            client.exec_command(f"mkdir -p {os.path.dirname(rp)}")
            sftp.put(str(lp), rp)
            if rel.endswith(".sh"):
                client.exec_command(f"chmod +x {rp} && sed -i 's/\\r$//' {rp}")
            print("upload", rel)

    sftp.close()

    script = f"""#!/bin/bash
set -e
mkdir -p /opt/silent-vpn/backend/update/pc /opt/silent-vpn/backend/update/android
chmod +x {REMOTE}/*.sh 2>/dev/null || true
ls -la {REMOTE}
"""
    sftp2 = client.open_sftp()
    sftp2.putfo(io.BytesIO(script.encode()), "/tmp/setup_build_agent.sh")
    sftp2.close()
    run(client, "bash /tmp/setup_build_agent.sh 2>&1", timeout=60)
    print("Pre-pull PC builder image (may take a few minutes)...")
    run(client, "docker pull electronuserland/builder:wine 2>&1 | tail -5", timeout=900)
    client.close()
    print("Done. Mount in docker-compose: ./build-agent -> /app/build-agent")


if __name__ == "__main__":
    main()
