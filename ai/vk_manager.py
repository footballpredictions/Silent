"""
VK AI Assistant — creates VK group calls, extracts TURN hashes,
monitors tunnel health 24/7 and auto-recreates on failure.

Auth: stored access_token (Android client) or password via vk_agent_auth.
"""
import asyncio
import aiohttp
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import VkHash
from app.services.vk_agent_auth import resolve_agent_token, validate_token, VK_API_VERSION, VK_USER_AGENT, vk_api_call

logger = logging.getLogger(__name__)

MAX_HASHES = 4


async def agent_heal_background(*, fill_only: bool = False) -> None:
    """Создание/проверка хешей в фоне (connect не ждёт — иначе 504 от nginx).

    fill_only: только calls.start (кнопка «Снять паузу») — без пачки preview,
    иначе liveness снова ловит error 9 и ставит паузу.
    """
    from app.database import AsyncSessionLocal
    from app.services.vk_agent_auth import set_agent_run_log, is_flood_cooldown

    try:
        async with AsyncSessionLocal() as db:
            flood, until = await is_flood_cooldown(db)
            if flood:
                msg = f"Пропуск: VK flood control до {until}. Новые звонки не создаём."
                await set_agent_run_log(db, msg, ok=False)
                logger.warning(msg)
                return
            manager = VkManager(db)
            try:
                parts: list[str] = []
                if not fill_only:
                    parts.append(await manager.probe_active_hashes())
                parts.append(await manager.fill_all_user_slots())
                summary = "; ".join(parts)
                await set_agent_run_log(db, summary, ok="ошиб" not in summary.lower() and "flood" not in summary.lower())
                logger.info("Background agent heal: %s", summary)
            finally:
                await manager.close()
    except Exception as e:
        logger.exception("Background agent heal failed: %s", e)
        try:
            async with AsyncSessionLocal() as db:
                from app.services.vk_agent_auth import set_agent_run_log
                await set_agent_run_log(db, f"Ошибка агента: {e}", ok=False)
        except Exception:
            pass


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
        self._flood_hit: bool = False

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
            msg = err.get("error_msg", "Unknown")
            if "flood" in msg.lower():
                self._flood_hit = True
                self._last_auth_error = msg
            if code in (5, 1116):
                self._token = None
            raise VkApiError(code, msg)
        return data.get("response", {})

    async def ensure_authenticated(self, verify_calls: bool = False) -> tuple[bool, str]:
        if self._token:
            ok, msg, _ = await validate_token(self._token)
            if ok:
                return True, msg
            self._token = None

        token, msg = await resolve_agent_token(self.db, verify_calls=verify_calls)
        if token:
            self._token = token
            return True, msg
        self._last_auth_error = msg
        return False, msg

    async def authenticate(self, verify_calls: bool = False) -> bool:
        ok, _ = await self.ensure_authenticated(verify_calls=verify_calls)
        return ok

    async def create_call(self) -> Optional[str]:
        """Create a new VK group call and return its hash."""
        try:
            resp = await self._vk_request("calls.start", {})
            join_link = resp.get("join_link", "")
            hash_val = self._extract_hash(join_link)
            if hash_val:
                logger.info("Created VK call, hash: %s...", hash_val[:12])
                return hash_val
            logger.error("Could not extract hash from join_link: %s", join_link)
            return None
        except VkApiError as e:
            logger.error("Failed to create VK call: %s", e)
            if "flood" in str(e).lower():
                self._flood_hit = True
            if e.code in (5, 1116):
                await self.ensure_authenticated(verify_calls=False)
            return None
        except Exception as e:
            logger.error("Unexpected error creating VK call: %s", e)
            return None

    async def probe_active_hashes(self) -> str:
        """Round-robin liveness: anonymous getCallPreview, без calls.start / TURN."""
        from app.services.vk_agent_auth import (
            _setting,
            _set_setting,
            is_flood_cooldown,
        )
        from ai.vk_hash_liveness import (
            JoinHashProber,
            KIND_FLOOD,
            PROBE_BUDGET,
            PROBE_SLEEP_SEC,
            SETTING_CURSOR,
            SETTING_LAST,
            SETTING_LAST_ALIVE,
            SETTING_LAST_DEAD,
            SETTING_LAST_MARKED,
            SETTING_LAST_MSG,
            SETTING_PROBE_UNTIL,
            PROBE_BACKOFF_MINUTES,
            apply_probe_kind,
            select_probe_batch,
        )

        flood, until = await is_flood_cooldown(self.db)
        if flood:
            return f"liveness пропуск: issuer flood до {until}"

        probe_until_raw = await _setting(self.db, SETTING_PROBE_UNTIL)
        if probe_until_raw:
            try:
                probe_until = datetime.strptime(probe_until_raw, "%Y-%m-%d %H:%M:%S UTC")
                if datetime.utcnow() < probe_until:
                    return f"liveness пауза preview до {probe_until_raw} (не блокирует создание хешей)"
            except ValueError:
                pass

        result = await self.db.execute(
            select(VkHash).where(
                VkHash.is_active == True,  # noqa: E712
                VkHash.user_id.isnot(None),
                VkHash.hash_value != "",
            )
        )
        rows = list(result.scalars().all())
        cursor = await _setting(self.db, SETTING_CURSOR)
        batch = select_probe_batch(rows, cursor, PROBE_BUDGET)
        if not batch:
            return "liveness: нет активных хешей"

        session = await self._get_session()
        prober = JoinHashProber(session)
        now = datetime.utcnow()
        alive = dead = pending = marked = skipped = 0
        probed = 0
        last_id = cursor or ""
        preview_flood = False

        for h in batch:
            if prober.flood:
                break
            kind = await prober.probe(h.hash_value)
            probed += 1
            if kind == KIND_FLOOD or prober.flood:
                # Анонимный preview (app 8093730) ≠ calls.start. Не ставим паузу issuer.
                preview_flood = True
                backoff = (datetime.utcnow() + timedelta(minutes=PROBE_BACKOFF_MINUTES)).strftime(
                    "%Y-%m-%d %H:%M:%S UTC"
                )
                await _set_setting(self.db, SETTING_PROBE_UNTIL, backoff)
                break
            state = {
                "last_error_code": int(getattr(h, "last_error_code", 0) or 0),
                "is_active": bool(h.is_active),
                "fail_count": int(h.fail_count or 0),
            }
            action = apply_probe_kind(state, kind)
            h.last_checked = now
            h.last_error_code = int(state["last_error_code"])
            h.is_active = bool(state["is_active"])
            h.fail_count = int(state["fail_count"])
            if action == "alive":
                alive += 1
            elif action == "pending":
                pending += 1
                h.last_failed = now
            elif action == "deactivated":
                marked += 1
                dead += 1
                h.last_failed = now
                logger.warning(
                    "hash liveness dead slot=%s user=%s hash=%s…",
                    h.slot_index,
                    h.user_id,
                    (h.hash_value or "")[:12],
                )
            else:
                skipped += 1
            last_id = str(h.id)
            await asyncio.sleep(PROBE_SLEEP_SEC)

        await self.db.commit()
        ts = now.strftime("%Y-%m-%d %H:%M:%S UTC")
        summary = (
            f"liveness: {probed}/{len(batch)} проб alive={alive} pending={pending} "
            f"marked_dead={marked} skip={skipped}"
        )
        if preview_flood:
            summary += " (preview flood — создание хешей не паузим)"
        await _set_setting(self.db, SETTING_CURSOR, last_id)
        await _set_setting(self.db, SETTING_LAST, ts)
        await _set_setting(self.db, SETTING_LAST_MSG, summary)
        await _set_setting(self.db, SETTING_LAST_ALIVE, str(alive))
        await _set_setting(self.db, SETTING_LAST_DEAD, str(pending + marked))
        await _set_setting(self.db, SETTING_LAST_MARKED, str(marked))
        return summary

    @staticmethod
    def _extract_hash(url_or_hash: str) -> Optional[str]:
        from app.services.user_hash_service import extract_call_hash
        return extract_call_hash(url_or_hash)

    async def upsert_hash_slot(
        self,
        slot: int,
        hash_val: str,
        call_link: str | None = None,
        user_id=None,
    ) -> VkHash:
        q = select(VkHash).where(VkHash.slot_index == slot)
        if user_id is not None:
            q = q.where(VkHash.user_id == user_id)
        else:
            q = q.where(VkHash.user_id.is_(None))
        result = await self.db.execute(q)
        existing = result.scalar_one_or_none()
        if existing:
            existing.hash_value = hash_val
            existing.call_link = call_link
            existing.is_active = True
            existing.fail_count = 0
            existing.last_error_code = 0
            existing.last_failed = None
            existing.last_checked = datetime.utcnow()
            existing.updated_at = datetime.utcnow()
            h = existing
        else:
            h = VkHash(
                hash_value=hash_val,
                slot_index=slot,
                call_link=call_link,
                is_active=True,
                fail_count=0,
                last_error_code=0,
                last_checked=datetime.utcnow(),
                user_id=user_id,
            )
            self.db.add(h)
        await self.db.commit()
        await self.db.refresh(h)
        return h

    async def create_hash_for_user_slot(self, user_id, slot: int) -> tuple[Optional[str], str]:
        if slot < 0 or slot >= MAX_HASHES:
            return None, f"Слот должен быть 0–{MAX_HASHES - 1}"
        ok, err = await self.ensure_authenticated()
        if not ok:
            return None, err
        hash_val = await self.create_call()
        if not hash_val:
            return None, self._last_auth_error or "calls.start не вернул хеш"
        link = f"https://vk.com/call/join/{hash_val}"
        await self.upsert_hash_slot(slot, hash_val, link, user_id=user_id)
        return hash_val, "OK"

    async def create_hash_for_slot(self, slot: int) -> tuple[Optional[str], str]:
        if slot < 0 or slot >= MAX_HASHES:
            return None, f"Слот должен быть 0–{MAX_HASHES - 1}"
        ok, err = await self.ensure_authenticated()
        if not ok:
            return None, err
        hash_val = await self.create_call()
        if not hash_val:
            return None, self._last_auth_error or "calls.start не вернул хеш"
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

    async def fill_user_empty_slots(self, user_id) -> int:
        """Пустые слоты и мёртвые (is_active=false / last_error_code=1)."""
        from app.services.user_hash_service import dedupe_user_hash_slots

        await dedupe_user_hash_slots(self.db, user_id)

        created = 0
        result = await self.db.execute(select(VkHash).where(VkHash.user_id == user_id))
        healthy_slots: set[int] = set()
        for h in result.scalars().all():
            if h.slot_index < 0 or h.slot_index >= MAX_HASHES:
                continue
            err = int(getattr(h, "last_error_code", 0) or 0)
            if h.is_active and err != 1:
                healthy_slots.add(h.slot_index)

        for slot in range(MAX_HASHES):
            if slot in healthy_slots or self._flood_hit:
                continue
            hash_val, msg = await self.create_hash_for_user_slot(user_id, slot)
            if hash_val:
                created += 1
            else:
                logger.warning("fill slot %s user %s: %s", slot, user_id, msg)
                if self._flood_hit or (msg and "flood" in msg.lower()):
                    break
            await asyncio.sleep(3)
        return created

    async def fill_all_user_slots(self) -> str:
        from app.services.user_hash_service import list_users_for_monitor
        from app.services.vk_agent_auth import set_flood_cooldown

        if self._flood_hit:
            return "Пропуск fill: flood после liveness"

        if not await self.authenticate(verify_calls=False):
            return f"Ошибка: {self._last_auth_error or 'нет токена VK'}"

        from app.services.user_hash_service import dedupe_all_user_hash_slots

        removed_dupes = await dedupe_all_user_hash_slots(self.db)

        user_ids = await list_users_for_monitor(self.db)
        if not user_ids:
            return "Нет пользователей для создания хешей"

        total_created = 0
        users_touched = 0
        for uid in user_ids:
            n = await self.fill_user_empty_slots(uid)
            if n:
                users_touched += 1
                total_created += n
            if self._flood_hit:
                await set_flood_cooldown(self.db, minutes=45)
                return (
                    f"VK flood control — остановились. Создано {total_created} хешей "
                    f"для {users_touched} пользов. Повтор через ~45 мин."
                )

        dup_part = f", удалено дубликатов: {removed_dupes}" if removed_dupes else ""
        return (
            f"Готово: +{total_created} хешей, обработано {len(user_ids)} пользов., "
            f"заполнено у {users_touched}{dup_part}"
        )

    async def check_and_heal_user(self, user_id) -> None:
        """Монитор: заменить мёртвые/пустые слоты (liveness — в probe_active_hashes)."""
        if not await self.authenticate(verify_calls=False):
            logger.error("check_and_heal_user: VK auth failed — %s", self._last_auth_error)
            return
        await self.fill_user_empty_slots(user_id)

    async def check_and_heal_all_users(self) -> None:
        from app.services.user_hash_service import list_users_for_monitor

        user_ids = await list_users_for_monitor(self.db)
        for uid in user_ids:
            if self._flood_hit:
                break
            await self.check_and_heal_user(uid)

    async def check_and_heal(self) -> None:
        """Проба живых хешей, затем заполнение пустых и помеченных мёртвыми."""
        probe = await self.probe_active_hashes()
        fill = await self.fill_all_user_slots()
        logger.info("check_and_heal: %s | %s", probe, fill)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
