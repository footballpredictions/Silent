"""Deploy PC update exe to VPS (host + container, versioned filename)."""
import io
import os
import sys

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = "132.243.234.162"
USER = "root"
PASS = "3txvDbnJvVaZg"


def versioned_filename(version: str, original: str) -> str:
    import re
    base, ext = os.path.splitext(original)
    if not ext:
        ext = ".exe"
    safe = version.strip()
    if safe:
        base = re.sub(rf"[\s-]?{re.escape(safe)}$", "", base).strip()
        return f"{base}-{safe}{ext}"
    return original


def main():
    local_file = sys.argv[1]
    version = sys.argv[2] if len(sys.argv) > 2 else None
    if not version:
        print("Usage: deploy_pc_update.py <setup.exe> <version e.g. 1.0.121>")
        sys.exit(1)

    platform = "pc"
    original_name = os.path.basename(local_file)
    filename = versioned_filename(version, original_name)
    remote_dir = f"/opt/silent-vpn/backend/update/{platform}"
    remote_file = f"{remote_dir}/{filename}"
    container_dir = f"/app/update/{platform}"
    container_dest = f"{container_dir}/{filename}"
    size = os.path.getsize(local_file)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=20)
    sftp = client.open_sftp()

    client.exec_command(f"mkdir -p {remote_dir}")
    client.exec_command(f"find {remote_dir} -maxdepth 1 -type f -delete 2>/dev/null || true")
    sftp.put(local_file, remote_file)
    print(f"uploaded host {remote_file} ({size // (1024 * 1024)} MB)")

    host_manifest_py = f"""
import json, os
from datetime import datetime, timezone
dest_dir = {remote_dir!r}
filename = {filename!r}
version = {version!r}
path = os.path.join(dest_dir, filename)
size = os.path.getsize(path) if os.path.isfile(path) else 0
manifest = {{
    "version": version,
    "filename": filename,
    "size": size,
    "uploaded_at": datetime.now(timezone.utc).isoformat(),
}}
with open(os.path.join(dest_dir, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)
print("host manifest ok", version, filename)
"""
    sftp.putfo(io.BytesIO(host_manifest_py.encode()), "/tmp/write_manifest_pc_host.py")
    _, out, _ = client.exec_command("python3 /tmp/write_manifest_pc_host.py 2>&1", timeout=30)
    print(out.read().decode("utf-8", errors="replace").strip())

    manifest_py = f"""
import json, os
from datetime import datetime, timezone
platform = {platform!r}
filename = {filename!r}
version = {version!r}
dest_dir = {container_dir!r}
path = os.path.join(dest_dir, filename)
size = os.path.getsize(path) if os.path.isfile(path) else 0
manifest = {{
    "version": version,
    "filename": filename,
    "size": size,
    "uploaded_at": datetime.now(timezone.utc).isoformat(),
}}
with open(os.path.join(dest_dir, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)
print("manifest ok", version, filename, size)
"""
    sftp.putfo(io.BytesIO(manifest_py.encode()), "/tmp/write_manifest_pc.py")

    check_ver = version
    script = f"""#!/bin/bash
set -e
docker exec backend-api-1 mkdir -p {container_dir}
docker exec backend-api-1 sh -c 'find {container_dir} -maxdepth 1 -type f -delete 2>/dev/null || true'
docker cp "{remote_file}" "backend-api-1:{container_dest}"
docker cp /tmp/write_manifest_pc.py backend-api-1:/tmp/write_manifest_pc.py
docker exec backend-api-1 python /tmp/write_manifest_pc.py
curl -s "http://localhost:8000/api/updates/check?platform=pc&version={check_ver}"
echo
curl -sI "http://localhost:8000/update/pc/{filename}" | head -3
"""
    sftp.putfo(io.BytesIO(script.encode()), "/tmp/deploy_pc_update.sh")
    sftp.close()
    _, out, _ = client.exec_command("bash /tmp/deploy_pc_update.sh 2>&1", timeout=300)
    print(out.read().decode("utf-8", errors="replace"))
    client.close()
    print("Done.")


if __name__ == "__main__":
    main()
