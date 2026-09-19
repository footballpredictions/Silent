import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = (ROOT / "files/usr/lib/silent-vpn/common.sh").read_text(encoding="utf-8")


class ApiFailoverTests(unittest.TestCase):
    def test_public_bases_cells_then_hive(self):
        start = COMMON.index("sv_api_bases()")
        chunk = COMMON[start : start + 900]
        hive = chunk.index("SV_PUBLIC_API")
        cell1 = chunk.index("87.58.213.193:9100")
        cell2 = chunk.index("78.17.74.27:9100")
        self.assertLess(cell1, cell2)
        self.assertLess(cell1, hive)
        self.assertIn("sv_hive_timeout_for", COMMON)

    def test_old_hive_override_is_ignored(self):
        self.assertIn("*132.243.234.162*", COMMON)


if __name__ == "__main__":
    unittest.main()
