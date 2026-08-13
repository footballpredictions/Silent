"""Endurance: имитация PC + Android olcrtc2 (WB), лог до смерти peer/SOCKS.

Поднимает 2× olcrtc2-cnc (разные fingerprint/device_type/порты), heartbeat + SOCKS
probe каждые N секунд, пишет лог пока процесс не умрёт или SOCKS не ляжет.

  cd backend
  python scripts/endurance_olcrtc2_clients.py
  python scripts/endurance_olcrtc2_clients.py --provider wbstream --minutes 60
  python scripts/endurance_olcrtc2_clients.py --hb-via-socks   # как LTE: API через SOCKS

Бинарник: pc/resources/olcrtc2-cnc.exe (или OLCRTC2_CNC / --cnc).
Отчёт: scripts/reports/endurance_olcrtc2_<ts>/
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PC_ROOT = BACKEND.parent / "pc"
DEFAULT_CNC = PC_ROOT / "resources" / "olcrtc2-cnc.exe"
DEFAULT_API = os.environ.get("SILENT_API", "https://132-243-234-162.nip.io").rstrip("/")
WB_HOSTS = (
    "stream.wb.ru",
    "rtc-el-01.wb.ru",
    "rtc-el-02.wb.ru",
    "stream-meetup.wildberries.ru",
)
SSL_CTX = ssl._create_unverified_context()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "Z"


def log_line(path: Path, msg: str, also_print: bool = True) -> None:
    line = f"[{utc_now()}] {msg}"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    if also_print:
        print(line, flush=True)


def http_json(
    method: str,
    url: str,
    body: dict | None = None,
    timeout: float = 25.0,
    proxy_url: str | None = None,
) -> tuple[int, dict | list | str]:
    data = None
    headers = {"Accept": "application/json", "User-Agent": "endurance-olcrtc2/1.0"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    handlers: list = []
    if proxy_url:
        handlers.append(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    handlers.append(urllib.request.HTTPSHandler(context=SSL_CTX))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = getattr(resp, "status", 200) or 200
            try:
                return code, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return code, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw) if raw else {"detail": str(e)}
        except json.JSONDecodeError:
            return e.code, raw
    except Exception as e:
        return 0, {"error": str(e)}


def resolve_static_hosts(hosts: tuple[str, ...] = WB_HOSTS) -> dict[str, str]:
    out: dict[str, str] = {}
    for h in hosts:
        try:
            infos = socket.getaddrinfo(h, None, socket.AF_INET, socket.SOCK_STREAM)
            for info in infos:
                ip = info[4][0]
                if ip and not ip.startswith("127."):
                    out[h] = ip
                    break
        except OSError:
            pass
    return out


def format_static_hosts(m: dict[str, str]) -> str:
    return ",".join(f"{k}={v}" for k, v in sorted(m.items()) if v)


def socks5_connect(
    host: str,
    port: int,
    dest_host: str,
    dest_port: int,
    user: str = "",
    password: str = "",
    timeout: float = 8.0,
) -> tuple[bool, str]:
    """RFC1928 + optional RFC1929. Returns (ok, detail)."""
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.settimeout(timeout)
        methods = [0x00]
        if user:
            methods = [0x02, 0x00]
        s.sendall(bytes([0x05, len(methods), *methods]))
        resp = s.recv(2)
        if len(resp) < 2 or resp[0] != 0x05:
            s.close()
            return False, f"bad greeting {resp!r}"
        if resp[1] == 0x02:
            u = user.encode()
            p = password.encode()
            s.sendall(bytes([0x01, len(u)]) + u + bytes([len(p)]) + p)
            auth = s.recv(2)
            if len(auth) < 2 or auth[1] != 0x00:
                s.close()
                return False, f"auth fail {auth!r}"
        elif resp[1] != 0x00:
            s.close()
            return False, f"method rejected {resp[1]}"
        # CONNECT domain
        hb = dest_host.encode()
        req = bytes([0x05, 0x01, 0x00, 0x03, len(hb)]) + hb + struct.pack("!H", dest_port)
        s.sendall(req)
        hdr = s.recv(4)
        if len(hdr) < 4:
            s.close()
            return False, "short connect reply"
        if hdr[1] != 0x00:
            s.close()
            return False, f"connect status={hdr[1]}"
        atyp = hdr[3]
        if atyp == 0x01:
            s.recv(4 + 2)
        elif atyp == 0x03:
            ln = s.recv(1)[0]
            s.recv(ln + 2)
        elif atyp == 0x04:
            s.recv(16 + 2)
        # TLS ClientHello-ish probe to dest (optional): just send nothing, success = dial ok
        s.close()
        return True, "dial ok"
    except Exception as e:
        return False, str(e)


@dataclass
class ClientSpec:
    label: str  # pc | android
    device_type: str
    fingerprint: str
    socks_port: int
    socks_user: str = ""
    socks_pass: str = ""
    room: str = ""
    room_db_id: str = ""
    key: str = ""
    provider: str = "wbstream"
    proc: subprocess.Popen | None = None
    dead: bool = False
    dead_reason: str = ""
    ready: bool = False
    last_socks_ok_at: float = 0.0
    socks_ok: int = 0
    socks_fail: int = 0
    hb_ok: int = 0
    hb_fail: int = 0
    events: list[dict] = field(default_factory=list)


class EnduranceRunner:
    def __init__(
        self,
        *,
        api: str,
        cnc: Path,
        provider: str,
        out_dir: Path,
        probe_sec: float,
        hb_sec: float,
        hb_via_socks: bool,
        minutes: float,
    ) -> None:
        self.api = api.rstrip("/")
        self.cnc = cnc
        self.provider = provider
        self.out_dir = out_dir
        self.probe_sec = probe_sec
        self.hb_sec = hb_sec
        self.hb_via_socks = hb_via_socks
        self.deadline = time.time() + max(1.0, minutes) * 60.0
        self.main_log = out_dir / "endurance.log"
        self._lock = threading.Lock()
        self.clients: list[ClientSpec] = []

    def emit(self, msg: str) -> None:
        log_line(self.main_log, msg)

    def assign(self, c: ClientSpec) -> bool:
        url = (
            f"{self.api}/api/vpn/olcrtc2-config"
            f"?device_type={urllib.parse.quote(c.device_type)}"
            f"&fingerprint={urllib.parse.quote(c.fingerprint)}"
            f"&provider={urllib.parse.quote(self.provider)}"
        )
        code, data = http_json("GET", url, timeout=40)
        self.emit(f"{c.label}: assign HTTP {code}")
        if code != 200 or not isinstance(data, dict):
            self.emit(f"{c.label}: assign fail {data!r}"[:300])
            return False
        prov = data.get("providers") or {}
        slot = prov.get(self.provider) or {}
        room = (slot.get("room") or data.get("room") or "").strip()
        key = (slot.get("crypto_key") or data.get("crypto_key") or "").strip()
        room_db_id = (slot.get("room_db_id") or "").strip()
        if not room or len(key) != 64:
            self.emit(f"{c.label}: bad config room={room!r} key_len={len(key)} denied={data.get('denied')}")
            return False
        c.room = room
        c.key = key
        c.room_db_id = room_db_id
        c.provider = self.provider
        self.emit(f"{c.label}: room={room[:40]} db={room_db_id[:8]}…")
        (self.out_dir / f"{c.label}_config.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True

    def start_cnc(self, c: ClientSpec, static_hosts: dict[str, str]) -> None:
        c.socks_user = f"s{secrets.token_hex(6)}"
        c.socks_pass = secrets.token_urlsafe(18)
        env = os.environ.copy()
        env.update(
            {
                "OLCRTC2_MODE": c.provider,
                "OLCRTC2_ROOM": c.room,
                "OLCRTC2_KEY": c.key,
                "OLCRTC2_SOCKS": f"127.0.0.1:{c.socks_port}",
                "OLCRTC2_SOCKS_USER": c.socks_user,
                "OLCRTC2_SOCKS_PASS": c.socks_pass,
                "OLCRTC2_DNS": "1.1.1.1:53",
            }
        )
        static_env = format_static_hosts(static_hosts)
        if static_env:
            env["OLCRTC_STATIC_HOSTS"] = static_env
        # без CONN_FILE — Go guest сам (как клиенты)
        proc_log = self.out_dir / f"{c.label}_cnc.log"
        self.emit(
            f"{c.label}: start cnc socks=127.0.0.1:{c.socks_port} static_hosts={len(static_hosts)}"
        )
        lf = proc_log.open("a", encoding="utf-8")
        c.proc = subprocess.Popen(
            [str(self.cnc)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(self.out_dir),
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        def pump() -> None:
            assert c.proc and c.proc.stdout
            for line in c.proc.stdout:
                line = line.rstrip("\n\r")
                ts = utc_now()
                lf.write(f"[{ts}] {line}\n")
                lf.flush()
                low = line.lower()
                if "olcrtc2-cnc ready" in low or "socks5 server listening" in low:
                    c.ready = True
                    self.emit(f"{c.label}: READY {line[:120]}")
                interesting = any(
                    x in low
                    for x in (
                        "missed pong",
                        "peer connection state",
                        "ice connection state",
                        "handshake",
                        "error",
                        "fail",
                        "closed",
                        "timeout",
                        "guest access",
                        "ready",
                        "session",
                    )
                )
                if interesting:
                    self.emit(f"{c.label}|cnc: {line[:220]}")
            code = c.proc.wait()
            c.dead = True
            c.dead_reason = f"process_exit:{code}"
            self.emit(f"{c.label}: PROCESS EXIT code={code}")
            lf.close()

        threading.Thread(target=pump, name=f"pump-{c.label}", daemon=True).start()

    def heartbeat(self, c: ClientSpec) -> None:
        if not c.room_db_id:
            return
        body = {
            "room_db_id": c.room_db_id,
            "fingerprint": c.fingerprint,
            "provider": c.provider,
            "device_type": c.device_type,
            "online": True,
        }
        proxy = None
        if self.hb_via_socks and c.ready and not c.dead:
            # socks5h — DNS через proxy (имитация «API через VPN»)
            u = urllib.parse.quote(c.socks_user, safe="")
            p = urllib.parse.quote(c.socks_pass, safe="")
            proxy = f"socks5h://{u}:{p}@127.0.0.1:{c.socks_port}"
        # stdlib не умеет socks без PySocks — при hb_via_socks пробуем requests/httpx
        if proxy:
            try:
                import httpx  # type: ignore

                r = httpx.post(
                    f"{self.api}/api/vpn/olcrtc2-heartbeat",
                    json=body,
                    timeout=15.0,
                    proxy=proxy,
                    verify=False,
                )
                code, data = r.status_code, (r.json() if r.content else {})
            except Exception as e:
                code, data = 0, {"error": f"hb_via_socks: {e}"}
        else:
            code, data = http_json(
                "POST", f"{self.api}/api/vpn/olcrtc2-heartbeat", body=body, timeout=15.0
            )
        if 200 <= code < 300:
            c.hb_ok += 1
            self.emit(f"{c.label}: HB ok ({c.hb_ok}) via={'socks' if proxy else 'direct'}")
        else:
            c.hb_fail += 1
            self.emit(f"{c.label}: HB FAIL #{c.hb_fail} HTTP {code} {str(data)[:120]}")

    def probe_socks(self, c: ClientSpec) -> None:
        if c.dead or not c.ready:
            return
        ok, detail = socks5_connect(
            "127.0.0.1",
            c.socks_port,
            "www.gstatic.com",
            443,
            user=c.socks_user,
            password=c.socks_pass,
            timeout=8.0,
        )
        if ok:
            c.socks_ok += 1
            c.last_socks_ok_at = time.time()
            self.emit(f"{c.label}: SOCKS ok #{c.socks_ok}")
        else:
            c.socks_fail += 1
            self.emit(f"{c.label}: SOCKS FAIL #{c.socks_fail} {detail}")
            # 3 подряд miss после ready → считаем мёртвым
            if c.socks_fail >= 3 and c.socks_ok > 0:
                c.dead = True
                c.dead_reason = f"socks_health_fail:{detail}"
                self.emit(f"{c.label}: MARK DEAD ({c.dead_reason})")
                if c.proc and c.proc.poll() is None:
                    c.proc.terminate()

    def leave(self, c: ClientSpec) -> None:
        if not c.room_db_id:
            return
        http_json(
            "POST",
            f"{self.api}/api/vpn/olcrtc2-heartbeat",
            body={
                "room_db_id": c.room_db_id,
                "fingerprint": c.fingerprint,
                "provider": c.provider,
                "device_type": c.device_type,
                "online": False,
            },
            timeout=10.0,
        )

    def run(self) -> int:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.emit(f"start api={self.api} provider={self.provider} cnc={self.cnc}")
        if not self.cnc.is_file():
            self.emit(f"FATAL: cnc not found: {self.cnc}")
            return 2

        ts = int(time.time())
        self.clients = [
            ClientSpec(
                label="pc",
                device_type="pc",
                fingerprint=f"endurance-pc-{ts}-{secrets.token_hex(4)}",
                socks_port=18808,
            ),
            ClientSpec(
                label="android",
                device_type="android",
                fingerprint=f"endurance-android-{ts}-{secrets.token_hex(4)}",
                socks_port=18809,
            ),
        ]

        static_hosts = resolve_static_hosts()
        self.emit(f"STATIC_HOSTS={len(static_hosts)} {static_hosts}")

        for c in self.clients:
            if not self.assign(c):
                self.emit(f"{c.label}: skip start (no room)")
                c.dead = True
                c.dead_reason = "assign_failed"
                continue
            self.start_cnc(c, static_hosts)

        # wait ready up to 90s
        t0 = time.time()
        while time.time() - t0 < 90:
            if all(c.ready or c.dead for c in self.clients):
                break
            time.sleep(0.5)

        for c in self.clients:
            self.emit(f"{c.label}: ready={c.ready} dead={c.dead}")

        last_probe = 0.0
        last_hb = 0.0
        while time.time() < self.deadline:
            if all(c.dead for c in self.clients):
                self.emit("all clients dead — stop")
                break
            now = time.time()
            if now - last_probe >= self.probe_sec:
                last_probe = now
                for c in self.clients:
                    if not c.dead:
                        self.probe_socks(c)
            if now - last_hb >= self.hb_sec:
                last_hb = now
                for c in self.clients:
                    if not c.dead and c.ready:
                        self.heartbeat(c)
            time.sleep(0.4)

        # cleanup
        for c in self.clients:
            if c.proc and c.proc.poll() is None:
                c.proc.terminate()
                try:
                    c.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    c.proc.kill()
            self.leave(c)

        summary = {
            "finished_at": utc_now(),
            "provider": self.provider,
            "hb_via_socks": self.hb_via_socks,
            "clients": [
                {
                    "label": c.label,
                    "device_type": c.device_type,
                    "fingerprint": c.fingerprint,
                    "room": c.room,
                    "room_db_id": c.room_db_id,
                    "ready": c.ready,
                    "dead": c.dead,
                    "dead_reason": c.dead_reason,
                    "socks_ok": c.socks_ok,
                    "socks_fail": c.socks_fail,
                    "hb_ok": c.hb_ok,
                    "hb_fail": c.hb_fail,
                    "alive_sec": round(c.last_socks_ok_at - t0, 1) if c.last_socks_ok_at else 0,
                }
                for c in self.clients
            ],
        }
        (self.out_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.emit(f"summary → {self.out_dir / 'summary.json'}")
        for c in self.clients:
            self.emit(
                f"RESULT {c.label}: dead={c.dead} reason={c.dead_reason} "
                f"socks={c.socks_ok}/{c.socks_fail} hb={c.hb_ok}/{c.hb_fail}"
            )
        return 0 if any(c.socks_ok > 0 for c in self.clients) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="olcrtc2 PC+Android endurance until death")
    ap.add_argument("--api", default=DEFAULT_API)
    ap.add_argument("--cnc", type=Path, default=Path(os.environ.get("OLCRTC2_CNC", str(DEFAULT_CNC))))
    ap.add_argument("--provider", default="wbstream", choices=("wbstream", "telemost"))
    ap.add_argument("--minutes", type=float, default=45.0)
    ap.add_argument("--probe-sec", type=float, default=15.0)
    ap.add_argument("--hb-sec", type=float, default=30.0)
    ap.add_argument(
        "--hb-via-socks",
        action="store_true",
        help="heartbeat через SOCKS (имитация LTE: API через VPN)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="каталог отчёта (default scripts/reports/endurance_…)",
    )
    args = ap.parse_args()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = args.out or (BACKEND / "scripts" / "reports" / f"endurance_olcrtc2_{stamp}")
    runner = EnduranceRunner(
        api=args.api,
        cnc=args.cnc,
        provider=args.provider,
        out_dir=out,
        probe_sec=args.probe_sec,
        hb_sec=args.hb_sec,
        hb_via_socks=args.hb_via_socks,
        minutes=args.minutes,
    )
    return runner.run()


if __name__ == "__main__":
    raise SystemExit(main())
