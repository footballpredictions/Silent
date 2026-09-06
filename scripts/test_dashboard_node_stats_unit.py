"""Unit: dashboard node system mapping + CPU% is all-cores (0–100)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.dashboard_node_stats import (  # noqa: E402
    QUEEN_NODE_ID,
    _system_from_cell_load,
)


def test_cell_load_maps_memory_used() -> None:
    sysm = _system_from_cell_load(
        "cell-1",
        {
            "cpu_percent": 42.5,
            "memory_percent": 50.0,
            "memory_total_gb": 8.0,
            "cpu_cores": 4,
            "cpu_model": "Intel(R) Xeon(R) Gold 6140 CPU @ 2.30GHz",
            "cpu_freq_base_mhz": 2300.0,
            "network_mbps_rx": 1.2,
            "network_mbps_tx": 0.5,
            "network_util_percent": 10.0,
            "network_link_capacity_mbps": 1000,
            "network_interface": "eth0",
        },
    )
    assert sysm["node_id"] == "cell-1"
    assert sysm["cpu_percent"] == 42.5
    assert sysm["cpu_cores"] == 4
    assert sysm["cpu_model"] and "Xeon" in sysm["cpu_model"]
    assert sysm["cpu_freq_base_mhz"] == 2300.0
    assert sysm["cpu_freq_current_mhz"] is None
    assert sysm["memory_used_gb"] == 4.0
    assert sysm["disk_percent"] is None
    assert sysm["reachable"] is True
    assert sysm["cpu_percent_scope"] == "all_cores"
    assert QUEEN_NODE_ID == "queen"


def test_cpu_percent_not_scaled_by_core_count() -> None:
    """6 ядер: 100% = все ядра загружены; не делим и не умножаем на число ядер."""
    a = _system_from_cell_load("a", {"cpu_percent": 50.0, "memory_percent": 0, "memory_total_gb": 0, "cpu_cores": 4})
    b = _system_from_cell_load("b", {"cpu_percent": 50.0, "memory_percent": 0, "memory_total_gb": 0, "cpu_cores": 6})
    assert a["cpu_percent"] == b["cpu_percent"] == 50.0
    assert a["cpu_cores"] == 4 and b["cpu_cores"] == 6


if __name__ == "__main__":
    test_cell_load_maps_memory_used()
    test_cpu_percent_not_scaled_by_core_count()
    print("OK")
