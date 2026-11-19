"""Publish desktop OTA assets without deleting old downloads or restarting services."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import shlex
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from _deploy_common import CONTAINER, REMOTE_BACKEND, connect, run_ssh


def versioned_filename(version: str, original: str) -> str:
    stem, ext = os.path.splitext(original)
    return original if re.search(r"(?<!\d)" + re.escape(version) + r"(?!\d)", stem) else f"{stem}-{version}{ext}"


def merge_manifest(existing: dict, entry: dict, platform: str, arch: str | None = None) -> dict:
    result = dict(existing)
    if platform != "mac":
        result.update(entry)
        return result
    if arch not in ("x64", "arm64"):
        raise ValueError("Mac OTA requires x64 or arm64")
    arches = dict(existing.get("arches") or {})
    if not arches and existing.get("filename"):
        arches["arm64" if "arm64" in existing["filename"].lower() else "x64"] = {
            key: existing[key] for key in ("version", "filename", "size", "sha256", "uploaded_at") if key in existing
        }
    arches[arch] = dict(entry)
    result.update(arches.get("x64", entry))
    result["arches"] = arches
    return result


def read_manifest(sftp, filename: str) -> dict:
    try:
        with sftp.open(filename, "rb") as source:
            return json.loads(source.read(2 * 1024 * 1024))
    except FileNotFoundError:
        return {}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("version")
    parser.add_argument("--platform", choices=("pc", "linux", "mac"), default="pc")
    parser.add_argument("--arch", choices=("x64", "arm64"))
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        parser.error("expected a numeric release version")
    if (args.platform == "mac") != bool(args.arch):
        parser.error("--arch is required only for mac")
    expected_ext = {"pc": ".exe", "linux": ".deb", "mac": ".dmg"}[args.platform]
    if args.file.suffix.lower() != expected_ext or args.file.stat().st_size < 1_000_000:
        parser.error("unexpected or incomplete desktop release asset")
    filename = versioned_filename(args.version, args.file.name)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._()-]{0,180}", filename):
        parser.error("unsafe asset filename")
    with args.file.open("rb") as source:
        digest = hashlib.sha256(source.read()).hexdigest()
    size = args.file.stat().st_size
    client = connect(timeout=15)
    sftp = None
    temporary = []
    try:
        remote = os.environ.get("DEPLOY_REMOTE", REMOTE_BACKEND)
        container = os.environ.get("DEPLOY_CONTAINER", CONTAINER)
        sftp = client.open_sftp()
        mounts = json.loads(run_ssh(client, "docker inspect --format '{{json .Mounts}}' " + shlex.quote(container)))
        mount = next((m for m in mounts if m.get("Destination") == "/app/update" and m.get("Type") == "bind"), None)
        expected_root = posixpath.join(remote, "update")
        if not mount or sftp.normalize(mount["Source"]) != sftp.normalize(expected_root):
            raise RuntimeError("OTA bind mount does not match the configured release directory")
        directory = posixpath.join(expected_root, args.platform)
        run_ssh(client, "mkdir -p -- " + shlex.quote(directory))
        destination = posixpath.join(directory, filename)
        try:
            sftp.stat(destination)
            exists = True
        except FileNotFoundError:
            exists = False
        checksum_cmd = lambda file: "sha256sum -- " + shlex.quote(file)
        if exists:
            if run_ssh(client, checksum_cmd(destination)).split()[0] != digest:
                raise RuntimeError("refusing to overwrite a different existing release asset")
        else:
            part = destination + "." + uuid.uuid4().hex + ".part"
            temporary.append(part)
            sftp.put(str(args.file), part)
            if run_ssh(client, checksum_cmd(part)).split()[0] != digest:
                raise RuntimeError("uploaded asset checksum mismatch")
            sftp.posix_rename(part, destination)
        manifest_path = posixpath.join(directory, "manifest.json")
        entry = {"version": args.version, "filename": filename, "size": size, "sha256": digest,
                 "uploaded_at": datetime.now(timezone.utc).isoformat()}
        manifest = merge_manifest(read_manifest(sftp, manifest_path), entry, args.platform, args.arch)
        part = posixpath.join(directory, ".manifest-" + uuid.uuid4().hex + ".tmp")
        temporary.append(part)
        with sftp.open(part, "wb") as output:
            output.write((json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        sftp.posix_rename(part, manifest_path)
        if read_manifest(sftp, manifest_path) != manifest:
            raise RuntimeError("published manifest verification failed")
        print(json.dumps({"platform": args.platform, "arch": args.arch, **entry}, ensure_ascii=False))
    finally:
        if sftp:
            for file in temporary:
                try:
                    sftp.remove(file)
                except FileNotFoundError:
                    pass
            sftp.close()
        client.close()


if __name__ == "__main__":
    main()
