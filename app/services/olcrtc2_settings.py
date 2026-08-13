"""olcrtc 2.0 settings — product session-mode (agent create), exit on Hive cell only.

Roles (product):
  Улей (queen)     — только WDTT/VK + API (olcrtc2 запрещён)
  Сота Telemost    — cell_ip / cells.telemost
  Сота WB          — cells.wbstream (default Сота 2)
  Сота 3+          — запас (пока вручную через cell_ip)
"""
from __future__ import annotations

import json
import logging
import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting

logger = logging.getLogger(__name__)

SETTINGS_KEY = "olcrtc2_settings"
DEFAULT_CELL_TELEMOST = "87.58.213.193"  # Сота 1
DEFAULT_CELL_WB = "78.17.74.27"  # Сота 2
DEFAULT_CELL_IP = DEFAULT_CELL_TELEMOST
QUEEN_IP = "132.243.234.162"


def _provision_url(ip: str) -> str:
    ip = (ip or "").strip()
    return f"http://{ip}:9101" if ip else ""


def _defaults() -> dict[str, Any]:
    return {
        "enabled": False,
        "agent_enabled": True,
        "provider": "telemost",
        "room": "",  # diag-only shared room (optional)
        "crypto_key": "",  # master fallback; per-session keys preferred
        "socks_host": "127.0.0.1",
        "socks_port": 8808,
        "transport": "vp8channel",
        # legacy aliases = Telemost cell
        "cell_ip": DEFAULT_CELL_TELEMOST,
        "cell_provision_url": _provision_url(DEFAULT_CELL_TELEMOST),
        "session_mode": True,
        # provider → cell IP (exit node)
        "cells": {
            "telemost": DEFAULT_CELL_TELEMOST,
            "wbstream": DEFAULT_CELL_WB,
        },
        # Какие провайдеры греет агент (assign клиент выбирает сам)
        "providers_enabled": ["telemost", "wbstream"],
        # Запас готовых пустых комнат на каждый device_type (pc/android).
        # Не 150 сразу: агент догоняет по мере подключений, запас не даёт «нет комнат».
        "warm_pool_per_dt": 20,
        # Цель онлайн на провайдера (WB и Телемост по отдельности, PC+Android вместе).
        "target_online": 150,
    }


def _sanitize_cell_ip(ip: str, *, fallback: str) -> str:
    ip = (ip or "").strip()
    if not ip or ip == QUEEN_IP:
        return fallback
    return ip


def _normalize_cells(raw: Any, *, telemost_fallback: str, wb_fallback: str) -> dict[str, str]:
    out = {
        "telemost": _sanitize_cell_ip(telemost_fallback, fallback=DEFAULT_CELL_TELEMOST),
        "wbstream": _sanitize_cell_ip(wb_fallback, fallback=DEFAULT_CELL_WB),
    }
    if isinstance(raw, dict):
        if raw.get("telemost"):
            out["telemost"] = _sanitize_cell_ip(str(raw["telemost"]), fallback=out["telemost"])
        if raw.get("wbstream"):
            out["wbstream"] = _sanitize_cell_ip(str(raw["wbstream"]), fallback=out["wbstream"])
    return out


def cell_ip_for_provider(settings: dict[str, Any], provider: str | None = None) -> str:
    """Exit cell IP for provider. Never queen."""
    prov = (provider or settings.get("provider") or "telemost").strip().lower()
    if prov not in ("telemost", "wbstream"):
        prov = "telemost"
    cells = settings.get("cells") if isinstance(settings.get("cells"), dict) else {}
    ip = _sanitize_cell_ip(
        str(cells.get(prov) or ""),
        fallback=DEFAULT_CELL_TELEMOST if prov == "telemost" else DEFAULT_CELL_WB,
    )
    # legacy: telemost may only be in cell_ip
    if prov == "telemost" and not (cells.get("telemost") or "").strip():
        ip = _sanitize_cell_ip(str(settings.get("cell_ip") or ""), fallback=ip)
    return ip


def cell_provision_url_for_provider(settings: dict[str, Any], provider: str | None = None) -> str:
    prov = (provider or settings.get("provider") or "telemost").strip().lower()
    if prov == "telemost":
        url = (settings.get("cell_provision_url") or "").strip().rstrip("/")
        if url and QUEEN_IP not in url:
            return url
    return _provision_url(cell_ip_for_provider(settings, provider))


def enabled_providers(settings: dict[str, Any]) -> list[str]:
    """Providers the warm agent should fill. Always a non-empty subset of telemost|wbstream."""
    raw = settings.get("providers_enabled")
    out: list[str] = []
    if isinstance(raw, list):
        for p in raw:
            pl = str(p or "").strip().lower()
            if pl in ("telemost", "wbstream") and pl not in out:
                out.append(pl)
    if out:
        return out
    # legacy: single settings.provider
    one = str(settings.get("provider") or "telemost").strip().lower()
    return ["wbstream"] if one == "wbstream" else ["telemost"]


