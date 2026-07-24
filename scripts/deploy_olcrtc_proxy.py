"""HTTP CONNECT proxy for olcrtc on LTE — ports 8080 (+ optional 18443).

Carriers often block high ports like 18443; 8080 is usually open.

  cd backend
  python scripts/deploy_olcrtc_proxy.py
"""
from __future__ import annotations

import io
import textwrap

from _deploy_common import connect, run

REMOTE = "/opt/silent-vpn/olcrtc"
PROXY_PY = f"{REMOTE}/connect_proxy.py"
UNIT = "/etc/systemd/system/silent-olcrtc-proxy.service"
PORTS = (8080, 18443)


def main() -> None:
    ports_list = ", ".join(str(p) for p in PORTS)
    proxy_src = textwrap.dedent(
        f"""\
        #!/usr/bin/env python3
        \"\"\"HTTP CONNECT proxy; listen on {ports_list}.\"\"\"
        import select
        import socket
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class H(BaseHTTPRequestHandler):
            timeout = 30

            def log_message(self, fmt, *args):
                sys_stderr = __import__("sys").stderr
                sys_stderr.write("%s - %s\\n" % (self.address_string(), fmt % args))

            def do_CONNECT(self):
                host_port = self.path.split(":", 1)
                host = host_port[0]
                port = int(host_port[1]) if len(host_port) > 1 else 443
                try:
                    upstream = socket.create_connection((host, port), timeout=15)
                except OSError as e:
                    self.send_error(502, str(e))
                    return
                self.send_response(200, "Connection Established")
                self.end_headers()
                self.connection.setblocking(False)
                upstream.setblocking(False)
                socks = [self.connection, upstream]
                try:
                    while True:
                        r, _, x = select.select(socks, [], socks, 60)
                        if x or not r:
                            break
                        for s in r:
                            other = upstream if s is self.connection else self.connection
                            data = s.recv(65536)
                            if not data:
                                return
                            other.sendall(data)
                except OSError:
                    pass
                finally:
                    try:
                        upstream.close()
                    except OSError:
                        pass

        def serve(port: int) -> None:
            ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()

        if __name__ == "__main__":
            ports = [{", ".join(str(p) for p in PORTS)}]
            for i, p in enumerate(ports):
                t = threading.Thread(target=serve, args=(p,), daemon=(i > 0))
                t.start()
            # keep main thread on first listener join
            threading.Event().wait()
        """
    )
    # Fix botched ports list in generated script
    proxy_src = textwrap.dedent(
        f"""\
        #!/usr/bin/env python3
        import select
        import socket
        import sys
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        PORTS = {list(PORTS)!r}

        class H(BaseHTTPRequestHandler):
            timeout = 30

            def log_message(self, fmt, *args):
                sys.stderr.write("%s - %s\\n" % (self.address_string(), fmt % args))

            def do_CONNECT(self):
                host_port = self.path.split(":", 1)
                host = host_port[0]
                port = int(host_port[1]) if len(host_port) > 1 else 443
                try:
                    upstream = socket.create_connection((host, port), timeout=15)
                except OSError as e:
                    self.send_error(502, str(e))
                    return
                self.send_response(200, "Connection Established")
                self.end_headers()
                self.connection.setblocking(False)
                upstream.setblocking(False)
                socks = [self.connection, upstream]
                try:
                    while True:
                        r, _, x = select.select(socks, [], socks, 60)
                        if x or not r:
                            break
                        for s in r:
                            other = upstream if s is self.connection else self.connection
                            data = s.recv(65536)
                            if not data:
                                return
                            other.sendall(data)
                except OSError:
                    pass
                finally:
                    try:
                        upstream.close()
                    except OSError:
                        pass

        def serve(port: int) -> None:
            print("CONNECT proxy listen", port, flush=True)
            ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()

        if __name__ == "__main__":
            threads = []
            for p in PORTS:
                t = threading.Thread(target=serve, args=(p,), daemon=False)
                t.start()
                threads.append(t)
            for t in threads:
                t.join()
        """
    )
    unit = textwrap.dedent(
        f"""\
        [Unit]
        Description=Silent olcrtc HTTP CONNECT proxy (LTE)
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=simple
        ExecStart=/usr/bin/python3 {PROXY_PY}
        Restart=on-failure
        RestartSec=3

        [Install]
        WantedBy=multi-user.target
        """
    )
    client = connect()
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(proxy_src.encode()), "/tmp/connect_proxy.py")
    sftp.putfo(io.BytesIO(unit.encode()), "/tmp/silent-olcrtc-proxy.service")
    sftp.close()
    run(client, f"mv /tmp/connect_proxy.py {PROXY_PY} && chmod 755 {PROXY_PY}")
    run(client, f"mv /tmp/silent-olcrtc-proxy.service {UNIT}")
    run(client, "systemctl daemon-reload")
    for p in PORTS:
        run(client, f"ufw allow {p}/tcp 2>/dev/null || iptables -I INPUT -p tcp --dport {p} -j ACCEPT 2>/dev/null || true")
    run(client, "systemctl restart silent-olcrtc-proxy.service")
    run(client, "sleep 1; systemctl --no-pager -l status silent-olcrtc-proxy.service | head -n 20")
    run(client, "ss -lntp | grep -E '8080|18443' || true")
    client.close()
    print("Done — HTTPS_PROXY=http://132.243.234.162:8080")


if __name__ == "__main__":
    main()
