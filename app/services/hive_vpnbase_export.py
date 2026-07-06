"""Encrypted export всех hive-manifest в Git (vpnbase) — backup при падении Улья."""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import encrypt_value
from app.models import HiveCell
from app.services.hive_standby import build_cell_manifest_enriched

logger = logging.getLogger(__name__)

_last_export_version: int = 0


async def build_cluster_export(db: AsyncSession) -> dict:
    result = await db.execute(
        select(HiveCell).where(HiveCell.status.in_(("active", "draining")))
    )
    cells = list(result.scalars().all())
    manifests = []
    version = 0
    for cell in cells:
        m = await build_cell_manifest_enriched(db, cell)
        manifests.append(m)
        version = max(version, int(m.get("version") or 0))
    return {
        "version": version,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "manifests": manifests,
    }


async def push_vpnbase_export(db: AsyncSession) -> dict:
    """Пушит зашифрованный снимок в GitHub (repo vpnbase), если настроен токен."""
    global _last_export_version

    if not settings.VPNBASE_GIT_ENABLED:
        return {"skipped": True}

    token = (settings.VPNBASE_GIT_TOKEN or "").strip()
    repo = (settings.VPNBASE_GIT_REPO or "silentvpn3/vpnbase").strip()
    branch = (settings.VPNBASE_GIT_BRANCH or "main").strip()
    path = (settings.VPNBASE_GIT_PATH or "hive_export.enc").strip()

    if not token:
        return {"skipped": True, "reason": "no_token"}

    export = await build_cluster_export(db)
    version = int(export.get("version") or 0)
    if version == _last_export_version:
        return {"skipped": True, "version": version}

    plaintext = json.dumps(export, ensure_ascii=False, separators=(",", ":"))
    enc = encrypt_value(plaintext)
    content_b64 = base64.b64encode(enc.encode("utf-8")).decode("ascii")

    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    sha = None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            head = await client.get(url, headers=headers, params={"ref": branch})
            if head.status_code == 200:
                sha = head.json().get("sha")
            body = {
                "message": f"hive export v{version}",
                "content": content_b64,
                "branch": branch,
            }
            if sha:
                body["sha"] = sha
            resp = await client.put(url, headers=headers, json=body)
        if resp.status_code not in (200, 201):
            detail = resp.text[:500]
            logger.warning("vpnbase git push failed: %s %s", resp.status_code, detail)
            return {"ok": False, "status": resp.status_code, "detail": detail}
    except Exception as e:
        logger.warning("vpnbase git push error: %s", e)
        return {"ok": False, "error": str(e)}

    _last_export_version = version
    logger.info("vpnbase export pushed v%s to %s", version, repo)
    return {"ok": True, "version": version, "repo": repo}
