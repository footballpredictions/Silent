"""Unit: сота принимает новый IP Улья без рестарта wdtt."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cell-agent"))

from queen_apply import (  # noqa: E402
    agent_dropin_text,
    current_queen_ip,
    parse_queen_hint,
    queen_state_dict,
    read_queen_ip_from_state,
    rewrite_socat_unit,
    should_apply_queen_ip,
    sibling_queen_hint_urls,
)


def test_rejects_junk_and_same_ip():
    assert should_apply_queen_ip(current="89.125.188.100", incoming="1.2.3.4") is True
    assert should_apply_queen_ip(current="89.125.188.100", incoming="89.125.188.100") is False
    assert should_apply_queen_ip(current="89.125.188.100", incoming="not-an-ip") is False
    assert should_apply_queen_ip(current="", incoming="1.2.3.4") is True


def test_state_roundtrip_and_live_file(tmp_path: Path | None = None):
    from pathlib import Path as P

    state = queen_state_dict(
        queen_ip="1.2.3.4",
        previous_ip="89.125.188.100",
        sibling_api_urls=["http://87.58.213.193:9100"],
    )
    raw = __import__("json").dumps(state)
    assert read_queen_ip_from_state(raw) == "1.2.3.4"
    path = (tmp_path or P(".")) / "hive_queen.json" if tmp_path else None
    if path is None:
        import tempfile

        path = P(tempfile.gettempdir()) / "silent_hive_queen_test.json"
    path.write_text(raw, encoding="utf-8")
    assert current_queen_ip("9.9.9.9", state_path=path) == "1.2.3.4"
    path.unlink(missing_ok=True)
    assert current_queen_ip("9.9.9.9", state_path=path) == "9.9.9.9"


def test_socat_and_dropin_point_to_new_ip():
    unit = "[Service]\nExecStart=/usr/bin/socat TCP-LISTEN:8000 TCP:89.125.188.100:80\n"
    assert "TCP:1.2.3.4:80" in rewrite_socat_unit(unit, "1.2.3.4")
    dropin = agent_dropin_text("1.2.3.4")
    assert "HIVE_QUEEN_IP=1.2.3.4" in dropin
    assert "1-2-3-4.nip.io" in dropin
    assert "wdtt" not in dropin.lower()


def test_sibling_hint():
    urls = sibling_queen_hint_urls(["http://87.58.213.193:9100/", ""])
    assert urls == ["http://87.58.213.193:9100/health"]
    assert parse_queen_hint({"queen_ip": "1.2.3.4"}) == "1.2.3.4"
    assert parse_queen_hint({"queen_ip": "nope"}) == ""


if __name__ == "__main__":
    test_rejects_junk_and_same_ip()
    test_state_roundtrip_and_live_file()
    test_socat_and_dropin_point_to_new_ip()
    test_sibling_hint()
    print("ok")
