"""Map GET /api/vpn/theme (ThemeResponse) to CSS variables.

Same field names as PC/Android. Fallbacks match ThemeResponse defaults
so an older hive without new keys still paints the client look.
"""

from __future__ import annotations

from typing import Any

PUBLIC_ASSET_BASE = "https://132-243-234-162.nip.io"

_DEFAULTS = {
    "primary_color": "#000000",
    "background_color": "#FFFFFF",
    "text_color": "#000000",
    "accent_color": "#1A1A1A",
    "toggle_on_color": "#000000",
    "toggle_off_color": "#CCCCCC",
    "font_family": "Inter",
    "app_name": "Silent VPN",
    "login_link_color": "#4680C2",
    "update_bar_background_color": "#2563EB",
    "update_bar_text_color": "#FFFFFF",
    "update_bar_progress_color": "#1D4ED8",
}


def _hex(value: str, fallback: str) -> str:
    raw = (value or "").strip()
    if raw.startswith("#") and len(raw) == 7:
        try:
            int(raw[1:], 16)
            return raw.upper()
        except ValueError:
            return fallback
    return fallback


def _rgb(hex_color: str) -> tuple[int, int, int] | None:
    h = hex_color.replace("#", "").strip()
    if len(h) != 6:
        return None
    try:
        n = int(h, 16)
    except ValueError:
        return None
    return (n >> 16) & 255, (n >> 8) & 255, n & 255


def _lum(hex_color: str) -> float:
    rgb = _rgb(hex_color)
    if not rgb:
        return 0.5
    r, g, b = rgb
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def _invert(hex_color: str, fallback: str) -> str:
    rgb = _rgb(hex_color)
    if not rgb:
        return fallback
    r, g, b = rgb
    return f"#{255 - r:02X}{255 - g:02X}{255 - b:02X}"


def resolve_asset_url(path: str | None) -> str:
    raw = (path or "").strip()
    if not raw:
        return ""
    if "?" in raw:
        raw = raw.split("?", 1)[0]
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw.replace("http://132.243.234.162", PUBLIC_ASSET_BASE).replace(
            "https://132.243.234.162", PUBLIC_ASSET_BASE
        )
    rel = raw if raw.startswith("/") else f"/{raw}"
    return f"{PUBLIC_ASSET_BASE}{rel}"


def resolve_app_name(raw: str | None) -> str:
    name = (raw or "").strip()
    if not name or name.lower() == "silent":
        return "Silent VPN"
    return name


def palette(theme: dict[str, Any] | None, mode: str = "light") -> dict[str, Any]:
    t = theme or {}
    want_dark = mode == "dark"
    light_bg = _hex(t.get("background_color"), _DEFAULTS["background_color"])
    light_fg = _hex(t.get("text_color"), _DEFAULTS["text_color"])
    light_primary = _hex(t.get("primary_color"), light_fg)
    light_accent = _hex(t.get("accent_color"), _DEFAULTS["accent_color"])
    light_on = _hex(t.get("toggle_on_color"), _DEFAULTS["toggle_on_color"])
    light_off = _hex(t.get("toggle_off_color"), _DEFAULTS["toggle_off_color"])
    light_link = _hex(t.get("login_link_color"), _DEFAULTS["login_link_color"])

    def pick(dark_key: str, light_val: str, inverted: str) -> str:
        if not want_dark:
            return light_val
        d = _hex(t.get(dark_key), "")
        return d or inverted

    bg = pick("dark_background_color", light_bg, "#0B0B0F")
    fg = pick("dark_text_color", light_fg, "#F5F5F7")
    primary = pick("dark_primary_color", light_primary, _invert(light_primary, "#FFFFFF"))
    accent = pick("dark_accent_color", light_accent, _invert(light_accent, "#E5E7EB"))
    toggle_on = pick("dark_toggle_on_color", light_on, "#FFFFFF")
    toggle_off = pick("dark_toggle_off_color", light_off, "#3F3F46")
    link = pick("dark_login_link_color", light_link, "#7DD3FC")
    dark = _lum(bg) < 0.45

    font = (t.get("font_family") or _DEFAULTS["font_family"]).strip() or "Inter"
    return {
        "bg": bg,
        "fg": fg,
        "primary": primary,
        "accent": accent,
        "toggleOn": toggle_on,
        "toggleOff": toggle_off,
        "link": link,
        "dark": dark,
        "muted": f"{fg}B3" if dark else f"{fg}99",
        "border": "#2A2A32" if dark else "#E5E7EB",
        "surface": "#14141A" if dark else "#F3F4F6",
        "fieldBg": "#16161C" if dark else "#F3F4F6",
        "hint": "#9CA3AF" if dark else "#6B7280",
        "green": "#4ADE80" if dark else "#16A34A",
        "red": "#EF4444",
        "primaryBtnBg": "#FFFFFF" if dark else fg,
        "primaryBtnFg": "#000000" if dark else bg,
        "fontFamily": f"{font}, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        "appTitle": resolve_app_name(t.get("app_name")).upper(),
        "logoUrl": resolve_asset_url(t.get("logo_url")),
        "homeBgUrl": resolve_asset_url(t.get("home_bg_image_url")),
        "updateBarBg": _hex(t.get("update_bar_background_color"), _DEFAULTS["update_bar_background_color"]),
        "updateBarFg": _hex(t.get("update_bar_text_color"), _DEFAULTS["update_bar_text_color"]),
    }
