"""
VK AI Assistant — creates VK group calls, extracts TURN hashes,
monitors tunnel health 24/7 and auto-recreates on failure.

Uses VK API client_id 6287487 (fallback: 8202606) following the
same auth flow as proxy-turn-vk-android.
"""
import asyncio
import aiohttp
import logging
import re
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import VkHash, VkCredentials, AppSetting
from app.core.security import decrypt_value
from app.config import settings

logger = logging.getLogger(__name__)

VK_API_VERSION = "5.199"
VK_CLIENT_IDS = [6287487, 8202606]
MAX_HASHES = 3


class VkApiError(Exception):
    def __init__(self, code: int, msg: str):
        self.code = code
        super().__init__(f"VK API Error {code}: {msg}")


class VkManager:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._session: Optional[aiohttp.ClientSession] = None
        self._token: Optional[str] = None
        self._client_id_idx: int = 0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": "VKAndroidApp/8.10-17765 (Android 14; SDK 34; arm64-v8a; Google Pixel 8; ru; 2560x1080)"},
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    async def _vk_request(self, method: str, params: dict) -> dict:
        session = await self._get_session()
        params["v"] = VK_API_VERSION
        if self._token:
            params["access_token"] = self._token

        url = f"https://api.vk.com/method/{method}"
        async with session.post(url, data=params) as resp:
            data = await resp.json()

        if "error" in data:
            err = data["error"]
            raise VkApiError(err.get("error_code", -1), err.get("error_msg", "Unknown"))
        return data.get("response", {})

    async def _load_credentials(self) -> tuple[str, str]:
        result = await self.db.execute(select(VkCredentials).where(VkCredentials.id == 1))
        creds = result.scalar_one_or_none()
        if not creds or not creds.is_configured:
            raise RuntimeError("VK credentials not configured in admin panel")
        login = decrypt_value(creds.login_enc)
        password = decrypt_value(creds.password_enc)
        return login, password

    async def authenticate(self) -> bool:
        """Authenticate with VK and get access token."""
        try:
            login, password = await self._load_credentials()
        except Exception as e:
            logger.error(f"Failed to load VK credentials: {e}")
            return False

        for client_id in VK_CLIENT_IDS:
            try:
                session = await self._get_session()
                async with session.get(
                    "https://oauth.vk.com/token",
                    params={
                        "grant_type": "password",
                        "client_id": client_id,
                        "client_secret": "",
                        "username": login,
                        "password": password,
                        "scope": "all",
                        "v": VK_API_VERSION,
                    }
                ) as resp:
                    data = await resp.json()

                if "access_token" in data:
                    self._token = data["access_token"]
                    logger.info(f"VK authenticated with client_id {client_id}")
                    return True

                logger.warning(f"VK auth failed with client_id {client_id}: {data.get('error_description', data)}")
            except Exception as e:
                logger.error(f"VK auth error with client_id {client_id}: {e}")

        return False

    async def _get_anonymous_token(self) -> Optional[str]:
        """Get anonymous TURN token for a call hash."""
        try:
            resp = await self._vk_request("calls.getAnonymousToken", {})
            return resp.get("token")
        except VkApiError as e:
            if e.code in (5, 1116):
                logger.warning(f"VK token invalid, re-authenticating: {e}")
                await self.authenticate()
            return None

    async def create_call(self) -> Optional[str]:
        """Create a new VK group call and return its hash."""
        try:
            resp = await self._vk_request("calls.create", {})
            join_link = resp.get("join_link", "")
            hash_val = self._extract_hash(join_link)
            if hash_val:
                logger.info(f"Created VK call, hash: {hash_val[:12]}...")
                return hash_val
            logger.error(f"Could not extract hash from join_link: {join_link}")
            return None
        except VkApiError as e:
            logger.error(f"Failed to create VK call: {e}")
            if e.code in (5, 1116):
                await self.authenticate()
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating VK call: {e}")
            return None

    async def _check_hash_alive(self, hash_val: str) -> bool:
        """Check if a VK call hash is still valid by trying to get TURN credentials."""
        try:
            session = await self._get_session()
            async with session.get(
                "https://api.vk.com/method/calls.getAnonymousToken",
                params={
                    "v": VK_API_VERSION,
                    "hash": hash_val,
                    "access_token": self._token or "",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
            return "response" in data
        except Exception:
            return False

    @staticmethod
    def _extract_hash(url_or_hash: str) -> Optional[str]:
        """Extract hash from VK call URL or return as-is if already a hash."""
        if not url_or_hash:
            return None
        # Full URL: vk.com/call/join/HASH
        match = re.search(r"/join/([A-Za-z0-9_\-]+)", url_or_hash)
        if match:
            return match.group(1)
        # Already a hash
        if re.match(r"^[A-Za-z0-9_\-]{8,}$", url_or_hash):
            return url_or_hash
        return None

    async def recreate_all_hashes(self) -> bool:
        """Recreate all VK call hashes. Called by monitor or manually from admin."""
        if not self._token:
            if not await self.authenticate():
                logger.error("Cannot recreate hashes: VK auth failed")
                return False

        logger.info("Recreating all VK hashes...")
        created: list[str] = []

        for slot in range(MAX_HASHES):
            hash_val = await self.create_call()
            if hash_val:
                created.append((slot, hash_val))
            else:
                logger.error(f"Failed to create hash for slot {slot}")
            await asyncio.sleep(2)  # Avoid API rate limiting

        if not created:
            return False

        # Update DB
        result = await self.db.execute(select(VkHash))
        existing = {h.slot_index: h for h in result.scalars().all()}

        for slot, hash_val in created:
            if slot in existing:
                h = existing[slot]
                h.hash_value = hash_val
                h.is_active = True
                h.fail_count = 0
                h.updated_at = datetime.utcnow()
            else:
                self.db.add(VkHash(
                    hash_value=hash_val,
                    slot_index=slot,
                    is_active=True,
                ))

        await self.db.commit()
        logger.info(f"Successfully recreated {len(created)}/{MAX_HASHES} hashes")
        return len(created) == MAX_HASHES

    async def check_and_heal(self) -> None:
        """Check all hashes; if any fail — try reconnect first, then recreate all."""
        result = await self.db.execute(
            select(VkHash).where(VkHash.is_active == True).order_by(VkHash.slot_index)
        )
        hashes = result.scalars().all()

        if not hashes:
            logger.info("No VK hashes in DB, creating fresh ones...")
            await self.recreate_all_hashes()
            return

        failed = []
        for h in hashes:
            alive = await self._check_hash_alive(h.hash_value)
            h.last_checked = datetime.utcnow()
            if not alive:
                h.fail_count += 1
                h.last_failed = datetime.utcnow()
                failed.append(h)
                logger.warning(f"Hash slot {h.slot_index} is dead (fail_count={h.fail_count})")
            else:
                h.fail_count = 0

        await self.db.commit()

        if failed:
            logger.warning(f"{len(failed)}/{len(hashes)} hashes failed. Recreating all...")
            await self.recreate_all_hashes()

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
