"""SeptronUniverse API entrypoint (Prompts/00_PREREQUISITE_Project_Setup.md §3.3).

Run: ``uvicorn main:app --reload`` (dev) / ``gunicorn -k uvicorn.workers.UvicornWorker main:app`` (prod).
"""

import os
import warnings
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import FastAPIDeprecationWarning, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import APIError, ErrorCode, error_response
from app.core.logging import configure_logging
from app.core.middleware import (
    AuditMiddleware,
    InstitutionContextMiddleware,
    ReadOnlyModeMiddleware,
    RequestLoggerMiddleware,
)
from app.core.ws import ws_router
from app.db.session import engine, redis_client

# FastAPI 0.135 deprecates ORJSONResponse in favour of Pydantic-native serialisation; the envelope still uses it
# (Prompts/00 §3.3/§3.7). Silence only this warning so error responses do not spam the logs; revisit in Phase 44.
warnings.filterwarnings("ignore", category=FastAPIDeprecationWarning, message=".*ORJSONResponse.*")

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await cast(Awaitable[bool], redis_client.ping())  # Redis is REQUIRED: fail loudly
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
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

# Middleware (added in reverse execution order): GZip → CORS → RequestLogger → InstitutionContext → ReadOnly → Audit
app.add_middleware(AuditMiddleware)
app.add_middleware(ReadOnlyModeMiddleware)
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
    return error_response(request, 422, ErrorCode.VALIDATION, "Request validation failed", {"errors": exc.errors()})


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
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.APP_ENV}


@app.get("/ready", include_in_schema=False)
async def ready() -> dict[str, str]:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await cast(Awaitable[bool], redis_client.ping())
    return {"status": "ready"}
