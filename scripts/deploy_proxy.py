"""Деплой Proxy fleet: API + proxy-agent + admin-ui. VPN/hive routing не меняет.

ВАЖНО:
- только `docker compose restart api nginx` (НЕ recreate — иначе теряются docker cp файлы);
- после копирования proxy-файлов подтягиваем полный `app/` с хоста, чтобы не оставить дыры в models;
- health-check обязателен.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

from _deploy_common import BACKEND_ROOT, CONTAINER, REMOTE, connect, run

client = connect()
sftp = client.open_sftp()

# Не копируем models/__init__.py отдельно «в обход» полного app —
# только proxy-специфичные файлы, затем sync полного app с хоста.
files = [
    "app/models/proxy_node.py",
    "app/services/proxy_service.py",
    "app/services/proxy_provision_service.py",
    "app/services/proxy_health_loop.py",
    "app/schemas/proxy.py",
    "app/api/proxy.py",
    "app/main.py",
    "app/config.py",
    "proxy-agent/main.py",
]

for rel in files:
    lp = BACKEND_ROOT / rel.replace("/", os.sep)
    if not lp.is_file():
        print("skip (missing)", rel)
        continue
    rp = f"{REMOTE}/{rel.replace(chr(92), '/')}"
    client.exec_command(f"mkdir -p {os.path.dirname(rp)}")
    sftp.put(str(lp), rp)
    print("upload", rel)

# models/__init__.py — только если локально есть ProxyNode в экспорте
init_lp = BACKEND_ROOT / "app" / "models" / "__init__.py"
if init_lp.is_file() and "ProxyNode" in init_lp.read_text(encoding="utf-8"):
    sftp.put(str(init_lp), f"{REMOTE}/app/models/__init__.py")
    print("upload app/models/__init__.py")

dist = BACKEND_ROOT / "admin-ui" / "dist"
if dist.is_dir():
    rdist = f"{REMOTE}/admin-ui/dist"
    client.exec_command(f"rm -rf {rdist}/assets && mkdir -p {rdist}/assets")
    for root, _, names in os.walk(dist):
        for name in names:
            lp = Path(root) / name
            rel = lp.relative_to(dist).as_posix()
            rp = f"{rdist}/{rel}"
            client.exec_command(f"mkdir -p {os.path.dirname(rp)}")
            sftp.put(str(lp), rp)
            print("ui", rel)
else:
    print("WARN: admin-ui/dist missing — run npm run build")

sftp.close()

script = f"""#!/bin/bash
set -e
cd {REMOTE}
# 1) proxy-файлы в контейнер
docker exec {CONTAINER} mkdir -p /app/proxy-agent /app/app/services /app/app/api /app/app/models /app/app/schemas
for f in {' '.join(files)} app/models/__init__.py; do
  [ -f "$f" ] && docker cp "$f" {CONTAINER}:/app/"$f"
done
[ -f proxy-agent/main.py ] && docker cp proxy-agent/main.py {CONTAINER}:/app/proxy-agent/main.py
# 2) страховка: полный app с хоста (не даём дыр в models после частичного cp)
docker cp {REMOTE}/app/. {CONTAINER}:/app/app/
docker exec {CONTAINER} pip install -q paramiko httpx 2>/dev/null || true
# 3) ТОЛЬКО restart — никогда recreate
docker compose restart api nginx
sleep 16
python3 - <<'PY'
import urllib.request
ok = True
for path in ["/api/health"]:
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8000" + path, timeout=10)
        print(path, r.status)
        if r.status != 200:
            ok = False
    except Exception as e:
        print(path, getattr(e, "code", e))
        ok = False
for path in ["/api/admin/proxy/nodes", "/api/admin/hive/cells"]:
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8000" + path, timeout=10)
        print(path, r.status)
    except Exception as e:
        print(path, getattr(e, "code", e))
if not ok:
    raise SystemExit("HEALTH_FAILED")
print("DEPLOY_PROXY_OK")
PY
"""
sftp2 = client.open_sftp()
sftp2.putfo(io.BytesIO(script.encode()), "/tmp/deploy_proxy.sh")
sftp2.close()
print(run(client, "bash /tmp/deploy_proxy.sh", timeout=180))
client.close()
print("DONE deploy_proxy")
