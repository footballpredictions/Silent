"""Seed/upgrade olcrtc room pool on prod without rotating crypto_key.

- Сохраняет существующий crypto_key (если есть и валидный)
- Jitsi / WB Stream / Telemost: слоты pc + android (разные room id)
- Пишет server.yaml + server-pc.yaml + server-android.yaml
- Restart olcrtc@pc и olcrtc@android

Использование:
  cd backend
  python scripts/configure_olcrtc_prod.py
"""
from __future__ import annotations

import io
import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _deploy_common import BACKEND_ROOT, connect, run  # noqa: E402

JITSI_PC = "https://meet.egovm.ru/SilentVpnOlcrtcHive"
JITSI_ANDROID = "https://meet.playform.ru/SilentVpnOlcrtcHiveAndroid"

# PC / Android — разные комнаты. Android WB: REPLACE до свежего ID с stream.wb.ru
WB_PC = "019e23c2-a580-7550-b08a-7ac5342ca21f"
WB_ANDROID = "019e23c2-a580-7550-b08a-ANDROID-REPLACE"
TELEMOST_PC = "02789996238784"
TELEMOST_ANDROID = "02789996238785"

REMOTE_OLCRTC = "/opt/silent-vpn/olcrtc"


def _srv_yaml(
    key: str,
    *,
    slot: str,
    jitsi_url: str,
    wb_room: str,
    telemost_room: str,
) -> str:
    data_dir = f"data-{slot}"
    lines = [
        "mode: srv",
        "crypto:",
        f'  key: "{key}"',
        "net:",
        '  dns: "8.8.8.8:53"',
        f"data: {data_dir}",
        "profiles:",
        f"  - name: jitsi-{slot}",
        "    auth:",
        "      provider: jitsi",
        "    room:",
        f'      id: "{jitsi_url}"',
        "    net:",
        "      transport: datachannel",
        '      dns: "8.8.8.8:53"',
        f"  - name: wbstream-{slot}",
        "    auth:",
        "      provider: wbstream",
        "    room:",
        f'      id: "{wb_room}"',
        "    net:",
        "      transport: vp8channel",
        '      dns: "8.8.8.8:53"',
        f"  - name: telemost-{slot}",
        "    auth:",
        "      provider: telemost",
        "    room:",
        f'      id: "{telemost_room}"',
        "    net:",
        "      transport: vp8channel",
        '      dns: "8.8.8.8:53"',
        "failover:",
        "  retry_delay: 2s",
        "  max_cycles: 0",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    client = connect()

    read_py = r"""
import json, asyncio
from sqlalchemy import text
from app.database import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as db:
        r = await db.execute(text("SELECT value FROM app_settings WHERE key='olcrtc_settings'"))
        row = r.fetchone()
        if not row:
            print("NONE")
            return
        try:
            d = json.loads(row[0])
            k = (d.get("crypto_key") or "").strip()
            print(k if len(k) == 64 else "NONE")
        except Exception:
            print("NONE")

asyncio.run(main())
"""
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(read_py.encode()), "/tmp/read_olcrtc_key.py")
    run(client, "docker cp /tmp/read_olcrtc_key.py backend-api-1:/tmp/read_olcrtc_key.py")
    key_out = run(
        client,
        "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/read_olcrtc_key.py",
    )
    key = ""
    for line in key_out.splitlines():
        t = line.strip()
        if len(t) == 64 and all(c in "0123456789abcdef" for c in t.lower()):
            key = t
            break
    if not key:
        key = secrets.token_hex(32)
        print("generated new crypto_key")
    else:
        print("reuse crypto_key from DB")

    settings = {
        "enabled": True,
        "crypto_key": key,
        "providers": {
            "jitsi": {
                "enabled": True,
                "room": JITSI_PC,
                "transport": "datachannel",
                "rooms": [
                    {
                        "id": "pc",
                        "url": JITSI_PC,
                        "max_clients": 4,
                        "device_types": ["pc"],
                    },
                    {
                        "id": "android",
                        "url": JITSI_ANDROID,
                        "max_clients": 4,
                        "device_types": ["android"],
                    },
                ],
            },
            "wbstream": {
                "enabled": True,
                "room": WB_PC,
                "transport": "vp8channel",
                "rooms": [
                    {
                        "id": "pc",
                        "url": WB_PC,
                        "max_clients": 4,
                        "device_types": ["pc"],
                    },
                    {
                        "id": "android",
                        "url": WB_ANDROID,
                        "max_clients": 4,
                        "device_types": ["android"],
                    },
                ],
            },
            "telemost": {
                "enabled": True,
                "room": TELEMOST_PC,
                "transport": "vp8channel",
                "rooms": [
                    {
                        "id": "pc",
                        "url": TELEMOST_PC,
                        "max_clients": 4,
                        "device_types": ["pc"],
                    },
                    {
                        "id": "android",
                        "url": TELEMOST_ANDROID,
                        "max_clients": 4,
                        "device_types": ["android"],
                    },
                ],
            },
        },
        "srv_status": "active",
        "srv_message": "room pool (jitsi+wb+telemost pc/android) seeded by configure_olcrtc_prod.py",
    }
    payload_json = json.dumps(settings, ensure_ascii=False)

    yaml_pc = _srv_yaml(
        key,
        slot="pc",
        jitsi_url=JITSI_PC,
        wb_room=WB_PC,
        telemost_room=TELEMOST_PC,
    )
    yaml_android = _srv_yaml(
        key,
        slot="android",
        jitsi_url=JITSI_ANDROID,
        wb_room=WB_ANDROID,
        telemost_room=TELEMOST_ANDROID,
    )

    local_dir = BACKEND_ROOT / "update" / "olcrtc"
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / "server.yaml").write_text(yaml_pc, encoding="utf-8")
    (local_dir / "server-pc.yaml").write_text(yaml_pc, encoding="utf-8")
    (local_dir / "server-android.yaml").write_text(yaml_android, encoding="utf-8")
    print("wrote", local_dir / "server-pc.yaml", "and server-android.yaml")

    seed_py = f"""
import json, asyncio
from sqlalchemy import text
from app.database import AsyncSessionLocal

SETTINGS = {payload_json!r}

async def main():
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO app_settings (key, value) VALUES (:k, :v) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            ),
            {{"k": "olcrtc_settings", "v": SETTINGS}},
        )
        await db.commit()
        print("db_ok")

asyncio.run(main())
"""
    sftp.putfo(io.BytesIO(seed_py.encode()), "/tmp/seed_olcrtc.py")
    run(client, f"mkdir -p {REMOTE_OLCRTC}/data-pc {REMOTE_OLCRTC}/data-android {REMOTE_OLCRTC}/data")
    sftp.put(str(local_dir / "server.yaml"), f"{REMOTE_OLCRTC}/server.yaml")
    sftp.put(str(local_dir / "server-pc.yaml"), f"{REMOTE_OLCRTC}/server-pc.yaml")
    sftp.put(str(local_dir / "server-android.yaml"), f"{REMOTE_OLCRTC}/server-android.yaml")
    sftp.close()

    run(client, "docker cp /tmp/seed_olcrtc.py backend-api-1:/tmp/seed_olcrtc.py")
    run(
        client,
        "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/seed_olcrtc.py",
    )
    run(client, f"chmod 600 {REMOTE_OLCRTC}/server*.yaml")

    template = f"""[Unit]
Description=Silent VPN olcrtc srv (%i)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={REMOTE_OLCRTC}
ExecStart={REMOTE_OLCRTC}/olcrtc {REMOTE_OLCRTC}/server-%i.yaml
Restart=on-failure
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
"""
    sftp2 = client.open_sftp()
    sftp2.putfo(io.BytesIO(template.encode()), "/tmp/olcrtc@.service")
    sftp2.close()
    run(client, "mv /tmp/olcrtc@.service /etc/systemd/system/olcrtc@.service")
    run(client, "systemctl daemon-reload")
    run(client, "systemctl disable --now olcrtc.service 2>/dev/null || true")
    for slot in ("pc", "android"):
        run(client, f"systemctl enable olcrtc@{slot}.service")
        run(client, f"systemctl restart olcrtc@{slot}.service")
        run(client, f"sleep 1; systemctl --no-pager -l status olcrtc@{slot}.service | head -n 20")

    run(client, "docker compose -f /opt/silent-vpn/backend/docker-compose.yml restart api >/dev/null")
    run(client, "sleep 10")
    run(
        client,
        'curl -s "http://127.0.0.1:8000/api/vpn/olcrtc-config?device_type=pc" | head -c 600; echo',
    )
    run(
        client,
        'curl -s "http://127.0.0.1:8000/api/vpn/olcrtc-config?device_type=android" | head -c 600; echo',
    )
    client.close()
    print(
        "Done — pool jitsi/wb/telemost: pc + android; "
        "replace WB_ANDROID placeholder before LTE test"
    )


if __name__ == "__main__":
    main()
