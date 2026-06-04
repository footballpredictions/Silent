"""Deploy client update file to VPS update/ folder (replaces old version)."""
import io
import os
import sys
import argparse
import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = "132.243.234.162"
USER = "root"
PASS = "3txvDbnJvVaZg"
LOCAL_BACKEND = r"C:\Users\silent27\AndroidStudioProjects\Silent\backend"
REMOTE_BACKEND = "/opt/silent-vpn/backend"


def deploy_update(local_file: str, platform: str, version: str | None = None):
    if platform not in ("pc", "android"):
        print("platform must be pc or android")
        sys.exit(1)
    if not os.path.isfile(local_file):
        print(f"File not found: {local_file}")
        sys.exit(1)

    filename = os.path.basename(local_file)
    remote_dir = f"{REMOTE_BACKEND}/update/{platform}"
    remote_file = f"{remote_dir}/{filename}"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=20)
    sftp = client.open_sftp()

    client.exec_command(f"mkdir -p {remote_dir}")
    # Remove old files except manifest (service will rewrite manifest)
    client.exec_command(f"find {remote_dir} -type f ! -name manifest.json -delete 2>/dev/null || true")
    sftp.put(local_file, remote_file)
    print(f"uploaded {remote_file}")

    # Update manifest via Python in container
    ver_arg = f'"{version}"' if version else "None"
    py_script = f"""
import json, os
from datetime import datetime, timezone
platform = "{platform}"
filename = "{filename}"
version = {ver_arg}
if not version:
    import re
    m = re.search(r"(\\d+\\.\\d+\\.\\d+)", filename)
    version = m.group(1) if m else "0.0.0"
dest_dir = "/app/update/" + platform
path = os.path.join(dest_dir, filename)
size = os.path.getsize(path) if os.path.isfile(path) else 0
manifest = {{
    "version": version,
    "filename": filename,
    "size": size,
    "uploaded_at": datetime.now(timezone.utc).isoformat(),
}}
with open(os.path.join(dest_dir, "manifest.json"), "w") as f:
    json.dump(manifest, f, indent=2)
print("manifest ok", version)
"""
    sftp.putfo(io.BytesIO(py_script.encode()), "/tmp/write_manifest.py")

    script = f"""#!/bin/bash
set -e
mkdir -p {remote_dir}
docker cp {remote_file} backend-api-1:/app/update/{platform}/{filename}
docker cp /tmp/write_manifest.py backend-api-1:/tmp/write_manifest.py
docker exec backend-api-1 python /tmp/write_manifest.py
# cleanup old binaries in container
docker exec backend-api-1 bash -c 'cd /app/update/{platform} && for f in *; do [ "$f" = "manifest.json" ] || [ "$f" = "{filename}" ] || rm -f "$f"; done'
curl -s "http://localhost:8000/api/updates/check?platform={platform}&version=0.0.0" | head -c 200
echo
"""
    sftp2 = client.open_sftp()
    sftp2.putfo(io.BytesIO(script.encode()), "/tmp/deploy_update.sh")
    sftp2.close()
    sftp.close()

    _, out, err = client.exec_command("bash /tmp/deploy_update.sh 2>&1", timeout=120)
    print(out.read().decode("utf-8", errors="replace"))
    print(err.read().decode("utf-8", errors="replace"))
    client.close()
    print("Done.")


def deploy_backend_files():
    """Deploy update API + admin UI to VPS."""
    files = [
        "app/main.py",
        "app/api/admin.py",
        "app/api/updates.py",
        "app/services/update_service.py",
    ]
    dist = os.path.join(LOCAL_BACKEND, "admin-ui", "dist")
    if not os.path.isdir(dist):
        print("Build admin-ui first: cd backend/admin-ui && npm run build")
        sys.exit(1)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=20)
    sftp = client.open_sftp()

    for rel in files:
        local = os.path.join(LOCAL_BACKEND, rel.replace("/", os.sep))
        remote = f"{REMOTE_BACKEND}/{rel}"
        sftp.put(local, remote)
        print(f"uploaded {rel}")

    remote_dist = f"{REMOTE_BACKEND}/admin-ui/dist"
    client.exec_command(f"mkdir -p {remote_dist}")
    for root, _, fnames in os.walk(dist):
        for name in fnames:
            lp = os.path.join(root, name)
            rel = os.path.relpath(lp, dist).replace("\\", "/")
            rp = f"{remote_dist}/{rel}"
            client.exec_command(f"mkdir -p {os.path.dirname(rp)}")
            sftp.put(lp, rp)
    sftp.close()

    script = """#!/bin/bash
set -e
cd /opt/silent-vpn/backend
for f in app/main.py app/api/admin.py app/api/updates.py app/services/update_service.py; do
  docker cp "$f" backend-api-1:/app/"$f"
done
docker cp admin-ui/dist/. backend-api-1:/app/admin-ui/dist/
docker exec backend-api-1 mkdir -p /app/update/pc /app/update/android
docker compose restart api
sleep 8
curl -s http://localhost:8000/api/health
echo
"""
    sftp2 = client.open_sftp()
    sftp2.putfo(io.BytesIO(script.encode()), "/tmp/deploy_update_api.sh")
    sftp2.close()
    _, out, err = client.exec_command("bash /tmp/deploy_update_api.sh 2>&1", timeout=180)
    print(out.read().decode("utf-8", errors="replace"))
    client.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Deploy app updates to Silent VPN backend")
    p.add_argument("--backend", action="store_true", help="Deploy update API + admin UI")
    p.add_argument("--file", help="Local update file (.exe or .apk)")
    p.add_argument("--platform", choices=["pc", "android"], help="Target platform")
    p.add_argument("--version", help="Version string (auto-detected from filename if omitted)")
    args = p.parse_args()

    if args.backend:
        deploy_backend_files()
    elif args.file and args.platform:
        deploy_update(args.file, args.platform, args.version)
    else:
        p.print_help()
        sys.exit(1)
