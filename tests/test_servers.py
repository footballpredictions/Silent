import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.silent_servers import display_vpn_servers, normalize_slot, selected_title


class ServerListTests(unittest.TestCase):
    def test_always_four_without_api(self):
        rows = display_vpn_servers(None)
        self.assertEqual([r["key"] for r in rows], ["server1", "server2", "server3", "server4"])
        self.assertEqual(rows[3]["title"], "Сервер 4 для ИИ")

    def test_merges_and_maps_legacy_keys(self):
        rows = display_vpn_servers([
            {"key": "queen", "title": "Улей", "public_ip": "1.1.1.1"},
            {"key": "cell1", "title": "Сота 1"},
        ])
        self.assertEqual(rows[0]["key"], "server1")
        self.assertEqual(rows[0]["title"], "Улей")
        self.assertEqual(rows[1]["key"], "server2")
        self.assertEqual(len(rows), 4)

    def test_normalize(self):
        self.assertEqual(normalize_slot("queen"), "server1")
        self.assertEqual(normalize_slot("ai_exit"), "server4")

    def test_selected_title(self):
        self.assertEqual(selected_title("server4"), "Сервер 4 для ИИ")
        self.assertEqual(selected_title("queen"), "Сервер 1")


if __name__ == "__main__":
    unittest.main()
