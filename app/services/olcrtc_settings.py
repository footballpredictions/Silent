"""Olcrtc (вариант 2 обхода) — настройки в app_settings + генерация server.yaml + room pool."""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting

OLCRTC_SETTINGS_KEY = "olcrtc_settings"

DEFAULT_TRANSPORTS = {
    "jitsi": "datachannel",
    "wbstream": "vp8channel",
    "telemost": "vp8channel",
}

PROVIDERS = ("jitsi", "wbstream", "telemost")

# MVP: две Jitsi-комнаты — разные data-dir + разные room.
# Android: meet.playform.ru (meet.egovm.ru на LTE часто DPI / handshake fail).
DEFAULT_JITSI_ROOMS = [
    {
        "id": "pc",
        "url": "https://meet.egovm.ru/SilentVpnOlcrtcHive",
        "max_clients": 4,
        "device_types": ["pc"],
    },
    {
        "id": "android",
        "url": "https://meet.playform.ru/SilentVpnOlcrtcHiveAndroid",
        "max_clients": 4,
        "device_types": ["android"],
    },
]

# Placeholder room IDs — заменить свежими с stream.wb.ru / telemost.yandex.ru
# (или через olcrtc_room_agent). PC и Android обязаны быть разными.
DEFAULT_WBSTREAM_ROOMS = [
    {
        "id": "pc",
        "url": "019e23c2-a580-7550-b08a-7ac5342ca21f",
        "max_clients": 4,
        "device_types": ["pc"],
    },
    {
        "id": "android",
        "url": "019e23c2-a580-7550-b08a-ANDROID-REPLACE",
        "max_clients": 4,
        "device_types": ["android"],
    },
]

DEFAULT_TELEMOST_ROOMS = [
    {
        "id": "pc",
        "url": "02789996238784",
        "max_clients": 4,
        "device_types": ["pc"],
    },
    {
        "id": "android",
        "url": "02789996238785",
        "max_clients": 4,
        "device_types": ["android"],
    },
]

_DEFAULT_ROOMS_BY_PROVIDER: dict[str, list[dict[str, Any]]] = {
    "jitsi": DEFAULT_JITSI_ROOMS,
    "wbstream": DEFAULT_WBSTREAM_ROOMS,
    "telemost": DEFAULT_TELEMOST_ROOMS,
}


@dataclass
class OlcrtcRoomSlot:
    id: str
    url: str
    max_clients: int = 4
    device_types: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "max_clients": self.max_clients,
            "device_types": list(self.device_types),
        }


@dataclass
class OlcrtcProviderConfig:
    enabled: bool = False
    room: str = ""
    transport: str = "datachannel"
    rooms: list[OlcrtcRoomSlot] = field(default_factory=list)

    def effective_rooms(self) -> list[OlcrtcRoomSlot]:
        if self.rooms:
            return [r for r in self.rooms if r.url.strip()]
        if self.room.strip():
            return [
                OlcrtcRoomSlot(id="default", url=self.room.strip(), max_clients=8, device_types=[])
            ]
        return []


@dataclass
class OlcrtcSettings:
    enabled: bool = False
    crypto_key: str = ""
    providers: dict[str, OlcrtcProviderConfig] = field(default_factory=dict)
    srv_status: str = "unknown"  # unknown | active | inactive | error
    srv_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "crypto_key": self.crypto_key,
            "providers": {
                name: {
                    "enabled": p.enabled,
                    "room": p.room,
                    "transport": p.transport,
                    "rooms": [r.to_dict() for r in p.rooms],
                }
                for name, p in self.providers.items()
            },
            "srv_status": self.srv_status,
            "srv_message": self.srv_message,
        }


def _slots_from_defaults(name: str) -> list[OlcrtcRoomSlot]:
    return [
        OlcrtcRoomSlot(
            id=r["id"],
            url=r["url"],
            max_clients=int(r.get("max_clients", 4)),
            device_types=list(r.get("device_types") or []),
        )
        for r in _DEFAULT_ROOMS_BY_PROVIDER.get(name, [])
    ]


