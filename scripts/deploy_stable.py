"""Полный деплой backend: app/ + ai/ + admin-ui/dist → хост VPS + restart api/nginx.

Живой Python — volume `./app` и `./ai` (как admin-ui). Recreate контейнера не откатывает код.
Не трогает wdtt.service.
"""
from __future__ import annotations

import io
import argparse
import os
import subprocess
import sys
import time
import shlex
from pathlib import Path, PurePosixPath

from _deploy_common import BACKEND_ROOT, CONTAINER, REMOTE, connect, run
from fix_tunnel_dnat import FIX_SH

PREFLIGHT_TESTS = (
    "scripts/test_nginx_http_api_unit.py",
    "scripts/test_cell_http_guard_unit.py",
    "scripts/test_admin_ui_cache_unit.py",
    "scripts/test_hive_capacity_regression_unit.py",
    "scripts/test_dashboard_online_consistency_unit.py",
    "scripts/test_admin_page_loading_unit.py",
    "scripts/test_deploy_stable_selection_unit.py",
    "scripts/test_vpn_kick_unit.py",
    "scripts/test_vpn_kick_storm_unit.py",
    "scripts/test_deleted_user_vpn_unit.py",
    "scripts/test_cell_agent_build_id_unit.py",
    "scripts/test_availability_refresh_unit.py",
    "scripts/test_availability_polling_unit.py",
)


def _preflight() -> None:
    """Fail closed: do not upload if dataplane invariants are broken."""
    for rel in PREFLIGHT_TESTS:
        path = BACKEND_ROOT / rel.replace("/", os.sep)
        if not path.is_file():
            raise SystemExit(f"preflight missing {rel}")
        print(f"preflight {rel}")
        r = subprocess.run([sys.executable, str(path)], cwd=str(BACKEND_ROOT))
        if r.returncode != 0:
            raise SystemExit(f"preflight failed: {rel} — deploy aborted")

SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".pytest_cache"}


def _upload_py_tree(sftp, client, sub: str) -> int:
    base = BACKEND_ROOT / sub
    n = 0
    for root, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            if not name.endswith(".py"):
                continue
            lp = Path(root) / name
            rel = lp.relative_to(BACKEND_ROOT).as_posix()
            rp = f"{REMOTE}/{rel}"
            client.exec_command(f"mkdir -p {os.path.dirname(rp)}")
            sftp.put(str(lp), rp)
            n += 1
    print(f"upload {sub}/: {n} py")
    return n


def _selected_python_paths(paths: list[str]) -> list[str]:
    result = []
    for rel in paths:
        path = PurePosixPath(rel)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] not in ("app", "ai") or path.suffix != ".py":
            raise ValueError(f"Not an app/ai Python file: {rel}")
        local = (BACKEND_ROOT / path).resolve()
        if not local.is_relative_to(BACKEND_ROOT.resolve()) or not local.is_file():
            raise ValueError(f"Missing or outside backend: {rel}")
        compile(local.read_text(encoding="utf-8-sig"), str(local), "exec")
        normalized = path.as_posix()
        if normalized not in result:
            result.append(normalized)
    return result


def _upload_admin_ui(sftp, client, dist: Path) -> None:
    """Publish entry point last; retain assets used by already-open admin tabs."""
    stamp = str(time.time_ns())
    files = sorted((p for p in dist.rglob('*') if p.is_file()), key=lambda p: (p.name == 'index.html', p.as_posix()))
    for local in files:
        rel = local.relative_to(dist).as_posix()
        remote = f"{REMOTE}/admin-ui/dist/{rel}"
        run(client, f"mkdir -p {shlex.quote(os.path.dirname(remote))}")
        temporary = f"{remote}.deploy-{stamp}"
        sftp.put(str(local), temporary)
        sftp.chmod(temporary, 0o644)
        sftp.posix_rename(temporary, remote)
        print("ui", rel)


def _upload_cell_agent_source(sftp, client) -> None:
    import runpy
    names = runpy.run_path(str(BACKEND_ROOT / 'cell-agent/build_id.py'))['SHIPPED']
    paths = [BACKEND_ROOT / 'cell-agent' / name for name in names]
    for path in paths:
        compile(path.read_text(encoding='utf-8'), str(path), 'exec')
    stamp = str(time.time_ns())
    for path in paths:
        remote = f'{REMOTE}/cell-agent/{path.name}'
        temporary = f'{remote}.deploy-{stamp}'
        sftp.put(str(path), temporary)
        sftp.chmod(temporary, 0o644)
        sftp.posix_rename(temporary, remote)
        print('cell-agent source', path.name)


