#!/usr/bin/env python3
"""Pack electron-builder linux-unpacked into a .deb (works from Windows)."""
from __future__ import annotations

import gzip
import hashlib
import io
import os
import stat
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNPACKED = ROOT / "build-linux" / "linux-unpacked"
OUT_DIR = ROOT / "build-linux"
RELEASES = ROOT.parent / "releases"
VERSION = "1.0.163"
PKG = "silent-vpn"
INSTALL_ROOT = f"opt/{PKG}"


def _tarinfo_dir(name: str, mtime: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name.rstrip("/") + "/")
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = mtime
    return info


def _taradd_file(tar: tarfile.TarFile, arcname: str, data: bytes, mode: int, mtime: int) -> None:
    info = tarfile.TarInfo(name=arcname)
    info.size = len(data)
    info.mode = mode
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = mtime
    tar.addfile(info, io.BytesIO(data))


def file_mode(path: Path) -> int:
    name = path.name.lower()
    if name in ("chrome-sandbox",):
        return 0o4755
    if name in ("silent-vpn", "wdtt-client", "wireguard-go", "silent-wg-helper"):
        return 0o755
    if path.suffix.lower() in (".so",):
        return 0o755
    # ELF without extension
    try:
        with path.open("rb") as f:
            mag = f.read(4)
        if mag == b"\x7fELF":
            return 0o755
    except OSError:
        pass
    return 0o644


def collect_data(mtime: int) -> tuple[bytes, list[tuple[str, str]], int]:
    md5s: list[tuple[str, str]] = []
    installed_size = 0
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.GNU_FORMAT, compresslevel=9) as tar:
        dirs = {
            "opt",
            INSTALL_ROOT,
            "usr",
            "usr/bin",
            "usr/libexec",
            "usr/lib",
            "usr/lib/systemd",
            "usr/lib/systemd/system",
            "usr/share",
            "usr/share/applications",
            "usr/share/icons",
            "usr/share/icons/hicolor",
            "usr/share/icons/hicolor/256x256",
            "usr/share/icons/hicolor/256x256/apps",
            "usr/share/polkit-1",
            "usr/share/polkit-1/actions",
            "usr/share/polkit-1/rules.d",
        }
        for d in sorted(dirs, key=lambda s: (s.count("/"), s)):
            tar.addfile(_tarinfo_dir(d, mtime))

        for src in UNPACKED.rglob("*"):
            if not src.is_file():
                continue
            rel = src.relative_to(UNPACKED).as_posix()
            arc = f"{INSTALL_ROOT}/{rel}"
            parent = str(Path(arc).parent).replace("\\", "/")
            parts = parent.split("/")
            acc = []
            for p in parts:
                acc.append(p)
                dname = "/".join(acc)
                if dname not in dirs:
                    dirs.add(dname)
                    tar.addfile(_tarinfo_dir(dname, mtime))
            data = src.read_bytes()
            mode = file_mode(src)
            _taradd_file(tar, arc, data, mode, mtime)
            digest = hashlib.md5(data).hexdigest()
            md5s.append((digest, arc))
            installed_size += len(data)

        desktop = (
            "[Desktop Entry]\n"
            "Name=Silent VPN\n"
            "Comment=Silent VPN\n"
            "Exec=/opt/silent-vpn/silent-vpn %U\n"
            "Icon=silent-vpn\n"
            "Terminal=false\n"
            "Type=Application\n"
            "Categories=Network;\n"
            "StartupWMClass=silent-vpn\n"
            "MimeType=x-scheme-handler/silentvpn;\n"
        ).encode("utf-8")
        _taradd_file(tar, "usr/share/applications/silent-vpn.desktop", desktop, 0o644, mtime)
        md5s.append((hashlib.md5(desktop).hexdigest(), "usr/share/applications/silent-vpn.desktop"))

        wrapper = (
            "#!/bin/sh\n"
            "exec /opt/silent-vpn/silent-vpn \"$@\"\n"
        ).encode("utf-8")
        _taradd_file(tar, "usr/bin/silent-vpn", wrapper, 0o755, mtime)
        md5s.append((hashlib.md5(wrapper).hexdigest(), "usr/bin/silent-vpn"))

        icon_src = ROOT / "assets" / "icon.png"
        if icon_src.is_file():
            icon = icon_src.read_bytes()
            _taradd_file(tar, "usr/share/icons/hicolor/256x256/apps/silent-vpn.png", icon, 0o644, mtime)
            md5s.append((hashlib.md5(icon).hexdigest(), "usr/share/icons/hicolor/256x256/apps/silent-vpn.png"))
            installed_size += len(icon)

        extras = [
            (
                "usr/libexec/silent-vpn-wg-helper",
                ROOT / "resources" / "linux" / "silent-wg-helper",
                0o755,
            ),
            (
                "usr/lib/systemd/system/silent-vpn-helper.service",
                ROOT / "resources" / "linux" / "silent-vpn-helper.service",
                0o644,
            ),
            (
                "usr/share/polkit-1/actions/ru.silent.vpn.wg.policy",
                ROOT / "resources" / "linux" / "ru.silent.vpn.wg.policy",
                0o644,
            ),
            (
                "usr/share/polkit-1/rules.d/ru.silent.vpn.rules",
                ROOT / "resources" / "linux" / "ru.silent.vpn.rules",
                0o644,
            ),
        ]
        extra_bytes = 0
        for arc, src, mode in extras:
            if not src.is_file():
                raise SystemExit(f"missing {src}")
            data = src.read_bytes()
            if src.name == "silent-wg-helper":
                data = data.replace(b"\r\n", b"\n")
            _taradd_file(tar, arc, data, mode, mtime)
            md5s.append((hashlib.md5(data).hexdigest(), arc))
            extra_bytes += len(data)

        installed_size += len(desktop) + len(wrapper) + extra_bytes
    return buf.getvalue(), md5s, installed_size


