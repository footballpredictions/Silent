#!/usr/bin/env python3
"""Copy panel session/devices/UI hotpatch to the lab OpenWrt router. Password from env only."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
HOST = os.environ.get("OPENWRT_HOST", "192.168.1.1")
USER = os.environ.get("OPENWRT_USER", "root")
PASSWORD = os.environ.get("OPENWRT_ROOT_PASSWORD", "")
if not PASSWORD:
    for candidate in (
        Path.home() / ".silent-openwrt-pass",
        ROOT.parent / ".silent-openwrt-pass",
    ):
        if candidate.is_file():
            PASSWORD = candidate.read_text(encoding="utf-8").strip()
            break
REMOTE_DIR = "/tmp/sv-panel-session"

FILES = [
    (ROOT / "files/usr/lib/silent-vpn/session.sh", "session.sh"),
    (ROOT / "files/usr/lib/silent-vpn/hive.sh", "hive.sh"),
    (ROOT / "files/usr/sbin/silent-vpn-ctl", "silent-vpn-ctl"),
    (ROOT / "files/www/cgi-bin/silent-api", "silent-api"),
    (ROOT / "web/index.html", "web/index.html"),
    (ROOT / "web/js/app.js", "web/app.js"),
    (ROOT / "web/js/api.js", "web/api.js"),
    (ROOT / "web/css/app.css", "web/app.css"),
    (ROOT / "scripts/hotpatch_panel_session.sh", "hotpatch_panel_session.sh"),
]


def put_via_ssh(client: paramiko.SSHClient, local: Path, remote: str) -> None:
    data = local.read_bytes().replace(b"\r\n", b"\n")
    stdin, stdout, stderr = client.exec_command(f"cat > {remote}")
    stdin.write(data)
    stdin.channel.shutdown_write()
    code = stdout.channel.recv_exit_status()
    err = stderr.read().decode("utf-8", "replace")
    if code != 0:
        raise RuntimeError(f"upload {local.name} failed ({code}): {err}")


def main() -> int:
    if not PASSWORD:
        print(
            "Set OPENWRT_ROOT_PASSWORD (router LuCI/root password). No password in repo.",
            file=sys.stderr,
        )
        return 2
    for path, _name in FILES:
        if not path.is_file():
            print(f"missing {path}", file=sys.stderr)
            return 2
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST,
        username=USER,
        password=PASSWORD,
        timeout=20,
        allow_agent=False,
        look_for_keys=False,
    )
    try:
        client.exec_command(f"mkdir -p {REMOTE_DIR}/web")[1].channel.recv_exit_status()
        for path, remote_name in FILES:
            put_via_ssh(client, path, f"{REMOTE_DIR}/{remote_name}")
        _stdin, stdout, stderr = client.exec_command(
            f"chmod +x {REMOTE_DIR}/hotpatch_panel_session.sh; sh {REMOTE_DIR}/hotpatch_panel_session.sh"
        )
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        sys.stdout.write(out)
        if err:
            sys.stderr.write(err)
        return code
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
