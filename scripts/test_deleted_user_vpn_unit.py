"""Replay the real queen deny sync after account/device cascade deletion, no host IO."""
from __future__ import annotations

import ast
import asyncio
import logging
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services import vpn_deny_net as deny


class Query:
    def where(self, *args):
        return self


def load_sync():
    tree = ast.parse((ROOT / "app/services/vpn_kick.py").read_text(encoding="utf-8-sig"))
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "sync_unpaid_deny_net")
    ns = dict(asyncio=asyncio, AsyncSession=object, select=lambda *args: Query(),
              Device=SimpleNamespace(id=0, user_id=0, device_fingerprint=0, is_active=True),
              _sync_unpaid_lock=asyncio.Lock(), _ensure_nsenter_helper=lambda: None,
              logger=logging.getLogger("deleted-user-test"))
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "vpn_kick.py", "exec"), ns)
    return ns["sync_unpaid_deny_net"]


class DeletedUserVpnTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_tunnel_of_deleted_account_is_denied_and_paid_tunnel_is_preserved(self):
        # The account and its device row are gone; wdtt keeps its GETCONF identity.
        identities = {
            "11111111-1111-4111-8111-111111111111": {"ip": "10.66.0.18", "pub": "deleted"},
            "22222222-2222-4222-8222-222222222222": {"ip": "10.66.0.19", "pub": "paid"},
            "boot:public": {"ip": "10.66.0.20", "pub": "bootstrap"},
        }
        paid_id = "22222222-2222-4222-8222-222222222222"
        async def execute(query):
            return SimpleNamespace(all=lambda: [(paid_id, "paid-user", "paid-fingerprint")])
        async def allowed(db):
            return {"paid-user"}
        def read(ids=None):
            selected = identities if ids is None else {i: identities[i] for i in ids if i in identities}
            return deny.IdentitiesRead(True, {k: v for k, v in selected.items() if not k.startswith("boot:")})
        applied = []
        subscriptions = SimpleNamespace(users_with_vpn_access_ids=allowed)
        with patch.dict(sys.modules, {"app.services.subscription_service": subscriptions}), \
             patch.object(deny, "read_host_wdtt_identities_result", read), \
             patch.object(deny, "sync_queen_deny_ips", lambda ips: applied.append(set(ips)) or len(ips)):
            await load_sync()(SimpleNamespace(execute=execute))
        self.assertEqual(applied, [{"10.66.0.18"}], "deleted account still has a working cached VPN identity")

    async def test_cell_manifest_keeps_deletion_deny_after_device_row_is_gone(self):
        deleted_id = "11111111-1111-4111-8111-111111111111"
        source = (ROOT / "app/services/hive_standby.py").read_text(encoding="utf-8-sig")
        fn = next(n for n in ast.parse(source).body if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == "build_cell_manifest_enriched")
        async def execute(query):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
        async def version(db): return 1
        async def deleted(db): return [deleted_id]
        async def meta(db): return None
        async def theme(db): raise RuntimeError("no theme in minimal fixture")
        ns = dict(AsyncSession=object, HiveCell=object, Device=SimpleNamespace(cell_id=0, preferred_server=0, is_active=True),
                  select=lambda *args: Query(), or_=lambda *args: True,
                  slot_for_cell=lambda cell: "server2", datetime=datetime,
                  settings=SimpleNamespace(VPN_SERVER_PORT=56000, WG_PORT=56001, FRONTEND_URL=""), hive_meta=meta)
        modules = {"app.services.hive_cell_sync": SimpleNamespace(manifest_version=version),
                   "app.services.theme_settings": SimpleNamespace(load_theme=theme)}
        with patch.dict(sys.modules, modules), patch.object(deny, "deleted_device_ids", deleted, create=True):
            exec(compile(ast.Module(body=[fn], type_ignores=[]), "hive_standby.py", "exec"), ns)
            manifest = await ns["build_cell_manifest_enriched"](
                SimpleNamespace(execute=execute),
                SimpleNamespace(id="cell2", name="cell", public_ip="192.0.2.10", wdtt_port=56000,
                                wg_port=56001, wg_public_key="public"))
        denied_ids = [d["id"] for d in manifest["devices"] if d.get("vpn_allowed") is False]
        self.assertIn(deleted_id, denied_ids, "a deleted row vanished from the cell deny manifest")

    def test_shared_paid_ip_and_bootstrap_addresses_are_not_denied(self):
        self.assertEqual(deny.denied_identity_ips({
            "gone": {"ip": "10.66.0.18"}, "paid": {"ip": "10.66.0.18"},
            "boot": {"ip": "10.66.0.19"}, "gateway": {"ip": "10.66.66.1"},
            "default": {"ip": "10.66.66.2"}, "invalid": {"ip": "203.0.113.1"},
        }, {"paid", "boot"}), set())

    async def test_unreachable_cell_receives_deletion_deny_on_next_sync(self):
        source = (ROOT / "app/services/hive_cell_sync.py").read_text(encoding="utf-8-sig")
        fn = next(n for n in ast.parse(source).body if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == "sync_all_cell_manifests")
        cell = SimpleNamespace(id="cell")
        async def execute(query):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [cell]))
        async def version(db): return 42
        async def build(db, target): return {"devices": [{"id": "deleted", "vpn_allowed": False}]}
        pushes = []
        async def push(target, manifest):
            pushes.append(manifest)
            return len(pushes) > 1  # Transient connection failure on the first delivery.
        ns = dict(AsyncSession=object, datetime=datetime, _last_manifest_version=0, _last_sync_at=None,
                  settings=SimpleNamespace(HIVE_CELL_MANIFEST_SYNC_ENABLED=True),
                  HiveCell=SimpleNamespace(is_queen=False, status=SimpleNamespace(in_=lambda _: True),
                                           api_url=SimpleNamespace(isnot=lambda _: True)),
                  select=lambda *args: Query(), manifest_version=version, build_cell_manifest=build,
                  push_manifest_to_cell=push, logger=logging.getLogger("deleted-user-test"))
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "hive_cell_sync.py", "exec"), ns)
        db = SimpleNamespace(execute=execute)
        self.assertEqual((await ns["sync_all_cell_manifests"](db))["synced"], 0)
        self.assertEqual((await ns["sync_all_cell_manifests"](db))["synced"], 1)
        self.assertTrue((await ns["sync_all_cell_manifests"](db))["skipped"])
        self.assertEqual(len(pushes), 2)

    def test_reconnect_uses_the_current_wdtt_ip_and_tombstones_never_include_keys(self):
        did = "11111111-1111-4111-8111-111111111111"
        for ip in ["10.66.0.18", "10.66.0.28"]:
            self.assertEqual(deny.denied_identity_ips({did: {"ip": ip}}, set()), {ip})
        rows = deny.deleted_manifest_entries([did, "boot:public", "not-a-device", did])
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["vpn_allowed"])
        self.assertEqual(rows[0]["wg_public_key"], "")
        self.assertEqual(deny.deleted_manifest_entries([did], existing_ids=[did]), [])

    async def test_failed_identity_snapshot_does_not_clear_existing_denies(self):
        applied = []
        with patch.object(deny, "read_host_wdtt_identities_result", lambda: deny.IdentitiesRead(False, {}, "unavailable")), \
             patch.object(deny, "sync_queen_deny_ips", lambda ips: applied.append(ips)):
            await load_sync()(SimpleNamespace(execute=lambda _: self.fail("failed snapshot must stop before DB")))
        self.assertEqual(applied, [])

    def test_large_deny_batch_uses_stdin_and_only_replaces_its_own_chain(self):
        import ipaddress
        ips = {str(ipaddress.IPv4Address("10.66.0.10") + i) for i in range(1948)}
        script = deny._iptables_sync_script(ips)
        self.assertIn("iptables-restore --noflush", script)
        self.assertEqual(script.count("-j DROP"), 3896)
        self.assertNotIn("-F FORWARD", script)
        with patch.object(deny.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            deny._nsenter(script)
        args = run.call_args.args[0]
        self.assertEqual(args[:4], ["docker", "exec", "-i", "silent-nsenter"])
        self.assertNotIn(script, args)
        self.assertEqual(run.call_args.kwargs["input"], script)

    async def test_deletion_records_commit_atomically_with_cascade_and_survive_reload(self):
        from sqlalchemy import create_engine, String, Text
        from sqlalchemy.orm import DeclarativeBase, mapped_column, Session
        class Base(DeclarativeBase): pass
        class Setting(Base):
            __tablename__ = "app_settings"
            key = mapped_column(String(100), primary_key=True)
            value = mapped_column(Text)
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        session = Session(engine)
        async def execute(query): return session.execute(query)
        did = "11111111-1111-4111-8111-111111111111"
        invalidations = []
        modules = {"app.models": SimpleNamespace(AppSetting=Setting),
                   "app.services.hive_cell_sync": SimpleNamespace(invalidate_manifest_cache=lambda: invalidations.append(True))}
        try:
            with patch.dict(sys.modules, modules):
                db = SimpleNamespace(execute=execute)
                self.assertEqual(await deny.remember_deleted_device_ids(db, [did]), 1)
                session.rollback()  # Simulated cascade failure must undo the deny record.
                self.assertEqual(await deny.deleted_device_ids(db), [])
                self.assertEqual(await deny.remember_deleted_device_ids(db, [did, did, "boot:public"]), 1)
                session.commit()
                self.assertEqual(await deny.remember_deleted_device_ids(db, [did]), 0)
                session.close()
                session = Session(engine)
                self.assertEqual(await deny.deleted_device_ids(db), [did])
                self.assertEqual(len(invalidations), 2)
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
