"""The account profile must show a live GETCONF session even without WDTT reports."""
import ast
import asyncio
import importlib.util
import json
import tempfile
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("presence_under_test", ROOT / "app/services/session_presence.py")
presence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(presence)


class Query:
    def __getattr__(self, _):
        return self

    def __call__(self, *args, **kwargs):
        return self

    def __eq__(self, _):
        return self


async def check_profile(relative, name):
    source = ast.parse((ROOT / relative).read_text(encoding="utf-8-sig"))
    fn = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    fn.args.defaults = []
    fn.args.args = [ast.arg(arg="user"), ast.arg(arg="db")] if name == "get_profile" else [ast.arg(arg="db"), ast.arg(arg="user")]
    fn.returns = None
    fn.decorator_list = []
    # Local imports retain production control flow but use explicit fixture dependencies.
    fn.body = [n for n in fn.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
    device = NS(id="pc-id", device_name="PC", device_type="pc", is_connected=False, last_connected=None)
    ns = {"UserProfileResponse": NS, "SubscriptionInfo": NS, "DeviceInfo": NS,
          "select": lambda *a: Query(), "Device": Query(), "LAST_SEEN_TOUCH_MINUTES": 5,
          "is_user_admin": lambda u: True}
    for symbol in ("touch_user_last_seen", "ensure_admin_flag", "clear_stale_online_status", "collapse_duplicate_devices", "ensure_trial_subscription"):
        ns[symbol] = AsyncMock()
    ns.update(user_in_test_mode=AsyncMock(return_value=False), count_active_sessions=AsyncMock(return_value=1),
              count_connected_sessions=AsyncMock(return_value=0), max_devices_for_user=AsyncMock(return_value=10),
              session_online_flags=AsyncMock(return_value={"pc-id": True}))
    db = NS(execute=AsyncMock(return_value=NS(scalars=lambda: NS(all=lambda: [device]))))
    user = NS(id="owner", email="owner@example.test", display_id="1", vk_user_id=None)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), relative, "exec"), ns)
    profile = await ns[name](user, db) if name == "get_profile" else await ns[name](db, user)
    assert profile.devices[0].is_connected, f"{name}: live PC is shown offline"
    assert profile.connected_count == 1, f"{name}: count disagrees with online rows"


async def main():
    for file, name in (("app/api/users.py", "get_profile"), ("app/services/client_sync_bundle.py", "_profile_for_user")):
        await check_profile(file, name)
    print("PASS profile and config bundle preserve live session presence")
    devices = [NS(id="pc", is_connected=False, device_fingerprint="fingerprint", wg_public_key="identity", wg_live_public_key="old-live"),
               NS(id="phone", is_connected=True), NS(id="offline", is_connected=False)]
    assert presence.online_flags(devices, {"refs": ["pc"]}) == {"pc": True, "phone": True, "offline": False}
    assert presence.online_flags(devices, {"refs": ["foreign"], "pubs": ["foreign"]}) == {"pc": False, "phone": True, "offline": False}
    assert presence.online_flags(devices, {"pubs": ["identity"]})["pc"]
    assert presence.online_flags(devices, {"pubs": ["old-live"]})["pc"]
    assert presence.online_flags(devices, {"refs": ["fingerprint"]})["pc"]
    with patch.object(presence, "presence_snapshot", AsyncMock(side_effect=RuntimeError)):
        assert await presence.session_online_flags(devices) == {"pc": False, "phone": True, "offline": False}
    print("PASS exact identities, account isolation, legacy keys and failure fallback")
    # Exercise the actual node mapper against the node's GETCONF database format.
    tree = ast.parse((ROOT / "cell-agent/standby_runtime.py").read_text(encoding="utf-8-sig"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "live_device_refs")
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "passwords.json"
        path.write_text(json.dumps({"devices": {"pc": {"pub_key": "live"}, "offline": {"pub_key": "stale"}, "boot:fp": {"pub_key": "live"}}, "main_password": "must-not-leak"}))
        ns = {"json": json, "WDTT_PASSWORDS_PATH": path}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "node-mapper", "exec"), ns)
        assert ns["live_device_refs"](["live"]) == ["pc"]
        assert ns["live_device_refs"]([]) == []
        path.write_text("bad json")
        assert ns["live_device_refs"](["live"]) == []
    print("PASS node exact-key mapping, stale peers, bootstrap exclusion, corrupt file")
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("wg_peer_counts", "wg_live_pubs")]
    ns = {"_local_handshakes": lambda: [(str(i), 1) for i in range(450)] + [("stale", 181), ("never", None)],
          "_wg_counts": {}, "_wg_live_pub_list": []}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "node-handshakes", "exec"), ns)
    assert ns["wg_peer_counts"]()["live_3m"] == 450
    assert len(ns["wg_live_pubs"]()) == 400
    assert len(ns["wg_live_pubs"](limit=None)) == 450
    print("PASS session references beyond dashboard's 400-key limit")
    redis = NS(get=AsyncMock(return_value=None), set=AsyncMock())
    modules = {"app.services.hive_service": NS(_get_shown_redis=lambda: redis)}
    collector = AsyncMock(return_value={"refs": ["pc"], "pubs": []})
    with patch.dict(sys.modules, modules), patch.object(presence, "collect_presence", collector):
        presence._cached_at = 0
        values = await asyncio.gather(*(presence.presence_snapshot() for _ in range(20)))
        assert all(v["refs"] == ["pc"] for v in values)
        assert collector.await_count == 1
        presence._cached_at -= 11
        redis.get.return_value = json.dumps({"refs": [], "pubs": []})
        assert (await presence.presence_snapshot())["refs"] == []
        assert collector.await_count == 1
        presence._cached_at -= 11
        redis.get.return_value = "[]"
        assert (await presence.presence_snapshot())["refs"] == ["pc"]
        assert collector.await_count == 2
        presence._cached_at -= 11
        redis.get.side_effect = RuntimeError
        redis.set.side_effect = RuntimeError
        collector.return_value = {"refs": [], "pubs": []}
        assert (await presence.presence_snapshot())["refs"] == []
    print("PASS concurrent polls coalesce, snapshots expire, workers share Redis, Redis failure")


if __name__ == "__main__":
    asyncio.run(main())
