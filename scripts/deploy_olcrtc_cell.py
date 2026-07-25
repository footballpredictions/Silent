"""Задеплоить olcrtc бинарь + template unit на соту (Hive worker).

  cd backend
  python scripts/deploy_olcrtc_cell.py <cell_ip>

Нужны: SSH root (как deploy_cell_agent), локальный бинарь olcrtc linux amd64.
YAML комнаты потом пушит API через cell-agent POST /v1/olcrtc/apply.
"""
from __future__ import annotations

import io
import os
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _deploy_common import BACKEND_ROOT, connect, run  # noqa: E402

REMOTE_OLCRTC = "/opt/silent-vpn/olcrtc"


def _template_unit() -> str:
    return textwrap.dedent(
        f"""\
        [Unit]
        Description=Silent VPN olcrtc srv (%i)
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=simple
        WorkingDirectory={REMOTE_OLCRTC}
        ExecStart={REMOTE_OLCRTC}/olcrtc {REMOTE_OLCRTC}/server-%i.yaml
        Restart=on-failure
        RestartSec=5
        LimitNOFILE=65535

        [Install]
        WantedBy=multi-user.target
        """
    )


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python scripts/deploy_olcrtc_cell.py <cell_ip>")
    cell_ip = sys.argv[1].strip()
    # connect() uses DEPLOY_HOST; override via env for cell
    os.environ["DEPLOY_HOST"] = cell_ip
    client = connect()
    sftp = client.open_sftp()
    run(client, f"mkdir -p {REMOTE_OLCRTC}/data")

    bin_candidates = [
        Path(os.environ["OLCRTC_BIN"]) if os.environ.get("OLCRTC_BIN") else None,
        BACKEND_ROOT / "olcrtc" / "olcrtc",
        BACKEND_ROOT.parent / "vendor" / "olcrtc" / "olcrtc",
    ]
    uploaded = False
    for cand in bin_candidates:
        if cand and cand.is_file():
            sftp.put(str(cand), f"{REMOTE_OLCRTC}/olcrtc")
            run(client, f"chmod +x {REMOTE_OLCRTC}/olcrtc")
            print("upload binary", cand)
            uploaded = True
            break
    if not uploaded:
        print("WARN: no local olcrtc binary — leave remote as-is")

    sftp.putfo(io.BytesIO(_template_unit().encode()), "/tmp/olcrtc@.service")
    run(client, "mv /tmp/olcrtc@.service /etc/systemd/system/olcrtc@.service")
    run(client, "systemctl daemon-reload")
    sftp.close()
    client.close()
    print(f"Done — olcrtc template on cell {cell_ip}. Push yaml via cell-agent /v1/olcrtc/apply")


if __name__ == "__main__":
    main()
