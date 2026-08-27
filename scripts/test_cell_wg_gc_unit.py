"""Unit tests: cell-agent local WG GC keeps manifest keys."""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cell-agent"))

fastapi_stub = ModuleType("fastapi")
fastapi_stub.FastAPI = object
fastapi_stub.Header = object
fastapi_stub.HTTPException = Exception
fastapi_stub.Request = object
sys.modules.setdefault("fastapi", fastapi_stub)
responses_stub = ModuleType("fastapi.responses")
responses_stub.JSONResponse = object
responses_stub.Response = object
sys.modules.setdefault("fastapi.responses", responses_stub)

pydantic_stub = ModuleType("pydantic")

class _BaseModel:
    pass

pydantic_stub.BaseModel = _BaseModel
sys.modules.setdefault("pydantic", pydantic_stub)
sys.modules.setdefault("httpx", ModuleType("httpx"))

import standby_runtime as sr  # noqa: E402


def test_peer_host_allowed_always_slash32():
    assert sr.peer_host_allowed("10.66.0.6/16") == "10.66.0.6/32"
    assert sr.peer_host_allowed("10.66.66.223/24") == "10.66.66.223/32"
    assert sr.peer_host_allowed("10.66.1.36/32") == "10.66.1.36/32"
    assert sr.peer_host_allowed("10.66.1.36") == "10.66.1.36/32"
    assert sr.peer_host_allowed("") == ""
    assert sr.peer_host_allowed(None) == ""


def test_gc_keeps_manifest_key_drops_never_and_stale():
    known = "devicekeyaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa="
    dead = "deadextraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa="
    live = "liveextraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa="
    old = "oldextraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa="
    sr._known_device_pubs = lambda: {known}  # type: ignore[method-assign]
    sr._local_handshakes = lambda: [  # type: ignore[method-assign]
        (known, None),
        (dead, None),
        (live, 30.0),
        (old, 7 * 3600.0),
    ]
    removed: list[str] = []
    sr.kick_wg_peer = lambda p: removed.append(p) or True  # type: ignore[assignment]
    sr._pending_never_hs.clear()
    sr._last_gc_at = 0.0
    got = sr.gc_stale_local_peers(grace_sec=0, limit=40)
    assert known not in removed
    assert live not in removed
    assert dead in removed
    assert old in removed
    assert got["removed"] == 2


def test_gc_throttles_within_window():
    sr._last_gc_at = sr.time.time()
    sr._known_device_pubs = lambda: set()  # type: ignore[method-assign]
    sr._local_handshakes = lambda: [("deadextraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa=", None)]  # type: ignore[method-assign]
    got = sr.gc_stale_local_peers(grace_sec=90, limit=40)
    assert got.get("skipped") is True


def test_failover_paths_allow_client_api_not_admin():
    assert sr.is_public_failover_path("vpn/theme")
    assert sr.is_public_failover_path("auth/login")
    assert sr.is_public_failover_path("payments/plans")
    assert not sr.is_public_failover_path("admin/stats")
    assert not sr.is_public_failover_path("vpn/internal/online")


def test_queen_health_urls_prefer_direct_ip():
    urls = sr.queen_health_urls("132.243.234.162", "https://132-243-234-162.nip.io")
    assert urls[0] == "http://132.243.234.162:8000/health"
    assert urls[1] == "https://132-243-234-162.nip.io/health"


def test_one_health_fail_does_not_enter_standby():
    healthy, streak, action = sr.apply_queen_health_tick(
        now_healthy=False, was_healthy=True, fail_streak=0, need=3
    )
    assert healthy is True
    assert streak == 1
    assert action is None


def test_three_health_fails_enter_standby():
    healthy, streak, action = True, 0, None
    for _ in range(3):
        healthy, streak, action = sr.apply_queen_health_tick(
            now_healthy=False, was_healthy=healthy, fail_streak=streak, need=3
        )
    assert healthy is False
    assert streak == 3
    assert action == "standby"


def test_health_ok_restores_queen_dnat():
    healthy, streak, action = sr.apply_queen_health_tick(
        now_healthy=True, was_healthy=False, fail_streak=5, need=3
    )
    assert healthy is True
    assert streak == 0
    assert action == "queen"


def test_manifest_does_not_steal_ip_from_live_extra():
    extra = "liveextraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa="
    android = "androidkeyaaaaaaaaaaaaaaaaaaaaaaaaaaaa="
    allowed = {extra: "10.66.0.71/32", android: "(none)"}
    hs = {extra: 40.0, android: None}
    assert sr.should_skip_manifest_ip_steal(android, "10.66.0.71/32", allowed, hs) is True
    assert sr.should_skip_manifest_ip_steal(extra, "10.66.0.71/32", allowed, hs) is False


def test_manifest_may_take_ip_from_never_hs_holder():
    dead = "deadextraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa="
    android = "androidkeyaaaaaaaaaaaaaaaaaaaaaaaaaaaa="
    allowed = {dead: "10.66.0.71/32"}
    hs = {dead: None, android: None}
    assert sr.should_skip_manifest_ip_steal(android, "10.66.0.71/32", allowed, hs) is False


def test_heal_restores_empty_live_extra_from_never_hs():
    extra = "liveextraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa="
    android = "androidkeyaaaaaaaaaaaaaaaaaaaaaaaaaaaa="
    pwd = {extra: "10.66.0.71"}
    allowed = {extra: "(none)", android: "10.66.0.71/32"}
    hs = {extra: 20.0, android: None}
    got = sr.extra_heal_assignments(pwd, allowed, hs)
    assert got == [(extra, "10.66.0.71")]


def test_heal_does_not_steal_from_other_live_peer():
    extra = "liveextraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa="
    other = "otherliveaaaaaaaaaaaaaaaaaaaaaaaaaaaaa="
    pwd = {extra: "10.66.0.71"}
    allowed = {extra: "(none)", other: "10.66.0.71/32"}
    hs = {extra: 20.0, other: 15.0}
    assert sr.extra_heal_assignments(pwd, allowed, hs) == []
    test_peer_host_allowed_always_slash32()
    test_gc_keeps_manifest_key_drops_never_and_stale()
    test_gc_throttles_within_window()
    test_failover_paths_allow_client_api_not_admin()
    test_queen_health_urls_prefer_direct_ip()
    test_one_health_fail_does_not_enter_standby()
    test_three_health_fails_enter_standby()
    test_health_ok_restores_queen_dnat()
    test_manifest_does_not_steal_ip_from_live_extra()
    test_manifest_may_take_ip_from_never_hs_holder()
    test_heal_restores_empty_live_extra_from_never_hs()
    test_heal_does_not_steal_from_other_live_peer()
    print("ok")
