"""Silent VPN Backend — FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from app.config import settings
from app.database import engine, Base

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

from app.log_buffer import install as _install_log_buffer
_install_log_buffer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create DB tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready")

    # Ensure admin user exists (only worker 0 does this to avoid race condition)
    import os
    if os.environ.get("UVICORN_WORKER_ID", "0") == "0":
        from sqlalchemy import select, text
        from app.database import AsyncSessionLocal
        from app.models import User
        from app.core.security import hash_password
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(User).where(User.email == settings.ADMIN_LOGIN))
                admin = result.scalar_one_or_none()
                if not admin:
                    admin = User(
                        email=settings.ADMIN_LOGIN,
                        password_hash=hash_password(settings.ADMIN_PASSWORD),
                        is_verified=True,
                        is_active=True,
                        is_admin=True,
                    )
                    db.add(admin)
                    await db.commit()
                    logger.info(f"Admin user created: {settings.ADMIN_LOGIN}")
                else:
                    # Sync admin flags and password on every startup
                    admin.is_admin = True
                    admin.is_verified = True
                    admin.password_hash = hash_password(settings.ADMIN_PASSWORD)
                    await db.commit()
                    logger.info(f"Admin user synced: {settings.ADMIN_LOGIN}")
        except Exception as e:
            logger.warning(f"Admin user init skipped (likely race): {e}")

    # Start VK tunnel monitor
    from ai.tunnel_monitor import start_monitor_background
    monitor_task = start_monitor_background()

    yield

    # Shutdown
    monitor_task.cancel()
    try:
        await monitor_task
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
from app.api.users import router as users_router
from app.api.vpn import router as vpn_router
from app.api.payments import router as payments_router
from app.api.admin import router as admin_router

app.include_router(auth_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(vpn_router, prefix="/api")
app.include_router(payments_router, prefix="/api")
app.include_router(admin_router, prefix="/api")

# Static files (logo, etc.)
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Serve admin UI SPA for all non-API routes
admin_ui_dist = os.path.join(os.path.dirname(__file__), "..", "admin-ui", "dist")
if os.path.exists(admin_ui_dist):
    app.mount("/", StaticFiles(directory=admin_ui_dist, html=True), name="admin-ui")


@app.get("/health")
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": settings.APP_VERSION}