def _deploy_selected_python(paths: list[str], *, admin_ui: Path | None = None, cell_agent_source: bool = False, nginx_config: bool = False) -> None:
    paths = _selected_python_paths(paths)
    if not paths:
        raise SystemExit("No Python files selected")
    _preflight()
    client = connect()
    try:
        with client.open_sftp() as sftp:
            stamp = str(time.time_ns())
            for rel in paths:
                remote = f"{REMOTE}/{rel}"
                existing = sftp.stat(remote)
                # Preserve the exact previous bytes before replacing an existing live file.
                with sftp.file(remote, "rb") as source, sftp.file(f"{remote}.before-{stamp}", "wb") as backup:
                    backup.write(source.read())
                temporary = f"{remote}.deploy-{stamp}"
                sftp.put(str(BACKEND_ROOT / rel), temporary)
                sftp.chmod(temporary, existing.st_mode & 0o777)
                sftp.posix_rename(temporary, remote)
                print("selected Python", rel)
            if admin_ui is not None:
                _upload_admin_ui(sftp, client, admin_ui)
            if cell_agent_source:
                _upload_cell_agent_source(sftp, client)
            if nginx_config:
                remote = f'{REMOTE}/docker/nginx.conf'
                with sftp.file(remote, 'rb') as source, sftp.file(f'{remote}.before-{stamp}', 'wb') as backup:
                    backup.write(source.read())
                sftp.put(str(BACKEND_ROOT / 'docker/nginx.conf'), remote)
                print('selected nginx config')
        _restart_and_verify(client, expected_admin_index=admin_ui / 'index.html' if admin_ui else None)
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-only", nargs="+", metavar="PATH", help="Only existing app/ai Python files; keep UI/compose/cell-agent unchanged")
    parser.add_argument("--with-admin-ui", action="store_true", help="Also publish the built admin UI with --python-only")
    parser.add_argument("--with-cell-agent-source", action="store_true", help="Publish the SHIPPED agent source bundle with --python-only")
    parser.add_argument("--with-nginx", action="store_true", help="Publish docker/nginx.conf with --python-only")
    args = parser.parse_args()
    dist = BACKEND_ROOT / "admin-ui" / "dist"
    if (not args.python_only or args.with_admin_ui) and not (dist / 'index.html').is_file():
        raise SystemExit("Сначала: cd admin-ui && npm run build")
    if args.python_only:
        _deploy_selected_python(args.python_only, admin_ui=dist if args.with_admin_ui else None, cell_agent_source=args.with_cell_agent_source, nginx_config=args.with_nginx)
        return
    if args.with_admin_ui:
        parser.error("--with-admin-ui requires --python-only")
    if args.with_cell_agent_source:
        parser.error("--with-cell-agent-source requires --python-only")
    if args.with_nginx:
        parser.error("--with-nginx requires --python-only")
    _preflight()

    client = connect()
    sftp = client.open_sftp()

    _upload_py_tree(sftp, client, "app")
    _upload_py_tree(sftp, client, "ai")

    _upload_admin_ui(sftp, client, dist)

    client.exec_command(f"mkdir -p {REMOTE}/cell-agent")
    _upload_cell_agent_source(sftp, client)

    client.exec_command(f"mkdir -p {REMOTE}/scripts")
    for name in ("fix_tunnel_dnat.py", "_deploy_common.py"):
        lp = BACKEND_ROOT / "scripts" / name
        if lp.is_file():
            sftp.put(str(lp), f"{REMOTE}/scripts/{name}")
            print(f"upload scripts/{name}")
    sftp.putfo(io.BytesIO(FIX_SH.encode()), "/tmp/fix_tunnel_dnat.sh")
    print("upload /tmp/fix_tunnel_dnat.sh")

    compose_local = BACKEND_ROOT / "docker-compose.yml"
    sftp.put(str(compose_local), f"{REMOTE}/docker-compose.yml")
    print("upload docker-compose.yml")

    static_dir = BACKEND_ROOT / "static"
    client.exec_command(f"mkdir -p {REMOTE}/static/theme")
    for name in ("logo.png", "logo-32.png", "vk-agent-oauth.html"):
        lp = static_dir / name
        if lp.is_file():
            sftp.put(str(lp), f"{REMOTE}/static/{name}")
            print(f"static/{name}")

    client.exec_command(f"mkdir -p {REMOTE}/docker")
    nginx_conf = BACKEND_ROOT / "docker" / "nginx.conf"
    if nginx_conf.is_file():
        sftp.put(str(nginx_conf), f"{REMOTE}/docker/nginx.conf")
        print("upload docker/nginx.conf")

    sftp.close()
    _restart_and_verify(client, expected_admin_index=dist / 'index.html')


