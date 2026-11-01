"""SeptronUniverse API entrypoint (Prompts/00_PREREQUISITE_Project_Setup.md §3.3).

Run: ``uvicorn main:app --reload`` (dev) / ``gunicorn -k uvicorn.workers.UvicornWorker main:app`` (prod).
"""

import contextlib
import mimetypes
import os
import warnings
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import FastAPIDeprecationWarning, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, ORJSONResponse, RedirectResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import APIError, ErrorCode, error_response
from app.core.files import storage, verify_signed_url
from app.core.logging import configure_logging
from app.core.middleware import (
    AuditMiddleware,
    InstitutionContextMiddleware,
    ReadOnlyModeMiddleware,
    RequestLoggerMiddleware,
    TenantUsageMiddleware,
)
from app.core.ws import ws_router
from app.db.session import PlatformSessionLocal, engine, redis_client

# FastAPI 0.135 deprecates ORJSONResponse in favour of Pydantic-native serialisation; the envelope still uses it
# (Prompts/00 §3.3/§3.7). Silence only this warning so error responses do not spam the logs; revisit in Phase 44.
warnings.filterwarnings("ignore", category=FastAPIDeprecationWarning, message=".*ORJSONResponse.*")

configure_logging()
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await cast(Awaitable[bool], redis_client.ping())  # Redis is REQUIRED: fail loudly
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    # read-only windows live in the DB; the middleware reads only the Redis mirror — rebuild it on every start
    from app.services.read_only_service import ReadOnlyService

    with contextlib.suppress(Exception):  # a missing table on a fresh DB (before 0001) must not block start-up
        async with PlatformSessionLocal() as db:
            windows = await ReadOnlyService(db).refresh_cache()
            log.info("read_only_cache_refreshed", windows=windows)
    with contextlib.suppress(Exception):  # Phase 38: subscription states read by the write gate
        from app.services.saas.subscription_service import SubscriptionService

        async with PlatformSessionLocal() as db:
            log.info("subscription_state_cache_refreshed", tenants=await SubscriptionService(db).refresh_state_cache())
    yield
    await engine.dispose()
    await redis_client.aclose()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
)

# Middleware (added in reverse execution order): GZip → CORS → RequestLogger → InstitutionContext → TenantUsage →
# ReadOnly → Audit
from app.core.hardening import SecurityHeadersMiddleware  # noqa: E402

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AuditMiddleware)
app.add_middleware(ReadOnlyModeMiddleware)
app.add_middleware(TenantUsageMiddleware)
app.add_middleware(InstitutionContextMiddleware)
app.add_middleware(RequestLoggerMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError) -> ORJSONResponse:
    if exc.code == ErrorCode.IDEMPOTENT_REPLAY:
        # Idempotency-Key replay: return the stored success response (same body, 200) marked as a replay
        stored = dict(exc.details.get("response") or {})
        meta = dict(stored.get("meta") or {})
        meta["idempotent_replay"] = True
        stored["meta"] = meta
        stored.setdefault("message", ErrorCode.IDEMPOTENT_REPLAY)
        resp = ORJSONResponse(status_code=200, content=stored)
        resp.headers["Idempotent-Replayed"] = "true"
        return resp
    return error_response(request, exc.status_code, exc.code, exc.message, exc.details)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> ORJSONResponse:
    # a validator that raises ValueError leaves the exception object in ``ctx.error``; orjson cannot encode it, which
    # turned every such 422 into a 500 — keep its message instead
    errors = [
        {**e, "ctx": {k: (str(v) if isinstance(v, Exception) else v) for k, v in e["ctx"].items()}} if e.get("ctx") else e
        for e in exc.errors()
    ]
    return error_response(request, 422, ErrorCode.VALIDATION, "Request validation failed", {"errors": errors})


@app.exception_handler(IntegrityError)
async def integrity_handler(request: Request, exc: IntegrityError) -> ORJSONResponse:
    return error_response(request, 409, ErrorCode.CONFLICT, "A record with the same key already exists")