def control_tar(md5s: list[tuple[str, str]], installed_size: int, mtime: int) -> bytes:
    control = (
        f"Package: {PKG}\n"
        f"Version: {VERSION}\n"
        "Section: net\n"
        "Priority: optional\n"
        "Architecture: amd64\n"
        "Maintainer: Silent VPN <noreply@silent>\n"
        "Depends: libgtk-3-0, libnotify4, libnss3, libxtst6, xdg-utils, libatspi2.0-0, libuuid1, python3, policykit-1, iproute2, systemd\n"
        f"Installed-Size: {max(1, installed_size // 1024)}\n"
        "Homepage: https://132-243-234-162.nip.io\n"
        "Description: Silent VPN desktop client\n"
        " Same app as Windows Silent VPN. Double-click this package to install.\n"
    ).encode("utf-8")
    md5text = "".join(f"{h}  {p}\n" for h, p in md5s).encode("utf-8")
    postinst = (
        "#!/bin/sh\n"
        "set -e\n"
        "BIN=/opt/silent-vpn/silent-vpn\n"
        "SANDBOX=/opt/silent-vpn/chrome-sandbox\n"
        "if [ -f \"$SANDBOX\" ]; then chmod 4755 \"$SANDBOX\" || true; fi\n"
        "chmod 755 \"$BIN\" || true\n"
        "chmod 755 /opt/silent-vpn/resources/wdtt-client 2>/dev/null || true\n"
        "chmod 755 /opt/silent-vpn/resources/silent-wg-helper 2>/dev/null || true\n"
        "chmod 755 /opt/silent-vpn/resources/wireguard-go 2>/dev/null || true\n"
        "chmod 755 /usr/libexec/silent-vpn-wg-helper 2>/dev/null || true\n"
        "if command -v update-desktop-database >/dev/null 2>&1; then\n"
        "  update-desktop-database -q /usr/share/applications || true\n"
        "fi\n"
        "if command -v xdg-mime >/dev/null 2>&1; then\n"
        "  xdg-mime default silent-vpn.desktop x-scheme-handler/silentvpn || true\n"
        "fi\n"
        "if [ -d /run/systemd/system ]; then\n"
        "  systemctl daemon-reload || true\n"
        "  systemctl enable silent-vpn-helper.service >/dev/null 2>&1 || true\n"
        "  systemctl restart silent-vpn-helper.service || true\n"
        "fi\n"
        "exit 0\n"
    ).encode("utf-8")
    prerm = (
        "#!/bin/sh\n"
        "set -e\n"
        "if [ -d /run/systemd/system ]; then\n"
        "  systemctl stop silent-vpn-helper.service >/dev/null 2>&1 || true\n"
        "fi\n"
        "exit 0\n"
    ).encode("utf-8")
    postrm = (
        "#!/bin/sh\n"
        "set -e\n"
        "if [ \"$1\" = remove ] || [ \"$1\" = purge ]; then\n"
        "  if [ -d /run/systemd/system ]; then\n"
        "    systemctl disable silent-vpn-helper.service >/dev/null 2>&1 || true\n"
        "    systemctl daemon-reload || true\n"
        "  fi\n"
        "  rm -f /run/silent-vpn/helper.sock\n"
        "fi\n"
        "exit 0\n"
    ).encode("utf-8")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.GNU_FORMAT, compresslevel=9) as tar:
        _taradd_file(tar, "control", control, 0o644, mtime)
        _taradd_file(tar, "md5sums", md5text, 0o644, mtime)
        _taradd_file(tar, "postinst", postinst, 0o755, mtime)
        _taradd_file(tar, "prerm", prerm, 0o755, mtime)
        _taradd_file(tar, "postrm", postrm, 0o755, mtime)
    return buf.getvalue()


