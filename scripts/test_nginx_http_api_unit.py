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
        if "132-243-234-162.nip.io" not in block:
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
    assert "return 301 https://132-243-234-162.nip.io" in block


if __name__ == "__main__":
    test_http_nip_io_proxies_api_instead_of_server_301()
    test_http_nip_io_still_redirects_browser_pages()
    print("ok")
