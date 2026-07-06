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
import threading
import time
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
_STOP_REQUESTED = False
_ACTIVE_PROC: Optional[subprocess.Popen] = None
_ACTIVE_PROC_LOCK = threading.Lock()

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


_MESSAGE_PREVIEW_LEN = 400
_MESSAGE_FULL_LEN = 16_000


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
    await _set_setting(db, "build_agent_message", message[:_MESSAGE_PREVIEW_LEN])
    await _set_setting(db, "build_agent_message_full", message[:_MESSAGE_FULL_LEN])
    if platform:
        await _set_setting(db, "build_agent_last_platform", platform)
    if bootstrap_hash:
        await _set_setting(db, "build_agent_bootstrap_hash", bootstrap_hash)


def is_build_running() -> bool:
    """Сборка OTA/build-agent идёт — не считать CPU Улья перегрузкой VPN."""
    return _BUILD_RUNNING


async def get_build_status(db: AsyncSession) -> dict:
    running = _BUILD_RUNNING
    nightly_pc = await _setting(db, "build_agent_nightly_pc_enabled")
    nightly_android = await _setting(db, "build_agent_nightly_android_enabled")
    return {
        "running": running,
        "stop_requested": _STOP_REQUESTED,
        "status": await _setting(db, "build_agent_status") or "idle",
        "message": await _setting(db, "build_agent_message"),
        "message_full": await _setting(db, "build_agent_message_full"),
        "last_at": await _setting(db, "build_agent_last_at"),
        "last_platform": await _setting(db, "build_agent_last_platform"),
        "bootstrap_hash": await _setting(db, "build_agent_bootstrap_hash"),
        "nightly_date": await _setting(db, "build_agent_nightly_date"),
        "nightly_pc_enabled": nightly_pc != "0",
        "nightly_android_enabled": nightly_android != "0",
    }


async def set_nightly_build_flags(
    db: AsyncSession,
    *,
    pc_enabled: Optional[bool] = None,
    android_enabled: Optional[bool] = None,
) -> dict:
    if pc_enabled is not None:
        await _set_setting(db, "build_agent_nightly_pc_enabled", "1" if pc_enabled else "0")
    if android_enabled is not None:
        await _set_setting(db, "build_agent_nightly_android_enabled", "1" if android_enabled else "0")
    return {
        "nightly_pc_enabled": (await _setting(db, "build_agent_nightly_pc_enabled")) != "0",
        "nightly_android_enabled": (await _setting(db, "build_agent_nightly_android_enabled")) != "0",
    }


async def request_stop_build(db: AsyncSession) -> dict:
    global _STOP_REQUESTED
    if not _BUILD_RUNNING:
        return {"running": False, "requested": False, "message": "Сборка сейчас не выполняется"}
    _STOP_REQUESTED = True
    with _ACTIVE_PROC_LOCK:
        proc = _ACTIVE_PROC
    if proc and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass
    await set_build_log(db, "Остановка сборки запрошена админом…", status="running")
    return {"running": True, "requested": True, "message": "Остановка запрошена"}


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


# Без wdtt-client.exe NSIS ~79 MB; полный установщик ~83 MB (см. build-agent/build_pc.sh).
_PC_MIN_INSTALLER_BYTES = int(os.environ.get("PC_MIN_INSTALLER_BYTES", "81000000"))


def _verify_pc_installer(artifact_path: str) -> None:
    size = os.path.getsize(artifact_path)
    if size < _PC_MIN_INSTALLER_BYTES:
        raise BuildAgentError(
            f"PC installer too small ({size} bytes): wdtt-client.exe likely missing "
            f"(expected >= {_PC_MIN_INSTALLER_BYTES})"
        )


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


_MIN_FREE_GB = float(os.environ.get("BUILD_AGENT_MIN_FREE_GB", "6"))
_MIN_FREE_INODES_PCT = float(os.environ.get("BUILD_AGENT_MIN_FREE_INODES_PCT", "3"))


