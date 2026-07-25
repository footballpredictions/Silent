"""Готовность LTE-пути: Android Telemost + WB rooms (не Jitsi).

Проверяет/чинит на проде:
  - android-telemost unit active + room в БД
  - android-wbstream: если есть storage_state — создать комнату; иначе отчёт «нужен cookie»
  - GET olcrtc-config?device_type=android для telemost/wbstream

  cd backend
  python scripts/prepare_olcrtc_lte_rooms.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

REMOTE = r"""
import asyncio
import json
import urllib.request

from app.database import AsyncSessionLocal
from app.services.olcrtc_rooms_db import list_rooms, pool_metrics
from app.services.olcrtc_room_accounts import load_room_accounts, resolve_storage_state
from ai.olcrtc_room_agent import heal_rooms, load_agent_state


async def main():
    async with AsyncSessionLocal() as db:
        state = await load_agent_state(db)
        accounts = await load_room_accounts(db)
        tm_ok = any(resolve_storage_state(a) for a in accounts.telemost)
        wb_ok = any(resolve_storage_state(a) for a in accounts.wbstream)
        print("ACCOUNTS", json.dumps({
            "telemost_storage": tm_ok,
            "wbstream_storage": wb_ok,
            "agent_enabled": state.enabled,
        }))
        # force heal — создаст WB/Telemost если cookies есть
        if tm_ok or wb_ok:
            st = await heal_rooms(db, force=True)
            print("HEAL", st.last_error or st.last_ok or "ok", "log_tail", (st.run_log or [])[-5:])
        rooms = await list_rooms(db, status="active")
        by = {}
        for r in rooms:
            if r.provider in ("telemost", "wbstream") and (
                r.slot_label == "android" or "android" in (r.device_types or [])
            ):
                by.setdefault(r.provider, []).append({
                    "unit": r.unit_name,
                    "room": r.room_url[:64],
                    "max": r.max_clients,
                })
        print("ANDROID_LTE_ROOMS", json.dumps(by, ensure_ascii=False))
        m = await pool_metrics(db)
        print("METRICS_TM_WB", json.dumps({
            "telemost": m.get("by_provider", {}).get("telemost"),
            "wbstream": m.get("by_provider", {}).get("wbstream"),
        }, ensure_ascii=False))

    d = json.load(urllib.request.urlopen(
        "http://127.0.0.1:8000/api/vpn/olcrtc-config?device_type=android&fingerprint=lte-prep",
        timeout=15,
    ))
    prov = d.get("providers") or {}
    print("CONFIG_ANDROID", json.dumps({
        "pool_denied": d.get("pool_denied"),
        "telemost": {
            "enabled": prov.get("telemost", {}).get("enabled"),
            "room": (prov.get("telemost", {}) or {}).get("room"),
            "denied": prov.get("telemost", {}).get("denied"),
        },
        "wbstream": {
            "enabled": prov.get("wbstream", {}).get("enabled"),
            "room": (prov.get("wbstream", {}) or {}).get("room"),
            "denied": prov.get("wbstream", {}).get("denied"),
        },
        "jitsi_room": (prov.get("jitsi", {}) or {}).get("room"),
    }, ensure_ascii=False))
    tm = prov.get("telemost") or {}
    ready = bool(tm.get("enabled") and tm.get("room") and not tm.get("denied"))
    print("LTE_PATH_READY", json.dumps({"telemost_android_ok": ready, "note": "физический LTE-прогон — на устройстве"}))
    if not ready:
        raise SystemExit(1)


asyncio.run(main())
"""


def main() -> None:
    client = connect()
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(REMOTE.encode()), "/tmp/prepare_olcrtc_lte.py")
    run(client, "docker cp /tmp/prepare_olcrtc_lte.py backend-api-1:/tmp/prepare_olcrtc_lte.py")
    out = run(
        client,
        "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/prepare_olcrtc_lte.py",
        timeout=300,
    )
    print(out)
    print(run(client, "systemctl is-active olcrtc@android-telemost.service olcrtc@pc-telemost.service 2>&1 || true"))
    # если heal создал yaml — подтянуть unit'ы
    if "android-wbstream" in out or "created" in out.lower() or "HEAL" in out:
        print("re-apply units if new rooms…")
        from apply_olcrtc_units_from_db import main as apply_main

        apply_main()
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
