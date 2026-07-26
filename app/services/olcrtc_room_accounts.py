"""Аккаунты для olcrtc_room_agent (Яндекс / WB) — только на сервере, не в git.

Хранение:
1. app_settings key ``olcrtc_room_accounts`` (JSON)
2. Переопределение из env:
   - OLCRTC_TELEMOST_STORAGE_STATE  — путь к Playwright storage_state JSON
   - OLCRTC_WBSTREAM_STORAGE_STATE
   - или inline base64 в OLCRTC_TELEMOST_STORAGE_STATE_B64 / OLCRTC_WBSTREAM_STORAGE_STATE_B64
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting

ACCOUNTS_KEY = "olcrtc_room_accounts"


@dataclass
class ProviderAccount:
    """Один стабильный аккаунт (не рандомная регистрация)."""

    label: str = ""
    # Playwright storage_state (cookies + origins) как dict
    storage_state: dict[str, Any] = field(default_factory=dict)
    # Опционально: путь к файлу на хосте (для host-side provision)
    storage_state_path: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "storage_state": self.storage_state,
            "storage_state_path": self.storage_state_path,
            "notes": self.notes,
            "configured": bool(self.storage_state) or bool(self.storage_state_path.strip()),
        }

    def public_dict(self) -> dict[str, Any]:
        """Без cookies — для админки."""
        return {
            "label": self.label,
            "storage_state_path": self.storage_state_path,
            "notes": self.notes,
            "configured": bool(self.storage_state) or bool(self.storage_state_path.strip()),
            "has_inline_state": bool(self.storage_state),
        }


@dataclass
class OlcrtcRoomAccounts:
    telemost: list[ProviderAccount] = field(default_factory=list)
    wbstream: list[ProviderAccount] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "telemost": [a.to_dict() for a in self.telemost],
            "wbstream": [a.to_dict() for a in self.wbstream],
        }

    def public_dict(self) -> dict[str, Any]:
        return {
            "telemost": [a.public_dict() for a in self.telemost],
            "wbstream": [a.public_dict() for a in self.wbstream],
        }


def _account_from_dict(raw: dict[str, Any] | None) -> ProviderAccount:
    d = raw or {}
    state = d.get("storage_state") or {}
    if isinstance(state, str) and state.strip():
        try:
            state = json.loads(state)
        except json.JSONDecodeError:
            state = {}
    if not isinstance(state, dict):
        state = {}
    return ProviderAccount(
        label=str(d.get("label") or "").strip(),
        storage_state=state,
        storage_state_path=str(d.get("storage_state_path") or "").strip(),
        notes=str(d.get("notes") or "").strip(),
    )


def parse_accounts(raw: dict[str, Any] | None) -> OlcrtcRoomAccounts:
    data = raw or {}
    return OlcrtcRoomAccounts(
        telemost=[_account_from_dict(x) for x in (data.get("telemost") or []) if isinstance(x, dict)],
        wbstream=[_account_from_dict(x) for x in (data.get("wbstream") or []) if isinstance(x, dict)],
    )


def _load_env_storage(provider: str) -> ProviderAccount | None:
    path_key = f"OLCRTC_{provider.upper()}_STORAGE_STATE"
    b64_key = f"{path_key}_B64"
    path = (os.environ.get(path_key) or "").strip()
    b64 = (os.environ.get(b64_key) or "").strip()
    if b64:
        try:
            raw = base64.b64decode(b64)
            state = json.loads(raw.decode("utf-8"))
            if isinstance(state, dict):
                return ProviderAccount(label=f"env:{provider}", storage_state=state)
        except Exception:
            pass
    if path and Path(path).is_file():
        try:
            state = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(state, dict):
                return ProviderAccount(
                    label=f"env:{provider}",
                    storage_state=state,
                    storage_state_path=path,
                )
        except Exception:
            return ProviderAccount(label=f"env:{provider}", storage_state_path=path)
    return None


def merge_env_accounts(acc: OlcrtcRoomAccounts) -> OlcrtcRoomAccounts:
    """Env overrides prepended if present."""
    for provider, attr in (("telemost", "telemost"), ("wbstream", "wbstream")):
        env_acc = _load_env_storage(provider)
        if not env_acc:
            continue
        lst: list[ProviderAccount] = getattr(acc, attr)
        # replace env-labeled or prepend
        lst = [a for a in lst if not a.label.startswith("env:")]
        lst.insert(0, env_acc)
        setattr(acc, attr, lst)
    return acc


async def load_room_accounts(db: AsyncSession) -> OlcrtcRoomAccounts:
    result = await db.execute(select(AppSetting).where(AppSetting.key == ACCOUNTS_KEY))
    row = result.scalar_one_or_none()
    if not row:
        return merge_env_accounts(OlcrtcRoomAccounts())
    try:
        return merge_env_accounts(parse_accounts(json.loads(row.value)))
    except (json.JSONDecodeError, TypeError, ValueError):
        return merge_env_accounts(OlcrtcRoomAccounts())


async def save_room_accounts(db: AsyncSession, accounts: OlcrtcRoomAccounts) -> OlcrtcRoomAccounts:
    # Не сохраняем env:-лейблы в DB (они из окружения)
    cleaned = OlcrtcRoomAccounts(
        telemost=[a for a in accounts.telemost if not a.label.startswith("env:")],
        wbstream=[a for a in accounts.wbstream if not a.label.startswith("env:")],
    )
    payload = json.dumps(cleaned.to_dict(), ensure_ascii=False)
    result = await db.execute(select(AppSetting).where(AppSetting.key == ACCOUNTS_KEY))
    row = result.scalar_one_or_none()
    if row:
        row.value = payload
    else:
        db.add(AppSetting(key=ACCOUNTS_KEY, value=payload))
    await db.commit()
    saved = await load_room_accounts(db)
    await sync_wbstream_auth_token_to_settings(db, saved)
    return saved


async def sync_wbstream_auth_token_to_settings(
    db: AsyncSession,
    accounts: OlcrtcRoomAccounts | None = None,
) -> str:
    """Достаёт JWT из WB storage_state → providers.wbstream.auth_token (для YAML + клиенты)."""
    from app.services.olcrtc_settings import load_olcrtc_settings, save_olcrtc_settings

    acc = accounts or await load_room_accounts(db)
    tok = ""
    for a in acc.wbstream:
        tok = extract_wb_access_token(resolve_storage_state(a))
        if tok:
            break
    if not tok:
        return ""
    settings = await load_olcrtc_settings(db)
    p = settings.providers.get("wbstream")
    if not p:
        return tok
    if (p.auth_token or "").strip() == tok:
        return tok
    p.auth_token = tok
    await save_olcrtc_settings(db, settings)
    return tok


def resolve_storage_state(account: ProviderAccount) -> dict[str, Any] | None:
    if account.storage_state:
        return account.storage_state
    path = (account.storage_state_path or "").strip()
    if path and Path(path).is_file():
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None
    return None


def extract_wb_access_token(storage_state: dict[str, Any] | None) -> str:
    """JWT accessToken из Playwright storage_state (localStorage wb_auth_auth_slice)."""
    if not storage_state:
        return ""
    for origin in storage_state.get("origins") or []:
        if not isinstance(origin, dict):
            continue
        for item in origin.get("localStorage") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            raw = item.get("value")
            if name == "wb_auth_auth_slice" and isinstance(raw, str) and raw.strip():
                try:
                    data = json.loads(raw)
                    tok = str((data or {}).get("accessToken") or "").strip()
                    if tok.startswith("eyJ"):
                        return tok
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
            # иногда токен лежит напрямую
            if isinstance(raw, str) and raw.strip().startswith("eyJ") and "access" in name.lower():
                return raw.strip()
    return ""


async def resolve_wbstream_access_token(db: AsyncSession) -> str:
    """Актуальный WB account token для auth.token (не guest)."""
    accounts = await load_room_accounts(db)
    for acc in accounts.wbstream:
        state = resolve_storage_state(acc)
        tok = extract_wb_access_token(state)
        if tok:
            return tok
    return ""
