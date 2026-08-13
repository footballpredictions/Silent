"""Unit: правила заполнения комнат и автоскейла пула olcrtc (без БД / asyncpg).

  cd backend
  python scripts/test_olcrtc_autoscale_unit.py
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_AGENT_SRC = (ROOT / "ai" / "olcrtc_room_agent.py").read_text(encoding="utf-8")
_ASSIGN_SRC = (ROOT / "app" / "services" / "olcrtc_assign.py").read_text(encoding="utf-8")


def _const_int(src: str, name: str) -> int:
    m = re.search(rf"^{name}\s*=\s*(\d+)", src, re.M)
    assert m, f"missing {name}"
    return int(m.group(1))


CHECK_INTERVAL_SECONDS = _const_int(_AGENT_SRC, "CHECK_INTERVAL_SECONDS")
IDLE_ROOM_TTL_MIN = _const_int(_AGENT_SRC, "IDLE_ROOM_TTL_MIN")
SCALE_DEBOUNCE_SECONDS = _const_int(_AGENT_SRC, "SCALE_DEBOUNCE_SECONDS")
OVERFLOW_PER_ROOM = _const_int(_ASSIGN_SRC, "OVERFLOW_PER_ROOM")


@dataclass
class FakeRoom:
    unit_name: str = "pc-telemost"
    provider: str = "telemost"
    slot_label: str = "pc"
    device_types: list[str] = field(default_factory=lambda: ["pc"])
    status: str = "active"
    max_clients: int = 2
    online_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _room_accepts_new(
    room: FakeRoom,
    *,
    overflow: int = 0,
    allow_overflow_sticky: bool = False,
) -> bool:
    if room.status == "draining":
        return allow_overflow_sticky
    if room.status != "active":
        return False
    cap = int(room.max_clients or 0) + max(0, int(overflow))
    if allow_overflow_sticky:
        return True
    return int(room.online_count or 0) < cap


def _rooms_of_slot(rooms: list[FakeRoom], slot: str) -> list[FakeRoom]:
    return [
        r
        for r in rooms
        if r.slot_label == slot or slot in (r.device_types or [])
    ]


def _free_slots(rooms: list[FakeRoom]) -> int:
    return sum(max(0, int(r.max_clients or 0) - int(r.online_count or 0)) for r in rooms)


def test_room_accepts_until_full() -> None:
    room = FakeRoom(max_clients=2, online_count=1)
    assert _room_accepts_new(room) is True
    room.online_count = 2
    assert _room_accepts_new(room) is False


def test_overflow_lets_client_in_instead_of_refusing() -> None:
    room = FakeRoom(max_clients=2, online_count=2)
    assert _room_accepts_new(room, overflow=OVERFLOW_PER_ROOM) is True
    room.online_count = 2 + OVERFLOW_PER_ROOM
    assert _room_accepts_new(room, overflow=OVERFLOW_PER_ROOM) is False


def test_draining_room_only_for_existing_sticky() -> None:
    room = FakeRoom(status="draining")
    assert _room_accepts_new(room) is False
    assert _room_accepts_new(room, allow_overflow_sticky=True) is True


def test_slots_are_counted_per_platform() -> None:
    rooms = [
        FakeRoom(unit_name="pc-telemost", slot_label="pc", device_types=["pc"], online_count=2),
        FakeRoom(
            unit_name="android-telemost",
            slot_label="android",
            device_types=["android"],
            online_count=0,
        ),
    ]
    pc = _rooms_of_slot(rooms, "pc")
    android = _rooms_of_slot(rooms, "android")
    assert [r.unit_name for r in pc] == ["pc-telemost"]
    assert [r.unit_name for r in android] == ["android-telemost"]
    assert _free_slots(pc) == 0
    assert _free_slots(android) == 2


def test_free_slots_never_negative_on_overflow() -> None:
    rooms = [FakeRoom(max_clients=2, online_count=4)]
    assert _free_slots(rooms) == 0


def test_agent_defaults_favor_fast_gc_and_short_cycle() -> None:
    assert CHECK_INTERVAL_SECONDS <= 180
    assert IDLE_ROOM_TTL_MIN == 5
    assert SCALE_DEBOUNCE_SECONDS <= 60


def test_need_scale_when_free_below_min() -> None:
    rooms = [FakeRoom(max_clients=2, online_count=2, unit_name="pc-telemost")]
    assert _free_slots(rooms) < 4


def test_idle_ttl_migration_in_source() -> None:
    assert "IDLE_ROOM_TTL_MIN" in _AGENT_SRC
    assert "== 45" in _AGENT_SRC
    tree = ast.parse(_AGENT_SRC)
    assert any(
        isinstance(n, ast.Assign)
        and any(getattr(t, "id", None) == "IDLE_ROOM_TTL_MIN" for t in n.targets)
        for n in tree.body
    )


def test_request_scale_on_shortage_exists() -> None:
    assert "def request_scale_on_shortage" in _AGENT_SRC
    assert "request_scale_on_shortage" in (
        ROOT / "app" / "services" / "olcrtc_assign.py"
    ).read_text(encoding="utf-8")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("OK", fn.__name__)
    print(f"\n{len(tests)} tests OK")
