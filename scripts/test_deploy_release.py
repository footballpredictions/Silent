import unittest
from deploy_release import merge_manifest, versioned_filename


class AndroidPublicationTest(unittest.TestCase):
    def test_versioned_apk_name_keeps_its_version(self):
        self.assertEqual(versioned_filename("1.0.175", "SilentVPN-release-1.0.175.apk"),
                         "SilentVPN-release-1.0.175.apk")

    def test_manifest_preserves_unknown_fields_without_mutating_old_entry(self):
        old = {"version": "1.0.174", "filename": "old.apk", "custom": True}
        result = merge_manifest(old, {"version": "1.0.175", "filename": "new.apk", "sha256": "digest"}, "android")
        self.assertEqual(old["filename"], "old.apk")
        self.assertEqual(result["filename"], "new.apk")
        self.assertTrue(result["custom"])


if __name__ == "__main__":
    unittest.main()