_HTTP_CODES = {401: ErrorCode.UNAUTHENTICATED, 403: ErrorCode.PERMISSION_DENIED, 404: ErrorCode.NOT_FOUND}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> ORJSONResponse:
    # Unknown routes / framework HTTP errors also use the envelope (never {"detail": …})
    code = _HTTP_CODES.get(exc.status_code, ErrorCode.INTERNAL if exc.status_code >= 500 else ErrorCode.VALIDATION)
    return error_response(request, exc.status_code, code, str(exc.detail or "Request failed"))


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception) -> ORJSONResponse:
    # error_response always attaches CORS headers (Orbit lesson: 500s were invisible to the browser)
    return error_response(request, 500, ErrorCode.INTERNAL, "Internal server error")


app.include_router(api_router, prefix="/api/v1")
app.include_router(ws_router)
from app.api.v1.endpoints import portals  # noqa: E402  (after the router registered every feature key)

# Phase 39: universal-link association files at the site root (public; outside /api/v1)
app.include_router(portals.well_known_router)
from app.api.v1.endpoints import hardening as _hardening  # noqa: E402

# Phase 43: JWK set of the RS256 signing keys (empty under HS256)
app.include_router(_hardening.well_known_router)
# Phase 40: server-rendered public sites (/site/{slug}/…), sitemap.xml and robots.txt per host
from app.api.v1.endpoints import public_website  # noqa: E402

app.include_router(public_website.site_router)
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@app.middleware("http")
async def metrics_guard(request: Request, call_next: Any) -> Any:
    """Phase 44: bearer-protected scrape (``METRICS_TOKEN``) + custom ops gauges refreshed at scrape time."""
    if request.url.path == "/metrics":
        import hmac

        token = settings.METRICS_TOKEN
        given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if token and not hmac.compare_digest(given, token):
            return error_response(request, 401, ErrorCode.UNAUTHENTICATED, "Metrics token required")
        if settings.is_production and not token:
            return error_response(request, 401, ErrorCode.UNAUTHENTICATED, "Metrics are disabled without METRICS_TOKEN")
        from app.core.ops_metrics import refresh

        with contextlib.suppress(Exception):
            await refresh()
    return await call_next(request)


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.APP_ENV}


@app.get("/ready", include_in_schema=False)
async def ready() -> ORJSONResponse:
    """DB + Redis + storage + migration head + outbox lag (RUN_AFTER_PHASE.md §5); 503 when a hard dependency fails."""
    from app.services.platform_service import PlatformService

    async with PlatformSessionLocal() as db:
        ok_, checks = await PlatformService(db).readiness()
    return ORJSONResponse(
        status_code=200 if ok_ else 503,
        content={"status": "ready" if ok_ else "degraded", "environment": settings.APP_ENV, "checks": checks},
    )


@app.get("/uploads/{key:path}", include_in_schema=False)
async def serve_upload(key: str, request: Request, sig: str | None = None, exp: int | None = None) -> Any:
    """Signed-URL gate for the local storage backend (Prompts/01 §01.6 file service).

    ``/uploads/{key}?sig=…&exp=…`` — the HMAC signature (``core/files.py``) must match and not be expired; the S3
    backend answers with a redirect to a presigned URL so clients can use one URL shape everywhere.
    """
    if not sig or not exp or not verify_signed_url(key, sig, exp):
        return error_response(request, 403, ErrorCode.PERMISSION_DENIED, "Invalid or expired file link")
    if settings.STORAGE_BACKEND == "s3":
        return RedirectResponse(storage.signed_url(key), status_code=302)
    root = Path(settings.UPLOAD_DIR).resolve()
    path = (root / key).resolve()
    if root not in path.parents or not path.is_file():
        return error_response(request, 404, ErrorCode.NOT_FOUND, "File not found")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"},
    )
