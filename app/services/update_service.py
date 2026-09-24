"""App update files stored in update/{platform}/ on the server."""
import json
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Optional

PLATFORMS = ("pc", "android", "linux", "mac", "openwrt")
MAC_ARCHES = ("x64", "arm64")
MANIFEST = "manifest.json"
UPLOAD_EXTS = {
    "pc": (".exe", ".msi"),
    "android": (".apk",),
    "linux": (".appimage", ".deb"),
    "mac": (".dmg", ".zip", ".pkg"),
    "openwrt": (".tar.gz", ".tgz"),
}

_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "update"))


def upload_suffix(filename: str) -> str:
    """Расширение для проверки загрузки (.tar.gz целиком, не .gz)."""
    name = (filename or "").lower()
    if name.endswith(".tar.gz"):
        return ".tar.gz"
    return os.path.splitext(name)[1]


def allowed_upload_exts(platform: str) -> tuple[str, ...]:
    return UPLOAD_EXTS.get(platform.lower().strip(), ())


def _platform_dir(platform: str) -> str:
    p = platform.lower().strip()
    if p not in PLATFORMS:
        raise ValueError(f"Unknown platform: {platform}")
    return os.path.join(_BASE, p)


def ensure_dirs() -> None:
    os.makedirs(_BASE, exist_ok=True)
    for p in PLATFORMS:
        os.makedirs(_platform_dir(p), exist_ok=True)


def _manifest_path(platform: str) -> str:
    return os.path.join(_platform_dir(platform), MANIFEST)


def _read_manifest(platform: str) -> Optional[dict]:
    path = _manifest_path(platform)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _write_manifest(platform: str, data: dict) -> None:
    ensure_dirs()
    path = _manifest_path(platform)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _parse_version(v: str) -> tuple:
    parts = re.findall(r"\d+", v or "0")
    return tuple(int(x) for x in parts) if parts else (0,)


def is_newer(latest: str, current: str) -> bool:
    return _parse_version(latest) > _parse_version(current)


def normalize_mac_arch(arch: Optional[str]) -> Optional[str]:
    a = (arch or "").strip().lower().replace("_", "")
    if a in ("x64", "amd64", "x8664", "intel"):
        return "x64"
    if a in ("arm64", "aarch64", "arm"):
        return "arm64"
    return None


def arch_from_filename(filename: str) -> Optional[str]:
    n = (filename or "").lower()
    if "arm64" in n or "aarch64" in n:
        return "arm64"
    if "x64" in n or "amd64" in n or "x86_64" in n:
        return "x64"
    return None


def _mac_files(manifest: Optional[dict]) -> dict:
    files = (manifest or {}).get("files")
    return dict(files) if isinstance(files, dict) else {}


def _mac_primary_arch(files: dict) -> Optional[str]:
    """Старые клиенты без arch берут Intel, если он есть."""
    if (files.get("x64") or {}).get("filename"):
        return "x64"
    if (files.get("arm64") or {}).get("filename"):
        return "arm64"
    return None


def _download_url(platform: str, filename: str) -> str:
    from urllib.parse import quote
    return f"/update/{platform}/{quote(filename)}"


def _annotate_mac_files(platform: str, entry: dict) -> dict:
    files = _mac_files(entry)
    if platform != "mac" or not files:
        return entry
    annotated = {}
    for arch, slot in files.items():
        if not isinstance(slot, dict) or not slot.get("filename"):
            continue
        row = dict(slot)
        path = os.path.join(_platform_dir(platform), slot["filename"])
        if os.path.isfile(path):
            row["download_url"] = _download_url(platform, slot["filename"])
            row["file_path"] = path
        annotated[arch] = row
    entry["files"] = annotated
    return entry


def list_all() -> list[dict]:
    ensure_dirs()
    out = []
    for platform in PLATFORMS:
        m = _read_manifest(platform)
        if m and m.get("filename"):
            fn = m["filename"]
            file_path = os.path.join(_platform_dir(platform), fn)
            entry = {"platform": platform, **m}
            if os.path.isfile(file_path):
                entry["download_url"] = _download_url(platform, fn)
            out.append(_annotate_mac_files(platform, entry))
        elif m:
            out.append(_annotate_mac_files(platform, {"platform": platform, **m}))
        else:
            out.append({"platform": platform, "version": None, "filename": None, "uploaded_at": None, "size": 0})
    return out


