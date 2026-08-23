"""После compose up/recreate — тот же полный деплой, что deploy_stable.py.

Раньше restore копировал только app/+ai/ через docker cp и на хосте звал
python3 scripts/fix_tunnel_dnat.py (нет _deploy_common → DNAT мог не починиться).
Теперь дыры нет: volume app/ai + канон deploy_stable.
"""
from __future__ import annotations

from pathlib import Path
import runpy

print("restore_api_container.py → deploy_stable.py (полный деплой, volume app/ai)")
runpy.run_path(str(Path(__file__).resolve().parent / "deploy_stable.py"), run_name="__main__")
