"""Синхронизация WB account JWT → settings.auth_token + srv YAML (без печати токена).

Запуск на VPS внутри контейнера или локально с DATABASE_URL:

  docker exec -w /app backend-api-1 python scripts/sync_olcrtc_wb_auth_token.py

После — скопировать YAML на хост и restart olcrtc@*-wbstream (см. deploy_olcrtc).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# /app в контейнере; локально — корень backend
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def main() -> int:
    from app.database import AsyncSessionLocal
    from app.services.olcrtc_room_accounts import sync_wbstream_auth_token_to_settings
    from app.services.olcrtc_rooms_db import write_all_unit_yaml_from_db
    from app.services.olcrtc_settings import load_olcrtc_settings

    async with AsyncSessionLocal() as db:
        tok = await sync_wbstream_auth_token_to_settings(db)
        if not tok:
            print("wb_auth_token: MISSING (нет accessToken в wbstream storage_state)")
            return 1
        files = await write_all_unit_yaml_from_db(db)
        settings = await load_olcrtc_settings(db)
        wb = settings.providers.get("wbstream")
        has = bool(wb and (wb.auth_token or "").strip())
        wb_units = [u for u in files if u.endswith("-wbstream") or "wbstream" in u]
        print(
            f"wb_auth_token: OK len={len(tok)} in_settings={has} "
            f"yaml_units={len(files)} wb_units={','.join(wb_units) or '-'}"
        )
        # sanity: yaml содержит token: без вывода значения
        for uid in wb_units:
            text = files[uid]
            ok = "token:" in text and "provider: wbstream" in text
            print(f"  yaml {uid}: auth.token={'yes' if ok else 'NO'}")
        return 0 if has else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
