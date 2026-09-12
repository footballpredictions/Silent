import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.silent_lan import (
    dnsmasq_address_lines,
    extract_lan_ip_from_host,
    host_is_silent_zone,
    lan_host,
    lan_url,
)


class LanNameTests(unittest.TestCase):
    def test_common_prefixes(self):
        cases = {
            "192.168.1.1": "192.168.1.1.silent.vpn",
            "192.168.0.1": "192.168.0.1.silent.vpn",
            "10.0.0.1": "10.0.0.1.silent.vpn",
            "10.1.1.1": "10.1.1.1.silent.vpn",
            "172.16.0.1": "172.16.0.1.silent.vpn",
        }
        for ip, host in cases.items():
            self.assertEqual(lan_host(ip), host)
            self.assertEqual(lan_url(ip), f"http://{host}")
            self.assertEqual(extract_lan_ip_from_host(host), ip)

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            lan_host("router.local")
        with self.assertRaises(ValueError):
            lan_host("192.168.1.256")

    def test_zone_match(self):
        self.assertTrue(host_is_silent_zone("192.168.1.1.silent.vpn"))
        self.assertTrue(host_is_silent_zone("SILENT.VPN:80"))
        self.assertFalse(host_is_silent_zone("192.168.1.1"))
        self.assertFalse(host_is_silent_zone("luci.local"))

    def test_dnsmasq_lines(self):
        lines = dnsmasq_address_lines("192.168.0.1")
        self.assertIn("address=/192.168.0.1.silent.vpn/192.168.0.1", lines)
        self.assertIn("address=/silent.vpn/192.168.0.1", lines)


if __name__ == "__main__":
    unittest.main()
