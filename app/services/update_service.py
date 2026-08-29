"""App update files stored in update/{platform}/ on the server."""
import json
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Optional

PLATFORMS = ("pc", "android", "linux")
MANIFEST = "manifest.json"

_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "update"))


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


def _download_url(platform: str, filename: str) -> str:
    from urllib.parse import quote
    return f"/update/{platform}/{quote(filename)}"


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
            out.append(entry)
        elif m:
            out.append({"platform": platform, **m})
        else:
            out.append({"platform": platform, "version": None, "filename": None, "uploaded_at": None, "size": 0})
    return out


def get_latest(platform: str) -> Optional[dict]:
    m = _read_manifest(platform)
    if not m or not m.get("filename"):
        return None
    file_path = os.path.join(_platform_dir(platform), m["filename"])
    if not os.path.isfile(file_path):
        # APK может быть только на GitHub после publish-github
        if not m.get("github_download_url"):
            return None
    return {
        **m,
        "platform": platform,
        "file_path": file_path if os.path.isfile(file_path) else None,
        "download_url": f"/update/{platform}/{m['filename']}",
    }


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


def check_update(platform: str, current_version: str) -> Optional[dict]:
    latest = get_latest(platform)
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
    out["tunnel_download_url"] = f"/api/updates/download/{platform}"
    return out


def _cleanup_platform_dir(platform: str, keep_filename: str) -> None:
    d = _platform_dir(platform)
    for name in os.listdir(d):
        if name == MANIFEST or name == keep_filename:
            continue
        path = os.path.join(d, name)
        try:
            if os.path.isfile(path):
                os.remove(path)
            elif os.path.isdir(path):
                shutil.rmtree(path)
        except OSError:
            pass


def publish_file(platform: str, filename: str, src_path: str, version: Optional[str] = None) -> dict:
    """Replace platform update with a new file; delete previous binaries."""
    ensure_dirs()
    safe_name = os.path.basename(filename)
    if not safe_name or safe_name == MANIFEST:
        raise ValueError("Invalid filename")

    if not version:
        m = re.search(r"(\d+\.\d+\.\d+)", safe_name)
        version = m.group(1) if m else "0.0.0"

    dest_dir = _platform_dir(platform)
    dest_path = os.path.join(dest_dir, safe_name)
    _cleanup_platform_dir(platform, safe_name)
    shutil.copy2(src_path, dest_path)
    size = os.path.getsize(dest_path)
    uploaded_at = datetime.now(timezone.utc).isoformat()

    manifest = {
        "version": version,
        "filename": safe_name,
        "size": size,
        "uploaded_at": uploaded_at,
    }
    _write_manifest(platform, manifest)
    return {"platform": platform, **manifest, "download_url": f"/update/{platform}/{safe_name}"}


def delete_platform_update(platform: str) -> bool:
    m = _read_manifest(platform)
    if m and m.get("filename"):
        fp = os.path.join(_platform_dir(platform), m["filename"])
        if os.path.isfile(fp):
            os.remove(fp)
    mp = _manifest_path(platform)
    if os.path.isfile(mp):
        os.remove(mp)
        return True
    return False
