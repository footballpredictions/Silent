"""Unit: admin_only cells hidden from non-admin clients / WDTT spill."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("app.database", SimpleNamespace(AsyncSessionLocal=None))

from app.services.hive_slots import (  # noqa: E402
    cell_is_admin_only,
    cell_selectable_by_user,
)


def _accepts_spill(cell, olcrtc_ips: set[str]) -> bool:
    """Зеркало cell_accepts_wdtt_spill без импорта hive_service (jose)."""
    if cell.is_queen:
        return True
    if getattr(cell, "admin_only", False):
        return False
    if getattr(cell, "accepts_wdtt", True) is False:
        return False
    ip = (cell.public_ip or "").strip()
    return ip not in olcrtc_ips


def test_admin_only_visibility():
    queen = SimpleNamespace(is_queen=True, admin_only=False, accepts_wdtt=True, public_ip="1.1.1.1")
    sota3 = SimpleNamespace(is_queen=False, admin_only=True, accepts_wdtt=True, public_ip="9.9.9.9")
    sota4 = SimpleNamespace(is_queen=False, admin_only=False, accepts_wdtt=True, public_ip="8.8.8.8")

    assert not cell_is_admin_only(queen)
    assert cell_is_admin_only(sota3)
    assert not cell_is_admin_only(sota4)

    assert cell_selectable_by_user(sota3, is_admin=True)
    assert not cell_selectable_by_user(sota3, is_admin=False)
    assert cell_selectable_by_user(sota4, is_admin=False)

    assert _accepts_spill(queen, set())
    assert not _accepts_spill(sota3, set())
    assert _accepts_spill(sota4, set())


if __name__ == "__main__":
    test_admin_only_visibility()
    print("ok")
