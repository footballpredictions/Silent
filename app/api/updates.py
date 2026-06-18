"""Public app update check API — reachable via VPN tunnel."""
from fastapi import APIRouter, Query

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
