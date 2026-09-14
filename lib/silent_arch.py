"""Map OpenWrt `uname -m` to bundled wdtt-client slot."""

from __future__ import annotations


def slot_from_uname(machine: str) -> str | None:
    m = (machine or "").strip().lower()
    if m in {"aarch64", "arm64"}:
        return "aarch64"
    if m.startswith("arm"):
        return "arm"
    if m.startswith("mips"):
        return "mipsel"
    if m in {"x86_64", "amd64"}:
        return "x86_64"
    return None
