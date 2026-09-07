"""Pure helpers for YuMoney notification datetime (no DB / FastAPI)."""
from __future__ import annotations

import re
from datetime import datetime, timezone

_YUMONEY_DT_RE = re.compile(
    r"""['\"]datetime['\"]\s*:\s*['\"]([^'\"]+)['\"]""",
    re.IGNORECASE,
)


def parse_yumoney_datetime(raw: str | None) -> datetime | None:
    """Парсит поле datetime из HTTP-уведомления ЮMoney → naive UTC."""
    value = (raw or "").strip()
    if not value:
        return None
    try:
        if value.endswith("Z") or value.endswith("z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def yumoney_datetime_from_notification(data: dict | None) -> datetime | None:
    if not isinstance(data, dict):
        return None
    return parse_yumoney_datetime(data.get("datetime"))


def yumoney_datetime_from_raw_response(raw_response: str | None) -> datetime | None:
    """Достаёт время оплаты из сохранённого raw_response (для старых платежей)."""
    if not raw_response:
        return None
    m = _YUMONEY_DT_RE.search(raw_response)
    if not m:
        return None
    return parse_yumoney_datetime(m.group(1))
