import unittest
from deploy_release import merge_manifest, versioned_filename


class DesktopPublicationTest(unittest.TestCase):
    def test_pc_replaces_only_current_entry_and_keeps_unknown_fields(self):
        old = {"version": "1.0.172", "filename": "old.exe", "custom": True}
        result = merge_manifest(old, {"version": "1.0.175", "filename": "new.exe"}, "pc")
        self.assertTrue(result["custom"])
        self.assertEqual(old["filename"], "old.exe")

    def test_mac_arm_upload_preserves_legacy_intel_download(self):
        old = {"version": "1.0.170", "filename": "Silent-1.0.170-x64.dmg", "size": 10}
        result = merge_manifest(old, {"version": "1.0.175", "filename": "new-arm64.dmg"}, "mac", "arm64")
        self.assertEqual(result["filename"], old["filename"])
        self.assertEqual(result["files"]["x64"]["filename"], old["filename"])
        self.assertEqual(result["files"]["arm64"]["version"], "1.0.175")

    def test_mac_intel_upload_keeps_arm_and_updates_legacy_default(self):
        old = {"files": {"arm64": {"version": "1.0.170", "filename": "old-arm.dmg"}}}
        result = merge_manifest(old, {"version": "1.0.175", "filename": "new-x64.dmg"}, "mac", "x64")
        self.assertEqual(result["filename"], "new-x64.dmg")
        self.assertEqual(result["files"]["arm64"]["filename"], "old-arm.dmg")

    def test_versioned_arch_names_are_not_given_a_second_version(self):
        self.assertEqual(versioned_filename("1.0.175", "Silent.1.0.175-arm64.dmg"), "Silent.1.0.175-arm64.dmg")
        self.assertEqual(versioned_filename("1.0.175", "Silent.exe"), "Silent-1.0.175.exe")

    def test_new_download_url_replaces_stale_url_for_both_mac_slots(self):
        old = {"github_download_url": "old-x64", "custom": True, "files": {
            "x64": {"filename": "old-x64.dmg", "github_download_url": "old-x64"},
            "arm64": {"filename": "old-arm64.dmg", "github_download_url": "old-arm64"},
        }}
        intel = {"version": "1.0.175", "filename": "new-x64.dmg", "github_download_url": "new-x64"}
        arm = {"version": "1.0.175", "filename": "new-arm64.dmg", "github_download_url": "new-arm64"}
        result = merge_manifest(merge_manifest(old, intel, "mac", "x64"), arm, "mac", "arm64")
        self.assertEqual(result["github_download_url"], "new-x64")
        self.assertEqual(result["files"]["arm64"]["github_download_url"], "new-arm64")
        self.assertEqual(result["files"]["x64"]["version"], "1.0.175")
        self.assertTrue(result["custom"])
        self.assertEqual(old["files"]["x64"]["filename"], "old-x64.dmg")


if __name__ == "__main__":
    unittest.main()