def _normalize_providers_enabled(raw: Any, *, fallback: list[str]) -> list[str]:
    out: list[str] = []
    if isinstance(raw, list):
        for p in raw:
            pl = str(p or "").strip().lower()
            if pl in ("telemost", "wbstream") and pl not in out:
                out.append(pl)
    return out or list(fallback)

async def load_olcrtc2_settings(db: AsyncSession) -> dict[str, Any]:
    row = (
        await db.execute(select(AppSetting).where(AppSetting.key == SETTINGS_KEY))
    ).scalar_one_or_none()
    out = _defaults()
    if not row or not (row.value or "").strip():
        return out
    try:
        data = json.loads(row.value)
        if isinstance(data, dict):
            for k in list(out.keys()):
                if k in data and k != "cells":
                    out[k] = data[k]
            if "agent_enabled" not in data and out.get("enabled"):
                out["agent_enabled"] = True
            telemost_fb = str(data.get("cell_ip") or out["cell_ip"] or DEFAULT_CELL_TELEMOST)
            wb_fb = DEFAULT_CELL_WB
            if isinstance(data.get("cells"), dict) and data["cells"].get("wbstream"):
                wb_fb = str(data["cells"]["wbstream"])
            out["cells"] = _normalize_cells(
                data.get("cells"),
                telemost_fallback=telemost_fb,
                wb_fallback=wb_fb,
            )
    except Exception as e:
        logger.warning("olcrtc2 settings parse: %s", e)

    out["provider"] = "telemost" if out.get("provider") != "wbstream" else "wbstream"
    out["socks_port"] = int(out.get("socks_port") or 8808)
    out["enabled"] = bool(out.get("enabled"))
    out["agent_enabled"] = bool(out.get("agent_enabled", True))
    out["session_mode"] = True
    try:
        out["warm_pool_per_dt"] = max(0, min(40, int(out.get("warm_pool_per_dt") or 20)))
    except (TypeError, ValueError):
        out["warm_pool_per_dt"] = 20
    try:
        out["target_online"] = max(0, min(1000, int(out.get("target_online") or 150)))
    except (TypeError, ValueError):
        out["target_online"] = 150

    # Keep legacy aliases in sync with telemost cell
    telemost_ip = cell_ip_for_provider(out, "telemost")
    out["cell_ip"] = telemost_ip
    if not (out.get("cell_provision_url") or "").strip() or QUEEN_IP in str(out.get("cell_provision_url") or ""):
        out["cell_provision_url"] = _provision_url(telemost_ip)
    out["cells"] = _normalize_cells(
        out.get("cells"),
        telemost_fallback=telemost_ip,
        wb_fallback=cell_ip_for_provider(out, "wbstream"),
    )
    out["providers_enabled"] = _normalize_providers_enabled(
        out.get("providers_enabled"),
        fallback=["telemost", "wbstream"],
    )
    return out


