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
        self.assertEqual(result["arches"]["x64"]["filename"], old["filename"])
        self.assertEqual(result["arches"]["arm64"]["version"], "1.0.175")

    def test_mac_intel_upload_keeps_arm_and_updates_legacy_default(self):
        old = {"arches": {"arm64": {"version": "1.0.170", "filename": "old-arm.dmg"}}}
        result = merge_manifest(old, {"version": "1.0.175", "filename": "new-x64.dmg"}, "mac", "x64")
        self.assertEqual(result["filename"], "new-x64.dmg")
        self.assertEqual(result["arches"]["arm64"]["filename"], "old-arm.dmg")

    def test_versioned_arch_names_are_not_given_a_second_version(self):
        self.assertEqual(versioned_filename("1.0.175", "Silent.1.0.175-arm64.dmg"), "Silent.1.0.175-arm64.dmg")
        self.assertEqual(versioned_filename("1.0.175", "Silent.exe"), "Silent-1.0.175.exe")


if __name__ == "__main__":
    unittest.main()
