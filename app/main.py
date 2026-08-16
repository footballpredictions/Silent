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
import app.models  # noqa: F401 — register ORM tables for create_all

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
            "ALTER TABLE admin_sessions ADD COLUMN IF NOT EXISTS label VARCHAR(128) NOT NULL DEFAULT ''"
        ))
        await conn.execute(text(
            "ALTER TABLE admin_sessions ADD COLUMN IF NOT EXISTS client_platform VARCHAR(64)"
        ))
        await conn.execute(text(
            "ALTER TABLE admin_sessions ADD COLUMN IF NOT EXISTS client_mobile BOOLEAN"
        ))
        await conn.execute(text(
            "ALTER TABLE admin_sessions ADD COLUMN IF NOT EXISTS device_fingerprint VARCHAR(128)"
        ))
        await conn.execute(text(
            "ALTER TABLE admin_trusted_devices ADD COLUMN IF NOT EXISTS device_fingerprint VARCHAR(128)"
        ))
        await conn.execute(text(
            "ALTER TABLE admin_trusted_devices ADD COLUMN IF NOT EXISTS device_type VARCHAR(32) NOT NULL DEFAULT 'pc'"
        ))
        await conn.execute(text(
            "ALTER TABLE admin_trusted_devices ALTER COLUMN token_hash DROP NOT NULL"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_admin_trusted_devices_fingerprint "
            "ON admin_trusted_devices (device_fingerprint) WHERE device_fingerprint IS NOT NULL"
        ))
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
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS test_mode_excluded BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS test_mode_personal BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS bootstrap_hash VARCHAR(255)"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP"
        ))
        await conn.execute(text(
            "UPDATE users u SET last_seen_at = sub.max_ts FROM ("
            "  SELECT user_id, MAX(GREATEST("
            "    COALESCE(last_connected, created_at), created_at"
            "  )) AS max_ts FROM devices GROUP BY user_id"
            ") sub WHERE u.id = sub.user_id AND u.last_seen_at IS NULL"
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
            "ALTER TABLE devices ADD COLUMN IF NOT EXISTS preferred_server VARCHAR(16) NOT NULL DEFAULT 'server1'"
        ))
        await conn.execute(text(
            "ALTER TABLE devices ALTER COLUMN preferred_server TYPE VARCHAR(64)"
        ))
        await conn.execute(text(
            "ALTER TABLE devices ALTER COLUMN preferred_server SET DEFAULT 'server1'"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_devices_cell_id ON devices (cell_id)"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS hive_load_samples (
                id UUID PRIMARY KEY,
                cell_id UUID NOT NULL REFERENCES hive_cells(id) ON DELETE CASCADE,
                sampled_at TIMESTAMP NOT NULL DEFAULT NOW(),
                online_count INTEGER NOT NULL DEFAULT 0,
                cpu_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
                memory_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
                network_mbps DOUBLE PRECISION NOT NULL DEFAULT 0,
                network_util_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
                link_capacity_mbps DOUBLE PRECISION NOT NULL DEFAULT 1000
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_hive_load_samples_cell_id ON hive_load_samples (cell_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_hive_load_samples_sampled_at ON hive_load_samples (sampled_at)"
        ))
        await conn.execute(text(
            "ALTER TABLE hive_cells ADD COLUMN IF NOT EXISTS link_capacity_mbps DOUBLE PRECISION"
        ))
        await conn.execute(text(
            "UPDATE hive_cells SET link_capacity_mbps = 10000 "
            "WHERE is_queen = false AND (link_capacity_mbps IS NULL OR link_capacity_mbps <= 0) "
            "AND id = (SELECT id FROM hive_cells WHERE is_queen = false "
            "ORDER BY created_at ASC NULLS LAST LIMIT 1)"
        ))
        await conn.execute(text(
            "UPDATE hive_cells SET link_capacity_mbps = 1000 "
            "WHERE is_queen = false AND (link_capacity_mbps IS NULL OR link_capacity_mbps <= 0)"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS hive_schema_migrations (
                name VARCHAR(128) PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS hive_incidents (
                id BIGSERIAL PRIMARY KEY,
                ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                severity VARCHAR(16) NOT NULL,
                source VARCHAR(128) NOT NULL,
                cell_name VARCHAR(255),
                cell_ip VARCHAR(255),
                category VARCHAR(64) NOT NULL,
                hint TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                checks_json TEXT NOT NULL DEFAULT '[]'
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_hive_incidents_ts ON hive_incidents (ts DESC)"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS hive_incident_meta (
                meta_key VARCHAR(64) PRIMARY KEY,
                meta_value VARCHAR(255),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        once = await conn.execute(text(
            "INSERT INTO hive_schema_migrations (name) VALUES ('cell_link_cap_v2') "
            "ON CONFLICT (name) DO NOTHING RETURNING name"
        ))
        if once.rowcount:
            await conn.execute(text(
                "UPDATE hive_cells SET link_capacity_mbps = 1000 "
                "WHERE is_queen = false AND link_capacity_mbps = 10000 "
                "AND id <> (SELECT id FROM hive_cells WHERE is_queen = false "
                "ORDER BY created_at ASC NULLS LAST LIMIT 1)"
            ))
        await conn.execute(text(
            "ALTER TABLE hive_load_samples ADD COLUMN IF NOT EXISTS cpu_cores INTEGER"
        ))
        await conn.execute(text(
            "ALTER TABLE hive_load_samples ADD COLUMN IF NOT EXISTS memory_total_gb DOUBLE PRECISION"
        ))
        once_v3 = await conn.execute(text(
            "INSERT INTO hive_schema_migrations (name) VALUES ('cell_link_cap_v3') "
            "ON CONFLICT (name) DO NOTHING RETURNING name"
        ))
        if once_v3.rowcount:
            await conn.execute(text(
                "UPDATE hive_cells SET link_capacity_mbps = 10000 "
                "WHERE is_queen = false AND name ~* '^[[:space:]]*сота[[:space:]]*1([[:space:]]|$)'"
            ))
            await conn.execute(text(
                "UPDATE hive_cells SET link_capacity_mbps = 1000 "
                "WHERE is_queen = false AND name !~* '^[[:space:]]*сота[[:space:]]*1([[:space:]]|$)'"
            ))
        await conn.execute(text(
            "ALTER TABLE hive_cells ADD COLUMN IF NOT EXISTS ssh_password_enc TEXT"
        ))
        await conn.execute(text(
            "ALTER TABLE hive_cells ADD COLUMN IF NOT EXISTS accepts_wdtt BOOLEAN NOT NULL DEFAULT TRUE"
        ))
        once_olcrtc_wdtt = await conn.execute(text(
            "INSERT INTO hive_schema_migrations (name) VALUES ('olcrtc_cells_no_wdtt_spill_v1') "
            "ON CONFLICT (name) DO NOTHING RETURNING name"
        ))
        if once_olcrtc_wdtt.rowcount:
            await conn.execute(text(
                "UPDATE hive_cells SET accepts_wdtt = FALSE "
                "WHERE is_queen = false AND public_ip IN ('87.58.213.193', '78.17.74.27')"
            ))
        once_auto_cap = await conn.execute(text(
            "INSERT INTO hive_schema_migrations (name) VALUES ('cell_auto_capacity_v1') "
            "ON CONFLICT (name) DO NOTHING RETURNING name"
        ))
        if once_auto_cap.rowcount:
            await conn.execute(text(
                "UPDATE hive_cells SET max_clients = 0 WHERE max_clients > 0"
            ))
        # Proxy fleet (SOCKS) — отдельно от VPN; create_all + raw SQL safety net
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS proxy_nodes (
                id UUID PRIMARY KEY,
                name VARCHAR(128) NOT NULL,
                role VARCHAR(32) NOT NULL DEFAULT 'dedicated',
                public_ip VARCHAR(255) NOT NULL,
                ssh_port INTEGER NOT NULL DEFAULT 22,
                socks_port INTEGER NOT NULL DEFAULT 1080,
                socks_user VARCHAR(128) NOT NULL DEFAULT '',
                socks_pass_enc TEXT,
                agent_url VARCHAR(512),
                agent_secret_enc TEXT,
                ssh_password_enc TEXT,
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                is_primary BOOLEAN NOT NULL DEFAULT FALSE,
                priority INTEGER NOT NULL DEFAULT 100,
                last_seen_at TIMESTAMP,
                last_error TEXT,
                previous_proxy_json TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_proxy_nodes_status ON proxy_nodes (status)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_proxy_nodes_public_ip ON proxy_nodes (public_ip)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_proxy_nodes_is_primary ON proxy_nodes (is_primary)"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code VARCHAR(16)"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by_user_id UUID REFERENCES users(id)"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS pending_promo_code VARCHAR(50)"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_referral_code "
            "ON users (referral_code) WHERE referral_code IS NOT NULL"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_users_referred_by_user_id ON users (referred_by_user_id)"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS referral_rewards (
                id UUID PRIMARY KEY,
                inviter_id UUID NOT NULL REFERENCES users(id),
                invitee_id UUID NOT NULL UNIQUE REFERENCES users(id),
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                payment_id UUID REFERENCES payments(id),
                rewarded_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_referral_rewards_inviter_id ON referral_rewards (inviter_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_referral_rewards_invitee_id ON referral_rewards (invitee_id)"
        ))
        # YuMoney: идемпотентность нотификаций + аудит суммы + промокод намерения
        await conn.execute(text(
            "ALTER TABLE payments ADD COLUMN IF NOT EXISTS operation_id VARCHAR(255)"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_payments_operation_id "
            "ON payments (operation_id) WHERE operation_id IS NOT NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE payments ADD COLUMN IF NOT EXISTS paid_amount NUMERIC(10, 2)"
        ))
        await conn.execute(text(
            "ALTER TABLE payments ADD COLUMN IF NOT EXISTS promo_code VARCHAR(50)"
        ))
    logger.info("Database tables ready")

    from app.database import AsyncSessionLocal
    from app.services.hive_service import ensure_queen_cell
    from app.services.hive_incidents import load_persisted_incidents
    from sqlalchemy import update as sql_update
    from app.models import Device

    await load_persisted_incidents()

    async with AsyncSessionLocal() as db:
        try:
            queen = await ensure_queen_cell(db)
            await db.execute(
                sql_update(Device).where(Device.cell_id.is_(None)).values(cell_id=queen.id)
            )
            await db.commit()
            from app.config import settings as app_settings
            from app.services.hive_service import migrate_devices_to_queen

            if not app_settings.HIVE_WORKER_ROUTING_ENABLED:
                await migrate_devices_to_queen(db)
        except Exception as e:
            logger.warning("Hive queen init skipped: %s", e)
        try:
            from app.services.subscription_service import (
                reconcile_stale_test_subscriptions,
                clear_legacy_global_test_flags,
            )
            from app.services.test_mode_settings import is_registration_test_mode_enabled
            fixed = await reconcile_stale_test_subscriptions(db)
            if fixed:
                logger.info("Reconciled %s stale test subscription(s)", fixed)
            if not await is_registration_test_mode_enabled(db):
                legacy = await clear_legacy_global_test_flags(db)
                if legacy:
                    logger.info("Cleared legacy is_test_user on %s user(s)", legacy)
        except Exception as e:
            logger.warning("Test subscription reconcile skipped: %s", e)

    # VK-only mode: olcrtc room sync is disabled.

    # Фоновые агенты — только в одном воркере (uvicorn --workers N поднимает
    # lifespan в каждом, без лидера агенты дублируются).
    # Импорты изолированы: сбой одного модуля НЕ должен валить весь API (502).
    agents_task = None
    try:
        from ai.tunnel_monitor import monitor_loop as vk_tunnel_monitor_loop
        from ai.release_build_scheduler import scheduler_loop as release_build_loop
        from app.services.agent_leader import start_when_leader
        from app.services.hive_capacity import capacity_sampler_loop
        from app.services.hive_rebalance_loop import hive_rebalance_loop
        from app.services.hive_cell_maintenance_loop import hive_cell_maintenance_loop
        from app.services.proxy_health_loop import proxy_health_loop

        agent_specs: list = [
            ("vk_tunnel_monitor", vk_tunnel_monitor_loop),
            ("release_build_scheduler", release_build_loop),
            ("hive_capacity_sampler", capacity_sampler_loop),
            ("hive_rebalance", hive_rebalance_loop),
            ("hive_cell_maintenance", hive_cell_maintenance_loop),
            ("proxy_health", proxy_health_loop),
        ]
        # VK-only mode: all olcrtc background agents are disabled.

        agents_task = start_when_leader("silent_background_agents", agent_specs)
    except Exception as e:
        logger.error("background agents failed to start (API still up): %s", e)

    yield

    # Shutdown
    if agents_task is not None:
        agents_task.cancel()
        try:
            await agents_task
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

# Admin UI/API: ADMIN_PUBLIC_HOST (nip.io) or tunnel gateway 10.66.66.1
from app.middleware.admin_host_guard import AdminHostGuardMiddleware

app.add_middleware(AdminHostGuardMiddleware)

# API routers
from app.api.auth import router as auth_router
from app.api.vk_auth import router as vk_auth_router
from app.api.users import router as users_router
from app.api.vpn import router as vpn_router
from app.api.payments import router as payments_router
from app.api.admin import router as admin_router
from app.api.hive import router as hive_router
from app.api.proxy import router as proxy_router
from app.api.updates import router as updates_router
from app.services import update_service

app.include_router(auth_router, prefix="/api")
app.include_router(vk_auth_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(vpn_router, prefix="/api")
app.include_router(payments_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(hive_router, prefix="/api")
app.include_router(proxy_router, prefix="/api")
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
