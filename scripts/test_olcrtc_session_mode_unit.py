"""Unit: session-mode flags (source-level, no DB/asyncpg)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_AGENT_SRC = (ROOT / "ai" / "olcrtc_room_agent.py").read_text(encoding="utf-8")
_ASSIGN_SRC = (ROOT / "app" / "services" / "olcrtc_assign.py").read_text(encoding="utf-8")
_HOST_SRC = (ROOT / "ai" / "olcrtc_host_provision_client.py").read_text(encoding="utf-8")
_RESET = ROOT / "scripts" / "olcrtc_session_reset.py"


def test_max_create_one():
    assert "MAX_CREATE_PER_CYCLE = 1" in _AGENT_SRC


def test_session_mode_fields():
    assert "session_mode: bool = True" in _AGENT_SRC
    assert "bootstrap_warm: int = 0" in _AGENT_SRC
    assert '"session_mode": state.session_mode' in _AGENT_SRC


def test_heal_skips_autoscale_in_session():
    assert "if state.session_mode:" in _AGENT_SRC
    assert "_bootstrap_warm_rooms" in _AGENT_SRC
    assert "_autoscale_pool" in _AGENT_SRC
    # session branch before legacy autoscale
    i_sess = _AGENT_SRC.index("if state.session_mode:")
    i_auto = _AGENT_SRC.index("if await _autoscale_pool")
    assert i_sess < i_auto


def test_request_scale_skips_session():
    assert "session_mode" in _AGENT_SRC
    assert "on-demand scale skipped (session_mode)" in _AGENT_SRC


def test_ensure_release_in_assign():
    assert "async def ensure_session_room" in _ASSIGN_SRC
    assert "async def release_session_room" in _ASSIGN_SRC
    assert "await ensure_session_room(" in _ASSIGN_SRC
    assert "await release_session_room(" in _ASSIGN_SRC
    assert "session ensure: Link timeout" in _ASSIGN_SRC


def test_host_only_fail_fast():
    assert "OLCRTC_HOST_ONLY" in _HOST_SRC
    assert "OLCRTC_ALLOW_INCONTAINER_PLAYWRIGHT" in _HOST_SRC


def test_reset_script_exists():
    assert _RESET.is_file()
    text = _RESET.read_text(encoding="utf-8")
    assert "session_mode" in text
    assert "telemost" in text
    assert "olcrtc@" in text


def test_default_max_clients_one():
    assert re.search(r"DEFAULT_MAX_CLIENTS\s*=\s*1", _AGENT_SRC)


if __name__ == "__main__":
    test_max_create_one()
    test_session_mode_fields()
    test_heal_skips_autoscale_in_session()
    test_request_scale_skips_session()
    test_ensure_release_in_assign()
    test_host_only_fail_fast()
    test_reset_script_exists()
    test_default_max_clients_one()
    print("OK", 8)
