"""YuMoney rejects Referer from 127.0.0.1 / *.silent.vpn — open like Android (no site)."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
API = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")


class PaymentOpenTests(unittest.TestCase):
    def test_does_not_window_open_with_referrer(self):
        self.assertNotIn('window.open(res.url, "_blank", "noopener")', APP)
        self.assertIn("openPaymentUrl", APP)
        self.assertIn("no-referrer", API)
        self.assertIn("noreferrer", API)

    def test_rejects_bare_yumoney_homepage(self):
        self.assertIn("https://yoomoney.ru/quickpay/", API)


if __name__ == "__main__":
    unittest.main()
