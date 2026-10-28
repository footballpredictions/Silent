#!/usr/bin/env python3
"""Canonical build: compile transport and produce four architecture packages."""

from __future__ import annotations

import sys
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.silent_release import ARCHES, artifact_name, package_info, read_version, write_tarball  # noqa: E402
from build_wdtt import main as build_transport  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-transport", action="store_true", help="Package already built, validated ELF binaries (development only)")
    args = parser.parse_args()
    if not args.skip_transport and build_transport():
        return 1
    version = read_version(ROOT)
    packages = {}
    for arch in ARCHES:
        dest = ROOT / "dist" / artifact_name(version, arch)
        write_tarball(ROOT, dest, arch)
        packages[arch] = package_info(dest, arch, version)
        print(f"Built {dest} ({dest.stat().st_size} bytes)")
    manifest = ROOT / "dist" / "openwrt-packages.json"
    manifest.write_text(json.dumps({"version": version, "arches": packages}, indent=2) + "\n", encoding="utf-8")
    (ROOT / "dist" / "SHA256SUMS").write_text("".join(f"{p['sha256']}  {p['filename']}\n" for p in packages.values()), encoding="ascii")
    for source, target in (("remote-install.sh", "router-install.sh"), ("remote-install.sh", "openwrt-install.sh"), ("uninstall.sh", "openwrt-uninstall.sh")):
        (ROOT / "dist" / target).write_bytes((ROOT / source).read_bytes().replace(b"\r\n", b"\n"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
