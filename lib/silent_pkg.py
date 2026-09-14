"""Pick OpenWrt package manager: opkg on 23/24, apk on 25+."""

from __future__ import annotations


def _major(release: str) -> int | None:
    head = (release or "").strip().split(".", 1)[0]
    return int(head) if head.isdigit() else None


def pkg_kind(
    release: str = "",
    *,
    has_apk: bool = False,
    has_opkg: bool = False,
    has_apk_db: bool = False,
) -> str | None:
    major = _major(release)
    if major is not None:
        prefer = "apk" if major >= 25 else "opkg"
        fallback = "opkg" if prefer == "apk" else "apk"
        if prefer == "apk" and has_apk:
            return "apk"
        if prefer == "opkg" and has_opkg:
            return "opkg"
        if fallback == "apk" and has_apk:
            return "apk"
        if fallback == "opkg" and has_opkg:
            return "opkg"
        return None
    if has_apk and has_apk_db:
        return "apk"
    if has_opkg:
        return "opkg"
    if has_apk:
        return "apk"
    return None
