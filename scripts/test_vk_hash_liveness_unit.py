"""Unit tests: VK join-hash liveness classify/apply (no network)."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai.vk_hash_liveness import (  # noqa: E402
    ERROR_DEAD,
    ERROR_OK,
    ERROR_PROBE_PENDING,
    KIND_ALIVE,
    KIND_DEAD,
    KIND_FLOOD,
    KIND_SKIP,
    apply_probe_kind,
    classify_preview_payload,
    classify_vk_api_error,
    is_call_dead_message,
    is_stale_anonym_token,
    select_probe_batch,
)


def test_outdated_is_not_dead():
    assert is_stale_anonym_token("PARAM : error.webrtc.auth.anonym_token.outdated")
    assert not is_call_dead_message("anonym_token.outdated")
    assert classify_vk_api_error(100, "PARAM : error.webrtc.auth.anonym_token.outdated") == KIND_SKIP


def test_call_not_found_is_dead():
    assert is_call_dead_message("call not found")
    assert classify_vk_api_error(15, "Call not found") == KIND_DEAD
    payload = {"error": {"error_code": 100, "error_msg": "conversation not found"}}
    assert classify_preview_payload(payload) == KIND_DEAD


def test_preview_alive():
    assert classify_preview_payload({"response": {"user_id": 1}}) == KIND_ALIVE


def test_flood():
    assert classify_vk_api_error(9, "Flood control") == KIND_FLOOD


def test_apply_two_dead_marks_error_1():
    state = {"last_error_code": ERROR_OK, "is_active": True, "fail_count": 0}
    assert apply_probe_kind(state, KIND_DEAD) == "pending"
    assert state["last_error_code"] == ERROR_PROBE_PENDING
    assert state["is_active"] is True
    assert apply_probe_kind(state, KIND_DEAD) == "deactivated"
    assert state["last_error_code"] == ERROR_DEAD
    assert state["is_active"] is False


def test_apply_alive_resets():
    state = {"last_error_code": ERROR_PROBE_PENDING, "is_active": True, "fail_count": 3}
    assert apply_probe_kind(state, KIND_ALIVE) == "alive"
    assert state["last_error_code"] == ERROR_OK
    assert state["fail_count"] == 0


def test_skip_and_flood_do_not_mutate():
    state = {"last_error_code": 0, "is_active": True, "fail_count": 1}
    apply_probe_kind(state, KIND_SKIP)
    apply_probe_kind(state, KIND_FLOOD)
    assert state["fail_count"] == 1
    assert state["is_active"] is True


def test_select_batch_prefers_pending():
    pending = SimpleNamespace(id="a", last_error_code=ERROR_PROBE_PENDING, fail_count=0, last_checked=None)
    ok = SimpleNamespace(id="b", last_error_code=0, fail_count=0, last_checked=None)
    batch = select_probe_batch([ok, pending], cursor="b", budget=1)
    assert batch[0] is pending


if __name__ == "__main__":
    test_outdated_is_not_dead()
    test_call_not_found_is_dead()
    test_preview_alive()
    test_flood()
    test_apply_two_dead_marks_error_1()
    test_apply_alive_resets()
    test_skip_and_flood_do_not_mutate()
    test_select_batch_prefers_pending()
    print("ok")
