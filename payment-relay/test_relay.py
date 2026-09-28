import hashlib
import hmac
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from relay import Inbox, Rejected, make_server

SECRET = "test-notification-secret"


def notification(**changes):
    data = dict(notification_type="card-incoming", operation_id="relay-test-1", amount="478.00",
                withdraw_amount="478.00", currency="643", datetime="2026-09-28T17:33:00+03:00",
                sender="", codepro="false", label="silent_test_only", test_notification="true",
                email="тест+оплата@example.com")
    data.update(changes)
    canonical = "&".join(f"{key}={quote(value, safe='')}" for key, value in sorted(data.items()))
    data["sign"] = hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return urlencode(data).encode()


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "inbox.sqlite3"
        self.now = 1000
        self.inbox = Inbox(self.path, [SECRET], clock=lambda: self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def test_outage_restart_then_delivery_keeps_exact_payload(self):
        body = notification()
        self.assertEqual(self.inbox.accept(body), "queued")
        self.assertTrue(self.inbox.deliver_one(lambda _: 503))
        self.assertEqual(self.inbox.stats()["pending"], 1)
        self.now += 5
        restarted = Inbox(self.path, [SECRET], clock=lambda: self.now)
        received = []
        self.assertTrue(restarted.deliver_one(lambda payload: received.append(payload) or 200))
        self.assertEqual(received, [body])
        self.assertEqual(restarted.stats()["pending"], 0)
        self.assertEqual(restarted.stats()["delivered"], 1)
        self.assertEqual(restarted.accept(body), "duplicate")
        self.assertFalse(restarted.deliver_one(lambda _: self.fail("replayed delivered event")))

    def test_lost_upstream_response_replays_same_event(self):
        body = notification()
        received = []
        def lost(payload):
            received.append(payload)
            raise TimeoutError()
        self.inbox.accept(body)
        self.inbox.deliver_one(lost)
        self.now += 5
        self.inbox.deliver_one(lambda payload: received.append(payload) or 200)
        self.assertEqual(received, [body, body])
        # Hive serializes the same label/operation; replay never creates another subscription.
        self.assertEqual(self.inbox.stats()["delivered"], 1)

    def test_parallel_duplicate_acceptance_is_atomic(self):
        body = notification()
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(self.inbox.accept, [body] * 24))
        self.assertEqual(results.count("queued"), 1)
        self.assertEqual(results.count("duplicate"), 23)
        self.assertEqual(self.inbox.stats()["pending"], 1)

    def test_bad_signature_tampering_and_ambiguous_form_never_queued(self):
        body = notification()
        for forged in (body.replace(b"478.00", b"999.00"), body + b"&amount=478.00", b"amount=478&sign=fake"):
            with self.assertRaises(Rejected):
                self.inbox.accept(forged)
        self.assertEqual(self.inbox.stats()["pending"], 0)

    def test_unknown_or_full_storage_not_acknowledged(self):
        tiny = Inbox(self.path, [SECRET], max_pending=1)
        tiny.accept(notification())
        self.assertEqual(tiny.accept(notification()), "duplicate")
        with self.assertRaises(Rejected) as result:
            tiny.accept(notification(operation_id="relay-test-2"))
        self.assertEqual(result.exception.status, 503)

    def test_real_http_boundary_and_restart(self):
        server = make_server(self.inbox, ("127.0.0.1", 0))
        runner = threading.Thread(target=server.serve_forever, daemon=True)
        runner.start()
        url = f"http://127.0.0.1:{server.server_port}/api/payments/yumoney/notify"
        try:
            request = Request(url, data=notification(), headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urlopen(request, timeout=3) as response:
                self.assertEqual(response.status, 200)
            restarted = Inbox(self.path, [SECRET])
            self.assertEqual(restarted.stats()["pending"], 1)
            with self.assertRaises(HTTPError) as rejected:
                urlopen(Request(url, data=b"sign=invalid", headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=3)
            self.assertEqual(rejected.exception.code, 400)
            self.assertEqual(restarted.stats()["pending"], 1)
        finally:
            server.shutdown()
            server.server_close()
            runner.join()

    def test_legacy_signature_still_supported(self):
        data = dict(notification_type="p2p-incoming", operation_id="legacy-test", amount="1.00",
                    currency="643", datetime="2026-09-28T15:00:00Z", sender="", codepro="false", label="relay_test")
        canonical = "&".join((data["notification_type"], data["operation_id"], data["amount"],
                              data["currency"], data["datetime"], data["sender"], data["codepro"], SECRET, data["label"]))
        data["sha1_hash"] = hashlib.sha1(canonical.encode()).hexdigest()
        self.assertEqual(self.inbox.accept(urlencode(data).encode()), "queued")


if __name__ == "__main__":
    unittest.main()
