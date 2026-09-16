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
    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        request.state.request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:16]
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        log.info(
            "http",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            ms=round((time.perf_counter() - start) * 1000, 1),
            request_id=request.state.request_id,
            institution_id=str(getattr(request.state, "institution_id", "") or ""),
            user_id=str(getattr(request.state, "user_id", "") or ""),
        )
        return response


class InstitutionContextMiddleware(BaseHTTPMiddleware):
    """Resolves the tenant from X-Institution-Id / X-Institution-Slug / custom host.

    ``get_current_user`` later overrides with the JWT claim (super admins may keep the header override).
    """

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        request.state.institution_id = request.headers.get("X-Institution-Id") or None
        request.state.institution_slug = request.headers.get("X-Institution-Slug") or None
        request.state.college_id = request.headers.get("X-College-Id") or None
        host = (request.headers.get("host") or "").split(":")[0]
        if not request.state.institution_slug and host and host not in settings.PLATFORM_HOSTS:
            # <slug>.universe.septronr.com or a mapped custom domain (Phase 40 resolves domains → slug)
            request.state.institution_slug = host.split(".")[0] if host.count(".") >= 2 else host
        return await call_next(request)


class ReadOnlyModeMiddleware(BaseHTTPMiddleware):
    """Writes are refused with ``503 READ_ONLY`` platform-wide (env) or per tenant (``read_only_modes`` cached in Redis)."""

    SAFE = {"GET", "HEAD", "OPTIONS"}

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        if request.method in self.SAFE or request.url.path.startswith("/api/v1/auth"):
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
