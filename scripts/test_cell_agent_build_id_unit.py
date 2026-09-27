"""Улей и сота обязаны отдавать один и тот же agent_build_id."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.hive_provision_service import cell_agent_build_id  # noqa: E402


def test_same_id_on_hive_and_cell() -> None:
    cell_path = ROOT / "cell-agent" / "build_id.py"
    spec = importlib.util.spec_from_file_location("silent_cell_build_id_test", cell_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    hive_id = cell_agent_build_id()
    cell_id = mod.agent_build_id(cell_path.parent)
    assert hive_id == cell_id
    assert len(hive_id) == 16


if __name__ == "__main__":
    test_same_id_on_hive_and_cell()
    print("ok")
