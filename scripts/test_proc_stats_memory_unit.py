"""Unit: host meminfo → dashboard GB fields (GiB, not decimal 1e9)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import proc_stats as ps  # noqa: E402


def test_meminfo_16gib_not_10() -> None:
    """Balloon-deflated host: MemTotal ~16GiB must not look like ~10."""
    meminfo = (
        "MemTotal:       16400724 kB\n"
        "MemFree:         7021234 kB\n"
        "MemAvailable:   12800000 kB\n"
    )
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "meminfo").write_text(meminfo, encoding="utf-8")
        (root / "stat").write_text("cpu  0 0 0 0 0 0 0 0 0 0\n", encoding="utf-8")
        (root / "cpuinfo").write_text("processor\t: 0\nprocessor\t: 1\n", encoding="utf-8")
        old = ps._host_proc_root
        ps._host_proc_root = lambda: str(root)  # type: ignore[assignment]
        try:
            total = ps._read_memory_total_gb()
            meta = ps._host_hardware_meta()
        finally:
            ps._host_proc_root = old  # type: ignore[assignment]

    assert total == 15.6, total
    assert meta["memory_total_gb"] == 15.6, meta
    # used = total - available ≈ 3.4 GiB
    assert meta["memory_used_gb"] == 3.4, meta
    assert meta["cpu_cores"] == 2


def test_meminfo_ballooned_10gib_detected() -> None:
    meminfo = "MemTotal:       10109268 kB\nMemAvailable:    7098700 kB\n"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "meminfo").write_text(meminfo, encoding="utf-8")
        (root / "cpuinfo").write_text("processor\t: 0\n", encoding="utf-8")
        old = ps._host_proc_root
        ps._host_proc_root = lambda: str(root)  # type: ignore[assignment]
        try:
            total = ps._read_memory_total_gb()
        finally:
            ps._host_proc_root = old  # type: ignore[assignment]
    assert total == 9.6, total
    assert total < 14.0  # watch script threshold


if __name__ == "__main__":
    test_meminfo_16gib_not_10()
    test_meminfo_ballooned_10gib_detected()
    print("OK")
