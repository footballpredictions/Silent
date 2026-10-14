"""Four OpenWrt artifacts, validation, download selection and GitHub contract."""
import asyncio
import hashlib
import io
import json
import os
import sys
import tempfile
import tarfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import update_service as us, github_release_service as gh
from app.api.updates import download_update_file
from fastapi import HTTPException
ARCHES = us.OPENWRT_ARCHES


def artifact_name(version, arch=None):
    return f"silent-vpn-openwrt-{version}{'-' + arch if arch else ''}.tar.gz"


def fixture(root):
    root.mkdir()
    (root / "VERSION").write_text("1.0.169")
    (root / "install.sh").write_text("#!/bin/sh\necho installed\n")


def write_tarball(root, dest, arch):
    version = (root / "VERSION").read_text().strip()
    build_id = hashlib.sha256((root / "install.sh").read_bytes() + version.encode()).hexdigest()
    metadata = {"schema_version": 1, "version": version, "arch": arch, "build_id": build_id}
    elf_class, machine = {"aarch64": (2, 183), "arm": (1, 40), "mipsel": (1, 8), "x86_64": (2, 62)}[arch]
    elf = bytearray(64)
    elf[:6] = b"\x7fELF" + bytes((elf_class, 1))
    elf[18:20] = machine.to_bytes(2, "little")
    files = {"VERSION": version.encode(), "ARCH": arch.encode(), "PACKAGE.json": json.dumps(metadata).encode(),
             "install.sh": (root / "install.sh").read_bytes(), "remote-install.sh": b"#!/bin/sh\necho installer\n",
             f"files/usr/lib/silent-vpn/wdtt/wdtt-client.{arch}": elf}
    with tarfile.open(dest, "w:gz") as archive:
        for name, data in files.items():
            member = tarfile.TarInfo("silent-vpn/" + name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))


class OpenWrtUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = us._BASE
        us._BASE = str(self.root / "updates")
        fixture(self.root / "source")

    def tearDown(self):
        us._BASE = self.base
        self.temp.cleanup()

    def upload(self, arch, version="1.0.169"):
        (self.root / "source/VERSION").write_text(version)
        name = artifact_name(version, arch)
        path = self.root / name
        write_tarball(self.root / "source", path, arch)
        return us.publish_file("openwrt", name, str(path), arch=arch)

    def complete(self):
        for arch in ARCHES:
            self.upload(arch)
        return us.get_latest("openwrt")

    def test_four_uploads_survive_and_downloads_select_arch(self):
        latest = self.complete()
        self.assertEqual({b["arch"] for b in us.openwrt_binaries(latest, require_complete=True)}, set(ARCHES))
        for arch in ARCHES:
            picked = us.get_latest("openwrt", arch)
            self.assertTrue(picked["filename"].endswith(f"-{arch}.tar.gz"))
            self.assertTrue(Path(picked["file_path"]).is_file())
            info = us.check_update("openwrt", "1.0.168", arch)
            self.assertEqual(info["arch"], arch)
            self.assertEqual(info["sha256"], picked["sha256"])
            self.assertEqual(info["unpacked_size"], picked["unpacked_size"])
            self.assertTrue(info["tunnel_download_url"].endswith(f"?arch={arch}"))
        self.assertIsNone(us.get_latest("openwrt", "mips64"))
        self.assertIsNone(us.check_update("openwrt", "1.0.168"))

    def test_mismatched_arch_is_rejected_without_destroying_existing(self):
        self.upload("arm")
        with self.assertRaises(ValueError):
            us.publish_file("openwrt", artifact_name("1.0.169", "arm"), str(self.root / artifact_name("1.0.169", "arm")), arch="aarch64")
        self.assertTrue(Path(us.get_latest("openwrt", "arm")["file_path"]).is_file())

    def test_archive_content_arch_is_validated(self):
        self.upload("arm")
        with self.assertRaises(ValueError):
            us.publish_file("openwrt", artifact_name("1.0.169", "mipsel"), str(self.root / artifact_name("1.0.169", "arm")), arch="mipsel")

    def test_partial_or_mixed_versions_cannot_publish(self):
        self.upload("arm")
        with self.assertRaises(ValueError):
            us.openwrt_binaries(us.get_latest("openwrt"), require_complete=True)
        self.complete()
        self.upload("arm", "1.0.170")
        with self.assertRaises(ValueError):
            us.openwrt_binaries(us.get_latest("openwrt"), require_complete=True)
        # A different slot must report its own actual version.
        self.assertEqual(us.get_latest("openwrt", "aarch64")["version"], "1.0.169")

    def test_delete_only_selected_arch(self):
        self.complete()
        us.delete_platform_update("openwrt", "arm")
        self.assertIsNone(us.get_latest("openwrt", "arm"))
        self.assertEqual(len(us.openwrt_binaries(us.get_latest("openwrt"))), 3)
        with self.assertRaises(ValueError):
            us.delete_platform_update("openwrt", "typo")
        self.assertEqual(len(us.openwrt_binaries(us.get_latest("openwrt"))), 3)

    def test_same_version_packages_from_different_builds_cannot_mix(self):
        self.complete()
        (self.root / "source/install.sh").write_text("#!/bin/sh\necho changed\n")
        self.upload("arm")
        with self.assertRaises(ValueError):
            us.openwrt_binaries(us.get_latest("openwrt"), require_complete=True)

    def test_github_names_and_installer_metadata(self):
        latest = self.complete()
        entry = gh._landing_entry_from_manifest("openwrt", latest, "https://example.test/file")
        self.assertEqual(set(entry["arches"]), set(ARCHES))
        for arch, slot in entry["arches"].items():
            self.assertEqual(slot["filename"], artifact_name("1.0.169", arch))
            self.assertEqual(len(slot["sha256"]), 64)
            self.assertGreater(slot["unpacked_size"], 0)

    def test_github_publish_uploads_four_files_and_paired_bootstrap(self):
        self.complete()
        uploaded = []
        async def upload(token, release, path, name):
            uploaded.append(name)
            return {"name": name, "browser_download_url": gh.asset_download_url("1.0.169", name)}
        release = {"id": 1, "assets": [], "html_url": "https://example.test/release"}
        with patch.object(gh, "_token", return_value="test"), \
             patch.object(gh, "_get_release_by_tag", AsyncMock(return_value=release)), \
             patch.object(gh, "_remove_platform_assets", AsyncMock()), \
             patch.object(gh, "_upload_release_asset", side_effect=upload), \
             patch.object(gh, "_update_release_meta", AsyncMock(return_value=release)), \
             patch.object(gh, "_read_repo_sha", AsyncMock(return_value="oldsha")), \
             patch.object(gh, "_write_repo_file", AsyncMock()) as write, \
             patch.object(gh, "_sync_landing_releases_json", AsyncMock(return_value={})) as landing, \
             patch.object(gh, "_sync_landing_index_html", AsyncMock()), \
             patch.object(gh, "_sync_openwrt_pages_tgz", AsyncMock()) as legacy:
            asyncio.run(gh.publish_platform("openwrt", sync_peer=False))
            self.assertEqual(set(uploaded), {artifact_name("1.0.169", a) for a in ARCHES})
            self.assertEqual(write.call_args.args[1], "openwrt-install.sh")
            self.assertIn(b"#!/bin/sh", write.call_args.args[2])
            landing.assert_awaited_once()
            self.assertEqual(landing.call_args.args[4], artifact_name("1.0.169", "x86_64"))
            self.assertTrue(landing.call_args.args[3].endswith(artifact_name("1.0.169", "x86_64")))
            legacy.assert_not_awaited()
        self.assertTrue(all(b["github_download_url"] for b in us.openwrt_binaries(us.get_latest("openwrt"))))

    def test_incomplete_publication_has_no_external_side_effects(self):
        self.upload("arm")
        with patch.object(gh, "_token") as token:
            with self.assertRaises(gh.GitHubReleaseError):
                asyncio.run(gh.publish_platform("openwrt"))
            token.assert_not_called()

    def test_public_download_needs_arch_and_returns_correct_file(self):
        self.complete()
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(download_update_file("openwrt", arch=""))
        self.assertEqual(caught.exception.status_code, 400)
        for arch in ARCHES:
            response = asyncio.run(download_update_file("openwrt", arch=arch))
            self.assertTrue(str(response.path).endswith(f"-{arch}.tar.gz"))

    def test_legacy_universal_manifest_remains_downloadable(self):
        us.ensure_dirs()
        name = "silent-vpn-openwrt-1.0.168.tar.gz"
        (Path(us._BASE) / "openwrt" / name).write_bytes(b"legacy file")
        us._write_manifest("openwrt", {"version": "1.0.168", "filename": name, "size": 11})
        self.assertEqual(us.get_latest("openwrt", "arm")["filename"], name)
        self.assertEqual(asyncio.run(download_update_file("openwrt", arch="")).filename, name)

    def test_other_platform_snapshot_does_not_advertise_staged_openwrt(self):
        self.upload("arm")
        manifest = {"version": "1.0.169", "filename": "app.apk", "size": 3}
        snapshot = asyncio.run(gh._build_landing_releases_snapshot("android", manifest, "https://example.test/app.apk"))
        self.assertNotIn("openwrt", snapshot)

    def test_legacy_release_asset_survives_architecture_publication(self):
        assets = [{"id": i, "name": name} for i, name in enumerate(
            [artifact_name("1.0.169"), "app.apk"] + [artifact_name("1.0.169", a) for a in ARCHES], start=1)]
        with patch.object(gh, "_delete_asset", AsyncMock()) as delete:
            asyncio.run(gh._remove_platform_assets("test", {"assets": assets}, "openwrt", architectures_only=True))
            self.assertEqual({call.args[1] for call in delete.call_args_list}, {3, 4, 5, 6})


if __name__ == "__main__":
    unittest.main()
