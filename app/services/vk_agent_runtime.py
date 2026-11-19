"""Independent controls and observed activity for the two VK workers."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func, or_
from app.models import AppSetting, VkHash

ROLES = ("issuer", "checker")


def now_utc():
    return datetime.now(timezone.utc)


def timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace(" UTC", "+00:00").replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


async def settings_snapshot(db):
    keys = ["vk_agent_enabled", "vk_issuer_enabled", "vk_checker_enabled",
            "vk_runtime_issuer", "vk_runtime_checker", "vk_agent_flood_until",
            "vk_hash_probe_until", "vk_agent_last_run", "vk_agent_last_message",
            "vk_hash_probe_last", "vk_hash_probe_last_message", "vk_agent_calls_ok"]
    keys += ["vk_hash_probe_interval_seconds", "vk_hash_probe_limit_stage"]
    return dict((await db.execute(select(AppSetting.key, AppSetting.value).where(AppSetting.key.in_(keys)))).all())


def enabled_from(values, role):
    return values.get(f"vk_{role}_enabled", values.get("vk_agent_enabled", "false")) == "true"


async def role_enabled(db, role):
    if role not in ROLES:
        raise ValueError("Unknown VK agent")
    return enabled_from(await settings_snapshot(db), role)


async def set_enabled(db, role, enabled):
    if role is not None and role not in ROLES:
        raise ValueError("Unknown VK agent")
    keys = ["vk_agent_enabled", "vk_issuer_enabled", "vk_checker_enabled"]
    rows = {row.key: row for row in (await db.execute(
        select(AppSetting).where(AppSetting.key.in_(keys)).with_for_update())).scalars().all()}
    old = {key: row.value for key, row in rows.items()}
    controls = {r: enabled_from(old, r) for r in ROLES}
    if role is None:
        controls = {r: enabled for r in ROLES}
    else:
        controls[role] = enabled
    values = {f"vk_{r}_enabled": str(value).lower() for r, value in controls.items()}
    values["vk_agent_enabled"] = str(any(controls.values())).lower()
    for key, value in values.items():
        if key in rows:
            rows[key].value = value
        else:
            db.add(AppSetting(key=key, value=value))
    await db.commit()
    return controls


async def record_activity(db, role, **fields):
    key = f"vk_runtime_{role}"
    row = await db.get(AppSetting, key)
    try:
        runtime = json.loads(row.value) if row else {}
    except (ValueError, TypeError):
        runtime = {}
    if not isinstance(runtime, dict):
        runtime = {}
    runtime.update(fields)
    runtime["observed_at"] = now_utc().isoformat()
    value = json.dumps(runtime, ensure_ascii=False)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    await db.commit()


async def record_probe_progress(db, *, attempted, budget, successful, outcome):
    row = await db.get(AppSetting, "vk_runtime_checker")
    previous = json.loads(row.value) if row else {}
    totals = dict(previous.get("totals") or {})
    totals.setdefault("since", now_utc().isoformat())
    increments = {"attempted": 1, "successful": int(outcome in ("alive", "pending", "deactivated")),
                  "limited": int(outcome == "flood"), "confirmed_dead": int(outcome == "deactivated"),
                  "skipped": int(outcome not in ("alive", "pending", "deactivated", "flood")),
                  "batches": int(attempted == 1)}
    for key, value in increments.items():
        totals[key] = int(totals.get(key) or 0) + value
    fields = {"state": "running", "counters_live": True, "totals": totals,
              "progress": {"attempted": attempted, "budget": budget, "successful": successful}}
    if increments["successful"]:
        fields["last_successful_at"] = now_utc().isoformat()
    await record_activity(db, "checker", **fields)


async def agents_status(db):
    values = await settings_snapshot(db)
    now = now_utc()
    agents = {}
    for role in ROLES:
        try:
            runtime = json.loads(values.get(f"vk_runtime_{role}", "{}"))
        except (ValueError, TypeError):
            runtime = {}
        if not isinstance(runtime, dict):
            runtime = {}
        enabled = enabled_from(values, role)
        until = timestamp(values.get("vk_hash_probe_until" if role == "checker" else "vk_agent_flood_until"))
        observed = timestamp(runtime.get("observed_at"))
        fresh = observed is not None and (now - observed).total_seconds() < (360 if role == "checker" else 180)
        running = runtime.get("state") == "running" and fresh
        state = "waiting"
        if not enabled:
            state = "stopping" if running else "disabled"
        elif until and until > now:
            state = "cooldown"
        elif not observed:
            state = "unknown"
        elif not fresh:
            state = "stale"
        elif runtime.get("state") == "error":
            state = "error"
        elif running:
            state = "running"
        fallback_last = values.get("vk_hash_probe_last" if role == "checker" else "vk_agent_last_run")
        fallback_msg = values.get("vk_hash_probe_last_message" if role == "checker" else "vk_agent_last_message")
        agents[role] = {**runtime, "enabled": enabled, "state": state,
                        "pause_until": until.isoformat() if until and until > now else None,
                        "last_completed_at": runtime.get("last_completed_at") or fallback_last,
                        "last_message": runtime.get("last_message") or fallback_msg}
        created = re.search(r"(?:Готово:|Очередь мёртвых хешей:)\s*\+(\d+)", agents[role].get("last_message") or "")
        agents[role]["last_created"] = int(created.group(1)) if created else None
    active, pending, dead = (await db.execute(select(
        func.count(VkHash.id).filter(VkHash.is_active == True),  # noqa: E712
        func.count(VkHash.id).filter(VkHash.is_active == True, VkHash.last_error_code == 2),  # noqa: E712
        func.count(VkHash.id).filter(or_(VkHash.is_active == False, VkHash.last_error_code == 1)),  # noqa: E712
    ).where(VkHash.user_id.isnot(None)))).one()
    return {"server_time": now.isoformat(), "agents": agents,
            "counts": {"active": active, "pending": pending, "dead": dead},
            "calls_ready": values.get("vk_agent_calls_ok") == "true"}


async def run_once(role):
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        if role == "checker":
            from ai.vk_hash_monitor import run_probe_cycle
            await run_probe_cycle(db)
        else:
            from ai.tunnel_monitor import run_heal_cycle
            await run_heal_cycle(db, full_fill=True)


async def tracked_cycle(db, role, operation, *, delay):
    from ai.vk_agent_lock import agent_lease
    async with agent_lease(f"runtime_{role}") as acquired:
        if not acquired:
            return None
        if not await role_enabled(db, role):
            await record_activity(db, role, state="disabled")
            return None
        values = await settings_snapshot(db)
        until = timestamp(values.get("vk_hash_probe_until" if role == "checker" else "vk_agent_flood_until"))
        if until and until > now_utc():
            await record_activity(db, role, state="waiting", next_run_at=until.isoformat())
            return None
        await record_activity(db, role, state="running", started_at=now_utc().isoformat(), counters_live=False)
        try:
            result = await operation()
        except Exception:
            await record_activity(db, role, state="error",
                                  last_message="Цикл не завершён. Агент повторит попытку автоматически.",
                                  next_run_at=(now_utc()+timedelta(seconds=60 if role == "checker" else delay)).isoformat())
            raise
        fields = {"state": "waiting", "next_run_at": (now_utc()+timedelta(seconds=delay)).isoformat()}
        if result:
            if str(result).startswith("Ошибка"):
                fields["state"] = "error"
            fields.update(last_completed_at=now_utc().isoformat(), last_message=str(result)[:500])
            match = re.search(r"liveness: (\d+)/(\d+).*alive=(\d+) pending=(\d+) marked_dead=(\d+) skip=(\d+)", str(result))
            if match:
                batch = dict(zip(("attempted", "budget", "alive", "pending", "dead", "skipped"), map(int, match.groups())))
                fields["last_batch"] = batch
                row = await db.get(AppSetting, f"vk_runtime_{role}")
                previous = json.loads(row.value) if row else {}
                totals = dict(previous.get("totals") or {})
                totals.setdefault("since", now_utc().isoformat())
                successful = batch["alive"] + batch["pending"] + batch["dead"]
                increments = {"attempted": batch["attempted"], "successful": successful,
                              "limited": max(0, batch["attempted"]-successful-batch["skipped"]),
                              "batches": 1, "confirmed_dead": batch["dead"], "skipped": batch["skipped"]}
                if not previous.get("counters_live"):
                    for key, value in increments.items():
                        totals[key] = int(totals.get(key) or 0) + value
                    fields["totals"] = totals
                if successful:
                    fields["last_successful_batch"] = batch
                    fields["last_successful_at"] = now_utc().isoformat()
        await record_activity(db, role, **fields)
        return result
