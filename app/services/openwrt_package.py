"""Validate a router package without extracting untrusted archive members."""
import hashlib
import json
import re
import tarfile
from pathlib import PurePosixPath

ARCHES = ("aarch64", "arm", "mipsel", "x86_64")
ELF_ABI = {"aarch64": (2, 183), "arm": (1, 40), "mipsel": (1, 8), "x86_64": (2, 62)}


def normalize_arch(value: str | None) -> str | None:
    value = (value or "").lower().strip()
    return {"arm64": "aarch64", "armv7l": "arm", "armv8l": "arm", "amd64": "x86_64"}.get(value, value if value in ARCHES else None)


def filename_arch(filename: str) -> str | None:
    match = re.search(r"-(aarch64|arm|mipsel|x86_64)\.(?:tar\.gz|tgz)$", filename.lower())
    return match.group(1) if match else None


def inspect_package(path: str, arch: str, version: str) -> dict:
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            if len(members) > 2048 or sum(m.size for m in members) > 64 * 1024 * 1024:
                raise ValueError("OpenWrt: слишком большой пакет")
            names = set()
            unpacked = 0
            for member in members:
                p = PurePosixPath(member.name)
                if (p.is_absolute() or ".." in p.parts or p.parts[:1] != ("silent-vpn",)
                        or not (member.isfile() or member.isdir()) or member.name in names):
                    raise ValueError("OpenWrt: некорректный состав архива")
                names.add(member.name)
                if member.isfile():
                    unpacked += ((member.size + 4095) // 4096) * 4096
            metadata_member = archive.getmember("silent-vpn/PACKAGE.json")
            if metadata_member.size > 4096:
                raise ValueError("OpenWrt: слишком большие метаданные")
            metadata = json.load(archive.extractfile(metadata_member))
            if (not isinstance(metadata, dict) or metadata.get("schema_version") != 1
                    or metadata.get("arch") != arch or metadata.get("version") != version
                    or not re.fullmatch(r"[0-9a-f]{64}", str(metadata.get("build_id", "")))):
                raise ValueError("OpenWrt: архитектура или версия внутри пакета не совпадает")
            if archive.extractfile("silent-vpn/ARCH").read(32).decode().strip() != arch:
                raise ValueError("OpenWrt: неверная архитектура ARCH")
            prefix = "silent-vpn/files/usr/lib/silent-vpn/wdtt/"
            binaries = {m.name for m in members if m.isfile() and m.name.startswith(prefix)}
            expected = prefix + f"wdtt-client.{arch}"
            if binaries != {expected}:
                raise ValueError("OpenWrt: пакет должен содержать один бинарник нужной архитектуры")
            data = archive.extractfile(expected).read(64)
            elf_class, machine = ELF_ABI[arch]
            if (len(data) < 52 or data[:6] != b"\x7fELF" + bytes((elf_class, 1))
                    or int.from_bytes(data[18:20], "little") != machine):
                raise ValueError("OpenWrt: бинарник не соответствует архитектуре")
            for name in ("install.sh", "remote-install.sh", "VERSION"):
                archive.getmember("silent-vpn/" + name)
            if archive.extractfile("silent-vpn/VERSION").read(64).decode().strip() != version:
                raise ValueError("OpenWrt: неверная VERSION")
    except (tarfile.TarError, KeyError, OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("OpenWrt: повреждённый пакет сборки") from exc
    with open(path, "rb") as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"unpacked_size": unpacked, "sha256": digest.hexdigest(), "version": version, "build_id": metadata["build_id"]}


def installer_script(path: str) -> bytes:
    with tarfile.open(path, "r:gz") as archive:
        member = archive.getmember("silent-vpn/remote-install.sh")
        if not member.isfile() or member.size > 64 * 1024:
            raise ValueError("OpenWrt: неверный установщик")
        return archive.extractfile(member).read()