def _verify_admin_ui(client, expected_index: Path | None = None) -> None:
    """Check the served SPA, not just uploaded files: stale HTML must fail publication."""
    import hashlib
    import json

    expected_sha = hashlib.sha256(expected_index.read_bytes()).hexdigest() if expected_index else None
    program = f'''
import hashlib,json,urllib.request
from app.config import settings
expected_sha={expected_sha!r}
sha=None
def fetch(path, method='GET'):
    request=urllib.request.Request('http://127.0.0.1:8000'+path,method=method,headers={{'Host':settings.ADMIN_PUBLIC_HOST}})
    with urllib.request.urlopen(request,timeout=10) as response:
        assert response.status==200, (path,response.status)
        return response.headers,response.read()
for path in ('/','/hive','/dashboard','/index.html'):
    headers,body=fetch(path)
    assert 'no-store' in headers.get('Cache-Control',''), ('cached admin entry',path)
    current=hashlib.sha256(body).hexdigest()
    assert sha is None or current==sha, ('different admin entries',path)
    assert expected_sha is None or current==expected_sha, ('served admin build differs from uploaded build',path)
    sha=current
headers,body=fetch('/admin-ui-version.json')
assert 'no-store' in headers.get('Cache-Control',''), 'cached admin version'
manifest=json.loads(body)
assert manifest.get('version') and manifest.get('assets'), 'missing admin version/assets'
for asset in manifest['assets']:
    assert asset.startswith('/assets/'), 'invalid admin asset'
    fetch(asset,'HEAD')
print(json.dumps({{'public_host':settings.ADMIN_PUBLIC_HOST,'entry_sha':sha}}))
'''
    stdin, stdout, stderr = client.exec_command(f'docker exec -i {shlex.quote(CONTAINER)} python -', timeout=90)
    stdin.write(program)
    stdin.flush()
    stdin.channel.shutdown_write()
    output = stdout.read().decode(errors='replace')
    status = stdout.channel.recv_exit_status()
    if status:
        raise SystemExit('Admin UI postflight failed: ' + stderr.read().decode(errors='replace')[-1500:])
    probe = json.loads(output)
    host = probe['public_host']
    for port in (443, 2083):
        command = shlex.join(['curl', '-skS', '--connect-timeout', '3', '--max-time', '12',
                              '--resolve', f'{host}:{port}:127.0.0.1', '-D', '-',
                              f'https://{host}:{port}/hive'])
        _, stdout, stderr = client.exec_command(command, timeout=20)
        raw = stdout.read()
        status = stdout.channel.recv_exit_status()
        if status or b'\r\n\r\n' not in raw:
            raise SystemExit(f'Admin UI HTTPS postflight failed on port {port}')
        headers, body = raw.split(b'\r\n\r\n', 1)
        lines = headers.decode().splitlines()
        if len(lines[0].split()) < 2 or lines[0].split()[1] != '200':
            raise SystemExit(f'Admin UI HTTPS status failed on port {port}')
        values = {key.lower(): value.strip() for key, value in
                  (line.split(':', 1) for line in lines[1:] if ':' in line)}
        if 'no-store' not in values.get('cache-control', '') or hashlib.sha256(body).hexdigest() != probe['entry_sha']:
            raise SystemExit(f'Admin UI HTTPS serves cached or different entry on port {port}')
    print('PASS admin publication: no-store entry/version, identical routes, expected build, assets and HTTPS 443/2083')


def _verify_registered_cell_allowlist(client) -> None:
    import ipaddress
    import json
    import re

    program = '''import asyncio,json
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import HiveCell
async def main():
    async with AsyncSessionLocal() as db:
        rows=(await db.execute(select(HiveCell.public_ip).where(HiveCell.is_queen==False,HiveCell.status.in_(('active','draining'))))).scalars().all()
        print(json.dumps(list(rows)))
asyncio.run(main())
'''
    stdin, stdout, stderr = client.exec_command(f'docker exec -i {shlex.quote(CONTAINER)} python -', timeout=30)
    stdin.write(program)
    stdin.flush()
    stdin.channel.shutdown_write()
    ips = json.loads(stdout.read())
    if stdout.channel.recv_exit_status():
        raise SystemExit('Could not verify registered cell allowlist')
    nginx = CONTAINER.replace('-api-', '-nginx-')
    _, stdout, stderr = client.exec_command(f'docker exec {shlex.quote(nginx)} nginx -T', timeout=30)
    conf = stdout.read().decode()
    if stdout.channel.recv_exit_status():
        raise SystemExit('Nginx config validation failed')
    match = re.search(r'server\s*\{\s*listen\s+80\s+default_server;(.*?)\blocation\b', conf, re.S)
    if not match:
        raise SystemExit('Missing default HTTP tunnel server')
    networks = [ipaddress.ip_network(address.strip(), strict=False)
                for address in re.findall(r'\ballow\s+([^;]+);', match.group(1))]
    missing = [address for address in ips if not any(ipaddress.ip_address(address) in network for network in networks)]
    if missing:
        raise SystemExit('Registered cell tunnel/bootstrap denied by nginx: ' + ', '.join(missing))
    print(f'PASS nginx tunnel allowlist: all {len(ips)} registered active cells')


