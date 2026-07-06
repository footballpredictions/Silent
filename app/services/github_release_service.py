"""Publish OTA binaries to GitHub Releases + sync silentvpn3.github.io releases.json."""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

import httpx

from app.services import update_service

logger = logging.getLogger(__name__)

GITHUB_OWNER = os.environ.get("GITHUB_RELEASES_OWNER", "silentvpn3")
GITHUB_REPO = os.environ.get("GITHUB_RELEASES_REPO", "silentvpn3.github.io")
GITHUB_API = "https://api.github.com"
RELEASES_JSON_PATH = "releases.json"
API_BASE_DEFAULT = "https://132-243-234-162.nip.io"


class GitHubReleaseError(Exception):
    """GitHub Releases / Contents API failure."""


def _token() -> str:
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_RELEASES_TOKEN") or "").strip()
    if not token:
        raise GitHubReleaseError(
            "GITHUB_TOKEN не задан на сервере (PAT: repo + releases для silentvpn3/silentvpn3.github.io)"
        )
    return token


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def release_tag(version: str) -> str:
    v = (version or "").strip()
    if not v:
        raise GitHubReleaseError("Пустая версия")
    return v if v.startswith("v") else f"v{v}"


def asset_download_url(version: str, filename: str) -> str:
    tag = release_tag(version)
    return (
        f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/"
        f"{tag}/{quote(filename)}"
    )


async def _request(
    method: str,
    url: str,
    *,
    token: str,
    json_body: Any = None,
    content: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 120.0,
) -> httpx.Response:
    headers = _headers(token)
    if content_type:
        headers["Content-Type"] = content_type
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(method, url, headers=headers, json=json_body, content=content)
    return resp


async def _get_release_by_tag(token: str, tag: str) -> Optional[dict]:
    url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tags/{quote(tag, safe='')}"
    resp = await _request("GET", url, token=token, timeout=30.0)
    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        raise GitHubReleaseError(f"GET release {tag}: HTTP {resp.status_code} {resp.text[:300]}")
    return resp.json()


def _release_title(platform: str, version: str) -> str:
    if platform == "pc":
        return f"Silent VPN — ПК v{version}"
    return f"Silent VPN — Android v{version}"


def _combined_release_title(version: str) -> str:
    return f"Silent VPN v{version}"


def _release_title_for_assets(version: str, asset_names: list[str]) -> str:
    has_pc = any(n.lower().endswith(".exe") for n in asset_names)
    has_apk = any(n.lower().endswith(".apk") for n in asset_names)
    if has_pc and has_apk:
        return _combined_release_title(version)
    if has_pc:
        return _release_title("pc", version)
    if has_apk:
        return _release_title("android", version)
    return _combined_release_title(version)


def _release_body_for_assets(version: str, asset_names: list[str]) -> str:
    landing = "https://silentvpn3.github.io/"
    has_pc = any(n.lower().endswith(".exe") for n in asset_names)
    has_apk = any(n.lower().endswith(".apk") for n in asset_names)
    lines = [f"Клиенты Silent VPN v{version}.\n"]
    if has_pc:
        lines.append("- **Windows (ПК)** — установщик `.exe`")
    if has_apk:
        lines.append("- **Android** — `.apk`")
    lines.append(f"\nСкачивание: {landing}")
    return "\n".join(lines)


async def _create_release(token: str, tag: str, version: str, platform: str) -> dict:
    url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
    body = {
        "tag_name": tag,
        "name": _release_title(platform, version),
        "body": _release_body_for_assets(version, [".exe" if platform == "pc" else ".apk"]),
        "draft": False,
        "prerelease": False,
        "generate_release_notes": False,
    }
    resp = await _request("POST", url, token=token, json_body=body, timeout=60.0)
    if resp.status_code >= 400:
        raise GitHubReleaseError(f"Create release {tag}: HTTP {resp.status_code} {resp.text[:400]}")
    return resp.json()