def mac_binaries(latest: dict) -> list[dict]:
    """Оба DMG Mac, если лежат на диске. Один старый файл без arch — как x64."""
    files = _mac_files(latest)
    if not files and latest.get("filename"):
        arch = arch_from_filename(latest["filename"]) or "x64"
        files = {arch: {"filename": latest["filename"], "size": latest.get("size") or 0}}
    out = []
    base = _platform_dir("mac")
    for arch in MAC_ARCHES:
        slot = files.get(arch) or {}
        fn = slot.get("filename")
        if not fn:
            continue
        path = slot.get("file_path") or os.path.join(base, fn)
        if not os.path.isfile(path):
            continue
        out.append({
            "arch": arch,
            "filename": fn,
            "file_path": path,
            "size": slot.get("size") or os.path.getsize(path),
            "github_download_url": slot.get("github_download_url") or "",
        })
    return out


def get_latest(platform: str, arch: Optional[str] = None) -> Optional[dict]:
    m = _read_manifest(platform)
    if not m:
        return None
    want = normalize_mac_arch(arch) if platform == "mac" else None
    if want:
        slot = _mac_files(m).get(want) or {}
        if not slot.get("filename"):
            return None
        picked = {
            **m,
            "filename": slot["filename"],
            "size": slot.get("size") or 0,
            "uploaded_at": slot.get("uploaded_at") or m.get("uploaded_at"),
            "github_download_url": slot.get("github_download_url") or "",
            "arch": want,
        }
    else:
        if not m.get("filename"):
            return None
        picked = dict(m)
    file_path = os.path.join(_platform_dir(platform), picked["filename"])
    if not os.path.isfile(file_path):
        if not picked.get("github_download_url"):
            return None
    result = {
        **picked,
        "platform": platform,
        "file_path": file_path if os.path.isfile(file_path) else None,
        "download_url": f"/update/{platform}/{picked['filename']}",
    }
    return _annotate_mac_files(platform, result)


def resolve_download_url(latest: dict) -> Optional[str]:
    """Приоритет: GitHub Releases (как landing), иначе локальный /update/ на VPS."""
    gh = (latest.get("github_download_url") or "").strip()
    if gh:
        return gh
    file_path = latest.get("file_path")
    if file_path and os.path.isfile(file_path):
        return latest.get("download_url")
    fn = latest.get("filename")
    ver = latest.get("version")
    if fn and ver:
        from app.services.github_release_service import asset_download_url
        return asset_download_url(ver, fn)
    return None


def _resolve_download_url(latest: dict) -> Optional[str]:
    return resolve_download_url(latest)


def check_update(platform: str, current_version: str, arch: Optional[str] = None) -> Optional[dict]:
    latest = get_latest(platform, arch=arch)
    if not latest:
        return None
    if not is_newer(latest["version"], current_version):
        return None
    primary = _resolve_download_url(latest)
    if not primary:
        return None
    out = {
        "available": True,
        "version": latest["version"],
        "filename": latest["filename"],
        "size": latest.get("size", 0),
        "uploaded_at": latest.get("uploaded_at"),
        "download_url": primary,
    }
    gh = (latest.get("github_download_url") or "").strip()
    if gh:
        out["github_download_url"] = gh
    elif primary.startswith("https://github.com/"):
        out["github_download_url"] = primary
    tunnel = f"/api/updates/download/{platform}"
    if latest.get("arch"):
        tunnel = f"{tunnel}?arch={latest['arch']}"
    out["tunnel_download_url"] = tunnel
    if latest.get("arch"):
        out["arch"] = latest["arch"]
    return out


def _cleanup_platform_dir(platform: str, keep_filename: str, extra_keep: Optional[set] = None) -> None:
    keep = {keep_filename}
    if extra_keep:
        keep |= {n for n in extra_keep if n}
    d = _platform_dir(platform)
    for name in os.listdir(d):
        if name == MANIFEST or name in keep:
            continue
        path = os.path.join(d, name)
        try:
            if os.path.isfile(path):
                os.remove(path)
            elif os.path.isdir(path):
                shutil.rmtree(path)
        except OSError:
            pass


