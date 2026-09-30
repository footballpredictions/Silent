"""Read-only-ish production timing of the admin page data paths.

Runs the existing app functions in the API container without exposing credentials.
The dashboard path may update its existing peak-online counter, like a normal GET.
"""
from __future__ import annotations

import json
import sys

from _deploy_common import CONTAINER, REMOTE, connect


REMOTE_CODE = r'''
import asyncio
import importlib
import json
import time
from app.database import AsyncSessionLocal
from app.api.admin import get_stats, list_users, list_users_paged
from app.services.admin_subscription_ops import list_subscription_users

phases = {}
def time_async(module_name, function_name):
    module = importlib.import_module(module_name)
    original = getattr(module, function_name)
    async def timed(*args, **kwargs):
        started = time.perf_counter()
        try:
            return await original(*args, **kwargs)
        finally:
            phases[function_name] = round((time.perf_counter() - started) * 1000)
    setattr(module, function_name, timed)

for module_name, function_name in (
    ("app.api.admin", "_dashboard_users_block"),
    ("app.api.admin", "list_dashboard_resource_nodes"),
    ("app.api.admin", "dashboard_system_for_node"),
    ("app.services.hive_service", "vpn_online_shown_total"),
):
    time_async(module_name, function_name)

async def measure(name, fn):
    phases.clear()
    async with AsyncSessionLocal() as db:
        started = time.perf_counter()
        result = await fn(db)
        query_ms = round((time.perf_counter() - started) * 1000)
        encoded = json.dumps(result, default=str, ensure_ascii=False)
        total_ms = round((time.perf_counter() - started) * 1000)
        return {"name": name, "query_ms": query_ms, "total_ms": total_ms,
                "phases_ms": phases.copy(),
                "bytes": len(encoded.encode("utf-8")),
                "vk_flat_bytes": len(json.dumps(result.get("vk_hashes", []), default=str).encode("utf-8")) if isinstance(result, dict) else 0,
                "rows": len(result) if isinstance(result, list) else
                        len(result.get("vk_users", result.get("items", [])))}

async def main():
    for round_number in range(2):
        rows = []
        rows.append(await measure("subscriptions", lambda db: list_subscription_users(
            db, q="", page=1, page_size=50, filter_mode="all")))
        rows.append(await measure("users", lambda db: list_users(
            skip=0, limit=None, _=True, db=db)))
        rows.append(await measure("users_paged", lambda db: list_users_paged(
            q="", page=1, page_size=50, sort="registered_new", _=True, db=db)))
        rows.append(await measure("dashboard_fast", lambda db: get_stats(
            light=False, fast=True, node_id="queen", _=True, db=db)))
        rows.append(await measure("dashboard_light", lambda db: get_stats(
            light=True, fast=False, node_id="queen", _=True, db=db)))
        rows.append(await measure("dashboard", lambda db: get_stats(
            light=False, fast=False, compact=False, node_id="queen", _=True, db=db)))
        rows.append(await measure("dashboard_compact", lambda db: get_stats(
            light=False, fast=False, compact=True, node_id="queen", _=True, db=db)))
        print(json.dumps({"round": round_number + 1, "measurements": rows}), flush=True)

asyncio.run(main())
'''


def main() -> int:
    client = connect(attempts=2, pause=2)
    try:
        stdin, stdout, stderr = client.exec_command(
            f"cd {REMOTE} && docker exec -i {CONTAINER} python -", timeout=120
        )
        stdin.write(REMOTE_CODE)
        stdin.channel.shutdown_write()
        output = stdout.read().decode("utf-8", errors="replace")
        error = stderr.read().decode("utf-8", errors="replace")
        status = stdout.channel.recv_exit_status()
        if output:
            print(output, end="")
        if status != 0:
            print(error[-3000:], file=sys.stderr)
        return status
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
