"""Admin login MFA + devices (same idea as user devices: fingerprint, phone/PC name)."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import create_access_token
from app.models.admin_auth import AdminMfaChallenge, AdminSession, AdminTrustedDevice
from app.services.email_service import send_admin_mfa_code_email
from app.services.rate_limiter import get_client_ip

_JUNK_NAMES = frozenset(
    {
        "",
        "linux",
        "x11",
        "chrome",
        "browser",
        "браузер",
        "пк",
        "телефон",
        "планшет",
        "mac",
        "pc",
        "k",
        "android",
        "mobile",
    }
)


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_device_type(device_type: str | None, *, mobile_hint: bool | None, platform: str | None) -> str:
    t = (device_type or "").strip().lower()
    if t in ("phone", "android", "mobile"):
        return "phone"
    if t in ("tablet", "ipad"):
        return "tablet"
    if t in ("pc", "desktop", "windows", "mac", "macos"):
        return "pc"
    plat = (platform or "").strip().lower()
    if plat == "android" or mobile_hint is True:
        return "phone"
    if plat == "ios":
        return "phone"
    return "pc"


def _format_phone_model(model: str) -> str:
    raw = (model or "").strip()
    if not raw or raw.lower() in _JUNK_NAMES:
        return ""
    if re.match(r"^(SM-|GT-)", raw, re.I) and not re.match(r"^Samsung\s", raw, re.I):
        raw = f"Samsung {raw}"
    elif re.match(r"^Pixel", raw, re.I) and not re.match(r"^Google\s", raw, re.I):
        raw = f"Google {raw}"
    return (raw[:1].upper() + raw[1:])[:64] if raw else ""


def _parse_android_model_from_ua(ua: str) -> str:
    m = re.search(r"Android\s+[\d.]+;\s*([^;)]+)", ua or "", re.I)
    if not m:
        return ""
    model = m.group(1).strip()
    if not model or model.lower() in _JUNK_NAMES or re.match(r"^Linux", model, re.I):
        return ""
    return model


def _resolve_device_label(
    request,
    *,
    device_type: str,
    device_name: str | None,
) -> str:
    """PC → always ПК. Phone → client name / Client Hints model / UA model."""
    if device_type == "pc":
        return "ПК"
    if device_type == "tablet":
        # Prefer real model, else «Планшет»
        pass

    name = (device_name or "").strip()[:64]
    if name.lower() not in _JUNK_NAMES:
        formatted = _format_phone_model(name) if device_type in ("phone", "tablet") else name
        if formatted:
            return formatted
        if name.lower() not in _JUNK_NAMES:
            return name

    ch_model = (request.headers.get("sec-ch-ua-model") or "").strip().strip('"')
    formatted = _format_phone_model(ch_model)
    if formatted:
        return formatted

    ua, _ = _client_meta(request)
    formatted = _format_phone_model(_parse_android_model_from_ua(ua))
    if formatted:
        return formatted

    if device_type == "tablet":
        return "Планшет"
    if device_type == "phone":
        return "Телефон"
    return "ПК"


def _client_meta(request) -> tuple[str, str]:
    ua = (request.headers.get("user-agent") or "")[:512]
    ip = get_client_ip(request)[:64]
    return ua, ip


def _resolve_platform_hints(
    request,
    *,
    platform_hint: str | None = None,
    mobile_hint: bool | None = None,
) -> tuple[str | None, bool | None]:
    ch_plat = (request.headers.get("sec-ch-ua-platform") or "").strip().strip('"') or None
    mobile_raw = (request.headers.get("sec-ch-ua-mobile") or "").strip()
    ch_mobile: bool | None = None
    if mobile_raw in ("?1", "1", "true"):
        ch_mobile = True
    elif mobile_raw in ("?0", "0", "false"):
        ch_mobile = False
    plat = (platform_hint or "").strip() or ch_plat
    mobile = mobile_hint if mobile_hint is not None else ch_mobile
    return plat or None, mobile


async def find_trusted_device(
    db: AsyncSession,
    *,
    device_token: str | None = None,
    fingerprint: str | None = None,
) -> AdminTrustedDevice | None:
    by_token: AdminTrustedDevice | None = None
    by_fp: AdminTrustedDevice | None = None
    if device_token:
        token_hash = _hash_secret(device_token)
        result = await db.execute(
            select(AdminTrustedDevice).where(
                AdminTrustedDevice.token_hash == token_hash,
                AdminTrustedDevice.revoked_at.is_(None),
            )
        )
        by_token = result.scalar_one_or_none()
    fp = (fingerprint or "").strip()
    if fp:
        result = await db.execute(
            select(AdminTrustedDevice).where(
                AdminTrustedDevice.device_fingerprint == fp,
                AdminTrustedDevice.revoked_at.is_(None),
            )
        )
        by_fp = result.scalar_one_or_none()
    if by_token and by_fp and by_token.id != by_fp.id:
        # Same browser, two rows — keep token row, drop fingerprint twin
        await _revoke_device_row(db, by_fp)
        return by_token
    return by_token or by_fp


async def _revoke_device_row(db: AsyncSession, device: AdminTrustedDevice) -> None:
    now = datetime.utcnow()
    device.revoked_at = now
    await _revoke_device_sessions(db, device.id)


async def _revoke_device_sessions(db: AsyncSession, device_id: uuid.UUID) -> None:
    now = datetime.utcnow()
    result = await db.execute(
        select(AdminSession).where(
            AdminSession.device_id == device_id,
            AdminSession.revoked_at.is_(None),
        )
    )
    for s in result.scalars().all():
        s.revoked_at = now


async def _revoke_sessions_by_fingerprint(db: AsyncSession, fingerprint: str | None) -> None:
    fp = (fingerprint or "").strip()
    if not fp:
        return
    now = datetime.utcnow()
    result = await db.execute(
        select(AdminSession).where(
            AdminSession.device_fingerprint == fp,
            AdminSession.revoked_at.is_(None),
        )
    )
    for s in result.scalars().all():
        s.revoked_at = now


async def _collapse_sibling_devices(
    db: AsyncSession,
    *,
    keep: AdminTrustedDevice,
    ua: str,
    ip: str,
    dtype: str,
) -> None:
    """Drop older clones of the same browser (new fingerprint after localStorage wipe)."""
    if not ua:
        return
    now = datetime.utcnow()
    result = await db.execute(
        select(AdminTrustedDevice).where(
            AdminTrustedDevice.id != keep.id,
            AdminTrustedDevice.revoked_at.is_(None),
            AdminTrustedDevice.device_type == dtype,
            AdminTrustedDevice.user_agent == ua[:512],
            AdminTrustedDevice.ip == (ip or "")[:64],
        )
    )
    for other in result.scalars().all():
        # Re-link active sessions to keep, then revoke clone
        sres = await db.execute(
            select(AdminSession).where(
                AdminSession.device_id == other.id,
                AdminSession.revoked_at.is_(None),
            )
        )
        for s in sres.scalars().all():
            s.device_id = keep.id
            s.device_fingerprint = keep.device_fingerprint
        other.revoked_at = now


async def upsert_trusted_device(
    db: AsyncSession,
    *,
    request,
    fingerprint: str,
    device_type: str,
    device_name: str,
    platform_hint: str | None,
    mobile_hint: bool | None,
    existing_device_token: str | None,
    issue_token: bool,
) -> tuple[AdminTrustedDevice, str | None]:
    """One row per browser fingerprint — like user devices."""
    ua, ip = _client_meta(request)
    plat, mobile = _resolve_platform_hints(
        request, platform_hint=platform_hint, mobile_hint=mobile_hint,
    )
    dtype = _normalize_device_type(device_type, mobile_hint=mobile, platform=plat)
    label = _resolve_device_label(request, device_type=dtype, device_name=device_name)
    fp = (fingerprint or "").strip()[:128]

    device = await find_trusted_device(
        db, device_token=existing_device_token, fingerprint=fp,
    )
    device_token: str | None = existing_device_token if device and existing_device_token else None

    if device is None:
        device_token = secrets.token_urlsafe(32) if issue_token else None
        device = AdminTrustedDevice(
            device_fingerprint=fp or None,
            device_type=dtype,
            label=label,
            token_hash=_hash_secret(device_token) if device_token else None,
            user_agent=ua,
            ip=ip,
            last_seen_at=datetime.utcnow(),
        )
        db.add(device)
        await db.flush()
    else:
        # Avoid unique fp conflict when updating onto another row's fingerprint
        if fp and device.device_fingerprint != fp:
            clash = await db.execute(
                select(AdminTrustedDevice).where(
                    AdminTrustedDevice.device_fingerprint == fp,
                    AdminTrustedDevice.id != device.id,
                    AdminTrustedDevice.revoked_at.is_(None),
                )
            )
            twin = clash.scalar_one_or_none()
            if twin:
                await _revoke_device_row(db, twin)
        device.device_fingerprint = fp or device.device_fingerprint
        device.device_type = dtype
        # Don't overwrite a good model with generic «Телефон»
        if label.lower() not in _JUNK_NAMES or (device.label or "").lower() in _JUNK_NAMES:
            device.label = label
        device.user_agent = ua
        device.ip = ip
        device.last_seen_at = datetime.utcnow()
        if issue_token:
            if existing_device_token and device.token_hash == _hash_secret(existing_device_token):
                device_token = existing_device_token
            else:
                device_token = secrets.token_urlsafe(32)
                device.token_hash = _hash_secret(device_token)
        await db.flush()

    await _collapse_sibling_devices(db, keep=device, ua=ua, ip=ip, dtype=dtype)
    await db.flush()
    return device, device_token


async def create_admin_session(
    db: AsyncSession,
    *,
    request,
    device: AdminTrustedDevice | None = None,
    fingerprint: str | None = None,
    platform_hint: str | None = None,
    mobile_hint: bool | None = None,
    device_type: str | None = None,
    device_name: str | None = None,
) -> tuple[str, uuid.UUID]:
    ua, ip = _client_meta(request)
    plat, mobile = _resolve_platform_hints(
        request, platform_hint=platform_hint, mobile_hint=mobile_hint,
    )
    dtype = _normalize_device_type(
        device.device_type if device else device_type,
        mobile_hint=mobile,
        platform=plat,
    )
    label = (
        (device.label if device else None)
        or _resolve_device_label(request, device_type=dtype, device_name=device_name)
    )
    fp = (fingerprint or (device.device_fingerprint if device else None) or "").strip() or None

    # One active session per device / fingerprint
    if device:
        await _revoke_device_sessions(db, device.id)
    if fp:
        await _revoke_sessions_by_fingerprint(db, fp)

    jti = secrets.token_urlsafe(24)
    expires = datetime.utcnow() + timedelta(hours=settings.ADMIN_SESSION_HOURS)
    if device:
        device.last_seen_at = datetime.utcnow()
        device.ip = ip
        device.user_agent = ua
        device.label = label
        device.device_type = dtype

    session = AdminSession(
        device_id=device.id if device else None,
        token_jti=jti,
        user_agent=ua,
        label=label,
        client_platform=(plat or None),
        client_mobile=mobile,
        device_fingerprint=fp,
        ip=ip,
        expires_at=expires,
        last_seen_at=datetime.utcnow(),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    token = create_access_token(
        "admin",
        expires_delta=timedelta(hours=settings.ADMIN_SESSION_HOURS),
        jti=jti,
    )
    return token, session.id


async def revoke_session_by_jti(
    db: AsyncSession,
    jti: str | None,
    *,
    revoke_device: bool = False,
) -> bool:
    if not jti:
        return False
    result = await db.execute(select(AdminSession).where(AdminSession.token_jti == jti))
    session = result.scalar_one_or_none()
    if not session:
        return False
    return await revoke_admin_session(db, session.id, revoke_device=revoke_device)


async def start_mfa_challenge(
    db: AsyncSession,
    *,
    request,
    remember_device: bool,
    fingerprint: str | None = None,
    device_type: str | None = None,
    device_name: str | None = None,
    platform_hint: str | None = None,
    mobile_hint: bool | None = None,
) -> uuid.UUID:
    ua, ip = _client_meta(request)
    code = f"{secrets.randbelow(1_000_000):06d}"
    meta = json.dumps(
        {
            "fingerprint": (fingerprint or "").strip(),
            "device_type": device_type or "",
            "device_name": device_name or "",
            "platform": platform_hint or "",
            "mobile": mobile_hint,
        },
        ensure_ascii=False,
    )
    challenge = AdminMfaChallenge(
        code_hash=_hash_secret(code),
        user_agent=ua,
        ip=ip,
        remember_device=remember_device,
        expires_at=datetime.utcnow() + timedelta(minutes=settings.ADMIN_MFA_CODE_TTL_MINUTES),
        meta=meta,
    )
    db.add(challenge)
    await db.commit()
    await db.refresh(challenge)

    to_email = (settings.ADMIN_MFA_EMAIL or "").strip()
    if not to_email:
        raise RuntimeError("ADMIN_MFA_EMAIL is empty")
    ok = send_admin_mfa_code_email(to_email, code, ttl_minutes=settings.ADMIN_MFA_CODE_TTL_MINUTES)
    if not ok:
        challenge.consumed_at = datetime.utcnow()
        await db.commit()
        raise RuntimeError("email_send_failed")
    return challenge.id


async def resend_mfa_challenge(
    db: AsyncSession,
    *,
    request,
    challenge_id: uuid.UUID,
) -> uuid.UUID:
    """Invalidate previous challenge and send a fresh code (after TTL / user request)."""
    result = await db.execute(
        select(AdminMfaChallenge).where(AdminMfaChallenge.id == challenge_id)
    )
    old = result.scalar_one_or_none()
    if not old:
        raise ValueError("challenge_not_found")

    now = datetime.utcnow()
    # Resend only after previous code expired (2 min window for entry)
    if old.expires_at and old.expires_at > now and not old.consumed_at:
        remaining = int((old.expires_at - now).total_seconds())
        raise ValueError(f"too_early:{max(1, remaining)}")

    if not old.consumed_at:
        old.consumed_at = now
        await db.commit()

    meta: dict = {}
    if old.meta:
        try:
            meta = json.loads(old.meta)
        except Exception:
            meta = {}

    return await start_mfa_challenge(
        db,
        request=request,
        remember_device=bool(old.remember_device),
        fingerprint=meta.get("fingerprint") or None,
        device_type=meta.get("device_type") or None,
        device_name=meta.get("device_name") or None,
        platform_hint=meta.get("platform") or None,
        mobile_hint=meta.get("mobile"),
    )


async def verify_mfa_and_login(
    db: AsyncSession,
    *,
    request,
    challenge_id: uuid.UUID,
    code: str,
    remember_device: bool | None = None,
    existing_device_token: str | None = None,
    fingerprint: str | None = None,
    device_type: str | None = None,
    device_name: str | None = None,
    platform_hint: str | None = None,
    mobile_hint: bool | None = None,
) -> tuple[str, str | None, uuid.UUID]:
    result = await db.execute(
        select(AdminMfaChallenge).where(AdminMfaChallenge.id == challenge_id)
    )
    challenge = result.scalar_one_or_none()
    if not challenge or challenge.consumed_at is not None:
        raise ValueError("invalid_challenge")
    if challenge.expires_at < datetime.utcnow():
        raise ValueError("expired")
    if challenge.attempts >= settings.ADMIN_MFA_MAX_ATTEMPTS:
        raise ValueError("too_many_attempts")

    challenge.attempts += 1
    if _hash_secret(code.strip()) != challenge.code_hash:
        await db.commit()
        raise ValueError("bad_code")

    challenge.consumed_at = datetime.utcnow()
    do_remember = challenge.remember_device if remember_device is None else remember_device

    meta: dict = {}
    if challenge.meta:
        try:
            meta = json.loads(challenge.meta)
        except json.JSONDecodeError:
            meta = {}

    fp = (fingerprint or meta.get("fingerprint") or "").strip()
    dtype = device_type or meta.get("device_type") or ""
    dname = device_name or meta.get("device_name") or ""
    plat = platform_hint if platform_hint is not None else meta.get("platform")
    mobile = mobile_hint if mobile_hint is not None else meta.get("mobile")

    device: AdminTrustedDevice | None = None
    device_token: str | None = None
    if do_remember and fp:
        device, device_token = await upsert_trusted_device(
            db,
            request=request,
            fingerprint=fp,
            device_type=dtype,
            device_name=dname,
            platform_hint=plat,
            mobile_hint=mobile if isinstance(mobile, bool) else None,
            existing_device_token=existing_device_token,
            issue_token=True,
        )
    elif fp:
        # Not remembered for MFA skip, but still dedupe sessions by fingerprint
        await _revoke_sessions_by_fingerprint(db, fp)

    token, session_id = await create_admin_session(
        db,
        request=request,
        device=device,
        fingerprint=fp or None,
        platform_hint=plat,
        mobile_hint=mobile if isinstance(mobile, bool) else None,
        device_type=dtype,
        device_name=dname,
    )
    return token, device_token, session_id


async def get_valid_session(db: AsyncSession, jti: str | None) -> AdminSession | None:
    if not jti:
        return None
    result = await db.execute(select(AdminSession).where(AdminSession.token_jti == jti))
    session = result.scalar_one_or_none()
    if not session:
        return None
    if session.revoked_at is not None:
        return None
    if session.expires_at < datetime.utcnow():
        return None
    session.last_seen_at = datetime.utcnow()
    await db.commit()
    return session


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat()


async def _dedupe_trusted_devices(db: AsyncSession) -> None:
    """Collapse leftover clones (same UA+IP+type or same fingerprint)."""
    result = await db.execute(
        select(AdminTrustedDevice)
        .where(AdminTrustedDevice.revoked_at.is_(None))
        .order_by(
            AdminTrustedDevice.last_seen_at.desc().nullslast(),
            AdminTrustedDevice.created_at.desc(),
        )
    )
    devices = list(result.scalars().all())
    seen_fp: set[str] = set()
    seen_ua_ip: set[str] = set()
    now = datetime.utcnow()
    changed = False
    for d in devices:
        fp = (d.device_fingerprint or "").strip()
        ua_ip = f"{d.device_type}|{(d.ip or '').strip()}|{(d.user_agent or '')[:240]}"
        drop = False
        if fp and fp in seen_fp:
            drop = True
        elif d.user_agent and ua_ip in seen_ua_ip:
            drop = True
        if drop:
            d.revoked_at = now
            await _revoke_device_sessions(db, d.id)
            changed = True
        else:
            if fp:
                seen_fp.add(fp)
            if d.user_agent:
                seen_ua_ip.add(ua_ip)
    if changed:
        await db.commit()


async def list_admin_sessions(db: AsyncSession, current_jti: str | None) -> list[dict]:
    """Return trusted devices (one row each) — not raw sessions."""
    await _dedupe_trusted_devices(db)
    result = await db.execute(
        select(AdminTrustedDevice)
        .where(AdminTrustedDevice.revoked_at.is_(None))
        .order_by(AdminTrustedDevice.created_at.desc())
    )
    devices = result.scalars().all()
    out: list[dict] = []
    for d in devices:
        sres = await db.execute(
            select(AdminSession)
            .where(
                AdminSession.device_id == d.id,
                AdminSession.revoked_at.is_(None),
                AdminSession.expires_at > datetime.utcnow(),
            )
            .order_by(AdminSession.created_at.desc())
            .limit(1)
        )
        session = sres.scalar_one_or_none()
        is_current = bool(session and current_jti and session.token_jti == current_jti)
        dtype = d.device_type or "pc"
        type_label = {"phone": "Телефон", "tablet": "Планшет", "pc": "ПК"}.get(dtype, "ПК")
        out.append(
            {
                "id": str(session.id) if session else str(d.id),
                "device_id": str(d.id),
                "label": d.label or type_label,
                "device_type": dtype,
                "ip": (session.ip if session else d.ip) or "",
                "user_agent": d.user_agent,
                "created_at": _iso(d.created_at),
                "last_seen_at": _iso((session.last_seen_at if session else None) or d.last_seen_at or d.created_at),
                "expires_at": _iso(session.expires_at) if session else None,
                "is_current": is_current,
                "is_trusted": True,
                "online": session is not None,
            }
        )
    return out


async def list_trusted_devices(db: AsyncSession) -> list[dict]:
    return await list_admin_sessions(db, None)


async def revoke_admin_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    revoke_device: bool = False,
) -> bool:
    result = await db.execute(select(AdminSession).where(AdminSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        # Allow deleting by device id from UI (list uses device id when no session)
        dres = await db.execute(select(AdminTrustedDevice).where(AdminTrustedDevice.id == session_id))
        device = dres.scalar_one_or_none()
        if device:
            return await revoke_trusted_device(db, device.id)
        return False
    now = datetime.utcnow()
    session.revoked_at = now
    if revoke_device and session.device_id:
        await revoke_trusted_device(db, session.device_id)
        return True
    await db.commit()
    return True


async def revoke_trusted_device(db: AsyncSession, device_id: uuid.UUID) -> bool:
    result = await db.execute(select(AdminTrustedDevice).where(AdminTrustedDevice.id == device_id))
    device = result.scalar_one_or_none()
    if not device or device.revoked_at is not None:
        return False
    now = datetime.utcnow()
    device.revoked_at = now
    others = await db.execute(
        select(AdminSession).where(
            AdminSession.device_id == device.id,
            AdminSession.revoked_at.is_(None),
        )
    )
    for o in others.scalars().all():
        o.revoked_at = now
    await db.commit()
    return True
