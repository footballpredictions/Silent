"""Имитация N пользователей olcrtc2 (Telemost + WB): assign → отчёт.

Проверяет, хватает ли warm-пула и успевает ли агент создавать комнаты,
чтобы не повторить кейс «2–3 подключились — остальным нет места».

  cd backend
  python scripts/loadtest_olcrtc2_sessions.py
  python scripts/loadtest_olcrtc2_sessions.py 20
  python scripts/loadtest_olcrtc2_sessions.py 50 --concurrency 10
  python scripts/loadtest_olcrtc2_sessions.py 30 --no-cleanup

Не поднимает реальный WebRTC на телефонах — бьёт /api/vpn/olcrtc2-config
и проверяет unit’ы на сотах (MODE / active / Link).
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import BACKEND_ROOT, connect, run  # noqa: E402


INNER = r'''
import asyncio
import json
import sys
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone

import httpx
from sqlalchemy import delete, func, select

from app.database import AsyncSessionLocal
from app.models.olcrtc2_room import Olcrtc2Room, Olcrtc2Sticky
from app.services.olcrtc2_assign import ensure_warm_pool, pool_stats, release_session_room
from app.services.olcrtc2_cell_units import probe_olcrtc2_unit
from app.services.olcrtc2_settings import enabled_providers, load_olcrtc2_settings

N = int(sys.argv[1])
CONCURRENCY = max(1, int(sys.argv[2]))
CLEANUP = sys.argv[3] != "0"
PREFIX = sys.argv[4]
DEVICE = sys.argv[5]  # android|pc|both
PROVIDERS_ARG = sys.argv[6]  # telemost,wbstream|all
SKIP_PRE_WARM = sys.argv[7] == "1" if len(sys.argv) > 7 else False

BASE = "http://127.0.0.1:8000/api/vpn/olcrtc2-config"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


async def snapshot(db):
    settings = await load_olcrtc2_settings(db)
    stats = await pool_stats(db)
    rooms = (await db.execute(select(Olcrtc2Room))).scalars().all()
    by = defaultdict(lambda: {"total": 0, "active": 0, "free": 0, "online": 0, "units": []})
    for r in rooms:
        key = f"{r.provider}:{r.device_type}"
        by[key]["total"] += 1
        if r.status == "active":
            by[key]["active"] += 1
        stickies = int(
            (
                await db.execute(
                    select(func.count()).select_from(Olcrtc2Sticky).where(Olcrtc2Sticky.room_id == r.id)
                )
            ).scalar()
            or 0
        )
        by[key]["online"] += stickies
        if r.status == "active" and stickies == 0:
            by[key]["free"] += 1
        by[key]["units"].append({
            "unit": r.unit_name,
            "status": r.status,
            "room": (r.room_url or "")[:40],
            "stickies": stickies,
            "max": r.max_clients,
            "tok": bool((r.auth_token or "").startswith("eyJ")),
        })
    return {
        "ts": _now_iso(),
        "settings": {
            "enabled": bool(settings.get("enabled")),
            "agent_enabled": bool(settings.get("agent_enabled")),
            "warm_pool_per_dt": int(settings.get("warm_pool_per_dt") or 3),
            "providers_enabled": enabled_providers(settings),
            "cells": settings.get("cells") or {},
            "cell_ip": settings.get("cell_ip"),
        },
        "pool_stats": stats,
        "by_key": dict(by),
    }


async def assign_one(client, sem, fp, device_type, provider):
    url = (
        f"{BASE}?device_type={device_type}&fingerprint={fp}"
        f"&provider={provider}"
    )
    t0 = time.perf_counter()
    async with sem:
        try:
            resp = await client.get(url, timeout=120.0)
            body = resp.json() if resp.content else {}
            ms = round((time.perf_counter() - t0) * 1000)
            denied = bool(body.get("pool_denied") or body.get("denied"))
            prov_entry = (body.get("providers") or {}).get(provider) or {}
            room = (
                prov_entry.get("room")
                or body.get("room")
                or body.get("room_url")
                or ""
            )
            unit = (
                body.get("assigned_slot")
                or prov_entry.get("room_slot_id")
                or body.get("unit_name")
                or ""
            )
            room_db_id = (
                prov_entry.get("room_db_id")
                or body.get("room_db_id")
                or ""
            )
            detail = (
                body.get("pool_denied_detail")
                or body.get("detail")
                or body.get("message")
                or ""
            )[:200]
            ok = resp.status_code < 400 and not denied and bool(room)
            return {
                "fp": fp,
                "device_type": device_type,
                "provider": provider,
                "ok": ok,
                "denied": denied,
                "http": resp.status_code,
                "ms": ms,
                "room": str(room)[:48],
                "unit": unit,
                "room_db_id": room_db_id,
                "detail": detail,
            }
        except Exception as e:
            ms = round((time.perf_counter() - t0) * 1000)
            return {
                "fp": fp,
                "device_type": device_type,
                "provider": provider,
                "ok": False,
                "denied": True,
                "http": 0,
                "ms": ms,
                "room": "",
                "unit": "",
                "room_db_id": "",
                "detail": str(e)[:200],
            }


async def probe_units(db, room_ids):
    out = []
    for rid in room_ids:
        try:
            uid = uuid.UUID(rid)
        except Exception:
            continue
        row = await db.get(Olcrtc2Room, uid)
        if not row:
            out.append({"room_db_id": rid, "missing": True})
            continue
        probe = await probe_olcrtc2_unit(db, row)
        out.append({
            "room_db_id": rid,
            "provider": row.provider,
            "unit": row.unit_name,
            "status": row.status,
            "room": (row.room_url or "")[:40],
            "probe_active": probe.get("active"),
            "probe_ok": probe.get("ok"),
            "probe_state": probe.get("state") or probe.get("message"),
            "has_env": probe.get("has_env"),
        })
    return out


async def cleanup(db, prefix):
    stickies = (
        await db.execute(
            select(Olcrtc2Sticky).where(Olcrtc2Sticky.fingerprint.like(f"{prefix}%"))
        )
    ).scalars().all()
    room_ids = {s.room_id for s in stickies}
    released = 0
    for s in stickies:
        await release_session_room(
            db,
            fingerprint=s.fingerprint,
            provider=s.provider,
            reason="loadtest_cleanup",
        )
        released += 1
    # release_session_room may tear rooms in session-mode; count leftover test stickies
    left = (
        await db.execute(
            select(func.count()).select_from(Olcrtc2Sticky).where(
                Olcrtc2Sticky.fingerprint.like(f"{prefix}%")
            )
        )
    ).scalar() or 0
    return {"released": released, "rooms_touched": len(room_ids), "stickies_left": int(left)}


async def main():
    report = {
        "started_at": _now_iso(),
        "n_per_combo": N,
        "concurrency": CONCURRENCY,
        "cleanup": CLEANUP,
        "prefix": PREFIX,
        "device": DEVICE,
        "providers_arg": PROVIDERS_ARG,
    }

    async with AsyncSessionLocal() as db:
        before = await snapshot(db)
        report["before"] = before
        print("BEFORE", json.dumps({
            "warm_pool_per_dt": before["settings"]["warm_pool_per_dt"],
            "providers": before["settings"]["providers_enabled"],
            "cells": before["settings"]["cells"],
            "by_key": {k: {kk: vv for kk, vv in v.items() if kk != "units"} for k, v in before["by_key"].items()},
            "pool_stats": before["pool_stats"],
        }, ensure_ascii=False))

        # Pre-warm so report shows agent capability
        if SKIP_PRE_WARM:
            warm = {"ok": True, "skipped": True}
            report["pre_warm"] = warm
            print("PRE_WARM", json.dumps(warm, ensure_ascii=False))
            after_warm = before
        else:
            warm = await ensure_warm_pool(db)
            report["pre_warm"] = warm
            print("PRE_WARM", json.dumps(warm, ensure_ascii=False, default=str))
            after_warm = await snapshot(db)
        report["after_warm"] = {
            "by_key": {k: {kk: vv for kk, vv in v.items() if kk != "units"} for k, v in after_warm["by_key"].items()},
            "pool_stats": after_warm["pool_stats"],
        }
        print("AFTER_WARM", json.dumps(report["after_warm"], ensure_ascii=False))

        providers = before["settings"]["providers_enabled"]
        if PROVIDERS_ARG != "all":
            want = [p.strip() for p in PROVIDERS_ARG.split(",") if p.strip()]
            providers = [p for p in providers if p in want]
        dts = ["android", "pc"] if DEVICE == "both" else [DEVICE if DEVICE in ("android", "pc") else "android"]

        jobs = []
        for prov in providers:
            for dt in dts:
                for i in range(N):
                    fp = f"{PREFIX}{prov[:2]}-{dt[:2]}-{i:04d}"
                    jobs.append((fp, dt, prov))

        sem = asyncio.Semaphore(CONCURRENCY)
        t0 = time.perf_counter()
        async with httpx.AsyncClient() as client:
            results = await asyncio.gather(
                *[assign_one(client, sem, fp, dt, prov) for fp, dt, prov in jobs]
            )
        elapsed = round(time.perf_counter() - t0, 2)
        report["assign_elapsed_sec"] = elapsed
        report["results"] = results

        # Summary per provider
        summary = {}
        for prov in providers:
            rows = [r for r in results if r["provider"] == prov]
            ok = [r for r in rows if r["ok"]]
            denied = [r for r in rows if not r["ok"]]
            rooms = Counter(r["room"] for r in ok if r["room"])
            units = Counter(r["unit"] for r in ok if r["unit"])
            ms_list = sorted(r["ms"] for r in rows)
            def pct(p):
                if not ms_list:
                    return None
                idx = min(len(ms_list) - 1, int(round((p / 100) * (len(ms_list) - 1))))
                return ms_list[idx]
            summary[prov] = {
                "total": len(rows),
                "ok": len(ok),
                "denied": len(denied),
                "unique_rooms": len(rooms),
                "unique_units": len(units),
                "shared_room_max": max(rooms.values()) if rooms else 0,
                "ms_p50": pct(50),
                "ms_p95": pct(95),
                "ms_max": ms_list[-1] if ms_list else None,
                "deny_samples": [
                    {"fp": d["fp"], "detail": d["detail"], "ms": d["ms"]} for d in denied[:8]
                ],
            }
            # session-mode expects unique rooms ~= ok (max_clients=1)
            summary[prov]["capacity_ok"] = (
                len(denied) == 0
                and len(rooms) == len(ok)
                and (max(rooms.values()) if rooms else 0) <= 1
            )
        report["summary"] = summary
        print("SUMMARY", json.dumps(summary, ensure_ascii=False))
        print("ELAPSED_SEC", elapsed)

        room_ids = [r["room_db_id"] for r in results if r.get("room_db_id")]
        probes = await probe_units(db, list(dict.fromkeys(room_ids))[:40])
        report["probes_sample"] = probes
        active_n = sum(1 for p in probes if p.get("probe_active"))
        print("PROBES", json.dumps({
            "sampled": len(probes),
            "active": active_n,
            "inactive": len(probes) - active_n,
            "bad": [p for p in probes if not p.get("probe_active")][:10],
        }, ensure_ascii=False, default=str))

        mid = await snapshot(db)
        report["during"] = {
            "by_key": {k: {kk: vv for kk, vv in v.items() if kk != "units"} for k, v in mid["by_key"].items()},
            "pool_stats": mid["pool_stats"],
        }
        print("DURING", json.dumps(report["during"], ensure_ascii=False))

        cleanup_info = None
        if CLEANUP:
            cleanup_info = await cleanup(db, PREFIX)
            report["cleanup"] = cleanup_info
            print("CLEANUP", json.dumps(cleanup_info, ensure_ascii=False))
            if SKIP_PRE_WARM:
                report["post_cleanup_warm"] = {"ok": True, "skipped": True}
                print("POST_WARM", '{"ok": true, "skipped": true}')
            else:
                refill = await ensure_warm_pool(db)
                report["post_cleanup_warm"] = refill
                print("POST_WARM", json.dumps(refill, ensure_ascii=False, default=str))

        after = await snapshot(db)
        report["after"] = {
            "by_key": {k: {kk: vv for kk, vv in v.items() if kk != "units"} for k, v in after["by_key"].items()},
            "pool_stats": after["pool_stats"],
        }
        print("AFTER", json.dumps(report["after"], ensure_ascii=False))

    # Verdict
    verdict = {"pass": True, "reasons": []}
    warm_target = int(before["settings"]["warm_pool_per_dt"] or 3)
    if warm_target < max(5, N // 2):
        verdict["reasons"].append(
            f"warm_pool_per_dt={warm_target} слишком мал для всплеска {N} "
            f"(рекомендация ≥{max(5, min(25, N))} на dt; сейчас on-demand + global create lock)"
        )
    for prov, s in summary.items():
        if s["denied"]:
            verdict["pass"] = False
            verdict["reasons"].append(f"{prov}: denied={s['denied']}/{s['total']}")
        if s["ok"] and s["unique_rooms"] < s["ok"]:
            verdict["pass"] = False
            verdict["reasons"].append(
                f"{prov}: unique_rooms={s['unique_rooms']} < ok={s['ok']} (коллизия слотов)"
            )
        if s.get("shared_room_max", 0) > 1:
            verdict["pass"] = False
            verdict["reasons"].append(f"{prov}: одна комната на {s['shared_room_max']} fp (max_clients нарушен)")
    report["verdict"] = verdict
    report["finished_at"] = _now_iso()
    print("VERDICT", json.dumps(verdict, ensure_ascii=False))
    print("REPORT_JSON_BEGIN")
    print(json.dumps(report, ensure_ascii=False, default=str))
    print("REPORT_JSON_END")

asyncio.run(main())
'''


def main() -> None:
    ap = argparse.ArgumentParser(description="Loadtest olcrtc2 session assign (Telemost+WB)")
    ap.add_argument("n", nargs="?", type=int, default=20, help="users per provider×device (default 20)")
    ap.add_argument("--concurrency", type=int, default=8, help="parallel assigns (default 8)")
    ap.add_argument("--no-cleanup", action="store_true", help="keep test stickies/rooms")
    ap.add_argument("--device", default="android", choices=("android", "pc", "both"))
    ap.add_argument("--providers", default="all", help="all | telemost,wbstream")
    ap.add_argument("--prefix", default=None, help="fingerprint prefix")
    ap.add_argument("--skip-pre-warm", action="store_true", help="do not fill warm pool before assign")
    args = ap.parse_args()

    n = max(1, min(80, int(args.n)))
    concurrency = max(1, min(40, int(args.concurrency)))
    cleanup = "0" if args.no_cleanup else "1"
    prefix = args.prefix or f"lt2-{datetime.now(timezone.utc).strftime('%H%M%S')}-"
    device = args.device
    providers = args.providers
    skip_warm = "1" if args.skip_pre_warm else "0"

    print(f"=== loadtest_olcrtc2_sessions n={n} concurrency={concurrency} device={device} providers={providers} skip_pre_warm={skip_warm} ===")

    queen = connect()
    sftp = queen.open_sftp()
    remote_py = "/tmp/loadtest_olcrtc2_sessions_inner.py"
    sftp.putfo(io.BytesIO(INNER.encode("utf-8")), remote_py)
    sftp.close()
    run(queen, f"docker cp {remote_py} backend-api-1:{remote_py}")

    cmd = (
        f"docker exec -e PYTHONPATH=/app -w /app backend-api-1 "
        f"python {remote_py} {n} {concurrency} {cleanup} {prefix} {device} {providers} {skip_warm}"
    )
    # Telemost Playwright create can be slow under load
    timeout = 60 + n * concurrency * 8
    raw = run(queen, cmd, timeout=timeout)
    print(raw)

    # Save report locally
    if "REPORT_JSON_BEGIN" in raw and "REPORT_JSON_END" in raw:
        chunk = raw.split("REPORT_JSON_BEGIN", 1)[1].split("REPORT_JSON_END", 1)[0].strip()
        out_dir = BACKEND_ROOT / "scripts" / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = out_dir / f"olcrtc2_loadtest_{stamp}.json"
        path.write_text(chunk, encoding="utf-8")
        print(f"REPORT_FILE {path}")
        try:
            data = json.loads(chunk)
            v = data.get("verdict") or {}
            print("=== SHORT REPORT ===")
            print(json.dumps({
                "n_per_combo": data.get("n_per_combo"),
                "elapsed_sec": data.get("assign_elapsed_sec"),
                "pre_warm": data.get("pre_warm"),
                "summary": data.get("summary"),
                "verdict": v,
                "before_warm_target": (data.get("before") or {}).get("settings", {}).get("warm_pool_per_dt"),
            }, ensure_ascii=False, indent=2))
        except Exception as e:
            print("report parse warn:", e)
    run(queen, f"rm -f {remote_py}; docker exec backend-api-1 rm -f {remote_py}")
    queen.close()


if __name__ == "__main__":
    main()
