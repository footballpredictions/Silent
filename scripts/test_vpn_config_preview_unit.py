"""Exercise the config-preview request with fake persistence and real response models."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from starlette.requests import Request
from app.api import vpn
from app.services import hive_profiles, subscription_service, threat_filter_settings, user_hash_service, vpn_service


async def main():
    request = Request({"type": "http", "headers": [(b"x-app-version", b"1.0.171")]})
    user = NS(id=uuid4(), email="test@example.invalid")
    device = NS(id=uuid4(), user_id=user.id, preferred_server="server1", cell_id="main", wg_address="10.66.66.5/32",
                wdtt_password="test", wg_private_key_enc="never decrypt this")
    cell = NS(id="cell", wg_public_key="", public_ip="192.0.2.1", wdtt_port=56000, is_queen=False)
    db = NS(execute=AsyncMock(side_effect=[NS(scalar_one_or_none=lambda: device), NS(scalar_one_or_none=lambda: user)]),
            commit=AsyncMock(side_effect=AssertionError("preview must not commit")))

    with (
        patch.object(vpn, "is_user_admin", return_value=True),
        patch.object(vpn_service.hive_service, "resolve_manual_server_cell", new=AsyncMock(return_value=("server2", cell))),
        patch("app.services.hive_slots.cell_visible_to_client", return_value=True),
        patch.object(subscription_service, "is_user_admin", return_value=True),
        patch.object(vpn_service, "get_server_public_key", new=AsyncMock(return_value="")),
        patch.object(vpn_service, "_generate_wg_keypair", side_effect=AssertionError("preview must not create keys")),
        patch("app.core.security.decrypt_value", side_effect=AssertionError("preview must not decrypt keys")),
        patch.object(user_hash_service, "get_vpn_hashes_for_user", new=AsyncMock(return_value=["test-hash"])),
        patch.object(user_hash_service, "get_server_hashes_for_user", new=AsyncMock(return_value=["test-hash"])),
        patch.object(hive_profiles, "get_profile", new=AsyncMock(return_value={"ai": False, "wg_mtu": 1200})),
        patch.object(threat_filter_settings, "resolve_wg_dns", new=AsyncMock(return_value="1.1.1.1")),
    ):
        result = await vpn.preview_vpn_config("test-device", "server2", request, user, db)
        assert result.selected_server == "server2" and result.vk_hashes == ["test-hash"]
        assert result.wg_private_key == "" and device.preferred_server == "server1" and device.cell_id == "main"
        db.commit.assert_not_awaited()

    db.execute.side_effect = None
    db.execute.return_value = NS(scalar_one_or_none=lambda: device)
    with (
        patch.object(vpn, "is_user_admin", return_value=False),
        patch.object(subscription_service, "user_in_test_mode", new=AsyncMock(return_value=False)),
        patch.object(subscription_service, "get_display_subscription", new=AsyncMock(return_value=None)),
    ):
        try:
            await vpn.preview_vpn_config("test-device", "server2", request, user, db)
        except HTTPException as exc:
            assert exc.status_code == 402
        else:
            raise AssertionError("expired subscription must not receive a profile")
    print("VPN config preview: PASS")


if __name__ == "__main__":
    asyncio.run(main())