def _restart_and_verify(client, *, expected_admin_index: Path | None = None) -> None:
    # Код уже на хосте. up -d api --no-deps recreate только если compose изменился;
    # после volume ./app и ./ai recreate безопасен. wdtt не трогаем.
    script = f"""#!/bin/bash
set -e
cd {REMOTE}
echo "=== compose apply (no-deps, never wdtt) ==="
docker compose up -d api nginx --no-deps
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if docker inspect -f '{{{{.State.Running}}}}' {CONTAINER} 2>/dev/null | grep -q true; then
    break
  fi
  sleep 1
done
docker exec {CONTAINER} pip install -q paramiko httpx redis disposable-email-domains 2>/dev/null || true
docker compose restart api nginx
sleep 14
echo "=== mounts ==="
n=$(docker inspect -f '{{{{range .Mounts}}}}{{{{println .Destination}}}}{{{{end}}}}' {CONTAINER} | grep -cE '^/app/(app|ai)$' || true)
echo "app/ai mounts: $n (need 2)"
if [ "$n" != "2" ]; then
  echo "ERROR: app/ai volumes missing after up" >&2
  docker inspect -f '{{{{json .Mounts}}}}' {CONTAINER}
  exit 1
fi
echo "=== tunnel DNAT ==="
bash /tmp/fix_tunnel_dnat.sh
echo "=== verify ==="
curl -sf http://127.0.0.1:8000/api/health && echo " health OK"
curl -sf http://127.0.0.1:8000/health && echo " /health OK" || true
alt=$(curl -sk -o /dev/null -w "%{{http_code}}" --connect-timeout 3 --resolve 89-125-188-100.nip.io:2083:127.0.0.1 https://89-125-188-100.nip.io:2083/api/health || true)
echo "alt2083 HTTP $alt (expect 200)"
admin=$(curl -s -o /dev/null -w "%{{http_code}}" http://127.0.0.1:8000/)
echo "admin: $admin"
hive=$(curl -s -o /dev/null -w "%{{http_code}}" -H "Host: 89-125-188-100.nip.io" http://127.0.0.1:8000/api/admin/hive/cells)
echo "hive/cells HTTP $hive (expect 401)"
if [ "$hive" = "404" ]; then
  echo "ERROR: hive routes missing" >&2
  exit 1
fi
wdtt=$(systemctl is-active wdtt.service || true)
echo "wdtt: $wdtt"
if [ "$wdtt" != "active" ]; then
  echo "ERROR: wdtt is not active (script did not restart it)" >&2
  exit 1
fi
echo "=== postflight (kick-storm / latency) ==="
python3 - <<'PY'
import sys
import time
import urllib.request
t0 = time.monotonic()
try:
    urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=3)
except Exception as e:
    print("ERROR: health request failed", e)
    sys.exit(1)
dt = time.monotonic() - t0
print(f"health_rtt {{dt:.3f}}s")
if dt > 1.5:
    print("ERROR: API health slower than 1.5s — likely event-loop / pool stall")
    sys.exit(1)
PY
sleep 18
kicks=$(docker logs --since 20s {CONTAINER} 2>&1 | grep -c "queen wg kick" || true)
echo "queen_wg_kick_20s=$kicks"
if [ "${{kicks:-0}}" -gt 40 ]; then
  echo "ERROR: unpaid kick storm ($kicks wg kicks / 20s). Do not leave this on prod." >&2
  exit 1
fi
"""
    sftp2 = client.open_sftp()
    sftp2.putfo(io.BytesIO(script.encode()), "/tmp/deploy_stable.sh")
    sftp2.close()
    run(client, "bash /tmp/deploy_stable.sh 2>&1", timeout=240)
    _verify_admin_ui(client, expected_admin_index)
    _verify_registered_cell_allowlist(client)
    client.close()
    print("Done")


if __name__ == "__main__":
    main()
