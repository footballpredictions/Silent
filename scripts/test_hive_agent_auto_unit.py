"""Unit: auto-upgrade must not SSH when /v1/status is unreachable."""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Не тянем SQLAlchemy/asyncpg — только чистая функция решения.
sys.modules.setdefault("app.database", SimpleNamespace(AsyncSessionLocal=None, Base=object))
fake_models = ModuleType("app.models")
fake_models.HiveCell = object  # type: ignore[attr-defined]
sys.modules.setdefault("app.models", fake_models)
sys.modules.setdefault(
    "app.services.hive_incidents",
    SimpleNamespace(push_incident=lambda **kwargs: False),
)
sys.modules.setdefault(
    "app.services.hive_provision_service",
    SimpleNamespace(cell_agent_build_id=lambda: "x", upgrade_cell_agent_via_ssh=lambda *a, **k: None),
)
sys.modules.setdefault(
    "app.services.hive_service",
    SimpleNamespace(fetch_worker_cell_load=None, resolve_ssh_password=None),
)

from app.services.hive_cell_agent_auto import should_attempt_agent_upgrade  # noqa: E402


def test_skip_when_unreachable():
    assert should_attempt_agent_upgrade(load=None, target_id="abc") is False


def test_skip_when_same_build():
    assert (
        should_attempt_agent_upgrade(
            load={"agent_build_id": "abc"},
            target_id="abc",
        )
        is False
    )


def test_upgrade_when_different_build():
    assert (
        should_attempt_agent_upgrade(
            load={"agent_build_id": "old"},
            target_id="new",
        )
        is True
    )


def test_upgrade_legacy_missing_build_id():
    assert should_attempt_agent_upgrade(load={}, target_id="new") is True
    assert should_attempt_agent_upgrade(load={"agent_build_id": ""}, target_id="new") is True


if __name__ == "__main__":
    test_skip_when_unreachable()
    test_skip_when_same_build()
    test_upgrade_when_different_build()
    test_upgrade_legacy_missing_build_id()
    print("ok")
