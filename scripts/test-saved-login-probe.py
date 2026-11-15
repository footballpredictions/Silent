"""Drive the production Swift launch probe against a local HTTP server on macOS."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import sys
import threading
import time


seen = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        seen.append((self.path, self.headers.get("Authorization"), self.headers.get("X-App-Version")))
        if self.path == "/slow":
            time.sleep(10)
            return
        payload = b'{"id":"fixture"}'
        status = {"/ok": 200, "/expired": 401, "/unavailable": 503}[self.path]
        self.send_response(status)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    subprocess.run([sys.argv[1], f"http://127.0.0.1:{server.server_port}"], check=True, timeout=25)
    assert [entry[0] for entry in seen[:4]] == ["/ok", "/expired", "/unavailable", "/slow"], seen
    assert all(entry[0] == "/slow" for entry in seen[4:]), seen
    assert len(seen) <= 5, "Probe retried public endpoints instead of deferring to bootstrap"
    assert all(entry[1] == "Bearer fixture-token" for entry in seen)
    assert all(entry[2] == "fixture" for entry in seen[:4])
    print("Saved login: no endpoint fan-out or token refresh before bootstrap: PASS")
finally:
    server.shutdown()
    server.server_close()
