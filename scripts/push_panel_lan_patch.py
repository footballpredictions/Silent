#!/usr/bin/env python3
"""Copy panel LAN-access hotpatch to the lab OpenWrt router. Password from env only."""

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
REMOTE_DIR = "/tmp/sv-lan-patch"

FILES = [
    ROOT / "dist" / "patch-lan" / "common.sh",
    ROOT / "dist" / "patch-lan" / "silent-api",
    ROOT / "dist" / "patch-lan" / "silent-entry",
    ROOT / "dist" / "patch-lan" / "hotpatch_panel_lan.sh",
]


def put_via_ssh(client: paramiko.SSHClient, local: Path, remote: str) -> None:
    """OpenWrt dropbear often has no SFTP — stream bytes over exec cat."""
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
    for path in FILES:
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
        client.exec_command(f"mkdir -p {REMOTE_DIR}")[1].channel.recv_exit_status()
        for path in FILES:
            put_via_ssh(client, path, f"{REMOTE_DIR}/{path.name}")
        _stdin, stdout, stderr = client.exec_command(f"sh {REMOTE_DIR}/hotpatch_panel_lan.sh")
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
