"""Cross-worker VK leases released by PostgreSQL at transaction end."""
from contextlib import asynccontextmanager
import zlib

from sqlalchemy import text
from app.database import engine


@asynccontextmanager
async def agent_lease(name: str):
    key = zlib.crc32(("vk:" + name).encode()) & 0x7FFFFFFF
    async with engine.begin() as connection:
        acquired = bool(await connection.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}))
        yield acquired
