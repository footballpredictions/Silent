import unittest
from pathlib import Path

PATH_SH = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "silent-vpn" / "path.sh"


class PathRouteTests(unittest.TestCase):
    def test_main_table_is_not_hijacked(self):
        text = PATH_SH.read_text(encoding="utf-8")
        self.assertNotIn("ip route replace 0.0.0.0/1", text)
        self.assertNotIn("ip route replace 128.0.0.0/1", text)
        self.assertIn("sv_path_lan_clients", text)
        self.assertIn('lookup main pref 50', text)
        self.assertIn('iif "$dev"', text)
        from_rules = [line for line in text.splitlines() if "ip rule add from" in line or 'rule add from' in line]
        self.assertTrue(from_rules)
        for line in from_rules:
            self.assertIn("iif", line)
        self.assertIn("snat ip to", text)
        self.assertIn("silent-vpn-quic", text)
        self.assertIn("mtu 1280", text)
        self.assertIn('.device="$SV_WG_IF"', text)
        self.assertIn("01-silent-masq.nft", text)
        self.assertIn("nat: FAILED", text)
        self.assertIn("flow_offloading", text)
        self.assertIn("net.ipv4.conf.all.rp_filter=2", text)
        self.assertNotIn('nft insert rule inet fw4 srcnat oifname "$SV_WG_IF" masquerade 2>/dev/null || true', text)


if __name__ == "__main__":
    unittest.main()
