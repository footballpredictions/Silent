"""Public app update check API — reachable via VPN tunnel."""
import os

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from app.services import update_service

router = APIRouter(prefix="/updates", tags=["updates"])


@router.get("/check")
async def check_update(
    platform: str = Query(..., pattern="^(pc|android)$"),
    version: str = Query(..., min_length=1, max_length=32),
):
    """Return update info if a newer version is available on the server."""
    info = update_service.check_update(platform, version)
    if not info:
        return {"available": False}
    return info


@router.get("/download/{platform}")
async def download_update_file(platform: str):
    """
    Скачивание OTA через tunnel API (10.66.66.1).
    LTE: приложение excluded из WG — GitHub напрямую недоступен; VPS стримит с диска или с GitHub.
    """
    p = platform.lower().strip()
    if p not in update_service.PLATFORMS:
        raise HTTPException(status_code=400, detail="Unknown platform")

    latest = update_service.get_latest(p)
    if not latest:
        raise HTTPException(status_code=404, detail="No update published")

    filename = latest.get("filename") or ("update.apk" if p == "android" else "update.exe")
    file_path = latest.get("file_path")
    if file_path and os.path.isfile(file_path):
        media = (
            "application/vnd.android.package-archive"
            if p == "android"
            else "application/octet-stream"
        )
        return FileResponse(file_path, filename=filename, media_type=media)

    source_url = update_service.resolve_download_url(latest)
    if not source_url or not source_url.startswith("http"):
        raise HTTPException(status_code=404, detail="No download source")

    async def stream_upstream():
        async with httpx.AsyncClient(follow_redirects=True, timeout=600.0) as client:
            async with client.stream("GET", source_url) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    raise HTTPException(
                        status_code=502,
                        detail=f"Upstream HTTP {resp.status_code}: {body[:200]!r}",
                    )
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    yield chunk

    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    # Клиенты (особенно Android 11–12) без Content-Length показывают 0% до конца загрузки.
    size = latest.get("size") or 0
    try:
        size_i = int(size)
    except (TypeError, ValueError):
        size_i = 0
    if size_i > 0:
        headers["Content-Length"] = str(size_i)

    return StreamingResponse(
        stream_upstream(),
        media_type="application/octet-stream",
        headers=headers,
    )