def _check_build_disk_space() -> None:
    """Не начинать сборку при нехватке места или inodes (типичная причина KSP/Hilt mkdir fail)."""
    try:
        st = os.statvfs(_WORKSPACE if _WORKSPACE.is_dir() else _BUILD_AGENT_ROOT)
    except OSError as e:
        logger.warning("Build agent disk check skipped: %s", e)
        return

    free_bytes = st.f_bavail * st.f_frsize
    free_gb = free_bytes / (1024 ** 3)
    if free_gb < _MIN_FREE_GB:
        raise BuildAgentError(
            f"Недостаточно места на диске: {free_gb:.1f} GB свободно "
            f"(нужно >= {_MIN_FREE_GB:g} GB). Очистите VPS или увеличьте диск."
        )

    if st.f_files > 0:
        inode_free_pct = (st.f_favail / st.f_files) * 100
        if inode_free_pct < _MIN_FREE_INODES_PCT:
            raise BuildAgentError(
                f"Недостаточно inodes: {inode_free_pct:.1f}% свободно "
                f"(нужно >= {_MIN_FREE_INODES_PCT:g}%). Gradle/KSP часто падает с mkdir error."
            )


def _workspace_artifact_paths(platform: str) -> list[Path]:
    repo = _WORKSPACE / platform
    paths: list[Path] = [_BUILD_AGENT_ROOT / ".gradle-cache" / platform]
    if not repo.is_dir():
        return paths

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
            repo / ".gradle",
            repo / "build",
            repo / "keystore",
            repo / "app" / "src" / "main" / "jniLibs",
        ])
    return paths


def _cleanup_platform_workspace(platform: str, *, git_clean: bool = True) -> int:
    """Удалить артефакты сборки (build/, Gradle-кеш, node_modules и т.д.)."""
    repo = _WORKSPACE / platform
    freed = 0
    for p in _workspace_artifact_paths(platform):
        if p.exists():
            freed += _remove_path(p)

    if git_clean and (repo / ".git").is_dir():
        subprocess.run(
            ["git", "clean", "-fdx"],
            cwd=str(repo),
            capture_output=True,
            timeout=180,
        )

    freed_mb = freed // (1024 * 1024)
    if freed_mb > 0:
        logger.info("Build agent cleanup %s: ~%s MB freed", platform, freed_mb)
    return freed


