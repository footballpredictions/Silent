"""Load and normalize client UI theme from app_settings."""
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting
from app.schemas.vpn import ThemeResponse

_LEGACY_APP_NAMES = frozenset({"", "silent"})


_DEFAULT_BONUSES_INTRO = (
    "Рефералка: отправьте другу ссылку или код. Он регистрируется по ним и оплачивает любую подписку — "
    "оба получаете +30 дней. Один бонус на одного друга, до 10 наград за 30 дней.\n\n"
    "Промокод: отдельная скидка или доп. дни к тарифу — вводится при регистрации или проверяется здесь.\n\n"
    "Условия программы могут измениться."
)

# Старые дублирующие тексты → одно intro + короткие подписи
_LEGACY_REFERRAL_HINTS = frozenset({
    "поделитесь ссылкой с другом. после его регистрации и оплаты любой подписки вы оба получите +1 месяц.",
})
_LEGACY_PROMO_HINTS = frozenset({
    "введите промокод, чтобы проверить скидку к тарифу.",
})
_LEGACY_RULES_PREFIXES = (
    "друг регистрируется по вашей ссылке",
    "после оплаты приглашённым оба получают",
)


def normalize_theme_data(data: dict) -> dict:
    out = dict(data)
    name = (out.get("app_name") or "").strip()
    if name.lower() in _LEGACY_APP_NAMES:
        out["app_name"] = "Silent VPN"

    # Strip cache-bust query from asset URLs; prefer PNG over SVG for Android BitmapFactory
    for key in ("logo_url", "home_bg_image_url"):
        val = (out.get(key) or "").strip()
        if not val:
            continue
        if "?" in val:
            val = val.split("?", 1)[0]
        if key == "logo_url" and val.lower().endswith(".svg"):
            val = "/static/logo.png"
        out[key] = val

    intro = (out.get("bonuses_intro_text") or "").strip()
    rules = (out.get("bonuses_rules_text") or "").strip()
    ref_hint = (out.get("bonuses_referral_hint") or "").strip()
    promo_hint = (out.get("bonuses_promo_hint") or "").strip()

    if not intro:
        if rules and rules.lower().startswith(_LEGACY_RULES_PREFIXES):
            out["bonuses_intro_text"] = _DEFAULT_BONUSES_INTRO
            out["bonuses_rules_text"] = ""
        elif rules:
            out["bonuses_intro_text"] = rules
            out["bonuses_rules_text"] = ""
        else:
            out["bonuses_intro_text"] = _DEFAULT_BONUSES_INTRO
    elif rules and rules.lower().startswith(_LEGACY_RULES_PREFIXES):
        # Убрать дубль внизу, если intro уже есть
        out["bonuses_rules_text"] = ""

    if ref_hint.lower() in _LEGACY_REFERRAL_HINTS or not ref_hint:
        out["bonuses_referral_hint"] = "Скопируйте и отправьте другу"
    if promo_hint.lower() in _LEGACY_PROMO_HINTS or not promo_hint:
        out["bonuses_promo_hint"] = "Проверить скидку к тарифу"
    if not (out.get("bonuses_referral_title") or "").strip() or (
        (out.get("bonuses_referral_title") or "").strip() == "Реферальная ссылка"
    ):
        out["bonuses_referral_title"] = "Ваша ссылка"

    return out


def theme_needs_migration(data: dict) -> bool:
    if (data.get("app_name") or "").strip().lower() in _LEGACY_APP_NAMES:
        return True
    logo = (data.get("logo_url") or "").strip()
    if "?" in logo or logo.lower().endswith(".svg"):
        return True
    home = (data.get("home_bg_image_url") or "").strip()
    if "?" in home:
        return True
    if not (data.get("bonuses_intro_text") or "").strip():
        return True
    rules = (data.get("bonuses_rules_text") or "").strip().lower()
    if rules.startswith(_LEGACY_RULES_PREFIXES):
        return True
    ref = (data.get("bonuses_referral_hint") or "").strip().lower()
    if ref in _LEGACY_REFERRAL_HINTS:
        return True
    return False


async def load_theme(db: AsyncSession, *, persist_migration: bool = False) -> ThemeResponse:
    result = await db.execute(select(AppSetting).where(AppSetting.key == "theme"))
    setting = result.scalar_one_or_none()
    theme: ThemeResponse
    if not setting:
        theme = ThemeResponse()
    else:
        try:
            raw = json.loads(setting.value)
            normalized = normalize_theme_data(raw)
            # Автомиграция bonuses-текстов на проде (без дублей в UI)
            should_persist = persist_migration or theme_needs_migration(raw)
            if should_persist and normalized != raw:
                setting.value = json.dumps(normalized, ensure_ascii=False)
                await db.commit()
            theme = ThemeResponse(**normalized)
        except Exception:
            theme = ThemeResponse()

    if not (theme.hive_standby_api_urls or "").strip():
        try:
            from app.services.hive_standby import standby_api_urls

            urls = await standby_api_urls(db)
            if urls:
                theme.hive_standby_api_urls = ",".join(urls)
        except Exception:
            pass
    return theme
