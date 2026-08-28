"""olcrtc room agents removed — leftover session-mode checks without agent source."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_ASSIGN_SRC = (ROOT / "app" / "services" / "olcrtc_assign.py").read_text(encoding="utf-8")
_HOST_SRC = (ROOT / "ai" / "olcrtc_host_provision_client.py").read_text(encoding="utf-8")
_RESET = ROOT / "scripts" / "olcrtc_session_reset.py"


def test_room_agents_deleted():
    assert not (ROOT / "ai" / "olcrtc_room_agent.py").is_file()
    assert not (ROOT / "ai" / "olcrtc2_room_agent.py").is_file()


def test_ensure_release_in_assign():
    assert "async def ensure_session_room" in _ASSIGN_SRC
    assert "async def release_session_room" in _ASSIGN_SRC


def test_host_only_fail_fast():
    assert "OLCRTC_HOST_ONLY" in _HOST_SRC
    assert "OLCRTC_ALLOW_INCONTAINER_PLAYWRIGHT" in _HOST_SRC


def test_reset_script_exists():
    assert _RESET.is_file()


if __name__ == "__main__":
    test_room_agents_deleted()
    test_ensure_release_in_assign()
    test_host_only_fail_fast()
    test_reset_script_exists()
    print("OK", 4)
