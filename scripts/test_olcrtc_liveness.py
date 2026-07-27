"""Unit tests for olcrtc room liveness classification."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai.olcrtc_room_liveness import _normalize_tm_url, _normalize_wb_id, _wb_body_means_dead


def test_wb_dead_404():
    assert _wb_body_means_dead(404, '{"code":5,"message":"Not Found"}')


def test_wb_dead_guests_cannot_create():
    assert _wb_body_means_dead(
        403, '{"code":7,"message":"guests cannot create rooms","details":[]}'
    )


def test_wb_alive_not_dead():
    assert not _wb_body_means_dead(200, "{}")
    assert not _wb_body_means_dead(401, '{"message":"invalid_token"}')
    assert not _wb_body_means_dead(500, "oops")


def test_normalize_wb():
    assert (
        _normalize_wb_id("https://stream.wb.ru/room/019fa3a0-3ff8-77fa-a5a5-2c87a48e34e0")
        == "019fa3a0-3ff8-77fa-a5a5-2c87a48e34e0"
    )
    assert _normalize_wb_id("019fa3a0-3ff8-77fa-a5a5-2c87a48e34e0") == (
        "019fa3a0-3ff8-77fa-a5a5-2c87a48e34e0"
    )


def test_normalize_tm():
    assert _normalize_tm_url("41676137683602") == "https://telemost.yandex.ru/j/41676137683602"
    assert _normalize_tm_url("https://telemost.yandex.ru/j/1") == "https://telemost.yandex.ru/j/1"


if __name__ == "__main__":
    test_wb_dead_404()
    test_wb_dead_guests_cannot_create()
    test_wb_alive_not_dead()
    test_normalize_wb()
    test_normalize_tm()
    print("ok")
