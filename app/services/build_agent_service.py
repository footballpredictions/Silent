"""OTA release builds: sync git, new bootstrap VK hash, rebuild without version bump."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting
from app.services import update_service

logger = logging.getLogger(__name__)

_BUILD_LOCK = asyncio.Lock()
_BUILD_RUNNING = False

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
_BUILD_AGENT_ROOT = Path(os.environ.get("BUILD_AGENT_ROOT", _BACKEND_ROOT / "build-agent"))
_WORKSPACE = Path(os.environ.get("BUILD_AGENT_WORKSPACE", _BUILD_AGENT_ROOT / "workspace"))


class BuildAgentError(Exception):
    pass


class BuildAgentBusy(BuildAgentError):
    pass


def _versioned_filename(version: str, original: str) -> str:
    base, ext = os.path.splitext(original)
    if not ext:
        ext = ".apk" if original.endswith("apk") else ".exe"
    safe = version.strip()
    if not safe:
        return original
    if base.endswith(safe) or base.endswith(f" {safe}"):
        return original
    return f"{base}-{safe}{ext}"


def _read_android_version(repo: Path) -> str:
    gradle = repo / "app" / "build.gradle.kts"
    if not gradle.is_file():
        gradle = repo / "build.gradle.kts"
    text = gradle.read_text(encoding="utf-8")
    m = re.search(r'versionName\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else "0.0.0"


def _read_pc_version(repo: Path) -> str:
    pkg = json.loads((repo / "package.json").read_text(encoding="utf-8"))
    return str(pkg.get("version", "0.0.0"))


async def _setting(db: AsyncSession, key: str) -> str | None:
    r = await db.execute(select(AppSetting).where(AppSetting.key == key))
    row = r.scalar_one_or_none()
    return row.value if row else None


async def _set_setting(db: AsyncSession, key: str, value: str) -> None:
    r = await db.execute(select(AppSetting).where(AppSetting.key == key))
    row = r.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    await db.commit()


async def set_build_log(
    db: AsyncSession,
    message: str,
    *,
    status: str = "idle",
    platform: str | None = None,
    bootstrap_hash: str | None = None,
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    await _set_setting(db, "build_agent_last_at", ts)
    await _set_setting(db, "build_agent_status", status)
    await _set_setting(db, "build_agent_message", message[:800])
    if platform:
        await _set_setting(db, "build_agent_last_platform", platform)
    if bootstrap_hash:
        await _set_setting(db, "build_agent_bootstrap_hash", bootstrap_hash)


def is_build_running() -> bool:
    """Сборка OTA/build-agent идёт — не считать CPU Улья перегрузкой VPN."""
    return _BUILD_RUNNING


async def get_build_status(db: AsyncSession) -> dict:
    running = _BUILD_RUNNING
    return {
        "running": running,
        "status": await _setting(db, "build_agent_status") or "idle",
        "message": await _setting(db, "build_agent_message"),
        "last_at": await _setting(db, "build_agent_last_at"),
        "last_platform": await _setting(db, "build_agent_last_platform"),
        "bootstrap_hash": await _setting(db, "build_agent_bootstrap_hash"),
        "nightly_date": await _setting(db, "build_agent_nightly_date"),
    }


async def create_bootstrap_hash(db: AsyncSession) -> str:
    from ai.vk_manager import VkManager

    manager = VkManager(db)
    try:
        ok, err = await manager.ensure_authenticated(verify_calls=False)
        if not ok:
            raise BuildAgentError(f"VK agent auth failed: {err}")
        hash_val = await manager.create_call()
        if not hash_val:
            raise BuildAgentError("VK create_call returned empty hash")
        return hash_val
    finally:
        await manager.close()


def _path_size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    if not path.is_dir():
        return 0
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def _remove_path(path: Path) -> int:
    size = _path_size(path)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.is_file():
        try:
            path.unlink()
        except OSError:
            return 0
    return size


def _cleanup_platform_workspace(platform: str) -> int:
    """Удалить артефакты сборки после публикации в update/."""
    repo = _WORKSPACE / platform
    if not repo.is_dir():
        return 0

    paths: list[Path] = []
    if platform == "pc":
        paths.extend([
            repo / "node_modules",
            repo / "dist",
            repo / "build-release-agent",
            repo / "build-output",
            repo / "resources" / "wdtt-client.exe",
        ])
        paths.extend(repo.glob("build-release-v*"))
        paths.extend(repo.glob("build-output-v*"))
        paths.extend(repo.glob("build-fresh"))
    elif platform == "android":
        paths.extend([
            repo / "app" / "build",
            repo / "app" / ".gradle",
            repo / "keystore",
            repo / "app" / "src" / "main" / "jniLibs",
        ])

    freed = 0
    for p in paths:
        if p.exists():
            freed += _remove_path(p)

    if (repo / ".git").is_dir():
        subprocess.run(
            ["git", "clean", "-fdx"],
            cwd=str(repo),
            capture_output=True,
            timeout=180,
        )

    logger.info("Build agent cleanup %s: ~%s MB freed", platform, freed // (1024 * 1024))
    return freed


def _run_shell(script: Path, platform: str, bootstrap_hash: str, timeout: int) -> str:
    env = os.environ.copy()
    env["BUILD_AGENT_ROOT"] = str(_BUILD_AGENT_ROOT)
    env["BUILD_AGENT_WORKSPACE"] = str(_WORKSPACE)
    env["BOOTSTRAP_VK_HASH"] = bootstrap_hash
    proc = subprocess.run(
        ["bash", str(script), bootstrap_hash],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        cwd=str(_BUILD_AGENT_ROOT),
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        lines = out.strip().splitlines()
        tail = "\n".join(lines[-40:]) if lines else f"exit {proc.returncode}"
        raise BuildAgentError(f"Build script failed:\n{tail[-4000:]}")
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    artifact = lines[-1] if lines else ""
    if artifact and not os.path.isabs(artifact):
        for candidate in (
            _WORKSPACE / platform / artifact,
            _BUILD_AGENT_ROOT / artifact,
        ):
            if candidate.is_file():
                artifact = str(candidate)
                break
    if artifact and not os.path.isfile(artifact) and platform == "pc":
        out_dir = _WORKSPACE / "pc" / "build-release-agent"
        if out_dir.is_dir():
            exes = sorted(out_dir.glob("*.exe"), key=os.path.getmtime, reverse=True)
            if exes:
                artifact = str(exes[0])
    if not artifact or not os.path.isfile(artifact):
        raise BuildAgentError(f"Artifact path not found in build output: {artifact!r}")
    return artifact


def _publish(platform: str, artifact_path: str, version: str) -> dict:
    original = os.path.basename(artifact_path)
    filename = _versioned_filename(version, original)
    return update_service.publish_file(platform, filename, artifact_path, version=version)


async def build_platform(
    db: AsyncSession,
    platform: str,
    *,
    force: bool = False,
    reuse_hash: str | None = None,
) -> dict:
    """Sync repo, embed new bootstrap hash, build release, publish to update/."""
    global _BUILD_RUNNING

    if platform not in update_service.PLATFORMS:
        raise BuildAgentError(f"Unknown platform: {platform}")

    if _BUILD_LOCK.locked() and not force:
        raise BuildAgentBusy("Сборка уже выполняется")

    script = _BUILD_AGENT_ROOT / f"build_{platform}.sh"
    if not script.is_file():
        raise BuildAgentError(f"Missing build script: {script}")

    async with _BUILD_LOCK:
        _BUILD_RUNNING = True
        bootstrap_hash = reuse_hash
        try:
            await set_build_log(
                db,
                f"Старт сборки {platform}…",
                status="running",
                platform=platform,
            )

            if not bootstrap_hash:
                bootstrap_hash = await create_bootstrap_hash(db)
                await set_build_log(
                    db,
                    f"Создан bootstrap-хеш для {platform}",
                    status="running",
                    platform=platform,
                    bootstrap_hash=bootstrap_hash,
                )

            timeout = int(os.environ.get("BUILD_AGENT_TIMEOUT_SEC", "3600"))
            artifact_path = await asyncio.to_thread(
                _run_shell, script, platform, bootstrap_hash, timeout,
            )

            repo = _WORKSPACE / platform
            version = _read_pc_version(repo) if platform == "pc" else _read_android_version(repo)
            info = _publish(platform, artifact_path, version)
            freed_mb = (await asyncio.to_thread(_cleanup_platform_workspace, platform)) // (1024 * 1024)

            msg = f"OK {platform} v{version} → {info['filename']}"
            if freed_mb > 0:
                msg += f", очищено ~{freed_mb} MB"
            await set_build_log(
                db,
                msg,
                status="ok",
                platform=platform,
                bootstrap_hash=bootstrap_hash,
            )
            logger.info("Build agent: %s", msg)
            return {"platform": platform, "version": version, "bootstrap_hash": bootstrap_hash, **info}
        except Exception as e:
            err = str(e)[:800]
            await set_build_log(
                db,
                f"Ошибка {platform}: {err}",
                status="error",
                platform=platform,
                bootstrap_hash=bootstrap_hash,
            )
            raise
        finally:
            _BUILD_RUNNING = False


async def run_nightly_release_builds(db: AsyncSession) -> None:
    """00:00 MSK: one bootstrap hash, rebuild PC + Android (version unchanged)."""
    from app.services.vk_agent_auth import is_agent_enabled, is_flood_cooldown

    if not await is_agent_enabled(db):
        logger.info("Nightly build skipped: VK agent disabled")
        return

    flood, until = await is_flood_cooldown(db)
    if flood:
        await set_build_log(db, f"Ночная сборка пропущена: VK flood до {until}", status="error")
        return

    bootstrap_hash = await create_bootstrap_hash(db)
    await set_build_log(
        db,
        "Ночная сборка: новый bootstrap-хеш, PC + Android…",
        status="running",
        bootstrap_hash=bootstrap_hash,
    )

    results = []
    errors = []
    for platform in ("android", "pc"):
        try:
            info = await build_platform(db, platform, force=True, reuse_hash=bootstrap_hash)
            results.append(f"{platform}=ok")
        except Exception as e:
            logger.exception("Nightly build %s failed", platform)
            errors.append(f"{platform}={e}")

    if errors:
        await set_build_log(
            db,
            f"Ночная сборка: {', '.join(results)}; ошибки: {'; '.join(errors)}",
            status="error",
            bootstrap_hash=bootstrap_hash,
        )
    else:
        await set_build_log(
            db,
            f"Ночная сборка завершена ({', '.join(results)})",
            status="ok",
            bootstrap_hash=bootstrap_hash,
        )


async def build_platform_background(platform: str) -> None:
    from app.database import AsyncSessionLocal
    from app.services.vk_agent_auth import is_agent_enabled

    try:
        async with AsyncSessionLocal() as db:
            if not await is_agent_enabled(db):
                await set_build_log(db, "Сборка отменена: AI-агент не подключён", status="error", platform=platform)
                return
            await build_platform(db, platform, force=True)
    except Exception:
        logger.exception("Background build failed for %s", platform)
