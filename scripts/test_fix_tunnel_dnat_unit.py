"""CELL_API на Улье должен пускать :8000 со всех рабочих сот, включая ИИ-выход."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fix_tunnel_dnat import CELL_API_SOURCE_IPS, FIX_SH  # noqa: E402


def test_cell3_ai_exit_can_reach_hive_8000():
    assert "192.177.26.38" in CELL_API_SOURCE_IPS
    for ip in CELL_API_SOURCE_IPS:
        assert ip in FIX_SH


def test_cell_api_redirects_to_nginx_80():
    # docker-proxy 127.0.0.1:8000; REDIRECT на eth0:8000 = Connection refused.
    assert "--to-ports 80 2>/dev/null" in FIX_SH
    assert "--to-ports 8000" not in FIX_SH


if __name__ == "__main__":
    test_cell3_ai_exit_can_reach_hive_8000()
    test_cell_api_redirects_to_nginx_80()
    print("ok")