def ar_member(name: str, data: bytes, mtime: int) -> bytes:
    # GNU ar header: 16 name, 12 mtime, 6 uid, 6 gid, 8 mode, 10 size, 2 magic
    hdr = (
        name.ljust(16).encode("ascii")
        + str(mtime).ljust(12).encode("ascii")
        + b"0     "
        + b"0     "
        + b"100644  "
        + str(len(data)).ljust(10).encode("ascii")
        + b"`\n"
    )
    if len(data) % 2 == 1:
        data = data + b"\n"
    return hdr + data


def main() -> None:
    if not UNPACKED.is_dir():
        raise SystemExit(f"missing unpacked app: {UNPACKED}")
    exe = UNPACKED / "silent-vpn"
    if not exe.is_file():
        cands = [p for p in UNPACKED.iterdir() if p.is_file() and p.stat().st_size > 1_000_000]
        exe = cands[0] if cands else None
    if not exe or not exe.is_file():
        raise SystemExit(f"missing binary in {UNPACKED}")
    mtime = int(time.time())
    data_tar, md5s, installed_size = collect_data(mtime)
    ctrl_tar = control_tar(md5s, installed_size, mtime)
    debian_binary = b"2.0\n"
    deb = (
        b"!<arch>\n"
        + ar_member("debian-binary", debian_binary, mtime)
        + ar_member("control.tar.gz", ctrl_tar, mtime)
        + ar_member("data.tar.gz", data_tar, mtime)
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    debian_name = OUT_DIR / f"{PKG}_{VERSION}_amd64.deb"
    friendly = OUT_DIR / f"Silent VPN Setup {VERSION}.deb"
    debian_name.write_bytes(deb)
    friendly.write_bytes(deb)
    RELEASES.mkdir(parents=True, exist_ok=True)
    (RELEASES / friendly.name).write_bytes(deb)
    print(f"OK {friendly} ({len(deb)} bytes)")
    print(f"OK {RELEASES / friendly.name}")


if __name__ == "__main__":
    main()
