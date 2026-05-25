"""
VK AI Assistant — creates VK group calls, extracts TURN hashes,
monitors tunnel health 24/7 and auto-recreates on failure.

Uses VK API client_id 6287487 (VK Android) following the
same auth flow as proxy-turn-vk-android.
"""
import asyncio
import aiohttp
import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import VkHash, VkCredentials
from app.core.security import decrypt_value

logger = logging.getLogger(__name__)

VK_API_VERSION = "5.131"
MAX_HASHES = 3

# Known VK client credentials (public, used in FOSS VK clients)
VK_CLIENTS = [
    {"id": 6287487,  "secret": "VeWdmVclDCtn6ihuP1nt"},  # VK Android
    {"id": 2274003,  "secret": "hHbZxrka2uZ6jB1inYsH"},  # VK Official
    {"id": 2685278,  "secret": "lxhD8OD7dMsqtXIm5IUY"},  # Kate Mobile
]


class VkApiError(Exception):
    def __init__(self, code: int, msg: str):
        self.code = code
        super().__init__(f"VK API Error {code}: {msg}")


class VkManager:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._session: Optional[aiohttp.ClientSession] = None
        self._token: Optional[str] = None
        self.last_error: str = ""

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "User-Agent": "VKAndroidApp/8.10-17765 (Android 14; SDK 34; arm64-v8a; Google Pixel 8; ru; 2560x1080)"
                },
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
            data = await resp.json(content_type=None)

        if "error" in data:
            err = data["error"]
            raise VkApiError(err.get("error_code", -1), err.get("error_msg", "Unknown"))
        return data.get("response", {})

    async def authenticate(self) -> bool:
        """
        Authenticate with VK.
        Priority: 1) saved server-side token  2) ask user to re-auth
        """
        try:
            result = await self.db.execute(select(VkCredentials).where(VkCredentials.id == 1))
            creds = result.scalar_one_or_none()

            if creds and creds.access_token:
                session = await self._get_session()
                async with session.get(
                    "https://api.vk.com/method/users.get",
                    params={"access_token": creds.access_token, "v": VK_API_VERSION},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json(content_type=None)

                if "response" in data:
                    self._token = creds.access_token
                    self.last_error = ""
                    logger.info("VK auth OK via saved token")
                    return True

                err = data.get("error", {})
                err_msg = err.get("error_msg", str(err))
                logger.warning(f"Saved token invalid: {err_msg}")
                creds.access_token = None
                await self.db.commit()
        except Exception as e:
            logger.warning(f"Token check error: {e}")

        self.last_error = "Токен VK не найден или устарел. Войдите через панель администратора."
        return False

    @classmethod
    async def direct_auth(cls, login: str, password: str) -> tuple[bool, str, str]:
        """
        Perform auth from server side via vk_api (implicit flow — no client_secret needed).
        Returns (success, token_or_empty, error_message).
        """
        import asyncio
        from functools import partial

        def _sync_auth():
            import vk_api as vk_api_lib
            vk_session = vk_api_lib.VkApi(login=login, password=password)
            try:
                vk_session.auth(token_only=True)
                token = vk_session.token.get("access_token", "")
                if token:
                    return True, token, ""
                return False, "", "Токен не получен после авторизации"
            except vk_api_lib.AuthError as e:
                msg = str(e)
                if "CAPTCHA" in msg.upper():
                    return False, "", "VK требует капчу. Попробуйте позже или войдите через браузер вк."
                if "two-factor" in msg.lower() or "2fa" in msg.lower() or "код" in msg.lower():
                    return False, "", "Требуется код из SMS/приложения (2FA). Временно отключите двухфакторку в настройках VK."
                if "password" in msg.lower() or "неверный" in msg.lower():
                    return False, "", f"Неверный логин или пароль: {msg}"
                return False, "", f"Ошибка авторизации VK: {msg}"
            except Exception as e:
                return False, "", f"Неожиданная ошибка: {e}"

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_auth)

    async def create_call(self) -> Optional[str]:
        """Create a new VK group call and return its hash."""
        try:
            resp = await self._vk_request("calls.create", {})
            join_link = resp.get("join_link", "")
            hash_val = self._extract_hash(join_link)
            if hash_val:
                logger.info(f"Created VK call, hash: {hash_val[:12]}...")
                return hash_val
            # Some API versions return hash directly
            if resp.get("hash"):
                return resp["hash"]
            logger.error(f"Cannot extract hash from response: {resp}")
            self.last_error = f"Не удалось извлечь хеш из ответа: {resp}"
            return None
        except VkApiError as e:
            self.last_error = str(e)
            logger.error(f"VK API error creating call: {e}")
            if e.code in (5, 1116):
                await self.authenticate()
            return None
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"Unexpected error creating VK call: {e}")
            return None

    async def _check_hash_alive(self, hash_val: str) -> bool:
        """Check if a VK call hash is still valid."""
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
        if re.match(r"^[A-Za-z0-9_\-]{8,}$", url_or_hash):
            return url_or_hash
        return None

    async def recreate_all_hashes(self) -> tuple[bool, str]:
        """
        Recreate all VK call hashes.
        Returns (success, error_message).
        """
        if not self._token:
            auth_ok = await self.authenticate()
            if not auth_ok:
                err = self.last_error or "VK авторизация не удалась"
                logger.error(f"Cannot recreate hashes: {err}")
                return False, f"Ошибка авторизации VK: {err}"

        logger.info("Recreating all VK hashes...")
        created: list[tuple[int, str]] = []
        errors: list[str] = []

        for slot in range(MAX_HASHES):
            hash_val = await self.create_call()
            if hash_val:
                created.append((slot, hash_val))
            else:
                err = self.last_error or f"Не удалось создать хеш для слота {slot}"
                errors.append(err)
                logger.error(f"Failed to create hash for slot {slot}: {err}")
            await asyncio.sleep(2)

        if not created:
            return False, f"Не удалось создать ни одного хеша. Ошибки: {'; '.join(errors)}"

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
        msg = f"Создано {len(created)}/{MAX_HASHES} хешей"
        if errors:
            msg += f". Ошибки: {'; '.join(errors)}"
        logger.info(msg)
        return len(created) == MAX_HASHES, msg

    async def check_and_heal(self) -> None:
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
            else:
                h.fail_count = 0

        await self.db.commit()

        if failed:
            logger.warning(f"{len(failed)}/{len(hashes)} hashes failed. Recreating all...")
            await self.recreate_all_hashes()

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
