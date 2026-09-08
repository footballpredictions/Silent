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
    cell_slot_title,
    cell_visible_to_client,
    client_meets_ai_exit_min,
)


def _accepts_spill(cell, olcrtc_ips: set[str]) -> bool:
    """Зеркало cell_accepts_wdtt_spill без импорта hive_service (jose)."""
    if cell.is_queen:
        return True
    if getattr(cell, "admin_only", False):
        return False
    if getattr(cell, "ai_exit", False):
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


def test_ai_exit_slot_title():
    """Подпись слота приходит с сервера — клиенты её не выдумывают."""
    queen = SimpleNamespace(is_queen=True, ai_exit=False)
    plain = SimpleNamespace(is_queen=False, ai_exit=False)
    ai = SimpleNamespace(is_queen=False, ai_exit=True)

    assert cell_slot_title(queen, "server1") == "Сервер 1"
    assert cell_slot_title(plain, "server3") == "Сервер 3"
    assert cell_slot_title(ai, "server4") == "Сервер 4 для ИИ"


def test_ai_exit_hidden_before_1_0_165():
    """Сервер 4 (ai_exit) не в списке у 1.0.164 и без версии — даже после снятия admin_only."""
    ai = SimpleNamespace(is_queen=False, admin_only=False, ai_exit=True)
    plain = SimpleNamespace(is_queen=False, admin_only=False, ai_exit=False)

    assert not client_meets_ai_exit_min("")
    assert not client_meets_ai_exit_min("1.0.164")
    assert not client_meets_ai_exit_min("1.0.164-debug")
    assert client_meets_ai_exit_min("1.0.165")
    assert client_meets_ai_exit_min("1.0.166")
    assert client_meets_ai_exit_min("1.1.0")

    assert not cell_visible_to_client(ai, is_admin=False, app_version="")
    assert not cell_visible_to_client(ai, is_admin=True, app_version="1.0.164")
    assert cell_visible_to_client(ai, is_admin=False, app_version="1.0.165")
    assert cell_visible_to_client(plain, is_admin=False, app_version="1.0.160")


def test_ai_exit_not_in_wdtt_spill():
    """Открытый ИИ-слот не забирает автобаланс WDTT — только ручной выбор в 1.0.165+."""
    ai = SimpleNamespace(is_queen=False, admin_only=False, accepts_wdtt=True, public_ip="9.9.9.9", ai_exit=True)
    assert not _accepts_spill(ai, set())


if __name__ == "__main__":
    test_admin_only_visibility()
    test_ai_exit_slot_title()
    test_ai_exit_hidden_before_1_0_165()
    test_ai_exit_not_in_wdtt_spill()
    print("ok")
