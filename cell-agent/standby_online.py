"""Решение: репорт wdtt /internal/online с соты должен попасть на Улей."""


def should_proxy_internal_online(*, queen_healthy: bool) -> bool:
    """Пока Улей жив — не глотать keepalive в локальный standby."""
    return bool(queen_healthy)


def hive_cell_id_from_manifest(manifest: dict | None) -> str:
    if not isinstance(manifest, dict):
        return ""
    return str(manifest.get("cell_id") or "").strip()
