"""Pack architecture-independent OpenWrt installer (scripts + web, no binaries)."""

from __future__ import annotations

import tarfile
from pathlib import Path

SKIP_WEB = {"toggle-demo.html"}
SKIP_DIR_NAMES = {"__pycache__", ".preview-cache"}
EXEC_SUFFIXES = {".sh"}
EXEC_NAMES = {"silent-vpn-ctl", "silent-entry", "silent-api", "99-silent-vpn"}


def read_version(root: Path) -> str:
    return (root / "VERSION").read_text(encoding="utf-8").strip()


def artifact_name(version: str) -> str:
    return f"silent-vpn-openwrt-{version}.tar.gz"


def _is_exec(path: Path) -> bool:
    return path.suffix in EXEC_SUFFIXES or path.name in EXEC_NAMES


def iter_release_files(root: Path) -> list[tuple[Path, str]]:
    """Return (absolute path, archive name under silent-vpn/)."""
    rows: list[tuple[Path, str]] = []
    rows.append((root / "install.sh", "silent-vpn/install.sh"))
    rows.append((root / "VERSION", "silent-vpn/VERSION"))
    for folder in ("files", "web"):
        base = root / folder
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            if folder == "web" and path.name in SKIP_WEB:
                continue
            rel = path.relative_to(root).as_posix()
            rows.append((path, f"silent-vpn/{rel}"))
    return rows


def write_tarball(root: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    members = iter_release_files(root)
    with tarfile.open(dest, "w:gz", format=tarfile.USTAR_FORMAT) as tar:
        for src, arcname in members:
            info = tar.gettarinfo(str(src), arcname)
            info.uid = 0
            info.gid = 0
            info.uname = "root"
            info.gname = "root"
            info.mode = 0o755 if _is_exec(src) else 0o644
            with src.open("rb") as fh:
                tar.addfile(info, fh)
    return dest
