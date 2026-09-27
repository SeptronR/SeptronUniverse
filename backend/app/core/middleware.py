"""Request middleware — Prompts/00_PREREQUISITE_Project_Setup.md §3.9.

Execution order (main.py adds them in reverse): GZip → CORS → RequestLogger → InstitutionContext → ReadOnly → Audit.
"""

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.errors import ErrorCode, error_response

log = structlog.get_logger()
CallNext = Callable[[Request], Awaitable[Response]]


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    """Assigns ``X-Request-Id`` and binds ``request_id`` / ``institution_id`` / ``user_id`` to every log line of the request
    (structlog contextvars — Prompts/01 §01.6 ``core/logging.py``); the access line is emitted once per request."""

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        request.state.request_id = (request.headers.get("X-Request-Id") or uuid.uuid4().hex[:16])[:40]
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request.state.request_id, path=request.url.path)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            # tenant/user are resolved downstream (InstitutionContext middleware, get_current_user) — bind for the access line
            structlog.contextvars.bind_contextvars(
                institution_id=str(getattr(request.state, "institution_id", "") or ""),
                user_id=str(getattr(request.state, "user_id", "") or ""),
            )
        response.headers["X-Request-Id"] = request.state.request_id
        log.info(
            "http",
            method=request.method,
            status=response.status_code,
            ms=round((time.perf_counter() - start) * 1000, 1),
        )
        structlog.contextvars.clear_contextvars()
        return response


class InstitutionContextMiddleware(BaseHTTPMiddleware):
    """Resolves the tenant from X-Institution-Id / X-Institution-Slug / custom host / the bearer token.

    The token's ``inst`` claim is read here (Phase 02) because router-level dependencies — ``feature_required`` — and
    the read-only gate run **before** ``get_current_user``: without it a client that does not send
    ``X-Institution-Id`` would be gated against the platform defaults instead of its own tenant's flags.
    ``get_current_user`` later overrides with the user row (super admins keep the header override).
    """

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        request.state.institution_id = request.headers.get("X-Institution-Id") or None
        request.state.institution_slug = request.headers.get("X-Institution-Slug") or None
        request.state.college_id = request.headers.get("X-College-Id") or None
        host = (request.headers.get("host") or "").split(":")[0]
        if not request.state.institution_slug and host and host not in settings.PLATFORM_HOSTS:
            # <slug>.universe.septronr.com or a mapped custom domain (Phase 40 resolves domains → slug)
            request.state.institution_slug = host.split(".")[0] if host.count(".") >= 2 else host
        if not request.state.institution_id:
            request.state.institution_id = _tenant_from_token(request.headers.get("authorization"))
        return await call_next(request)


def _tenant_from_token(header: str | None) -> str | None:
    """``inst`` claim of a bearer access token (signature verified); ``None`` for anything else."""
    if not header or not header.lower().startswith("bearer "):
        return None
    from app.core.security import decode_token

    try:
        claims = decode_token(header[7:].strip(), expected_type="access")
    except Exception:  # noqa: BLE001 - an invalid/limited token simply carries no tenant; the route still authenticates
        return None
    inst = claims.get("inst")
    return str(inst) if inst else None


class ReadOnlyModeMiddleware(BaseHTTPMiddleware):
    """Writes are refused with ``503 READ_ONLY`` platform-wide (env) or per tenant (``read_only_modes`` cached in Redis)."""

    SAFE = {"GET", "HEAD", "OPTIONS"}
    # auth flows stay open (people must be able to sign in), and the read-only switch itself must remain reachable so an
    # operator can lift a window (Prompts/01 §01.8 POST /platform/read-only)
    EXEMPT_PREFIXES = ("/api/v1/auth", "/api/v1/platform/read-only")

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        if request.method in self.SAFE or request.url.path.startswith(self.EXEMPT_PREFIXES):
            return await call_next(request)
        if settings.READ_ONLY_MODE or await self._tenant_read_only(request):
            return error_response(request, 503, ErrorCode.READ_ONLY, "The platform is in read-only mode")
        return await call_next(request)

    @staticmethod
    async def _tenant_read_only(request: Request) -> bool:
        # Keys are maintained by services/read_only_service.py (Phase 01); a Redis outage never blocks writes here.
        from app.db.session import redis_client

        try:
            if await redis_client.get("ro:platform"):
                return True
            inst = getattr(request.state, "institution_id", None)
            return bool(inst and await redis_client.get(f"ro:{inst}"))
        except Exception:  # pragma: no cover - degraded Redis
            return False


class AuditMiddleware(BaseHTTPMiddleware):
    """Fallback audit for 2xx mutations that did not call ``log_audit()`` explicitly (services should always call it)."""

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        response = await call_next(request)
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and 200 <= response.status_code < 300
            and not getattr(request.state, "audited", False)
        ):
            from app.core.audit import audit_fallback

            await audit_fallback(request, response.status_code)
        return response
