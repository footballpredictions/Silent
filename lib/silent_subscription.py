"""Dock/subscription copy — same as PC MainScreen / Android MainScreen."""


def is_unlimited_like(profile: dict | None) -> bool:
    if not profile:
        return False
    plan = (profile.get("subscription") or {}).get("plan_type")
    return bool(profile.get("is_admin") or plan in ("unlimited", "test"))


def has_vpn_access(profile: dict | None) -> bool:
    if not profile:
        return False
    return bool(profile.get("is_admin") or (profile.get("subscription") or {}).get("is_active"))


def dock_kind(profile: dict | None) -> str | None:
    if not profile:
        return None
    sub = profile.get("subscription") or {}
    plan = sub.get("plan_type")
    if plan == "test":
        return "test"
    if profile.get("is_admin") or plan == "unlimited":
        return "unlimited"
    if sub.get("is_active") and plan == "trial":
        return "trial"
    if sub.get("is_active"):
        return "paid"
    return "pay"