def _run_shell(script: Path, platform: str, bootstrap_hash: str, timeout: int) -> str:
    global _ACTIVE_PROC
    env = os.environ.copy()
    env["BUILD_AGENT_ROOT"] = str(_BUILD_AGENT_ROOT)
    env["BUILD_AGENT_WORKSPACE"] = str(_WORKSPACE)
    env["BOOTSTRAP_VK_HASH"] = bootstrap_hash
    proc = subprocess.Popen(
        ["bash", str(script), bootstrap_hash],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        cwd=str(_BUILD_AGENT_ROOT),
    )
    with _ACTIVE_PROC_LOCK:
        _ACTIVE_PROC = proc
    start = time.monotonic()
    timed_out = False
    try:
        while proc.poll() is None:
            if _STOP_REQUESTED:
                try:
                    proc.terminate()
                    proc.wait(timeout=8)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                break
            if time.monotonic() - start > timeout:
                timed_out = True
                try:
                    proc.kill()
                except Exception:
                    pass
                break
            time.sleep(0.5)
        stdout_data, _ = proc.communicate(timeout=15)
    finally:
        with _ACTIVE_PROC_LOCK:
            _ACTIVE_PROC = None
    out = stdout_data if isinstance(stdout_data, str) else (stdout_data or "")
    if out is None:
        out = ""
    if timed_out:
        raise BuildAgentError(f"Build script timeout after {timeout}s")
    if _STOP_REQUESTED:
        raise BuildAgentError("Build stopped by admin request")
    if proc.returncode != 0:
        lines = out.strip().splitlines()
        tail = "\n".join(lines[-120:]) if lines else f"exit {proc.returncode}"
        raise BuildAgentError(f"Build script failed (exit {proc.returncode}):\n{tail[-12000:]}")
    lines = [ln.strip() for ln in out.strip().splitlines() if ln.strip()]
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
    global _BUILD_RUNNING, _STOP_REQUESTED

    if platform not in update_service.PLATFORMS:
        raise BuildAgentError(f"Unknown platform: {platform}")

    if _BUILD_LOCK.locked() and not force:
        raise BuildAgentBusy("Сборка уже выполняется")

    script = _BUILD_AGENT_ROOT / f"build_{platform}.sh"
    if not script.is_file():
        raise BuildAgentError(f"Missing build script: {script}")

    async with _BUILD_LOCK:
        _STOP_REQUESTED = False
        _BUILD_RUNNING = True
        bootstrap_hash = reuse_hash
        cleanup_freed_mb = 0
        try:
            await set_build_log(
                db,
                f"Старт сборки {platform}…",
                status="running",
                platform=platform,
            )

            await asyncio.to_thread(_check_build_disk_space)
            cleanup_freed_mb += (await asyncio.to_thread(_cleanup_platform_workspace, platform)) // (1024 * 1024)

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
            if platform == "pc":
                _verify_pc_installer(artifact_path)
            info = _publish(platform, artifact_path, version)

            msg = f"OK {platform} v{version} → {info['filename']}"
            try:
                from app.services.github_release_service import is_configured, publish_platform
                if is_configured():
                    gh = await publish_platform(platform)
                    msg += f", GitHub ✓"
                    info = {**info, "github_download_url": gh.get("download_url")}
            except Exception as gh_err:
                logger.warning("GitHub publish after build (%s): %s", platform, gh_err)
                msg += f", GitHub: {str(gh_err)[:120]}"
            if cleanup_freed_mb > 0:
                msg += f", очищено ~{cleanup_freed_mb} MB"
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
            err = str(e)
            suffix = f", очищено ~{cleanup_freed_mb} MB" if cleanup_freed_mb > 0 else ""
            await set_build_log(
                db,
                f"Ошибка {platform}: {err}{suffix}",
                status="error",
                platform=platform,
                bootstrap_hash=bootstrap_hash,
            )
            raise
        finally:
            try:
                post_freed = (await asyncio.to_thread(_cleanup_platform_workspace, platform)) // (1024 * 1024)
                if post_freed > 0:
                    cleanup_freed_mb += post_freed
                    logger.info("Build agent post-cleanup %s: ~%s MB (total ~%s MB)", platform, post_freed, cleanup_freed_mb)
            except Exception:
                logger.exception("Build agent post-cleanup failed for %s", platform)
            _BUILD_RUNNING = False
            _STOP_REQUESTED = False


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

    pc_enabled = (await _setting(db, "build_agent_nightly_pc_enabled")) != "0"
    android_enabled = (await _setting(db, "build_agent_nightly_android_enabled")) != "0"
    platforms = []
    if android_enabled:
        platforms.append("android")
    if pc_enabled:
        platforms.append("pc")
    if not platforms:
        await set_build_log(db, "Ночная сборка отключена для всех платформ", status="ok")
        return

    results = []
    errors = []
    for platform in platforms:
        try:
            info = await build_platform(db, platform, force=True, reuse_hash=bootstrap_hash)
            results.append(f"{platform}=ok")
        except Exception as e:
            logger.exception("Nightly build %s failed", platform)
            errors.append(f"{platform}={e}")

    if errors:
        failed_platform = next(
            (p for p in platforms if any(e.startswith(f"{p}=") for e in errors)),
            platforms[0],
        )
        await set_build_log(
            db,
            f"Ночная сборка: {', '.join(results)}; ошибки: {'; '.join(errors)}",
            status="error",
            platform=failed_platform,
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
