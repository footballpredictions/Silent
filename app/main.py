"""Silent VPN Backend — FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from app.config import settings
from app.database import engine, Base
from sqlalchemy import text

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create DB tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS vk_user_id BIGINT"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS vk_linked_at TIMESTAMP"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS vk_config_published_at TIMESTAMP"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_vk_user_id ON users (vk_user_id) WHERE vk_user_id IS NOT NULL"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS vk_link_sessions (
                state VARCHAR(64) PRIMARY KEY,
                user_id UUID REFERENCES users(id),
                code_verifier VARCHAR(128) NOT NULL,
                expires_at TIMESTAMP NOT NULL
            )
        """))
        await conn.execute(text(
            "ALTER TABLE vk_link_sessions ALTER COLUMN user_id DROP NOT NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE vk_link_sessions ADD COLUMN IF NOT EXISTS vk_user_id BIGINT"
        ))
        await conn.execute(text(
            "ALTER TABLE vk_link_sessions ADD COLUMN IF NOT EXISTS bootstrap_hash VARCHAR(255)"
        ))
        await conn.execute(text(
            "ALTER TABLE vk_link_sessions ADD COLUMN IF NOT EXISTS completed BOOLEAN DEFAULT FALSE"
        ))
        await conn.execute(text(
            "ALTER TABLE vk_link_sessions ADD COLUMN IF NOT EXISTS purpose VARCHAR(32) DEFAULT 'guest'"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_test_user BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS bootstrap_hash VARCHAR(255)"
        ))
        await conn.execute(text(
            "ALTER TABLE vk_hashes ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_vk_hashes_user_id ON vk_hashes (user_id)"
        ))
        await conn.execute(text(
            "UPDATE users SET is_admin = TRUE WHERE LOWER(email) = LOWER(:admin_email)"
        ), {"admin_email": settings.ADMIN_LOGIN})
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_vk_link_sessions_user_id ON vk_link_sessions (user_id)"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS hive_cells (
                id UUID PRIMARY KEY,
                name VARCHAR(128) NOT NULL,
                is_queen BOOLEAN NOT NULL DEFAULT FALSE,
                public_ip VARCHAR(255) NOT NULL,
                wdtt_port INTEGER NOT NULL DEFAULT 56000,
                wg_port INTEGER NOT NULL DEFAULT 56001,
                wg_public_key TEXT DEFAULT '',
                api_url VARCHAR(512),
                api_secret_enc TEXT,
                tunnel_api_url VARCHAR(512),
                max_clients INTEGER NOT NULL DEFAULT 100,
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                priority INTEGER NOT NULL DEFAULT 100,
                last_seen_at TIMESTAMP,
                last_error TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_hive_cells_is_queen ON hive_cells (is_queen)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_hive_cells_status ON hive_cells (status)"
        ))
        await conn.execute(text(
            "ALTER TABLE devices ADD COLUMN IF NOT EXISTS cell_id UUID REFERENCES hive_cells(id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_devices_cell_id ON devices (cell_id)"
        ))
    logger.info("Database tables ready")

    from app.database import AsyncSessionLocal
    from app.services.hive_service import ensure_queen_cell
    from sqlalchemy import update as sql_update
    from app.models import Device

    async with AsyncSessionLocal() as db:
        try:
            queen = await ensure_queen_cell(db)
            await db.execute(
                sql_update(Device).where(Device.cell_id.is_(None)).values(cell_id=queen.id)
            )
            await db.commit()
        except Exception as e:
            logger.warning("Hive queen init skipped: %s", e)

    # Start VK tunnel monitor + nightly OTA rebuild scheduler
    from ai.tunnel_monitor import start_monitor_background
    from ai.release_build_scheduler import start_release_build_scheduler

    monitor_task = start_monitor_background()
    build_scheduler_task = start_release_build_scheduler()

    yield

    # Shutdown
    for task in (monitor_task, build_scheduler_task):
        task.cancel()
        try:
            await task
        except Exception:
            pass
    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Silent VPN API",
    version=settings.APP_VERSION,
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
from app.api.auth import router as auth_router
from app.api.vk_auth import router as vk_auth_router
from app.api.users import router as users_router
from app.api.vpn import router as vpn_router
from app.api.payments import router as payments_router
from app.api.admin import router as admin_router
from app.api.hive import router as hive_router
from app.api.updates import router as updates_router
from app.services import update_service

app.include_router(auth_router, prefix="/api")
app.include_router(vk_auth_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(vpn_router, prefix="/api")
app.include_router(payments_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(hive_router, prefix="/api")
app.include_router(updates_router, prefix="/api")


@app.get("/health")
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": settings.APP_VERSION}


@app.api_route(
    "/api/{_api_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def api_unmatched(_api_path: str):
    """Неизвестный API — 404, а не 405 от SPA catch-all."""
    raise HTTPException(status_code=404, detail="API endpoint not found")


# Legacy OAuth landing (GET/POST) — иначе POST даёт 405
_vk_oauth_html = os.path.join(os.path.dirname(__file__), "..", "static", "vk-agent-oauth.html")


@app.api_route("/static/vk-agent-oauth.html", methods=["GET", "POST"], include_in_schema=False)
async def vk_agent_oauth_landing():
    if os.path.isfile(_vk_oauth_html):
        return FileResponse(_vk_oauth_html, media_type="text/html")
    raise HTTPException(status_code=404, detail="Not Found")


# Static files (logo, etc.)
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Client app updates (PC installer, Android APK)
update_service.ensure_dirs()
update_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "update"))
app.mount("/update", StaticFiles(directory=update_dir), name="updates")

# Admin UI SPA — index.html fallback for client-side routes (/dashboard, /users, …)
admin_ui_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "admin-ui", "dist"))
admin_ui_index = os.path.join(admin_ui_dist, "index.html")

if os.path.isfile(admin_ui_index):
    assets_dir = os.path.join(admin_ui_dist, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="admin-assets")

    @app.get("/")
    async def serve_admin_root():
        return FileResponse(admin_ui_index, media_type="text/html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_admin_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = os.path.normpath(os.path.join(admin_ui_dist, full_path))
        if not candidate.startswith(admin_ui_dist):
            raise HTTPException(status_code=404, detail="Not Found")
        if os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(admin_ui_index, media_type="text/html")
else:
    logger.warning(
        "Admin UI not found at %s — build: cd admin-ui && npm install && npm run build",
        admin_ui_dist,
    )