def publish_file(
    platform: str,
    filename: str,
    src_path: str,
    version: Optional[str] = None,
    arch: Optional[str] = None,
) -> dict:
    """Replace platform update with a new file. Mac keeps the other architecture."""
    ensure_dirs()
    safe_name = os.path.basename(filename)
    if not safe_name or safe_name == MANIFEST:
        raise ValueError("Invalid filename")

    if not version:
        m = re.search(r"(\d+\.\d+\.\d+)", safe_name)
        version = m.group(1) if m else "0.0.0"

    dest_dir = _platform_dir(platform)
    dest_path = os.path.join(dest_dir, safe_name)
    uploaded_at = datetime.now(timezone.utc).isoformat()

    if platform == "mac":
        arch_norm = normalize_mac_arch(arch) or arch_from_filename(safe_name)
        if not arch_norm:
            raise ValueError("Mac: укажите архитектуру x64 или arm64 (в имени файла -x64 или -arm64)")
        prev = _read_manifest(platform) or {}
        files = _mac_files(prev)
        if prev.get("filename") and not files:
            old_arch = arch_from_filename(prev["filename"]) or "x64"
            files[old_arch] = {
                "filename": prev["filename"],
                "size": prev.get("size") or 0,
                "uploaded_at": prev.get("uploaded_at"),
                "github_download_url": prev.get("github_download_url") or "",
            }
        keep = {
            (files.get(a) or {}).get("filename")
            for a in MAC_ARCHES
            if a != arch_norm and (files.get(a) or {}).get("filename")
        }
        keep.add(safe_name)
        _cleanup_platform_dir(platform, safe_name, keep)
        shutil.copy2(src_path, dest_path)
        size = os.path.getsize(dest_path)
        files[arch_norm] = {
            "filename": safe_name,
            "size": size,
            "uploaded_at": uploaded_at,
        }
        primary = _mac_primary_arch(files) or arch_norm
        slot = files[primary]
        manifest = {
            "version": version,
            "filename": slot["filename"],
            "size": slot.get("size") or 0,
            "uploaded_at": slot.get("uploaded_at") or uploaded_at,
            "files": files,
        }
        if prev.get("github_download_url") and primary != arch_norm:
            manifest["github_download_url"] = prev.get("github_download_url")
        _write_manifest(platform, manifest)
        return {
            "platform": platform,
            "arch": arch_norm,
            **manifest,
            "download_url": f"/update/{platform}/{safe_name}",
        }

    _cleanup_platform_dir(platform, safe_name)
    shutil.copy2(src_path, dest_path)
    size = os.path.getsize(dest_path)
    manifest = {
        "version": version,
        "filename": safe_name,
        "size": size,
        "uploaded_at": uploaded_at,
    }
    _write_manifest(platform, manifest)
    return {"platform": platform, **manifest, "download_url": f"/update/{platform}/{safe_name}"}


def delete_platform_update(platform: str, arch: Optional[str] = None) -> bool:
    m = _read_manifest(platform)
    want = normalize_mac_arch(arch) if platform == "mac" else None
    if want and m:
        files = _mac_files(m)
        slot = files.pop(want, None) or {}
        fn = slot.get("filename")
        if fn:
            fp = os.path.join(_platform_dir(platform), fn)
            if os.path.isfile(fp):
                os.remove(fp)
        primary = _mac_primary_arch(files)
        if not primary:
            mp = _manifest_path(platform)
            if os.path.isfile(mp):
                os.remove(mp)
            return True
        slot = files[primary]
        m["files"] = files
        m["filename"] = slot["filename"]
        m["size"] = slot.get("size") or 0
        m["uploaded_at"] = slot.get("uploaded_at")
        m["github_download_url"] = slot.get("github_download_url") or ""
        _write_manifest(platform, m)
        return True
    if m and m.get("filename"):
        names = {m["filename"]}
        for slot in _mac_files(m).values():
            if isinstance(slot, dict) and slot.get("filename"):
                names.add(slot["filename"])
        for fn in names:
            fp = os.path.join(_platform_dir(platform), fn)
            if os.path.isfile(fp):
                os.remove(fp)
    mp = _manifest_path(platform)
    if os.path.isfile(mp):
        os.remove(mp)
        return True
    return False
