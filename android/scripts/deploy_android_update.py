"""Deploy Android release APK to VPS."""
import io
import os
import sys
import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = "132.243.234.162"
USER = "root"
PASS = "3txvDbnJvVaZg"


def main():
    local_file = sys.argv[1]
    version = sys.argv[2] if len(sys.argv) > 2 else None
    platform = "android"
    filename = os.path.basename(local_file)
    remote_dir = f"/opt/silent-vpn/backend/update/{platform}"
    remote_file = f"{remote_dir}/{filename}"
    container_dest = f"/app/update/{platform}/{filename}"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=20)
    sftp = client.open_sftp()
    client.exec_command(f"mkdir -p {remote_dir}")
    client.exec_command(f"find {remote_dir} -type f ! -name manifest.json -delete 2>/dev/null || true")
    sftp.put(local_file, remote_file)
    print(f"uploaded {remote_file} ({os.path.getsize(local_file) // (1024 * 1024)} MB)")

    ver_arg = f'"{version}"' if version else "None"
    py_script = f"""
import json, os
from datetime import datetime, timezone
filename = {filename!r}
version = {ver_arg}
if not version:
    import re
    m = re.search(r"(\\d+\\.\\d+\\.\\d+)", filename)
    version = m.group(1) if m else "0.0.0"
dest_dir = "/app/update/android"
path = os.path.join(dest_dir, filename)
size = os.path.getsize(path) if os.path.isfile(path) else 0
manifest = {{"version": version, "filename": filename, "size": size, "uploaded_at": datetime.now(timezone.utc).isoformat()}}
with open(os.path.join(dest_dir, "manifest.json"), "w") as f:
    json.dump(manifest, f, indent=2)
print("manifest ok", version, size)
"""
    sftp.putfo(io.BytesIO(py_script.encode()), "/tmp/write_manifest_android.py")
    check_ver = version or "1.0.71"
    script = f"""#!/bin/bash
set -e
docker exec backend-api-1 mkdir -p /app/update/android
docker cp "{remote_file}" "backend-api-1:{container_dest}"
docker cp /tmp/write_manifest_android.py backend-api-1:/tmp/write_manifest_android.py
docker exec backend-api-1 python /tmp/write_manifest_android.py
curl -s "http://localhost:8000/api/updates/check?platform=android&version={check_ver}"
echo
"""
    sftp2 = client.open_sftp()
    sftp2.putfo(io.BytesIO(script.encode()), "/tmp/deploy_android_update.sh")
    sftp2.close()
    sftp.close()
    _, out, _ = client.exec_command("bash /tmp/deploy_android_update.sh 2>&1", timeout=300)
    print(out.read().decode("utf-8", errors="replace"))
    client.close()
    print("Done.")


if __name__ == "__main__":
    main()
