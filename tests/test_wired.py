import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.silent_wired import is_wireless_ifname


class WiredGuardTests(unittest.TestCase):
    def test_wifi_ifnames(self):
        self.assertTrue(is_wireless_ifname("wlan0"))
        self.assertTrue(is_wireless_ifname("phy0-ap0"))
        self.assertTrue(is_wireless_ifname("ra0"))

    def test_ethernet_ifnames(self):
        self.assertFalse(is_wireless_ifname("lan1"))
        self.assertFalse(is_wireless_ifname("eth0"))
        self.assertFalse(is_wireless_ifname("br-lan"))

    def test_cgi_requires_local_network(self):
        root = Path(__file__).resolve().parents[1]
        entry = (root / "files/www/cgi-bin/silent-entry").read_text(encoding="utf-8")
        api = (root / "files/www/cgi-bin/silent-api").read_text(encoding="utf-8")
        self.assertIn("sv_http_allow_lan", entry)
        self.assertIn("sv_http_allow_lan", api)
        self.assertNotIn("только по кабел", entry.lower())
        self.assertNotIn("только по кабел", api.lower())
        self.assertIn("Wi-Fi", entry)
        self.assertIn("кабел", entry.lower())
        self.assertIn("Wi-Fi", api)
        deny = (root / "files/usr/lib/silent-vpn/common.sh").read_text(encoding="utf-8")
        self.assertIn("sv_dev_is_lan", deny)


if __name__ == "__main__":
    unittest.main()
