"""Unit checks for Linux OTA helpers (без Docker / asyncpg)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.github_release_service import (  # noqa: E402
    _platform_asset_ext,
    _patch_index_html_releases,
    _release_has_platform_asset,
    github_asset_filename,
)


def _versioned_filename(version: str, original: str) -> str:
    """Зеркало build_agent_service._versioned_filename (без импорта SQLAlchemy)."""
    import os

    base, ext = os.path.splitext(original)
    if not ext:
        lower = original.lower()
        if lower.endswith("apk"):
            ext = ".apk"
        elif lower.endswith("deb") or "linux" in lower:
            ext = ".deb"
        else:
            ext = ".exe"
    safe = version.strip()
    if not safe:
        return original
    if base.endswith(safe) or base.endswith(f" {safe}"):
        return original
    return f"{base}-{safe}{ext}"


_SAMPLE_HTML = """
<a id="pcDownload" href="OLD_PC"></a>
<span id="pcVersion" data-version="1.0.0">v1.0.0</span>
<p id="pcMeta">1 MB</p>
<a id="androidDownload" href="OLD_APK"></a>
<span id="androidVersion" data-version="1.0.0">v1.0.0</span>
<p id="androidMeta">1 MB</p>
<a id="linuxDownload" href="OLD_DEB"></a>
<span id="linuxVersion" data-version="1.0.0">v1.0.0</span>
<p id="linuxMeta">1 MB</p>
<script>
                        const INLINE_FALLBACK = {
      pc: {
        version: "1.0.0",
        size: 1,
        filename: "a.exe",
        download_url: "OLD_PC",
      },
      android: {
        version: "1.0.0",
        size: 1,
        filename: "a.apk",
        download_url: "OLD_APK",
      },
    };
</script>
"""


class LinuxBuildAgentUnit(unittest.TestCase):
    def test_versioned_filename_linux_deb(self) -> None:
        self.assertEqual(
            _versioned_filename("1.0.165", "Silent VPN Setup 1.0.165.deb"),
            "Silent VPN Setup 1.0.165.deb",
        )
        self.assertEqual(
            _versioned_filename("1.0.166", "SilentVPN.deb"),
            "SilentVPN-1.0.166.deb",
        )

    def test_deb_ar_magic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "x.deb"
            bad.write_bytes(b"not-a-deb")
            with bad.open("rb") as fh:
                self.assertFalse(fh.read(8).startswith(b"!<arch>\n"))
            good = Path(td) / "ok.deb"
            good.write_bytes(b"!<arch>\n" + b"x" * 20)
            with good.open("rb") as fh:
                self.assertTrue(fh.read(8).startswith(b"!<arch>\n"))

    def test_github_linux_asset_ext_and_filename(self) -> None:
        self.assertEqual(_platform_asset_ext("linux"), ".deb")
        self.assertEqual(
            github_asset_filename("linux", "Silent VPN Setup 1.0.165.deb", "1.0.165"),
            "Silent.VPN.Setup.1.0.165.deb",
        )
        release = {"assets": [{"name": "Silent.VPN.Setup.1.0.165.deb"}]}
        self.assertTrue(_release_has_platform_asset(release, "linux"))
        self.assertFalse(_release_has_platform_asset(release, "pc"))
        self.assertFalse(_release_has_platform_asset(release, "android"))

    def test_patch_index_html_includes_linux(self) -> None:
        releases = {
            "pc": {
                "version": "1.0.163",
                "filename": "Silent.VPN.Setup.1.0.163.exe",
                "size": 10,
                "download_url": "https://example/pc.exe",
            },
            "android": {
                "version": "1.0.163",
                "filename": "app.apk",
                "size": 20,
                "download_url": "https://example/app.apk",
            },
            "linux": {
                "version": "1.0.165",
                "filename": "Silent.VPN.Setup.1.0.165.deb",
                "size": 118398104,
                "download_url": "https://example/linux.deb",
            },
        }
        out = _patch_index_html_releases(_SAMPLE_HTML, releases)
        self.assertIn('id="linuxDownload" href="https://example/linux.deb"', out)
        self.assertIn('id="linuxVersion" data-version="1.0.165">v1.0.165', out)
        self.assertIn("112.9 MB", out)
        self.assertIn("linux: {", out)
        self.assertIn("Silent.VPN.Setup.1.0.165.deb", out)


if __name__ == "__main__":
    unittest.main()
