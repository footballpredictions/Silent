"""Restrict admin UI/API to known hosts.

Allowed:
- ADMIN_PUBLIC_HOST (public nip.io via nginx)
- WireGuard tunnel gateway 10.66.66.1 (PC/Android open admin while VPN is on —
  ISP whitelist often blocks nip.io when bypassed outside the tunnel)

Client VPN API on tunnel stays unrestricted (non-admin paths).
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings

# DNAT 10.66.66.1:8000 → api; browser Host is 10.66.66.1[:8000]
_TUNNEL_ADMIN_HOSTS = frozenset({"10.66.66.1"})


def _normalize_host(host: str) -> str:
    h = (host or "").strip().lower()
    if not h:
        return ""
    # strip port
    if h.startswith("["):
        # [::1]:8000
        end = h.find("]")
        return h[1:end] if end > 0 else h
    return h.split(":")[0]


def host_allows_admin(host_header: str) -> bool:
    host = _normalize_host(host_header)
    allowed = _normalize_host(settings.ADMIN_PUBLIC_HOST)
    if host and allowed and host == allowed:
        return True
    # VPN session: admin SPA + /api/admin/* via tunnel gateway (still login + MFA)
    if host in _TUNNEL_ADMIN_HOSTS:
        return True
    if settings.DEBUG and host in ("localhost", "127.0.0.1", "::1"):
        return True
    return False


def is_admin_surface(path: str) -> bool:
    """True if path is admin SPA or admin-only API."""
    if path.startswith("/api/admin") or path.startswith("/api/auth/admin"):
        return True
    # Non-admin API and infra
    if path.startswith("/api/"):
        return False
    if path in ("/health",) or path.startswith("/health"):
        return False
    if path.startswith("/static/") or path.startswith("/update/"):
        return False
    # Everything else is admin SPA (/, /dashboard, /assets/...)
    return True


class AdminHostGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path or "/"
        if is_admin_surface(path) and not host_allows_admin(request.headers.get("host", "")):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        response = await call_next(request)
        if host_allows_admin(request.headers.get("host", "")):
            # Ask browser to send phone model (Sec-CH-UA-Model) on next requests
            response.headers["Accept-CH"] = "Sec-CH-UA-Model, Sec-CH-UA-Platform, Sec-CH-UA-Mobile"
            response.headers["Permissions-Policy"] = (
                "ch-ua-model=(self), ch-ua-platform=(self), ch-ua-mobile=(self)"
            )
        return response