def _parse_rooms(raw: Any, legacy_room: str = "") -> list[OlcrtcRoomSlot]:
    out: list[OlcrtcRoomSlot] = []
    if isinstance(raw, list):
        for i, item in enumerate(raw):
            if isinstance(item, str) and item.strip():
                out.append(
                    OlcrtcRoomSlot(
                        id=f"r{i}",
                        url=item.strip(),
                        max_clients=4,
                        device_types=[],
                    )
                )
                continue
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or item.get("room") or "").strip()
            if not url:
                continue
            dts = item.get("device_types") or item.get("deviceTypes") or []
            if isinstance(dts, str):
                dts = [dts]
            out.append(
                OlcrtcRoomSlot(
                    id=str(item.get("id") or f"r{i}").strip() or f"r{i}",
                    url=url,
                    max_clients=max(1, int(item.get("max_clients") or item.get("maxClients") or 4)),
                    device_types=[str(x).strip().lower() for x in dts if str(x).strip()],
                )
            )
    if out:
        return out
    if legacy_room.strip():
        return [
            OlcrtcRoomSlot(
                id="default",
                url=legacy_room.strip(),
                max_clients=8,
                device_types=[],
            )
        ]
    return []


def _default_providers() -> dict[str, OlcrtcProviderConfig]:
    out: dict[str, OlcrtcProviderConfig] = {}
    for name in PROVIDERS:
        rooms = _slots_from_defaults(name)
        out[name] = OlcrtcProviderConfig(
            enabled=False,
            room=rooms[0].url if rooms else "",
            transport=DEFAULT_TRANSPORTS[name],
            rooms=rooms,
        )
    return out


def generate_crypto_key() -> str:
    return secrets.token_hex(32)


def parse_settings(raw: dict[str, Any] | None) -> OlcrtcSettings:
    data = raw or {}
    providers = _default_providers()
    incoming = data.get("providers") or {}
    for name in PROVIDERS:
        src = incoming.get(name) or {}
        legacy_room = str(src.get("room") or "").strip()
        rooms = _parse_rooms(src.get("rooms"), legacy_room)
        # Миграция: пустой пул → дефолтные pc/android слоты
        if not rooms:
            rooms = _slots_from_defaults(name)
            if legacy_room and rooms:
                rooms[0].url = legacy_room
        # Старый одиночный room без android-слота → добавить android из дефолта
        elif name in ("wbstream", "telemost") and len(rooms) == 1:
            defaults = _slots_from_defaults(name)
            android_def = next((d for d in defaults if d.id == "android"), None)
            only = rooms[0]
            if only.id in ("default", "pc", "r0") and android_def:
                if only.id == "default":
                    only.id = "pc"
                if not only.device_types:
                    only.device_types = ["pc"]
                if not any(r.id == "android" for r in rooms):
                    rooms.append(android_def)
        providers[name] = OlcrtcProviderConfig(
            enabled=bool(src.get("enabled", False)),
            room=legacy_room or (rooms[0].url if rooms else ""),
            transport=str(src.get("transport") or DEFAULT_TRANSPORTS[name]).strip()
            or DEFAULT_TRANSPORTS[name],
            rooms=rooms,
        )
    key = str(data.get("crypto_key") or "").strip()
    return OlcrtcSettings(
        enabled=bool(data.get("enabled", False)),
        crypto_key=key,
        providers=providers,
        srv_status=str(data.get("srv_status") or "unknown"),
        srv_message=str(data.get("srv_message") or ""),
    )


async def load_olcrtc_settings(db: AsyncSession) -> OlcrtcSettings:
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == OLCRTC_SETTINGS_KEY)
    )
    row = result.scalar_one_or_none()
    if not row:
        return parse_settings(None)
    try:
        return parse_settings(json.loads(row.value))
    except (json.JSONDecodeError, TypeError, ValueError):
        return parse_settings(None)