async def _update_release_meta(token: str, release: dict, version: str, asset_names: list[str]) -> dict:
    release_id = release.get("id")
    if not release_id:
        return release
    url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/{release_id}"
    body = {
        "name": _release_title_for_assets(version, asset_names),
        "body": _release_body_for_assets(version, asset_names),
    }
    resp = await _request("PATCH", url, token=token, json_body=body, timeout=30.0)
    if resp.status_code >= 400:
        raise GitHubReleaseError(f"Update release {release_id}: HTTP {resp.status_code} {resp.text[:300]}")
    return resp.json()


async def _delete_asset(token: str, asset_id: int) -> None:
    url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/assets/{asset_id}"
    resp = await _request("DELETE", url, token=token, timeout=30.0)
    if resp.status_code not in (204, 404):
        raise GitHubReleaseError(f"Delete asset {asset_id}: HTTP {resp.status_code}")


async def _remove_platform_assets(token: str, release: dict, platform: str) -> None:
    """Удалить только файлы этой платформы (.exe / .apk), не трогая другую."""
    ext = ".exe" if platform == "pc" else ".apk"
    for asset in release.get("assets") or []:
        name = (asset.get("name") or "").lower()
        if name.endswith(ext):
            await _delete_asset(token, int(asset["id"]))


async def _upload_release_asset(token: str, release: dict, file_path: str, filename: str) -> dict:
    upload_url = release.get("upload_url", "").split("{", 1)[0]
    if not upload_url:
        raise GitHubReleaseError("upload_url отсутствует в release")
    url = f"{upload_url}?name={quote(filename)}"
    with open(file_path, "rb") as fh:
        data = fh.read()
    resp = await _request(
        "POST",
        url,
        token=token,
        content=data,
        content_type="application/octet-stream",
        timeout=600.0,
    )
    if resp.status_code >= 400:
        raise GitHubReleaseError(f"Upload {filename}: HTTP {resp.status_code} {resp.text[:400]}")
    return resp.json()


async def _read_repo_file(token: str, path: str) -> tuple[Optional[dict], Optional[str]]:
    url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{quote(path, safe='/')}"
    resp = await _request("GET", url, token=token, timeout=30.0)
    if resp.status_code == 404:
        return None, None
    if resp.status_code >= 400:
        raise GitHubReleaseError(f"GET {path}: HTTP {resp.status_code} {resp.text[:300]}")
    payload = resp.json()
    raw = base64.b64decode(payload["content"])
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("utf-8")
    return json.loads(text), payload.get("sha")


async def _write_repo_file(token: str, path: str, content: str, sha: Optional[str], message: str) -> None:
    url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{quote(path, safe='/')}"
    body: dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        body["sha"] = sha
    resp = await _request("PUT", url, token=token, json_body=body, timeout=60.0)
    if resp.status_code >= 400:
        raise GitHubReleaseError(f"PUT {path}: HTTP {resp.status_code} {resp.text[:400]}")


def _platform_label(platform: str) -> str:
    return "PC (Windows)" if platform == "pc" else "Android"


async def _sync_landing_releases_json(
    token: str,
    platform: str,
    manifest: dict,
    download_url: str,
    github_filename: str | None = None,
) -> None:
    current, sha = await _read_repo_file(token, RELEASES_JSON_PATH)
    if not isinstance(current, dict):
        current = {}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {
        "version": manifest["version"],
        "filename": github_filename or manifest["filename"],
        "size": manifest.get("size", 0),
        "download_url": download_url,
    }
    current["updated_at"] = now
    current["api_base"] = current.get("api_base") or API_BASE_DEFAULT
    current["github_repo"] = f"{GITHUB_OWNER}/{GITHUB_REPO}"
    current[platform] = entry
    for p in update_service.PLATFORMS:
        local = update_service.get_latest(p)
        if not local or p == platform:
            continue
        if p not in current or not current[p].get("download_url"):
            current[p] = {
                "version": local["version"],
                "filename": local["filename"],
                "size": local.get("size", 0),
                "download_url": asset_download_url(local["version"], local["filename"]),
            }
    text = json.dumps(current, ensure_ascii=False, indent=2) + "\n"
    await _write_repo_file(
        token,
        RELEASES_JSON_PATH,
        text,
        sha,
        f"releases.json: {_platform_label(platform)} v{manifest['version']}",
    )


