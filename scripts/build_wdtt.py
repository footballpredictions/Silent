#!/usr/bin/env python3
"""Cross-compile wdtt-client for OpenWrt arches (static Go, CGO off)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WDTT_SRC = ROOT.parent / "pc" / "wdtt-go"
OUT = ROOT / "files" / "usr" / "lib" / "silent-vpn" / "wdtt"

TARGETS = (
    ("aarch64", "arm64", {}),
    ("arm", "arm", {"GOARM": "7"}),
    ("mipsel", "mipsle", {"GOMIPS": "softfloat"}),
    ("x86_64", "amd64", {}),
)


def main() -> int:
    if not (WDTT_SRC / "go.mod").is_file():
        print(f"wdtt source not found: {WDTT_SRC}", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    env_base = os.environ.copy()
    env_base["CGO_ENABLED"] = "0"
    env_base["GOOS"] = "linux"
    env_base["GOTOOLCHAIN"] = env_base.get("GOTOOLCHAIN") or "local"
    env_base.setdefault("GOPROXY", "https://proxy.golang.org,direct")
    for name, goarch, extra in TARGETS:
        dest = OUT / f"wdtt-client.{name}"
        env = env_base.copy()
        env["GOARCH"] = goarch
        env.update(extra)
        print(f"wdtt-client.{name} ({goarch})...")
        subprocess.run(
            [
                "go",
                "build",
                "-ldflags=-s -w -checklinkname=0",
                "-trimpath",
                "-o",
                str(dest),
                ".",
            ],
            cwd=WDTT_SRC,
            env=env,
            check=True,
        )
        print(f"  {dest.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
