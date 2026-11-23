"""Checker must never issue rooms; issuer consumes persisted dead slots."""
import sys
import unittest
from pathlib import Path
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai import tunnel_monitor
from ai import vk_hash_monitor


class SplitTests(unittest.IsolatedAsyncioTestCase):
    async def test_vk_code_9_stops_issuer_even_without_flood_word(self):
        from ai.vk_manager import VkManager, VkApiError
        manager = VkManager(MagicMock())
        manager._token = "test-only"
        with patch("ai.vk_manager.vk_api_call", AsyncMock(return_value={
                "error": {"error_code": 9, "error_msg": "Too many requests"}})):
            with self.assertRaises(VkApiError):
                await manager._vk_request("calls.start", {})
        self.assertTrue(manager._flood_hit)

    async def test_internal_error_retries_call_status_but_not_call_creation(self):
        from ai.vk_manager import VkManager, VkApiError
        manager = VkManager(MagicMock())
        manager._token = "test-only"
        error = {"error": {"error_code": 10, "error_msg": "Internal server error"}}
        vk = AsyncMock(side_effect=[error, {"response": {"items": []}}, error])
        with patch("ai.vk_manager.vk_api_call", vk), patch("ai.vk_manager.asyncio.sleep", AsyncMock()):
            self.assertEqual(await manager._vk_request("messages.getCurrentCalls", {}), {"items": []})
            with self.assertRaisesRegex(VkApiError, "calls.start: VK API Error 10"):
                await manager._vk_request("calls.start", {})
        self.assertEqual(vk.await_count, 3)

    async def asyncSetUp(self):
        @asynccontextmanager
        async def lease(name):
            yield True
        self.patches = [
            patch("ai.vk_agent_lock.agent_lease", lease),
            patch("app.services.vk_agent_auth.is_flood_cooldown", AsyncMock(return_value=(False, None))),
            patch("app.services.vk_agent_runtime.role_enabled", AsyncMock(return_value=True)),
            patch("app.services.vk_agent_runtime.settings_snapshot", AsyncMock(return_value={})),
            patch("app.services.vk_agent_runtime.record_activity", AsyncMock()),
        ]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        for item in reversed(self.patches):
            item.stop()

    async def test_checker_only_probes_and_closes(self):
        db = MagicMock()
        manager = MagicMock()
        manager.probe_active_hashes = AsyncMock(return_value="liveness: 8 alive")
        manager.close = AsyncMock()
        with patch("app.services.vk_agent_auth.is_agent_enabled", AsyncMock(return_value=True)), \
             patch.object(vk_hash_monitor, "VkManager", return_value=manager):
            await vk_hash_monitor.run_probe_cycle(db)
        manager.probe_active_hashes.assert_awaited_once()
        manager.authenticate.assert_not_called()
        manager.fill_all_user_slots.assert_not_called()
        manager.close.assert_awaited_once()

    async def test_disabled_checker_does_not_access_vk(self):
        with patch("app.services.vk_agent_runtime.role_enabled", AsyncMock(return_value=False)), \
             patch.object(vk_hash_monitor, "VkManager") as manager:
            await vk_hash_monitor.run_probe_cycle(MagicMock())
        manager.assert_not_called()

    async def test_consumer_with_empty_queue_does_not_authenticate_or_probe(self):
        db = MagicMock()
        db.scalar = AsyncMock(return_value=None)
        db.execute = AsyncMock(return_value=MagicMock())
        db.execute.return_value.scalars.return_value.all.return_value = []
        with patch("app.services.vk_agent_auth.is_agent_enabled", AsyncMock(return_value=True)), \
             patch.object(tunnel_monitor, "VkManager") as manager:
            await tunnel_monitor.run_heal_cycle(db, full_fill=False)
        manager.assert_not_called()

    async def test_consumer_heals_only_queued_users_without_probing(self):
        db = MagicMock()
        db.scalar = AsyncMock(return_value=None)
        db.execute = AsyncMock(return_value=MagicMock())
        db.execute.return_value.scalars.return_value.all.return_value = ["user-1"]
        manager = MagicMock()
        manager.authenticate = AsyncMock(return_value=True)
        manager.fill_user_empty_slots = AsyncMock(return_value=1)
        manager.close = AsyncMock()
        manager._flood_hit = False
        manager._room_exit_failed = False
        with patch("app.services.vk_agent_auth.is_agent_enabled", AsyncMock(return_value=True)), \
             patch("app.services.vk_agent_auth.set_agent_run_log", AsyncMock()), \
             patch.object(tunnel_monitor, "VkManager", return_value=manager):
            await tunnel_monitor.run_heal_cycle(db, full_fill=False)
        manager.fill_user_empty_slots.assert_awaited_once_with("user-1")
        manager.probe_active_hashes.assert_not_called()
        manager.fill_all_user_slots.assert_not_called()
        manager.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
