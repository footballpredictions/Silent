"""Простой rate-limiter по IP на базе Redis (fixed window, INCR + EXPIRE).

Используется для защиты публичных эндпоинтов (регистрация и т.п.) от
скриптового флуда с одного IP. При недоступности Redis — fail-open (не
блокируем пользователей из-за инфраструктурного сбоя).
"""
import logging

from redis import asyncio as aioredis
from fastapi import Request

from app.config import settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def get_client_ip(request: Request) -> str:
    """IP клиента с учётом nginx (X-Real-IP / X-Forwarded-For), с фолбэком
    на request.client.host (прямые запросы через WG-tunnel API)."""
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


async def is_rate_limited(key: str, max_attempts: int, window_seconds: int) -> bool:
    """True — лимит превышен, запрос нужно отклонить."""
    if max_attempts <= 0:
        return False
    try:
        redis = _get_redis()
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, window_seconds)
        return current > max_attempts
    except Exception as e:
        logger.warning(f"Rate limiter Redis error (fail-open): {e}")
        return False


async def check_ip_rate_limit(request: Request, scope: str, max_attempts: int, window_seconds: int) -> bool:
    """Удобный хелпер: собирает ключ `rl:{scope}:{ip}` и проверяет лимит."""
    ip = get_client_ip(request)
    return await is_rate_limited(f"rl:{scope}:{ip}", max_attempts, window_seconds)
