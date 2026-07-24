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
    jitsi_rooms = [
        OlcrtcRoomSlot(
            id=r["id"],
            url=r["url"],
            max_clients=int(r.get("max_clients", 4)),
            device_types=list(r.get("device_types") or []),
        )
        for r in DEFAULT_JITSI_ROOMS
    ]
    return {
        "jitsi": OlcrtcProviderConfig(
            enabled=False,
            room=DEFAULT_JITSI_ROOMS[0]["url"],
            transport=DEFAULT_TRANSPORTS["jitsi"],
            rooms=jitsi_rooms,
        ),
        "wbstream": OlcrtcProviderConfig(
            enabled=False,
            room="",
            transport=DEFAULT_TRANSPORTS["wbstream"],
            rooms=[],
        ),
        "telemost": OlcrtcProviderConfig(
            enabled=False,
            room="",
            transport=DEFAULT_TRANSPORTS["telemost"],
            rooms=[],
        ),
    }


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
        # Миграция: старый одиночный jitsi room → пул pc/android, если rooms пуст
        if name == "jitsi" and not rooms:
            rooms = [
                OlcrtcRoomSlot(
                    id=r["id"],
                    url=r["url"],
                    max_clients=int(r.get("max_clients", 4)),
                    device_types=list(r.get("device_types") or []),
                )
                for r in DEFAULT_JITSI_ROOMS
            ]
            if legacy_room:
                rooms[0].url = legacy_room
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
    dt = (device_type or "").strip().lower()
    if dt in ("ios", "android_tv", "android-tv"):
        dt = "android"
    if dt not in ("pc", "android"):
        # неизвестный тип — sticky по fingerprint среди всех
        dt = ""

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
    for name, p in settings.providers.items():
        slot = assign_room_slot(p, device_type=device_type, fingerprint=fingerprint)
        room_url = slot.url if slot else ""
        if name == "jitsi" and slot:
            assigned_slot = slot.id
        enabled = bool(settings.enabled and p.enabled and key_ok and room_url)
        providers_out[name] = {
            "enabled": enabled,
            "room": room_url if (settings.enabled and p.enabled and key_ok) else "",
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
        "assigned_slot": assigned_slot or "",
        "device_type": (device_type or "").strip().lower(),
        # LTE: HTTP CONNECT на :8080 (18443 часто режется оператором). olcrtc может игнор. env —
        # основной обход DPI: android-комната на meet.playform.ru.
        "jitsi_https_proxy": "http://132.243.234.162:8080"
        if (settings.enabled and key_ok)
        else "",
    }


def render_server_yaml(settings: OlcrtcSettings, *, slot_id: str | None = None) -> str:
    """YAML для olcrtc mode=srv.

    slot_id: если задан — только эта jitsi-комната из пула (для systemd olcrtc@pc / @android).
    Без slot_id — legacy: один yaml со всеми enabled провайдерами (первая jitsi-комната).
    """
    if not settings.crypto_key or len(settings.crypto_key) != 64:
        raise ValueError("crypto_key must be 64 hex characters")

    profiles: list[tuple[str, str, str]] = []  # (name, provider, room_url)

    jitsi = settings.providers.get("jitsi")
    if jitsi and jitsi.enabled:
        rooms = jitsi.effective_rooms()
        if slot_id:
            rooms = [r for r in rooms if r.id == slot_id]
            if not rooms:
                raise ValueError(f"jitsi room slot not found: {slot_id}")
            for r in rooms:
                profiles.append((f"jitsi-{r.id}", "jitsi", r.url))
        else:
            # Один srv: только первая комната (остальные — отдельные unit'ы)
            if rooms:
                r = rooms[0]
                profiles.append((f"jitsi-{r.id}", "jitsi", r.url))

    for name in ("wbstream", "telemost"):
        p = settings.providers.get(name)
        if not p or not p.enabled:
            continue
        rooms = p.effective_rooms()
        if not rooms:
            continue
        # Для non-jitsi оставляем в «главном» yaml без slot_id
        if slot_id and slot_id not in ("pc", "default", rooms[0].id):
            continue
        if slot_id and slot_id == "android":
            continue
        profiles.append((name, name, rooms[0].url))

    if not profiles:
        raise ValueError("нужен хотя бы один включённый провайдер с room")

    data_dir = f"data-{slot_id}" if slot_id else "data"
    lines = [
        "mode: srv",
        "crypto:",
        f'  key: "{settings.crypto_key}"',
        "net:",
        '  dns: "8.8.8.8:53"',
        f"data: {data_dir}",
        "profiles:",
    ]
    for pname, provider, room_url in profiles:
        transport = (
            settings.providers.get(provider).transport  # type: ignore[union-attr]
            if settings.providers.get(provider)
            else DEFAULT_TRANSPORTS.get(provider, "datachannel")
        )
        lines.append(f"  - name: {pname}")
        lines.append("    auth:")
        lines.append(f"      provider: {provider}")
        lines.append("    room:")
        lines.append(f'      id: "{room_url}"')
        lines.append("    net:")
        lines.append(f"      transport: {transport}")
        lines.append('      dns: "8.8.8.8:53"')
    lines.append("failover:")
    lines.append("  retry_delay: 2s")
    lines.append("  max_cycles: 0")
    lines.append("")
    return "\n".join(lines)


def render_all_server_yaml_files(settings: OlcrtcSettings) -> dict[str, str]:
    """slot_id → yaml. Для jitsi-пула: pc + android (+ legacy server.yaml = pc)."""
    out: dict[str, str] = {}
    jitsi = settings.providers.get("jitsi")
    if jitsi and jitsi.enabled and jitsi.effective_rooms():
        rooms = jitsi.effective_rooms()
        for r in rooms:
            out[r.id] = render_server_yaml(settings, slot_id=r.id)
        # legacy path
        out["default"] = out.get("pc") or next(iter(out.values()))
    else:
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
    return "\n".join(
        [
            "mode: cnc",
            "auth:",
            f"  provider: {provider}",
            "room:",
            f'  id: "{slot.url}"',
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
