"""Админ может выдать подписку по оплате, если webhook YuMoney не дошёл."""

MANUAL_ACTIVATE_STATUSES = frozenset({"pending", "completed", "expired"})


def can_manual_activate(*, status: str | None, applied: bool, is_admin: bool) -> bool:
    if is_admin or applied:
        return False
    return (status or "").strip().lower() in MANUAL_ACTIVATE_STATUSES
