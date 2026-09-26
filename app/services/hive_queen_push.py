"""Улей сам говорит сотам свой публичный IP. Соты применяют без правки кода."""
from __future__ import annotations

import ipaddress
import logging

from app.config import settings

logger = logging.getLogger(__name__)


def queen_public_ip(raw: str | None = None) -> str:
    text = (raw if raw is not None else settings.VPN_SERVER_IP or "").strip()
    if not text:
        return ""
    try:
        return str(ipaddress.IPv4Address(text))
    except ValueError:
        return ""


def configure_payload(queen_ip: str, sibling_urls: list[str]) -> dict:
    return {
        "hive_queen_ip": queen_ip,
        "sibling_api_urls": [u for u in sibling_urls if u],
    }


async def push_queen_ip_to_cells(db) -> dict:
    from sqlalchemy import select

    import httpx

    from app.core.security import decrypt_value
    from app.models import HiveCell
    from app.services.hive_service import _validate_outbound_url

    queen_ip = queen_public_ip()
    if not queen_ip:
        return {"pushed": 0, "skipped": True}

    result = await db.execute(
        select(HiveCell).where(
            HiveCell.is_queen == False,  # noqa: E712
            HiveCell.status.in_(("active", "draining")),
            HiveCell.api_url.isnot(None),
        )
    )
    workers = list(result.scalars().all())
    siblings: list[str] = []
    for cell in workers:
        try:
            siblings.append(_validate_outbound_url(cell.api_url))
        except ValueError:
            continue

    pushed = 0
    timeout = settings.HIVE_CELL_HTTP_TIMEOUT_SEC
    body = configure_payload(queen_ip, siblings)
    for cell in workers:
        if not cell.api_secret_enc:
            continue
        try:
            secret = decrypt_value(cell.api_secret_enc)
            base = _validate_outbound_url(cell.api_url)
        except Exception:
            continue
        url = f"{base}/v1/configure"
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                resp = await client.post(
                    url,
                    headers={"X-Cell-Agent-Secret": secret},
                    json=body,
                )
            if resp.status_code < 400:
                pushed += 1
            else:
                logger.debug("Hive queen-ip %s: HTTP %s", cell.name, resp.status_code)
        except Exception as e:
            logger.debug("Hive queen-ip %s failed: %s", cell.name, e)
    if pushed:
        logger.info("Hive queen-ip push: %s/%s cells → %s", pushed, len(workers), queen_ip)
    return {"pushed": pushed, "total": len(workers), "queen_ip": queen_ip}
