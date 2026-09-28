"""Durable, signed YuMoney inbox. No users, subscriptions or VPN credentials here."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import signal
import sqlite3
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

LOG = logging.getLogger("payment-relay")
NOTIFY_PATH = "/api/payments/yumoney/notify"
MAX_BODY = 32768
MAX_PENDING = 100000


class Rejected(ValueError):
    def __init__(self, status: int, reason: str):
        self.status, self.reason = status, reason
        super().__init__(reason)


def valid_signature(data: dict[str, str], secret: str) -> bool:
    if not secret:
        return False
    if data.get("sign"):
        canonical = "&".join(f"{key}={quote(data[key], safe='')}" for key in sorted(data) if key != "sign")
        expected = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, data["sign"])
    # Accept historical notifications through the same compatibility path as the hive.
    if data.get("sha1_hash"):
        canonical = "&".join((data.get("notification_type", ""), data.get("operation_id", ""),
                              data.get("amount", ""), data.get("currency", "643"),
                              data.get("datetime", ""), data.get("sender", ""),
                              data.get("codepro", "false"), secret, data.get("label", "")))
        return hmac.compare_digest(hashlib.sha1(canonical.encode()).hexdigest(), data["sha1_hash"])
    return False


def verified_fields(body: bytes, secrets: list[str]) -> dict[str, str]:
    if not body or len(body) > MAX_BODY:
        raise Rejected(413, "body too large or empty")
    try:
        pairs = parse_qsl(body.decode("utf-8"), keep_blank_values=True, max_num_fields=80,
                          encoding="utf-8", errors="strict")
    except (ValueError, UnicodeError):
        raise Rejected(400, "invalid form") from None
    data = dict(pairs)
    if len(data) != len(pairs):
        raise Rejected(400, "duplicate form fields")
    if not any(valid_signature(data, secret) for secret in secrets):
        raise Rejected(400, "invalid signature")
    if not data.get("operation_id") or data.get("notification_type") not in ("p2p-incoming", "card-incoming"):
        raise Rejected(400, "missing notification fields")
    return data


class Inbox:
    def __init__(self, path: str | Path, secrets: list[str], *, clock=time.time, max_pending=MAX_PENDING):
        self.path, self.secrets, self.clock, self.max_pending = str(path), secrets, clock, max_pending
        if not secrets or not all(secrets):
            raise ValueError("notification secrets required")
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS inbox (
                digest TEXT PRIMARY KEY, body BLOB, state TEXT NOT NULL DEFAULT 'pending',
                created REAL NOT NULL, next_attempt REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                delivered REAL, last_status INTEGER)""")
            db.execute("CREATE INDEX IF NOT EXISTS due ON inbox(state, next_attempt)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def accept(self, body: bytes) -> str:
        data = verified_fields(body, self.secrets)
        # Canonical payload identifies semantically identical retries, even with different form order.
        digest = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        now = self.clock()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM inbox WHERE digest=?", (digest,)).fetchone():
                return "duplicate"
            if db.execute("SELECT COUNT(*) FROM inbox WHERE state='pending'").fetchone()[0] >= self.max_pending:
                raise Rejected(503, "inbox full")
            db.execute("INSERT INTO inbox(digest,body,created,next_attempt) VALUES(?,?,?,?)", (digest, body, now, now))
        # HTTP 200 is returned only after this synchronous transaction commits.
        return "queued"

    def deliver_one(self, sender) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT * FROM inbox WHERE state='pending' AND next_attempt<=? ORDER BY created LIMIT 1", (self.clock(),)).fetchone()
        if row is None:
            return False
        try:
            status = sender(bytes(row["body"]))
        except Exception as error:
            # Do not log request bodies, labels, secrets or recipient information.
            LOG.warning("upstream request failed: %s", type(error).__name__)
            status = 0
        now, attempt = self.clock(), row["attempts"] + 1
        with self.connect() as db:
            if status == 200:
                db.execute("UPDATE inbox SET state='delivered',body=NULL,delivered=?,attempts=?,last_status=200 WHERE digest=?", (now, attempt, row["digest"]))
            else:
                delay = min(300, 2 ** min(attempt, 9))
                db.execute("UPDATE inbox SET next_attempt=?,attempts=?,last_status=? WHERE digest=?", (now + delay, attempt, status, row["digest"]))
        LOG.info("delivery status=%d attempt=%d", status, attempt)
        return True

    def stats(self) -> dict:
        with self.connect() as db:
            pending = db.execute("SELECT COUNT(*),MIN(created),MAX(attempts) FROM inbox WHERE state='pending'").fetchone()
            delivered = db.execute("SELECT COUNT(*),MAX(delivered) FROM inbox WHERE state='delivered'").fetchone()
        return {"pending": pending[0], "oldest_pending_seconds": round(max(0, self.clock() - pending[1])) if pending[1] else 0,
                "max_attempts": pending[2] or 0, "delivered": delivered[0], "last_delivery": delivered[1]}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Upstream:
    def __init__(self, urls: list[str]):
        if not urls or any(urlsplit(url).scheme != "https" or urlsplit(url).path != NOTIFY_PATH for url in urls):
            raise ValueError("only fixed HTTPS webhook upstreams permitted")
        self.urls, self.opener = urls, build_opener(NoRedirect())

    def __call__(self, body: bytes) -> int:
        status = 0
        for url in self.urls:
            request = Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Silent-Payment-Relay/1"}, method="POST")
            try:
                with self.opener.open(request, timeout=8) as response:
                    status = response.status
                    # Reject a generic HTML proxy success page. The hive returns JSON after commit.
                    payload = json.loads(response.read(4096))
                    if status == 200 and payload.get("status") == "ok":
                        return 200
                    status = 502
            except HTTPError as error:
                status = error.code
            except (URLError, OSError, ValueError, AttributeError):
                status = 0
        return status


def make_server(inbox: Inbox, address=("127.0.0.1", 9180)):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def reply(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                try:
                    self.reply(200, {"status": "ok", **inbox.stats()})
                except sqlite3.Error:
                    self.reply(503, {"status": "storage unavailable"})
            else:
                self.reply(404, {"status": "not found"})

        def do_POST(self):
            if self.path != NOTIFY_PATH:
                self.reply(404, {"status": "not found"})
                return
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise Rejected(400, "transfer encoding unsupported")
                if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/x-www-form-urlencoded":
                    raise Rejected(415, "expected form")
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise Rejected(400, "invalid content length") from None
                if size <= 0 or size > MAX_BODY:
                    raise Rejected(413, "body too large or empty")
                body = self.rfile.read(size)
                if len(body) != size:
                    raise Rejected(400, "incomplete body")
                reason = inbox.accept(body)
                self.reply(200, {"status": "ok", "reason": reason})
            except Rejected as error:
                self.reply(error.status, {"status": error.reason})
            except (sqlite3.Error, OSError):
                LOG.exception("cannot save notification")
                self.reply(503, {"status": "storage unavailable"})

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(address, Handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/etc/silent-payment-relay/config.json")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    inbox = Inbox(config["database"], config["notification_secrets"])
    upstream = Upstream(config["upstreams"])
    stopped = threading.Event()
    server = make_server(inbox)

    def worker():
        while not stopped.is_set():
            try:
                if not inbox.deliver_one(upstream):
                    stopped.wait(1)
            except Exception:
                LOG.exception("delivery loop failure; inbox retained")
                stopped.wait(5)

    def stop(*args):
        stopped.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    delivery = threading.Thread(target=worker, daemon=True)
    delivery.start()
    LOG.info("receiver ready on 127.0.0.1:9180")
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        stopped.set()
        delivery.join(timeout=20)
        server.server_close()


if __name__ == "__main__":
    main()