async def save_olcrtc_settings(db: AsyncSession, settings: OlcrtcSettings) -> OlcrtcSettings:
    payload = json.dumps(settings.to_dict(), ensure_ascii=False)
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == OLCRTC_SETTINGS_KEY)
    )
    row = result.scalar_one_or_none()
    if row:
        row.value = payload
    else:
        db.add(AppSetting(key=OLCRTC_SETTINGS_KEY, value=payload))
    await db.commit()
    return settings


def normalize_device_type(device_type: str = "") -> str:
    dt = (device_type or "").strip().lower()
    if dt in ("ios", "android_tv", "android-tv"):
        return "android"
    if dt in ("pc", "android"):
        return dt
    return ""


def assign_room_slot(
    provider: OlcrtcProviderConfig,
    *,
    device_type: str = "",
    fingerprint: str = "",
) -> OlcrtcRoomSlot | None:
    """Выбор комнаты: сначала слоты под device_type, иначе hash sticky по fingerprint."""
    rooms = provider.effective_rooms()
    if not rooms:
        return None
    dt = normalize_device_type(device_type)

    typed = [r for r in rooms if dt and dt in (r.device_types or [])]
    pool = typed if typed else rooms
    if len(pool) == 1:
        return pool[0]
    key = f"{dt}|{fingerprint or 'anon'}"
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    idx = int(h[:8], 16) % len(pool)
    return pool[idx]


def public_client_config(
    settings: OlcrtcSettings,
    *,
    device_type: str = "",
    fingerprint: str = "",
) -> dict[str, Any]:
    """Публичный конфиг для debug-клиентов. room назначается из пула."""
    key_ok = len(settings.crypto_key) == 64
    providers_out: dict[str, Any] = {}
    assigned_slot: str | None = None
    dt = normalize_device_type(device_type)
    for name, p in settings.providers.items():
        slot = assign_room_slot(p, device_type=device_type, fingerprint=fingerprint)
        room_url = slot.url if slot else ""
        if slot and not assigned_slot:
            assigned_slot = slot.id
        enabled = bool(settings.enabled and p.enabled and key_ok and room_url)
        # Placeholder android rooms — не отдаём клиенту как «готово»
        if enabled and "REPLACE" in room_url.upper():
            enabled = False
            room_url = ""
        # Клиенту отдаём нормализованный id (telemost: цифры без URL)
        if enabled and room_url:
            room_url = normalize_room_id(name, room_url)
        providers_out[name] = {
            "enabled": enabled,
            "room": room_url if (settings.enabled and p.enabled and key_ok and enabled) else "",
            "transport": p.transport or DEFAULT_TRANSPORTS[name],
            "room_slot_id": slot.id if (enabled and slot) else "",
            "rooms_count": len(p.effective_rooms()),
        }
    return {
        "enabled": bool(settings.enabled and key_ok),
        "crypto_key": settings.crypto_key if (settings.enabled and key_ok) else "",
        "providers": providers_out,
        "socks_host": "127.0.0.1",
        "socks_port": 8808,
        "assigned_slot": assigned_slot or dt or "",
        "device_type": dt,
        # LTE: HTTP CONNECT на :8080 (18443 часто режется оператором). olcrtc может игнор. env —
        # основной обход DPI: android-комната на meet.playform.ru / WB / Telemost.
        "jitsi_https_proxy": "http://132.243.234.162:8080"
        if (settings.enabled and key_ok)
        else "",
    }


def _room_matches_slot(room: OlcrtcRoomSlot, slot_id: str) -> bool:
    sid = (slot_id or "").strip().lower()
    if not sid:
        return True
    if room.id.strip().lower() == sid:
        return True
    if sid in (room.device_types or []):
        return True
    return False


