"""Два одновременных /v1/status не должны удваивать сбор и вылезать за короткий таймаут."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cell-agent"))

from status_cache import StatusCache  # noqa: E402


def test_overlapping_polls_collect_once_and_fit_short_timeout():
    calls = 0

    def collect():
        nonlocal calls
        calls += 1
        time.sleep(0.3)
        return {"cpu": 10}

    async def run():
        cache = StatusCache(ttl=2.0)
        started = time.monotonic()
        a, b = await asyncio.gather(cache.get(collect), cache.get(collect))
        return a, b, time.monotonic() - started

    a, b, elapsed = asyncio.run(run())
    assert a == b == {"cpu": 10}
    assert calls == 1
    assert elapsed < 0.5


def test_status_collect_does_not_wait_on_ipify_or_olcrtc():
    text = (ROOT / "cell-agent" / "main.py").read_text(encoding="utf-8")
    body = text.split("def _collect_status", 1)[1].split("\n_STATUS_CACHE", 1)[0]
    assert "ipify" not in body
    assert "olcrtc@" not in body
    assert "CELL_PUBLIC_IP" in body


if __name__ == "__main__":
    test_overlapping_polls_collect_once_and_fit_short_timeout()
    test_status_collect_does_not_wait_on_ipify_or_olcrtc()
    print("ok")
