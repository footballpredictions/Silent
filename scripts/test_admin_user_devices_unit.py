"""Unit: админка — список устройств пользователя без секретов."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.admin_user_devices import device_public_dict  # noqa: E402

SECRET_ATTRS = (
    "wg_private_key_enc",
    "wdtt_password",
    "wg_public_key",
    "wg_live_public_key",
    "wg_private_key",
    "device_fingerprint",
)


def _device(**over):
    base = dict(
        id=uuid4(),
        device_name="vivo V2520A",
        device_type="android",
        last_ip="10.66.66.8",
        last_connected=datetime(2026, 9, 19, 14, 0, 0),
        created_at=datetime(2026, 9, 1, 10, 0, 0),
        is_connected=True,
        preferred_server="queen",
        wg_private_key_enc="SECRET-PRIV",
        wdtt_password="SECRET-PWD",
        wg_public_key="SECRET-PUB",
        wg_live_public_key="SECRET-LIVE",
        device_fingerprint="fp-should-not-leak",
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_public_dict_shows_session_fields():
    row = device_public_dict(_device())
    assert row["device_name"] == "vivo V2520A"
    assert row["device_type"] == "android"
    assert row["last_ip"] == "10.66.66.8"
    assert row["is_connected"] is True
    assert row["preferred_server"] == "queen"
    assert "id" in row
    assert row["last_connected"] == datetime(2026, 9, 19, 14, 0, 0)
    assert row["created_at"] == datetime(2026, 9, 1, 10, 0, 0)


def test_public_dict_omits_keys_and_fingerprint():
    row = device_public_dict(_device())
    keys = set(row)
    for secret in SECRET_ATTRS:
        assert secret not in keys
        assert "SECRET" not in str(row.values())


def test_empty_name_falls_back_to_type():
    row = device_public_dict(_device(device_name="  ", device_type="pc"))
    assert row["device_name"] == "pc"


if __name__ == "__main__":
    test_public_dict_shows_session_fields()
    test_public_dict_omits_keys_and_fingerprint()
    test_empty_name_falls_back_to_type()
    print("ok")