def collect_pool_slot_ids(settings: OlcrtcSettings) -> list[str]:
    """Уникальные slot id из всех enabled провайдеров (порядок: pc, android, …)."""
    seen: list[str] = []
    for name in PROVIDERS:
        p = settings.providers.get(name)
        if not p or not p.enabled:
            continue
        for r in p.effective_rooms():
            sid = (r.id or "").strip()
            if sid and sid not in seen:
                seen.append(sid)
    # Стабильный порядок: pc/android первыми
    preferred = [s for s in ("pc", "android") if s in seen]
    rest = [s for s in seen if s not in preferred]
    return preferred + rest


def normalize_room_id(provider: str, room: str) -> str:
    """Клиент/сервер должны быть в одной комнате; Telemost — numeric id из URL."""
    u = (room or "").strip()
    if not u:
        return ""
    if provider == "telemost":
        import re

        m = re.search(r"/j/(\d+)", u)
        if m:
            return m.group(1)
        if re.fullmatch(r"\d{8,}", u):
            return u
    return u


def render_server_yaml(
    settings: OlcrtcSettings,
    *,
    slot_id: str | None = None,
    provider: str | None = None,
) -> str:
    """YAML для olcrtc mode=srv — ровно один провайдер + один слот.

    Failover нескольких провайдеров в одном процессе нельзя: srv залипает на
    первом живом (jitsi) и клиент на telemost/wb ждёт peer вечно.
    Unit: olcrtc@pc-telemost ← server-pc-telemost.yaml
    """
    if not settings.crypto_key or len(settings.crypto_key) != 64:
        raise ValueError("crypto_key must be 64 hex characters")

    names = [provider] if provider else list(PROVIDERS)
    profiles: list[tuple[str, str, str]] = []  # (name, provider, room_url)

    for name in names:
        if name not in PROVIDERS:
            continue
        p = settings.providers.get(name)
        if not p or not p.enabled:
            continue
        rooms = p.effective_rooms()
        if not rooms:
            continue
        if slot_id:
            matched = [r for r in rooms if _room_matches_slot(r, slot_id)]
            if not matched:
                continue
            for r in matched:
                rid = normalize_room_id(name, r.url)
                if is_placeholder_room(rid):
                    continue
                profiles.append((f"{name}-{r.id}", name, rid))
        else:
            r = rooms[0]
            rid = normalize_room_id(name, r.url)
            if not is_placeholder_room(rid):
                profiles.append((f"{name}-{r.id}", name, rid))

    if not profiles:
        raise ValueError(
            "нужен включённый провайдер с room"
            + (f" provider={provider}" if provider else "")
            + (f" slot={slot_id}" if slot_id else "")
        )

    # Один профиль на unit — без «залипания» на jitsi
    pname, prov, room_url = profiles[0]
    transport = (
        settings.providers.get(prov).transport  # type: ignore[union-attr]
        if settings.providers.get(prov)
        else DEFAULT_TRANSPORTS.get(prov, "datachannel")
    )
    if slot_id and provider:
        data_dir = f"data-{slot_id}-{provider}"
    elif slot_id:
        data_dir = f"data-{slot_id}"
    else:
        data_dir = "data"

    lines = [
        "mode: srv",
        "crypto:",
        f'  key: "{settings.crypto_key}"',
        "net:",
        '  dns: "8.8.8.8:53"',
        f"data: {data_dir}",
        "profiles:",
        f"  - name: {pname}",
        "    auth:",
        f"      provider: {prov}",
        "    room:",
        f'      id: "{room_url}"',
        "    net:",
        f"      transport: {transport}",
        '      dns: "8.8.8.8:53"',
        "failover:",
        "  retry_delay: 2s",
        "  max_cycles: 0",
        "",
    ]
    return "\n".join(lines)


def collect_unit_ids(settings: OlcrtcSettings) -> list[str]:
    """systemd instance ids: pc-jitsi, pc-telemost, android-jitsi, …"""
    out: list[str] = []
    for sid in collect_pool_slot_ids(settings):
        for name in PROVIDERS:
            p = settings.providers.get(name)
            if not p or not p.enabled:
                continue
            matched = [
                r
                for r in p.effective_rooms()
                if _room_matches_slot(r, sid) and not is_placeholder_room(r.url)
            ]
            if not matched:
                continue
            uid = f"{sid}-{name}"
            if uid not in out:
                out.append(uid)
    return out