async def save_olcrtc2_settings(db: AsyncSession, patch: dict[str, Any]) -> dict[str, Any]:
    cur = await load_olcrtc2_settings(db)
    if "enabled" in patch:
        cur["enabled"] = bool(patch["enabled"])
    if "agent_enabled" in patch:
        cur["agent_enabled"] = bool(patch["agent_enabled"])
    if "provider" in patch and patch["provider"] in ("telemost", "wbstream"):
        cur["provider"] = patch["provider"]
    if "room" in patch:
        cur["room"] = str(patch["room"] or "").strip()
    if "crypto_key" in patch:
        key = str(patch["crypto_key"] or "").strip().lower()
        if key and len(key) != 64:
            raise ValueError("crypto_key must be 64 hex chars")
        cur["crypto_key"] = key
    if "socks_port" in patch:
        cur["socks_port"] = int(patch["socks_port"] or 8808)
    if "transport" in patch and patch["transport"]:
        cur["transport"] = str(patch["transport"])
    if "warm_pool_per_dt" in patch and patch["warm_pool_per_dt"] is not None:
        cur["warm_pool_per_dt"] = max(0, min(40, int(patch["warm_pool_per_dt"])))
    if "target_online" in patch and patch["target_online"] is not None:
        cur["target_online"] = max(0, min(1000, int(patch["target_online"])))
    if "providers_enabled" in patch:
        cur["providers_enabled"] = _normalize_providers_enabled(
            patch["providers_enabled"],
            fallback=enabled_providers(cur),
        )

    cells = dict(cur.get("cells") or {})
    if "cells" in patch and isinstance(patch["cells"], dict):
        for k in ("telemost", "wbstream"):
            if patch["cells"].get(k):
                ip = _sanitize_cell_ip(str(patch["cells"][k]), fallback=cells.get(k, ""))
                if ip == QUEEN_IP:
                    raise ValueError(f"cells.{k} cannot be WDTT queen")
                cells[k] = ip
    if "cell_ip_wbstream" in patch and str(patch["cell_ip_wbstream"] or "").strip():
        ip = _sanitize_cell_ip(str(patch["cell_ip_wbstream"]), fallback=DEFAULT_CELL_WB)
        if ip == QUEEN_IP:
            raise ValueError("cell_ip_wbstream cannot be WDTT queen")
        cells["wbstream"] = ip
    if "cell_ip" in patch and str(patch["cell_ip"] or "").strip():
        ip = _sanitize_cell_ip(str(patch["cell_ip"]), fallback=DEFAULT_CELL_TELEMOST)
        if ip == QUEEN_IP:
            raise ValueError("cell_ip cannot be WDTT queen")
        cells["telemost"] = ip
        cur["cell_ip"] = ip
        cur["cell_provision_url"] = _provision_url(ip)
    if "cell_provision_url" in patch and patch["cell_provision_url"] is not None:
        url = str(patch["cell_provision_url"] or "").strip()
        if url and QUEEN_IP in url:
            raise ValueError("cell_provision_url cannot point at WDTT queen")
        cur["cell_provision_url"] = url

    cur["cells"] = _normalize_cells(
        cells,
        telemost_fallback=str(cells.get("telemost") or DEFAULT_CELL_TELEMOST),
        wb_fallback=str(cells.get("wbstream") or DEFAULT_CELL_WB),
    )
    cur["cell_ip"] = cur["cells"]["telemost"]
    cur["providers_enabled"] = _normalize_providers_enabled(
        cur.get("providers_enabled"),
        fallback=["telemost", "wbstream"],
    )
    if not (cur.get("cell_provision_url") or "").strip():
        cur["cell_provision_url"] = _provision_url(cur["cell_ip"])

    if cur["enabled"] and not cur["crypto_key"]:
        cur["crypto_key"] = secrets.token_hex(32)
    if cur["enabled"] and not cur["agent_enabled"] and not cur["room"]:
        raise ValueError("без агента нужен diag Room ID, либо включите agent_enabled")

    raw = json.dumps(cur, ensure_ascii=False)
    row = (
        await db.execute(select(AppSetting).where(AppSetting.key == SETTINGS_KEY))
    ).scalar_one_or_none()
    if row:
        row.value = raw
    else:
        db.add(AppSetting(key=SETTINGS_KEY, value=raw))
    await db.commit()
    return cur


def denied_config(
    settings: dict[str, Any],
    *,
    device_type: str,
    detail: str,
    fingerprint: str = "",
) -> dict[str, Any]:
    return {
        "enabled": False,
        "crypto_key": "",
        "socks_host": settings.get("socks_host") or "127.0.0.1",
        "socks_port": int(settings.get("socks_port") or 8808),
        "assigned_slot": "",
        "device_type": device_type,
        "pool_denied": True,
        "pool_denied_detail": detail,
        "providers": {},
        "session_mode": True,
        "family": "olcrtc2",
        "fingerprint": (fingerprint or "")[:128],
    }


def room_to_public_config(
    settings: dict[str, Any],
    *,
    room_url: str,
    crypto_key: str,
    provider: str,
    device_type: str,
    room_db_id: str,
    unit_name: str = "",
    fingerprint: str = "",
    auth_token: str = "",
) -> dict[str, Any]:
    transport = settings.get("transport") or "vp8channel"
    prov = provider if provider in ("telemost", "wbstream") else "telemost"
    entry: dict[str, Any] = {
        "enabled": True,
        "room": room_url,
        "transport": transport,
        "room_slot_id": unit_name or f"olcrtc2-{prov}",
        "room_db_id": room_db_id,
        "rooms_count": 1,
    }
    if auth_token:
        entry["auth_token"] = auth_token
    return {
        "enabled": True,
        "crypto_key": crypto_key,
        "socks_host": settings.get("socks_host") or "127.0.0.1",
        "socks_port": int(settings.get("socks_port") or 8808),
        "assigned_slot": unit_name or f"olcrtc2-{prov}-{device_type}",
        "device_type": device_type,
        "pool_denied": False,
        "pool_denied_detail": "",
        "providers": {prov: entry},
        "session_mode": True,
        "family": "olcrtc2",
        "fingerprint": (fingerprint or "")[:128],
    }

