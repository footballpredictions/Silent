"""Validate a complete Keenetic CPU package without extracting executable files."""
import hashlib
import json
import os
import re
import tarfile

ARCHES = ("aarch64", "armv7", "armv5", "mipsel", "mips", "x86_64", "i386")
ABI = {"aarch64": (2, 1, 183), "armv7": (1, 1, 40), "armv5": (1, 1, 40),
       "mipsel": (1, 1, 8), "mips": (1, 2, 8), "x86_64": (2, 1, 62), "i386": (1, 1, 3)}


def normalize_arch(value):
    value = (value or "").strip().lower()
    return {"arm64": "aarch64", "armv7l": "armv7", "armv8l": "armv7", "armv5l": "armv5",
            "armv6l": "armv5", "amd64": "x86_64", "i686": "i386"}.get(value, value if value in ARCHES else None)


def filename_arch(filename):
    m = re.fullmatch(r"silent-vpn-keenetic-\d+\.\d+\.\d+-(aarch64|armv7|armv5|mipsel|mips|x86_64|i386)\.tar\.gz", filename)
    return m[1] if m else None


def inspect_package(path, arch, version):
    if arch not in ARCHES or not re.fullmatch(r"\d+\.\d+\.\d+", version) or os.path.getsize(path) > 64 * 1024 * 1024:
        raise ValueError("Keenetic: неверная архитектура, версия или размер")
    prefix = f"silent-vpn-keenetic-{version}/"
    required = {"ARCH", "VERSION", "PACKAGE.json", "install.sh", "uninstall.sh", "README.md", "RESEARCH.md", "THIRD_PARTY_LICENSES.txt",
                "files/network.sh", "files/guard.sh", "files/100-silent-keenetic.sh", "files/S99silent-keenetic",
                "files/ru-direct.domains", "files/ru-vpn.domains", f"bin/{arch}/silent-keenetic", f"bin/{arch}/spass"}
    try:
        with tarfile.open(path, "r:gz") as tf:
            seen = set()
            unpacked = 0
            for m in tf:
                rel = m.name.removeprefix(prefix)
                if (not m.name.startswith(prefix) or rel not in required or rel in seen or not m.isfile()
                        or m.mode & 0o7000 or m.size < 0 or m.size > 256 * 1024 * 1024):
                    raise ValueError("Keenetic: небезопасный состав архива")
                seen.add(rel)
                unpacked += m.size
                if unpacked > 256 * 1024 * 1024:
                    raise ValueError("Keenetic: слишком большой пакет")
            if seen != required:
                raise ValueError("Keenetic: неполный пакет")
            def read(name, limit):
                m = tf.getmember(prefix + name)
                if m.size > limit:
                    raise ValueError("Keenetic: неверный размер метаданных")
                return tf.extractfile(m).read()
            metadata = json.loads(read("PACKAGE.json", 4096))
            if (metadata.get("schema_version") != 1 or metadata.get("platform") != "keenetic"
                    or metadata.get("arch") != arch or metadata.get("version") != version
                    or not re.fullmatch(r"[0-9a-f]{64}", str(metadata.get("build_id", "")))
                    or read("ARCH", 32) != (arch + "\n").encode()
                    or read("VERSION", 64) != (version + "\n").encode()):
                raise ValueError("Keenetic: ARCH/VERSION/PACKAGE.json не совпадают")
            for binary in ("silent-keenetic", "spass"):
                member = tf.getmember(prefix + f"bin/{arch}/{binary}")
                head = tf.extractfile(member).read(65536)
                cls, endian, machine = ABI[arch]
                order = "little" if endian == 1 else "big"
                if (not member.mode & 0o111 or len(head) < 64 or head[:6] != b"\x7fELF" + bytes((cls, endian))
                        or int.from_bytes(head[18:20], order) != machine):
                    raise ValueError("Keenetic: неверный ELF CPU/endian")
                if cls == 1:
                    offset, size, count = (int.from_bytes(head[a:b], order) for a, b in ((28, 32), (42, 44), (44, 46)))
                else:
                    offset, size, count = (int.from_bytes(head[a:b], order) for a, b in ((32, 40), (54, 56), (56, 58)))
                if not 0 < count <= 128 or size < 32 or offset + size * count > len(head):
                    raise ValueError("Keenetic: повреждённый ELF")
                if any(int.from_bytes(head[offset+i*size:offset+i*size+4], order) == 3 for i in range(count)):
                    raise ValueError("Keenetic: нужен статический ELF")
    except (tarfile.TarError, OSError, UnicodeError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        raise ValueError("Keenetic: повреждённый пакет") from exc
    with open(path, "rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"platform": "keenetic", "unpacked_size": unpacked, "sha256": digest, "version": version, "build_id": metadata["build_id"]}


def installer_script(path):
    with tarfile.open(path, "r:gz") as tf:
        candidates = [m for m in tf if m.name.endswith("/install.sh") and m.isfile() and m.size <= 65536]
        if len(candidates) != 1:
            raise ValueError("Keenetic: неверный установщик")
        return tf.extractfile(candidates[0]).read()