def render_all_server_yaml_files(settings: OlcrtcSettings) -> dict[str, str]:
    """unit_id → yaml. Отдельный srv на (slot, provider); legacy pc/android = *-jitsi."""
    out: dict[str, str] = {}
    for uid in collect_unit_ids(settings):
        # uid = "{slot}-{provider}"
        parts = uid.rsplit("-", 1)
        if len(parts) != 2 or parts[1] not in PROVIDERS:
            continue
        sid, prov = parts[0], parts[1]
        out[uid] = render_server_yaml(settings, slot_id=sid, provider=prov)
    if "pc-jitsi" in out:
        out["pc"] = out["pc-jitsi"]
        out["default"] = out["pc-jitsi"]
    elif "pc-telemost" in out:
        out["pc"] = out["pc-telemost"]
        out["default"] = out["pc-telemost"]
    elif out:
        first = next(iter(out.values()))
        out["default"] = first
    if "android-jitsi" in out:
        out["android"] = out["android-jitsi"]
    elif "android-telemost" in out:
        out["android"] = out["android-telemost"]
    if not out:
        out["default"] = render_server_yaml(settings)
    return out


def render_client_yaml(
    settings: OlcrtcSettings,
    provider: str,
    *,
    socks_host: str = "127.0.0.1",
    socks_port: int = 8808,
    device_type: str = "",
    fingerprint: str = "",
) -> str:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    p = settings.providers.get(provider) or OlcrtcProviderConfig(
        transport=DEFAULT_TRANSPORTS[provider]
    )
    if not settings.crypto_key or len(settings.crypto_key) != 64:
        raise ValueError("crypto_key must be 64 hex characters")
    slot = assign_room_slot(p, device_type=device_type, fingerprint=fingerprint)
    if not slot or not slot.url.strip():
        raise ValueError(f"room empty for {provider}")
    room_id = normalize_room_id(provider, slot.url)
    return "\n".join(
        [
            "mode: cnc",
            "auth:",
            f"  provider: {provider}",
            "room:",
            f'  id: "{room_id}"',
            "crypto:",
            f'  key: "{settings.crypto_key}"',
            "net:",
            f"  transport: {p.transport}",
            '  dns: "8.8.8.8:53"',
            "socks:",
            f'  host: "{socks_host}"',
            f"  port: {socks_port}",
            "data: data",
            "",
        ]
    )


def apply_yaml_paths() -> list[Path]:
    """Куда API пишет server.yaml для последующего deploy_olcrtc.py / host unit."""
    return [
        Path("/app/update/olcrtc/server.yaml"),
        Path(__file__).resolve().parents[2] / "update" / "olcrtc" / "server.yaml",
    ]


def write_server_yaml_file(yaml_text: str, *, filename: str = "server.yaml") -> str:
    last_err: Exception | None = None
    for base in [
        Path("/app/update/olcrtc"),
        Path(__file__).resolve().parents[2] / "update" / "olcrtc",
    ]:
        try:
            base.mkdir(parents=True, exist_ok=True)
            path = base / filename
            path.write_text(yaml_text, encoding="utf-8")
            return str(path)
        except OSError as e:
            last_err = e
    raise RuntimeError(f"cannot write {filename}: {last_err}")


def write_all_server_yaml_files(settings: OlcrtcSettings) -> list[str]:
    files = render_all_server_yaml_files(settings)
    written: list[str] = []
    for slot_id, yaml_text in files.items():
        name = "server.yaml" if slot_id == "default" else f"server-{slot_id}.yaml"
        written.append(write_server_yaml_file(yaml_text, filename=name))
    return written


def is_placeholder_room(url: str) -> bool:
    u = (url or "").strip().upper()
    return (not u) or ("REPLACE" in u) or u.endswith("-PLACEHOLDER")
