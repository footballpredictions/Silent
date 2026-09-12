import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAINS = ROOT / "files" / "usr" / "lib" / "silent-vpn" / "ru-direct.domains"


class RuDirectListTests(unittest.TestCase):
    def test_list_has_core_ru_services(self):
        rows = [
            line.strip()
            for line in DOMAINS.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertGreaterEqual(len(rows), 20)
        for must in ("yandex.ru", "vk.com", "gosuslugi.ru", "sberbank.ru", "ozon.ru"):
            self.assertIn(must, rows)
        for row in rows:
            self.assertFalse(row.startswith("www."))
            self.assertNotIn(" ", row)


if __name__ == "__main__":
    unittest.main()
