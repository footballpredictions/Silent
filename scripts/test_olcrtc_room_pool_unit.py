"""Unit tests: WB/Telemost room pool + per-provider yaml units (no DB)."""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as _app_pkg  # noqa: F401, E402

_fake_models = types.ModuleType("app.models")


class _AppSetting:
    pass


_fake_models.AppSetting = _AppSetting
sys.modules["app.models"] = _fake_models

from app.services.olcrtc_settings import (  # noqa: E402
    OlcrtcProviderConfig,
    OlcrtcRoomSlot,
    OlcrtcSettings,
    assign_room_slot,
    collect_unit_ids,
    is_placeholder_room,
    normalize_room_id,
    public_client_config,
    render_all_server_yaml_files,
)


def _settings() -> OlcrtcSettings:
    key = "a" * 64
    return OlcrtcSettings(
        enabled=True,
        crypto_key=key,
        providers={
            "jitsi": OlcrtcProviderConfig(
                enabled=True,
                transport="datachannel",
                rooms=[
                    OlcrtcRoomSlot("pc", "https://meet.egovm.ru/Hive", 4, ["pc"]),
                    OlcrtcRoomSlot("android", "https://meet.playform.ru/HiveA", 4, ["android"]),
                ],
            ),
            "wbstream": OlcrtcProviderConfig(
                enabled=True,
                transport="vp8channel",
                rooms=[
                    OlcrtcRoomSlot("pc", "wb-pc-uuid", 4, ["pc"]),
                    OlcrtcRoomSlot("android", "wb-android-uuid", 4, ["android"]),
                ],
            ),
            "telemost": OlcrtcProviderConfig(
                enabled=True,
                transport="vp8channel",
                rooms=[
                    OlcrtcRoomSlot(
                        "pc", "https://telemost.yandex.ru/j/72153214476536", 4, ["pc"]
                    ),
                    OlcrtcRoomSlot("android", "22222222222222", 4, ["android"]),
                ],
            ),
        },
    )


def test_assign_by_device():
    s = _settings()
    wb = s.providers["wbstream"]
    assert assign_room_slot(wb, device_type="pc").url == "wb-pc-uuid"
    assert assign_room_slot(wb, device_type="android").url == "wb-android-uuid"


def test_separate_units_per_provider():
    s = _settings()
    units = collect_unit_ids(s)
    assert "pc-jitsi" in units
    assert "pc-telemost" in units
    assert "pc-wbstream" in units
    assert "android-telemost" in units
    files = render_all_server_yaml_files(s)
    y_tm = files["pc-telemost"]
    assert "provider: telemost" in y_tm
    assert "72153214476536" in y_tm
    assert "provider: jitsi" not in y_tm
    assert "data-pc-telemost" in y_tm
    y_j = files["pc-jitsi"]
    assert "provider: jitsi" in y_j
    assert "provider: telemost" not in y_j


def test_client_gets_numeric_telemost():
    s = _settings()
    cfg = public_client_config(s, device_type="pc")
    assert cfg["providers"]["telemost"]["room"] == "72153214476536"


def test_normalize():
    assert normalize_room_id("telemost", "https://telemost.yandex.ru/j/123") == "123"
    assert not is_placeholder_room("72153214476536")


if __name__ == "__main__":
    test_assign_by_device()
    test_separate_units_per_provider()
    test_client_gets_numeric_telemost()
    test_normalize()
    print("OK", 4)
