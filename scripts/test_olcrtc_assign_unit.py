"""Unit: normalize + pool denied messaging (no DB)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.olcrtc_assign import NO_ROOM_DETAIL  # noqa: E402
from app.services.olcrtc_settings import normalize_room_id  # noqa: E402


def test_normalize_and_denied_text():
    assert normalize_room_id("telemost", "https://telemost.yandex.ru/j/99") == "99"
    assert "свободных" in NO_ROOM_DETAIL.lower() or "комнат" in NO_ROOM_DETAIL.lower()


if __name__ == "__main__":
    test_normalize_and_denied_text()
    print("OK", 1)
