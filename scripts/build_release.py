#!/usr/bin/env python3
"""Build universal OpenWrt installer tarball (all architectures)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.silent_release import artifact_name, read_version, write_tarball  # noqa: E402


def main() -> int:
    version = read_version(ROOT)
    dest = ROOT / "dist" / artifact_name(version)
    write_tarball(ROOT, dest)
    print(f"Built {dest} ({dest.stat().st_size} bytes)")
    print("Universal: shell + web only, no CPU-specific binaries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