def _patch_manifest_github(platform: str, download_url: str) -> None:
    mp = update_service._manifest_path(platform)
    if not os.path.isfile(mp):
        return
    try:
        with open(mp, encoding="utf-8") as fh:
            data = json.load(fh)
        data["github_download_url"] = download_url
        data["github_published_at"] = datetime.now(timezone.utc).isoformat()
        with open(mp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("manifest github fields: %s", e)


async def _sync_peer_assets_from_server(
    token: str,
    release: dict,
    version: str,
    *,
    skip_platform: str | None = None,
) -> dict:
    """Добавить на релиз файлы другой платформы с VPS (тот же v{version}), если их нет."""
    asset_names = {a.get("name") for a in release.get("assets") or [] if a.get("name")}
    ext_by_platform = {"pc": ".exe", "android": ".apk"}
    for platform in update_service.PLATFORMS:
        if platform == skip_platform:
            continue
        latest = update_service.get_latest(platform)
        if not latest or str(latest.get("version")) != str(version):
            continue
        filename = latest.get("filename")
        file_path = latest.get("file_path")
        if not filename or not file_path or not os.path.isfile(file_path):
            continue
        ext = ext_by_platform.get(platform, "")
        if ext and any((n or "").lower().endswith(ext) for n in asset_names):
            continue
        if filename in asset_names:
            continue
        uploaded = await _upload_release_asset(token, release, file_path, filename)
        name = uploaded.get("name") or filename
        asset_names.add(name)
        logger.info("GitHub release %s: restored %s from server update/", version, name)
    fresh = await _get_release_by_tag(token, release_tag(version))
    return fresh or release


async def publish_platform(platform: str, *, sync_landing: bool = True) -> dict:
    """Upload update/{platform} file to GitHub Release v{version}; replace asset if exists."""
    if platform not in update_service.PLATFORMS:
        raise GitHubReleaseError(f"Unknown platform: {platform}")

    latest = update_service.get_latest(platform)
    if not latest:
        raise GitHubReleaseError(f"Нет файла обновления для {platform} в update/")

    token = _token()
    version = latest["version"]
    filename = latest["filename"]
    file_path = latest["file_path"]
    tag = release_tag(version)

    release = await _get_release_by_tag(token, tag)
    if not release:
        release = await _create_release(token, tag, version, platform)
        logger.info("GitHub release created: %s (%s)", tag, platform)
    else:
        await _remove_platform_assets(token, release, platform)

    uploaded = await _upload_release_asset(token, release, file_path, filename)
    asset_name = uploaded.get("name") or filename

    release = await _get_release_by_tag(token, tag) or release
    release = await _sync_peer_assets_from_server(token, release, version, skip_platform=platform)
    asset_names = [a.get("name") or "" for a in release.get("assets") or []]
    release = await _update_release_meta(token, release, version, asset_names)
    download_url = uploaded.get("browser_download_url") or asset_download_url(version, asset_name)
    release_page = release.get("html_url") or f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tag/{tag}"

    if sync_landing:
        await _sync_landing_releases_json(token, platform, latest, download_url, asset_name)

    _patch_manifest_github(platform, download_url)

    return {
        "platform": platform,
        "version": version,
        "filename": asset_name,
        "tag": tag,
        "download_url": download_url,
        "release_url": release_page,
        "landing_synced": sync_landing,
    }


async def publish_all_available(*, sync_landing: bool = True) -> list[dict]:
    results = []
    for platform in update_service.PLATFORMS:
        if update_service.get_latest(platform):
            results.append(await publish_platform(platform, sync_landing=sync_landing))
    if not results:
        raise GitHubReleaseError("Нет опубликованных обновлений на сервере")
    return results


def is_configured() -> bool:
    return bool((os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_RELEASES_TOKEN") or "").strip())
