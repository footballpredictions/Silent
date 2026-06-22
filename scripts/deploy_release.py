"""Загрузка Android APK на VPS для OTA.

Использование:
  python scripts/deploy_release.py app\\build\\outputs\\apk\\release\\app-release.apk 1.0.130
"""
from __future__ import annotations

import io
import os
import sys

from _deploy_common import CONTAINER, REMOTE_BACKEND, connect, run_ssh

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def versioned_filename(version: str, original: str) -> str:
    base, ext = os.path.splitext(original)
    if not ext:
        ext = ".apk"
    safe = version.strip()
    return f"{base}-{safe}{ext}" if safe else original


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python scripts/deploy_release.py <path-to.apk> <version>")
        sys.exit(1)

    local_file = sys.argv[1]
    version = sys.argv[2]
    platform = "android"
    filename = versioned_filename(version, os.path.basename(local_file))
    remote_dir = f"{REMOTE_BACKEND}/update/{platform}"
    remote_file = f"{remote_dir}/{filename}"
    container_dir = f"/app/update/{platform}"
    container_dest = f"{container_dir}/{filename}"
    size = os.path.getsize(local_file)

    client = connect()
    sftp = client.open_sftp()
    run_ssh(client, f"mkdir -p {remote_dir}")
    run_ssh(client, f"find {remote_dir} -maxdepth 1 -type f -delete 2>/dev/null || true")
    sftp.put(local_file, remote_file)
    run_ssh(client, f"test -f {remote_file}")
    print(f"uploaded {remote_file} ({size // (1024 * 1024)} MB)")

    manifest_py = f"""
import json, os, glob
from datetime import datetime, timezone
dest_dir = {container_dir!r}
filename = {filename!r}
version = {version!r}
os.makedirs(dest_dir, exist_ok=True)
for old in glob.glob(os.path.join(dest_dir, "*")):
    if os.path.basename(old) not in ("manifest.json", filename):
        os.remove(old)
path = os.path.join(dest_dir, filename)
size = os.path.getsize(path) if os.path.isfile(path) else 0
manifest = {{"version": version, "filename": filename, "size": size,
    "uploaded_at": datetime.now(timezone.utc).isoformat()}}
with open(os.path.join(dest_dir, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)
print("manifest ok", version, filename)
"""
    sftp.putfo(io.BytesIO(manifest_py.encode()), "/tmp/write_manifest_android.py")
    deploy_sh = f"""#!/bin/bash
set -e
docker exec {CONTAINER} mkdir -p {container_dir}
docker cp "{remote_file}" "{CONTAINER}:{container_dest}"
docker cp /tmp/write_manifest_android.py {CONTAINER}:/tmp/write_manifest_android.py
docker exec {CONTAINER} python /tmp/write_manifest_android.py
curl -s "http://localhost:8000/api/updates/check?platform=android&version=0.0.0"
echo
"""
    sftp.putfo(io.BytesIO(deploy_sh.encode()), "/tmp/deploy_android_release.sh")
    sftp.close()
    _, out, err = client.exec_command("bash /tmp/deploy_android_release.sh 2>&1", timeout=300)
    deploy_out = out.read().decode("utf-8", errors="replace")
    deploy_code = out.channel.recv_exit_status()
    print(deploy_out)
    if deploy_code != 0:
        e = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"deploy script failed ({deploy_code})\n{e or deploy_out}")
    client.close()
    print("Done.")


if __name__ == "__main__":
    main()
