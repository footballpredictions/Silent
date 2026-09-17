"""Исполнитель запасного порта: публикация в тему, 443/wdtt не трогаем."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai.hive_api_port_exec import (  # noqa: E402
    apply_close_stale_alt,
    apply_open_candidate,
    load_published_ports,
)
from ai.hive_api_port_policy import KEEP_FOREVER  # noqa: E402


def test_open_publishes_only_if_locally_listening():
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        runtime = Path(td) / "alt_ports"
        result = apply_open_candidate(2083, listening=False, runtime_path=runtime)
        assert result["ok"] is False
        assert result["executed"] is False
        assert load_published_ports(runtime) == ()

        result = apply_open_candidate(2083, listening=True, runtime_path=runtime)
        assert result["ok"] is True
        assert result["executed"] is True
        assert result["port"] == 2083
        assert load_published_ports(runtime) == (2083,)


def test_never_publish_or_close_keep_forever():
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        runtime = Path(td) / "alt_keep"
        runtime.write_text("2083\n", encoding="utf-8")
        for port in (443, 22, 80, 8000, 56000, 56001):
            opened = apply_open_candidate(port, listening=True, runtime_path=runtime)
            assert opened["ok"] is False, port
            closed = apply_close_stale_alt(port, runtime_path=runtime)
            assert closed["ok"] is False, port
            assert port in KEEP_FOREVER
        assert load_published_ports(runtime) == (2083,)


def test_close_only_removes_published_alt():
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        runtime = Path(td) / "alt_close"
        runtime.write_text("2083,2053\n", encoding="utf-8")
        result = apply_close_stale_alt(2083, runtime_path=runtime)
        assert result["ok"] is True
        assert load_published_ports(runtime) == (2053,)


if __name__ == "__main__":
    test_open_publishes_only_if_locally_listening()
    test_never_publish_or_close_keep_forever()
    test_close_only_removes_published_alt()
    print("ok (3 tests)")
