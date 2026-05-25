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
import threading
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import VkHash, VkCredentials
from app.core.security import decrypt_value

# Pending 2FA sessions: {session_id: (thread, code_event, code_holder, result_holder)}
_pending_2fa: dict = {}

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
    async def direct_auth(cls, login: str, password: str) -> dict:
        """
        Start VK auth from server side (vk_api implicit flow).
        Returns dict with keys:
          success=True, token=...           — auth done, no 2FA
          need_2fa=True, session_id=...     — SMS sent, waiting for code
          success=False, message=...        — error
        """
        loop = asyncio.get_event_loop()
        session_id = str(uuid.uuid4())

        code_event = threading.Event()
        code_holder: list = [None]          # code_holder[0] = provided code
        result_holder: list = [None]        # result_holder[0] = final dict

        def _auth_handler():
            """Called by vk_api when 2FA code is needed."""
            logger.info("VK 2FA required, waiting for code...")
            code_event.wait(timeout=300)   # wait up to 5 min
            if code_holder[0]:
                return code_holder[0], True
            raise Exception("Timeout: 2FA code not provided within 5 minutes")

        def _sync_auth():
            import vk_api as vk_api_lib
            vk_session = vk_api_lib.VkApi(
                login=login,
                password=password,
                auth_handler=_auth_handler,
            )
            try:
                vk_session.auth(token_only=True)
                token = vk_session.token.get("access_token", "")
                if token:
                    result_holder[0] = {"success": True, "token": token}
                else:
                    result_holder[0] = {"success": False, "message": "Токен не получен"}
            except vk_api_lib.AuthError as e:
                msg = str(e)
                if "captcha" in msg.lower():
                    result_holder[0] = {"success": False, "message": "VK требует капчу. Попробуйте позже."}
                elif "password" in msg.lower() or "неверн" in msg.lower() or "invalid" in msg.lower():
                    result_holder[0] = {"success": False, "message": f"Неверный логин или пароль VK: {msg}"}
                else:
                    result_holder[0] = {"success": False, "message": f"Ошибка VK: {msg}"}
            except Exception as e:
                result_holder[0] = {"success": False, "message": f"Ошибка: {e}"}
            finally:
                _pending_2fa.pop(session_id, None)

        t = threading.Thread(target=_sync_auth, daemon=True)
        t.start()

        # Wait up to 4 seconds — enough for auth without 2FA
        t.join(timeout=4)

        if not t.is_alive():
            # Auth completed (success or error, no 2FA needed)
            return result_holder[0] or {"success": False, "message": "Неизвестная ошибка"}

        # Auth thread is blocked waiting for 2FA code — SMS already sent by VK
        _pending_2fa[session_id] = (t, code_event, code_holder, result_holder)
        return {"need_2fa": True, "session_id": session_id,
                "message": "VK отправил SMS с кодом. Введите его ниже."}

    @classmethod
    async def submit_2fa_code(cls, session_id: str, code: str) -> dict:
        """
        Provide 2FA code for a pending auth session.
        Returns same format as direct_auth.
        """
        entry = _pending_2fa.get(session_id)
        if not entry:
            return {"success": False, "message": "Сессия не найдена или уже завершена. Попробуйте войти заново."}

        t, code_event, code_holder, result_holder = entry
        code_holder[0] = code
        code_event.set()   # wake up the waiting auth thread

        # Wait for the auth thread to finish
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: t.join(timeout=15))

        if t.is_alive():
            return {"success": False, "message": "Сервер VK не ответил вовремя. Попробуйте снова."}

        return result_holder[0] or {"success": False, "message": "Неизвестная ошибка"}

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
