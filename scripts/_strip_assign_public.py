from pathlib import Path

p = Path(__file__).resolve().parents[1] / "app/services/olcrtc_assign.py"
lines = p.read_text(encoding="utf-8").splitlines(True)
start = next(i for i, l in enumerate(lines) if l.startswith("async def assign_public_config"))
end = next(i for i, l in enumerate(lines) if i > start and l.startswith("async def report_room_failure"))
stub = '''async def assign_public_config(
    db: AsyncSession,
    *,
    device_type: str = "",
    fingerprint: str = "",
    preferred_provider: str = "",
) -> dict[str, Any]:
    """olcrtc снят с продукта — клиентам всегда disabled (WDTT only)."""
    _ = (db, fingerprint, preferred_provider)
    return {
        "enabled": False,
        "crypto_key": "",
        "socks_host": "127.0.0.1",
        "socks_port": 8808,
        "assigned_slot": "",
        "device_type": normalize_device_type(device_type) or "",
        "pool_denied": True,
        "pool_denied_detail": "olcrtc disabled",
        "providers": {},
        "session_mode": False,
    }


'''
p.write_text("".join(lines[:start] + [stub] + lines[end:]), encoding="utf-8")
print(f"ok replaced {end - start} lines")
