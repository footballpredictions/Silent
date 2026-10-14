"""Map OpenWrt `uname -m` to bundled wdtt-client slot."""

from __future__ import annotations


def slot_from_uname(machine: str, *, little_endian: bool | None = None) -> str | None:
    m = (machine or "").strip().lower()
    if m in {"aarch64", "arm64"}:
        return "aarch64"
    if m in {"armv7l", "armv8l"}:
        return "arm"
    if m in {"mips", "mipsel"} and little_endian is True:
        return "mipsel"
    if m in {"x86_64", "amd64"}:
        return "x86_64"
    return None
