"""Лимит карточки: живой WG, а не одна строка is_connected в истории."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("app.database", SimpleNamespace(AsyncSessionLocal=None, Base=object))
sys.modules.setdefault("app.services.hive_incidents", SimpleNamespace(push_incident=lambda **k: None))
sys.modules.setdefault("app.models", SimpleNamespace(HiveCell=object, HiveLoadSample=object))
sys.modules.setdefault(
    "app.services.hive_load",
    SimpleNamespace(queen_accepting_new_vpn=lambda: (True, {})),
)

from app.services.hive_capacity import (  # noqa: E402
    NodeHardware,
    _blend_live_capacity,
    compute_max_online_from_samples,
)
from app.services.hive_slots import online_count_for_capacity  # noqa: E402


def _sample(**kw):
    base = dict(
        online_count=1,
        cpu_percent=55.0,
        memory_percent=42.0,
        network_mbps=40.0,
        link_capacity_mbps=1000.0,
        cpu_cores=4,
        memory_total_gb=8.0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _history_of_one_db_user():
    hw = NodeHardware(cpu_cores=4, memory_total_gb=8, link_capacity_mbps=1000)
    samples = [_sample(online_count=0, cpu_percent=8, memory_percent=20, network_mbps=1)] * 4
    samples += [_sample()] * 8
    return hw, samples, compute_max_online_from_samples(samples, hardware=hw)


def test_db_only_history_caps_near_fifteen():
    """Как на карточке до починки: 1 человек в БД, CPU всей ноды → потолок ~15."""
    _hw, _samples, profile = _history_of_one_db_user()
    assert profile.mode == "adaptive"
    assert profile.max_online < 43
    assert 10 <= profile.max_online <= 20


def test_wire_online_lifts_limit_above_people_already_there():
    hw, samples, profile = _history_of_one_db_user()
    load = {
        "cpu_percent": 55,
        "memory_percent": 42,
        "network_mbps_rx": 40,
        "network_mbps_tx": 10,
        "network_util_percent": 4,
        "cpu_cores": 4,
        "memory_total_gb": 8,
        "wg_peers_live_3m": 43,
    }
    assert online_count_for_capacity(1, load) == 43
    stale = _blend_live_capacity(
        profile, online_count=1, load=load, hardware=hw, samples=samples
    )
    assert stale.mode == "adaptive"
    assert stale.max_online < 43
    fixed = _blend_live_capacity(
        profile,
        online_count=online_count_for_capacity(1, load),
        load=load,
        hardware=hw,
        samples=samples,
    )
    assert fixed.max_online >= 43
    assert fixed.mode == "adaptive+live"


if __name__ == "__main__":
    test_db_only_history_caps_near_fifteen()
    test_wire_online_lifts_limit_above_people_already_there()
    print("ok")
