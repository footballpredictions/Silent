"""
VK AI Assistant — creates VK group calls, extracts TURN hashes,
monitors tunnel health 24/7 and auto-recreates on failure.

Auth: stored access_token (Android client) or password via vk_agent_auth.
"""
import asyncio
import aiohttp
import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import VkHash
from app.services.vk_agent_auth import resolve_agent_token, validate_token, VK_API_VERSION, VK_USER_AGENT, vk_api_call

logger = logging.getLogger(__name__)

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
        self._last_auth_error: str = ""

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": VK_USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    async def _vk_request(self, method: str, params: dict) -> dict:
        if not self._token:
            ok, err = await self.ensure_authenticated()
            if not ok:
                raise VkApiError(-1, err)
        data = await vk_api_call(method, self._token, params or None)
        if "error" in data:
            err = data["error"]
            code = err.get("error_code", -1)
            if code in (5, 1116):
                self._token = None
            raise VkApiError(code, err.get("error_msg", "Unknown"))
        return data.get("response", {})

    async def ensure_authenticated(self) -> tuple[bool, str]:
        if self._token:
            ok, msg, _ = await validate_token(self._token)
            if ok:
                return True, msg
            self._token = None

        token, msg = await resolve_agent_token(self.db, verify_calls=True)
        if token:
            self._token = token
            return True, msg
        self._last_auth_error = msg
        return False, msg

    async def authenticate(self) -> bool:
        ok, _ = await self.ensure_authenticated()
        return ok

    async def create_call(self) -> Optional[str]:
        """Create a new VK group call and return its hash."""
        try:
            resp = await self._vk_request("calls.create", {})
            join_link = resp.get("join_link", "")
            hash_val = self._extract_hash(join_link)
            if hash_val:
                logger.info("Created VK call, hash: %s...", hash_val[:12])
                return hash_val
            logger.error("Could not extract hash from join_link: %s", join_link)
            return None
        except VkApiError as e:
            logger.error("Failed to create VK call: %s", e)
            if e.code in (5, 1116):
                await self.ensure_authenticated()
            return None
        except Exception as e:
            logger.error("Unexpected error creating VK call: %s", e)
            return None

    async def _check_hash_alive(self, hash_val: str) -> bool:
        try:
            if not self._token:
                await self.ensure_authenticated()
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
                data = await resp.json(content_type=None)
            return "response" in data
        except Exception:
            return False

    @staticmethod
    def _extract_hash(url_or_hash: str) -> Optional[str]:
        if not url_or_hash:
            return None
        match = re.search(r"/join/([A-Za-z0-9_\-]+)", url_or_hash)
        if match:
            return match.group(1)
        if re.match(r"^[A-Za-z0-9_\-]{8,}$", url_or_hash.strip()):
            return url_or_hash.strip()
        return None

    async def upsert_hash_slot(self, slot: int, hash_val: str, call_link: str | None = None) -> VkHash:
        result = await self.db.execute(select(VkHash).where(VkHash.slot_index == slot))
        existing = result.scalar_one_or_none()
        if existing:
            existing.hash_value = hash_val
            existing.call_link = call_link
            existing.is_active = True
            existing.fail_count = 0
            existing.updated_at = datetime.utcnow()
            h = existing
        else:
            h = VkHash(
                hash_value=hash_val,
                slot_index=slot,
                call_link=call_link,
                is_active=True,
            )
            self.db.add(h)
        await self.db.commit()
        await self.db.refresh(h)
        return h

    async def create_hash_for_slot(self, slot: int) -> tuple[Optional[str], str]:
        if slot < 0 or slot >= MAX_HASHES:
            return None, f"Слот должен быть 0–{MAX_HASHES - 1}"
        ok, err = await self.ensure_authenticated()
        if not ok:
            return None, err
        hash_val = await self.create_call()
        if not hash_val:
            return None, self._last_auth_error or "calls.create не вернул хеш"
        link = f"https://vk.com/call/join/{hash_val}"
        await self.upsert_hash_slot(slot, hash_val, link)
        return hash_val, "OK"

    async def recreate_all_hashes(self) -> tuple[bool, str]:
        ok, err = await self.ensure_authenticated()
        if not ok:
            return False, err

        logger.info("Recreating all VK hashes...")
        created: list[tuple[int, str]] = []

        for slot in range(MAX_HASHES):
            hash_val = await self.create_call()
            if hash_val:
                created.append((slot, hash_val))
            else:
                logger.error("Failed to create hash for slot %s", slot)
            await asyncio.sleep(2)

        if not created:
            return False, "Не удалось создать ни одного хеша (проверьте VK токен)"

        for slot, hash_val in created:
            link = f"https://vk.com/call/join/{hash_val}"
            await self.upsert_hash_slot(slot, hash_val, link)

        logger.info("Successfully recreated %s/%s hashes", len(created), MAX_HASHES)

        try:
            from app.services.vk_config_publisher import publish_all_configs
            await publish_all_configs(self.db)
        except Exception as e:
            logger.warning("VK config publish after hash recreate failed: %s", e)

        if len(created) < MAX_HASHES:
            return True, f"Создано {len(created)}/{MAX_HASHES} хешей (частично)"
        return True, f"Создано {MAX_HASHES} хешей"

    async def check_and_heal(self) -> None:
        if not await self.authenticate():
            logger.error("check_and_heal: VK auth failed — %s", self._last_auth_error)
            return

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
                logger.warning("Hash slot %s is dead (fail_count=%s)", h.slot_index, h.fail_count)
            else:
                h.fail_count = 0

        await self.db.commit()

        if failed:
            logger.warning("%s/%s hashes failed — replacing dead slots", len(failed), len(hashes))
            replaced = 0
            for h in failed:
                new_hash = await self.create_call()
                if new_hash:
                    h.hash_value = new_hash
                    h.call_link = f"https://vk.com/call/join/{new_hash}"
                    h.is_active = True
                    h.fail_count = 0
                    h.updated_at = datetime.utcnow()
                    replaced += 1
                else:
                    h.is_active = False
                await asyncio.sleep(2)
            await self.db.commit()
            if replaced:
                logger.info("Replaced %s dead hash slot(s)", replaced)
                try:
                    from app.services.vk_config_publisher import publish_all_configs
                    await publish_all_configs(self.db)
                except Exception as e:
                    logger.warning("VK publish after hash replace failed: %s", e)
            elif len(failed) == len(hashes):
                logger.warning("All slots failed — full recreate")
                await self.recreate_all_hashes()

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
