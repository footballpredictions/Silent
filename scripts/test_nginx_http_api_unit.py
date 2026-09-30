"""HTTP nip.io :80 must proxy /api/ — не 301. Иначе POST register → GET → 404."""
from __future__ import annotations

from pathlib import Path

NGINX = Path(__file__).resolve().parents[1] / "docker" / "nginx.conf"


def _server_blocks(conf: str) -> list[str]:
    blocks: list[str] = []
    idx = 0
    while True:
        start = conf.find("server {", idx)
        if start < 0:
            break
        depth = 0
        end = None
        for j, ch in enumerate(conf[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        if end is None:
            break
        blocks.append(conf[start:end])
        idx = end
    return blocks


def _http_nip_io_block(conf: str) -> str:
    found = []
    for block in _server_blocks(conf):
        if "89-125-188-100.nip.io" not in block:
            continue
        if "listen 443" in block:
            continue
        if "listen 80 default_server" in block:
            continue
        if "listen 80;" in block:
            found.append(block)
    assert found, "нет server listen 80 для nip.io"
    assert len(found) == 1, found
    return found[0]


def test_http_nip_io_proxies_api_instead_of_server_301():
    """Сота DNAT 10.66.66.1:8000 → Улей:80. Клиент шлёт Host nip.io.
    Server-level 301 превращает POST /api/auth/register в GET → API endpoint not found.
    """
    conf = NGINX.read_text(encoding="utf-8")
    block = _http_nip_io_block(conf)
    assert "location /api/" in block
    assert "proxy_pass http://api" in block
    head = block.split("location /api/", 1)[0]
    assert "return 301" not in head, "301 на весь :80 ломает POST через туннель соты"


def test_http_nip_io_still_redirects_browser_pages():
    block = _http_nip_io_block(NGINX.read_text(encoding="utf-8"))
    assert "location / {" in block or "location /{" in block
    assert "return 301 https://89-125-188-100.nip.io" in block


def _default_http80_block(conf: str) -> str:
    found = []
    for block in _server_blocks(conf):
        if "listen 80 default_server" in block:
            found.append(block)
    assert found, "нет listen 80 default_server"
    assert len(found) == 1, found
    return found[0]


def test_default_http80_proxies_admin_spa_not_444():
    """Сота DNAT → Улей:80, Host 10.66.66.1. return 444 на / ломает ПК-админку."""
    block = _default_http80_block(NGINX.read_text(encoding="utf-8"))
    loc = block.split("location / {", 1)[-1] if "location / {" in block else ""
    assert loc, "нет location /"
    assert "proxy_pass http://api" in loc
    assert "return 444" not in loc
    assert "allow 87.58.213.193" in block
    assert "deny all" in block


def test_default_https_exposes_only_health_to_ip_control():
    """Check-host HTTPS-by-IP must reach health; raw-IP admin and API stay closed."""
    conf = NGINX.read_text(encoding="utf-8")
    blocks = [b for b in _server_blocks(conf) if "listen 443 ssl http2 default_server" in b]
    assert len(blocks) == 1
    block = blocks[0]
    before_health, health_and_fallback = block.split("location = /api/health {", 1)
    health, fallback = health_and_fallback.split("location / {", 1)
    assert "return 444" not in before_health, "server-level 444 bypasses exact health location"
    assert "proxy_pass http://api;" in health
    assert "return 444;" in fallback
    assert "location /api/" not in block, "do not expose the rest of API by raw IP"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
    print(f"ok ({len(tests)} tests)")
