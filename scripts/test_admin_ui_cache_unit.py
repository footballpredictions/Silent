"""Exercise the actual SPA routes: reopening must request the current entry point."""
from __future__ import annotations

import ast
import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fixture_app(dist: Path) -> FastAPI:
    """Load the real route declarations without DB/startup/background VPN tasks."""
    tree = ast.parse((ROOT / 'app/main.py').read_text(encoding='utf-8'))
    block = next(node for node in tree.body if isinstance(node, ast.If) and
                 any(isinstance(child, ast.AsyncFunctionDef) and child.name == 'serve_admin_root'
                     for child in ast.walk(node)))
    app = FastAPI()
    namespace = dict(app=app, admin_ui_dist=str(dist), admin_ui_index=str(dist/'index.html'),
                     os=os, FileResponse=FileResponse, StaticFiles=StaticFiles,
                     HTTPException=HTTPException, logger=logging.getLogger(__name__))
    exec(compile(ast.Module(body=[block], type_ignores=[]), 'app/main.py', 'exec'), namespace)
    return app


async def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory() as temporary:
        dist = Path(temporary)
        (dist/'assets').mkdir()
        (dist/'index.html').write_text('<html>old-build<script type="module" src="/assets/app-OLD.js"></script></html>', encoding='utf-8')
        (dist/'assets/app-OLD.js').write_text('old-bundle', encoding='utf-8')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fixture_app(dist)),
                                     base_url='http://admin.test') as client:
            for path in ('/', '/hive', '/dashboard', '/index.html'):
                response = await client.get(path)
                if response.status_code != 200 or 'no-store' not in response.headers.get('cache-control', ''):
                    failures += 1
                    print('FAIL entry can reuse stale browser cache', path, dict(response.headers))
            version = await client.get('/admin-ui-version.json')
            if version.headers.get('content-type', '').startswith('application/json'):
                old_version = version.json()['version']
                assert version.json()['assets'] == ['/assets/app-OLD.js']
                assert 'no-store' in version.headers.get('cache-control', '')
            else:
                old_version = None
                failures += 1
                print('FAIL version probe returns stale SPA HTML instead of current version')
            (dist/'index.html').write_text('<html>new-build<script type="module" src="/assets/app-NEW.js"></script></html>', encoding='utf-8')
            response = await client.get('/hive')
            assert 'new-build' in response.text
            assert (await client.get('/api/missing')).status_code == 404
            assert (await client.get('/assets/app-OLD.js')).text == 'old-bundle'
            if old_version:
                version = await client.get('/admin-ui-version.json')
                assert version.json()['version'] != old_version
                assert version.json()['assets'] == ['/assets/app-NEW.js']
    if not failures:
        print('PASS entry/root/deep links/index alias use no-store; new deploy and old assets coexist')
    return failures


if __name__ == '__main__':
    raise SystemExit(bool(asyncio.run(main())))
