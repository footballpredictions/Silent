"""Pack OpenWrt installers; an architecture package contains one static ELF."""

from __future__ import annotations

import io
import hashlib
import json
import tarfile
from pathlib import Path

SKIP_WEB = {"toggle-demo.html"}
SKIP_DIR_NAMES = {"__pycache__", ".preview-cache"}
EXEC_SUFFIXES = {".sh"}
EXEC_NAMES = {"silent-vpn-ctl", "silent-entry", "silent-api", "99-silent-vpn", "remote-install.sh"}
ARCHES = ("aarch64", "arm", "mipsel", "x86_64")
ELF_ABI = {"aarch64": (2, 183), "arm": (1, 40), "mipsel": (1, 8), "x86_64": (2, 62)}


def validate_binary(data: bytes, arch: str) -> None:
    elf_class, machine = ELF_ABI[arch]
    if (len(data) < 52 or data[:4] != b"\x7fELF" or data[4:6] != bytes((elf_class, 1))
            or int.from_bytes(data[18:20], "little") != machine):
        raise ValueError(f"Invalid little-endian Linux ELF for {arch}")


def read_version(root: Path) -> str:
    return (root / "VERSION").read_text(encoding="utf-8").strip()


def artifact_name(version: str, arch: str | None = None) -> str:
    if arch is not None and arch not in ARCHES:
        raise ValueError(f"Unsupported architecture: {arch}")
    return f"silent-vpn-openwrt-{version}{'-' + arch if arch else ''}.tar.gz"


def _is_exec(path: Path) -> bool:
    return (
        path.suffix in EXEC_SUFFIXES
        or path.name in EXEC_NAMES
        or path.name.startswith("wdtt-client.")
        or path.read_bytes().startswith(b"#!")
    )


def iter_release_files(root: Path, arch: str | None = None) -> list[tuple[Path, str]]:
    """Return (absolute path, archive name under silent-vpn/)."""
    rows: list[tuple[Path, str]] = []
    rows.append((root / "install.sh", "silent-vpn/install.sh"))
    rows.append((root / "VERSION", "silent-vpn/VERSION"))
    uninstall = root / "uninstall.sh"
    if uninstall.is_file():
        rows.append((uninstall, "silent-vpn/uninstall.sh"))
    remote = root / "remote-install.sh"
    if remote.is_file():
        rows.append((remote, "silent-vpn/remote-install.sh"))
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
            if arch and rel.startswith("files/usr/lib/silent-vpn/wdtt/") and path.name != f"wdtt-client.{arch}":
                continue
            rows.append((path, f"silent-vpn/{rel}"))
    return rows


def write_tarball(root: Path, dest: Path, arch: str | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    members = iter_release_files(root, arch)
    if arch:
        validate_binary((root / f"files/usr/lib/silent-vpn/wdtt/wdtt-client.{arch}").read_bytes(), arch)
    with tarfile.open(dest, "w:gz", format=tarfile.USTAR_FORMAT) as tar:
        for src, arcname in members:
            data = src.read_bytes()
            # A Windows checkout may have CRLF even when Git stores LF.
            # Normalize shell scripts, sourced helpers and DNS domain lists;
            # native binaries must keep their original bytes.
            if src.suffix in {".sh", ".domains"} or data.startswith(b"#!"):
                data = data.replace(b"\r\n", b"\n")
            info = tar.gettarinfo(str(src), arcname)
            info.size = len(data)
            info.uid = 0
            info.gid = 0
            info.uname = "root"
            info.gname = "root"
            info.mode = 0o755 if _is_exec(src) else 0o644
            tar.addfile(info, io.BytesIO(data))
        if arch:
            digest = hashlib.sha256()
            for source, name in iter_release_files(root):
                content = source.read_bytes()
                if source.suffix in {".sh", ".domains"} or content.startswith(b"#!"):
                    content = content.replace(b"\r\n", b"\n")
                digest.update(name.encode() + b"\0" + hashlib.sha256(content).digest())
            metadata = {"schema_version": 1, "arch": arch, "version": read_version(root), "build_id": digest.hexdigest()}
            data = json.dumps(metadata, sort_keys=True).encode() + b"\n"
            for name, content in (("ARCH", arch.encode() + b"\n"), ("PACKAGE.json", data)):
                info = tarfile.TarInfo(f"silent-vpn/{name}")
                info.mode = 0o644
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
    return dest


def package_info(path: Path, arch: str, version: str) -> dict:
    with tarfile.open(path, "r:gz") as archive:
        # Round up each file for overlay/tmp filesystem allocation.
        unpacked = sum(((m.size + 4095) // 4096) * 4096 for m in archive if m.isfile())
        build_id = json.load(archive.extractfile("silent-vpn/PACKAGE.json"))["build_id"]
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"arch": arch, "version": version, "filename": path.name,
            "size": path.stat().st_size, "unpacked_size": unpacked,
            "sha256": digest, "build_id": build_id}
