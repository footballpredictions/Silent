"""olcrtc room agents removed — WDTT only (2026-08-28)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_room_agents_deleted() -> None:
    assert not (ROOT / "ai" / "olcrtc_room_agent.py").is_file()
    assert not (ROOT / "ai" / "olcrtc2_room_agent.py").is_file()


if __name__ == "__main__":
    test_room_agents_deleted()
    print("OK room agents removed")
