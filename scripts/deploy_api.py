"""DEPRECATED: всегда полный деплой.

Раньше копировал урезанный FILES — файл не в списке оставался старым в контейнере
(вход 500, 2026-08-16: не попал app/models/device.py).

Канон: python scripts/deploy_stable.py
Этот файл оставлен как алиас, чтобы старая команда не пропускала код.
"""
from __future__ import annotations

from pathlib import Path
import runpy

print("deploy_api.py → deploy_stable.py (полный app/**/*.py + ai/**/*.py)")
runpy.run_path(str(Path(__file__).resolve().parent / "deploy_stable.py"), run_name="__main__")
