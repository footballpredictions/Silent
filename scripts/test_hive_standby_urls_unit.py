"""Unit tests: standby URL — живые соты раньше мёртвых портов Улья."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.standby_urls import compose_standby_api_urls

CELLS = ["http://87.58.213.193:9100", "http://78.17.74.27:9100"]
ALTS = [
    "https://132-243-234-162.nip.io:2083",
    "https://132.243.234.162:2083",
]


def test_cells_come_before_unpublished_alt_ports():
    """Регресс 2026-09-16: alt-порты первыми съедали фолбэк и письма."""
    urls = compose_standby_api_urls(CELLS, ALTS)
    assert urls[:2] == CELLS
    assert urls[2:] == ALTS


def test_empty_alt_is_just_cells():
    assert compose_standby_api_urls(CELLS, []) == CELLS


def test_dedupes_and_skips_blank():
    urls = compose_standby_api_urls(
        [CELLS[0], "", CELLS[0], CELLS[1]],
        [ALTS[0], ALTS[0]],
    )
    assert urls == [CELLS[0], CELLS[1], ALTS[0]]


def test_runtime_file_ports_go_after_cells():
    """Исполнитель пишет порт в файл — в теме он после живых сот."""
    import tempfile

    from ai.hive_api_port_exec import load_published_ports
    from ai.hive_api_port_policy import alt_https_urls

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "alt"
        p.write_text("2083\n", encoding="utf-8")
        ports = load_published_ports(p)
    urls = alt_https_urls("132-243-234-162.nip.io", "132.243.234.162", ports)
    assert urls == ALTS
    cells_then_alt = compose_standby_api_urls(CELLS, urls)
    assert cells_then_alt[:2] == CELLS
    assert cells_then_alt[2:] == ALTS


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"ok ({len(tests)} tests)")
