# PREREQUISITE — PROJECT SETUP & FILE STRUCTURE

## Context
You are building **SeptronUniverse**, a production-grade, multi-tenant **College & University ERP**.
Stack: **FastAPI (Python 3.12) · SQLAlchemy 2 async · Alembic · PostgreSQL 15+ (RLS) · Redis 7 · Celery 5 | React 18 (TypeScript) · Vite · Tailwind · Radix | Flutter 3.22+**

This is the very first step. Create the entire monorepo skeleton — every folder, config and boilerplate file below — so that every subsequent phase prompt builds on one consistent, working foundation. The canonical table/column names live in `Database_Schema.sql`; the design authority is `docs/`. Everything here mirrors SeptronOrbit's architecture with the hardening recorded in `docs/Technical_Architecture.md` and `docs/ADR/`.

---

## 1. Technology stack reference

| Layer | Technology |
|---|---|
| Backend framework | FastAPI (async), uvicorn (dev) / gunicorn + uvicorn workers (prod) |
| ORM / migrations | SQLAlchemy 2.x async (asyncpg) + Alembic (single head, expand/contract) |
| Database | PostgreSQL 15+ with Row-Level Security, partitions, `pg_trgm` |
| Cache / queue / realtime | Redis 7 (Celery broker + result, cache, pub/sub for WebSocket, rate limits, idempotency) |
| Background work | Celery 5 (queues `notifications, emails, documents, reports, integrations, scheduled`) + Beat; transactional outbox in `domain_events` |
| Auth | JWT access (15 min, memory) + refresh (7 d, httpOnly cookie, rotation), JTI blacklist, OTP, TOTP MFA, sessions, SSO hooks |
| Authorization | feature flags → permissions → role scopes → row-level visibility resolver → PII masking (`docs/Authorization_and_Visibility.md`) |
| Files | Local (dev) / S3-compatible (prod), per-tenant prefixes, signed URLs |
| PDF | WeasyPrint + Jinja2 (bilingual templates) |
| Comms | SMS (MSG91/Twilio, DLT), WhatsApp (Meta), Email (SMTP/SendGrid/SES), Push (FCM/WebPush) |
| Validation | Pydantic v2 |
| Observability | Prometheus instrumentator, Sentry, JSON logs with request/tenant/user ids, Flower |
| Frontend | React 18 + TypeScript + Vite, React Router v6, TanStack Query v5, Zustand, Tailwind + Radix primitives, react-hook-form + zod, TanStack Table v8, Recharts, FullCalendar, dnd-kit, TipTap, Lucide, date-fns, sonner, react-i18next (scaffold), openapi-typescript (generated types) |
| Mobile | Flutter 3.22+, Riverpod, go_router, dio, drift (offline), flutter_secure_storage, firebase_messaging (see `docs/Mobile_App_UI_Structure.md`) |
| Verification | API scripts (PowerShell/httpx) + Playwright UI suites; structural guards in CI (no unit-test suites) |
| Containers / CI | Docker Compose; GitHub Actions → `ghcr.io/septronr/universe-api` → `orbit-infra` |

---

## 2. Monorepo structure to create

```
SeptronUniverse/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── api/v1/
│   │   │   ├── __init__.py
│   │   │   ├── router.py                  ← aggregates module routers with feature_required()
│   │   │   ├── public.py                  ← PUBLIC_ROUTES registry (no auth)
│   │   │   └── endpoints/                 ← one file per module (added by phases)
│   │   ├── core/
│   │   │   ├── config.py                  ← Settings (pydantic-settings)
│   │   │   ├── security.py                ← JWT (kid rotation), bcrypt, TOTP, tokens
│   │   │   ├── middleware.py              ← RequestLogger, InstitutionContext, ReadOnlyMode, Audit fallback
│   │   │   ├── errors.py                  ← APIError + error-code catalogue
│   │   │   ├── features.py                ← feature registry + feature_required()
│   │   │   ├── authz/
│   │   │   │   ├── dependencies.py        ← get_current_user, permission_required, get_scopes
│   │   │   │   ├── visibility.py          ← VisibilityResolver + ownership link registry
│   │   │   │   └── masking.py             ← mask_pii()
│   │   │   ├── packs/                     ← regulatory packs registry (IN, GENERIC)
│   │   │   ├── events.py                  ← domain events (transactional outbox)
│   │   │   ├── idempotency.py             ← Idempotency-Key dependency
│   │   │   ├── jobs.py                    ← background_jobs helper + @job decorator
│   │   │   ├── workflow/engine.py         ← approval-workflow engine
│   │   │   ├── audit.py                   ← log_audit()
│   │   │   ├── tenancy.py                 ← timezone/locale/currency helpers
│   │   │   ├── files.py                   ← storage abstraction (local/S3, signed URLs)
│   │   │   ├── rate_limit.py              ← Redis fixed-window limiter + captcha
│   │   │   ├── ws.py                      ← WebSocket manager (Redis pub/sub)
│   │   │   └── logging.py                 ← JSON logging
│   │   ├── db/session.py                  ← engine, Base, get_db (sets RLS context)
│   │   ├── models/
│   │   │   ├── __init__.py                ← imports every model module (Alembic autogenerate)
│   │   │   ├── base.py                    ← mixins
│   │   │   └── platform.py                ← institutions, colleges, users, roles, features, jobs, events, workflow …
│   │   ├── schemas/                       ← by domain (never by phase)
│   │   ├── repositories/base.py           ← BaseRepository
│   │   ├── services/                      ← business logic
│   │   ├── integrations/registry.py       ← adapter registry + mocks
│   │   ├── tasks/
│   │   │   ├── celery_app.py
│   │   │   ├── outbox.py                  ← relay task
│   │   │   └── beat.py                    ← Beat schedule catalogue
│   │   ├── templates/                     ← Jinja2 HTML for PDFs
│   │   └── utils/{response.py, pagination.py, sequences.py}
│   ├── alembic/{env.py, script.py.mako, versions/}
│   ├── scripts/
│   │   ├── check_schema_drift.py          ← Base.metadata vs Database_Schema.sql
│   │   ├── check_authz_coverage.py        ← every route has permission + feature or is public
│   │   ├── check_feature_registry.py      ← registry ↔ docs/Feature_Flags.md ↔ DB seed
│   │   ├── gen_access_matrix.py           ← route × role CSV
│   │   ├── export_openapi.py
│   │   ├── scaffold_module.py             ← generates module skeleton
│   │   ├── seed_platform.py               ← permissions, role templates, features, plans, packs
│   │   ├── seed_demo_institution.py       ← --type university|autonomous|affiliated  --only <module>
│   │   └── verify/                        ← per-phase API verification scripts (.ps1 / .py)
│   ├── main.py · Dockerfile · docker-entrypoint.sh · requirements.txt · requirements-dev.txt · .env.example · alembic.ini · pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── api/{axios.ts, generated/openapi.d.ts}
│   │   ├── store/{authStore.ts, sessionStore.ts, notificationStore.ts}
│   │   ├── hooks/{usePermission.ts, useFeature.ts, useVisibility.ts}
│   │   ├── routes/{index.tsx, PrivateRoute.tsx, PermissionRoute.tsx, FeatureRoute.tsx, PortalRoute.tsx, SuperAdminRoute.tsx, AdminShellRoute.tsx}
│   │   ├── components/{ui, shared, layout, charts}
│   │   ├── features/<module>/{api.ts, hooks.ts, pages/, components/, types.ts}
│   │   ├── lib/{queryClient.ts, push.ts, captcha.ts, payments.ts, i18n.ts}
│   │   ├── utils/{constants.ts, formatters.ts, validators.ts, cn.ts}
│   │   ├── nav.ts                         ← NAV_GROUPS (permission + feature gated)
│   │   └── main.tsx · App.tsx · index.css
│   ├── public/{manifest.json, sw.js, icons/}
│   ├── package.json · vite.config.ts · tsconfig.json · tailwind.config.ts · postcss.config.js · index.html · .env.example
├── flutter/                               ← created in Phase 42 (pubspec + core skeleton described in docs/Mobile_App_UI_Structure.md)
├── e2e/                                   ← Playwright suites per round
├── nginx/nginx.conf
├── docker-compose.yml · docker-compose.prod.yml
├── .github/workflows/{build.yml, frontend-build.yml, frontend-deploy.yml, guards.yml}
├── .claude/launch.json
├── Database_Schema.sql · Architecture.md · docs/ · Prompts/ · RUN_AFTER_PHASE.md · QA_Test_Plan.md · Real_World_Launch_Plan.md
└── .gitignore · README.md
```

---

## 3. Backend files to generate

### 3.1 `backend/requirements.txt`
```
fastapi==0.135.3
starlette==0.52.1
uvicorn[standard]==0.44.0
gunicorn==25.3.0
SQLAlchemy[asyncio]==2.0.49
asyncpg==0.31.0
alembic==1.18.4
pydantic==2.13.0
pydantic-settings==2.13.1
email-validator==2.3.0
python-multipart==0.0.26
python-jose[cryptography]==3.5.0
bcrypt==5.0.0
pyotp==2.9.0
redis==7.4.0
celery==5.6.3
flower==2.0.1
httpx==0.28.1
aiofiles==25.1.0
boto3==1.42.89
weasyprint==68.1
Jinja2==3.1.6
openpyxl==3.1.5
pillow==12.2.0
qrcode==8.2
icalendar==7.0.3
python-slugify==8.0.4
python-magic==0.4.27
orjson==3.11.3
prometheus-fastapi-instrumentator==7.1.0
sentry-sdk[fastapi]==2.42.0
structlog==25.5.0
websockets==16.0
python-dotenv==1.2.2
```
`backend/requirements-dev.txt`: `ruff==0.14.2`, `black==25.9.0`, `mypy==1.19.0`, `import-linter==2.6`, `pip-audit==2.9.0`, `bandit==1.8.6`, `httpx==0.28.1` (for verification scripts).

### 3.2 `backend/.env.example`
```
# Application
APP_NAME=SeptronUniverse
APP_ENV=development                 # development | demo | production
SECRET_KEY=change-me-64-hex
JWT_KID=k1
JWT_PREVIOUS_KEYS={}                # {"k0":"old-secret"} during rotation
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
ALLOWED_ORIGINS=["http://localhost:5173"]
PLATFORM_HOSTS=["localhost","universe.septronr.com"]
READ_ONLY_MODE=false
# Database (app role is NOT BYPASSRLS; platform role for cross-tenant super-admin queries)
DATABASE_URL=postgresql+asyncpg://universe_app:pass@localhost:5432/universe
PLATFORM_DATABASE_URL=postgresql+asyncpg://universe_platform:pass@localhost:5432/universe
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
# Redis (required)
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
# Storage
STORAGE_BACKEND=local               # local | s3
UPLOAD_DIR=./uploads
S3_BUCKET= S3_REGION= S3_ENDPOINT_URL= AWS_ACCESS_KEY_ID= AWS_SECRET_ACCESS_KEY=
SIGNED_URL_TTL_SECONDS=900
# Integrations (per-tenant overrides live in integration_connections; these are platform defaults / sandbox)
SMS_PROVIDER=mock  WHATSAPP_PROVIDER=mock  EMAIL_PROVIDER=mock  PUSH_PROVIDER=mock  PAYMENT_PROVIDER=mock
SMTP_HOST= SMTP_PORT=587 SMTP_USER= SMTP_PASSWORD= EMAIL_FROM=noreply@universe.local
MSG91_AUTH_KEY= TWILIO_ACCOUNT_SID= TWILIO_AUTH_TOKEN=
META_WA_TOKEN= META_WA_PHONE_ID= META_APP_SECRET=
FCM_CREDENTIALS_JSON= VAPID_PUBLIC_KEY= VAPID_PRIVATE_KEY=
RAZORPAY_KEY_ID= RAZORPAY_KEY_SECRET= RAZORPAY_WEBHOOK_SECRET=
CAPTCHA_PROVIDER=none  CAPTCHA_SECRET=
INTEGRATION_ENCRYPTION_KEY=base64-32-bytes
# Observability
SENTRY_DSN=
LOG_LEVEL=INFO
# Platform bootstrap
INSTALL_SECRET_KEY=change-me
SUPERADMIN_EMAIL=superadmin@universe.local
```

### 3.3 `backend/main.py`
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import APIError, error_response
from app.core.logging import configure_logging
from app.core.middleware import AuditMiddleware, InstitutionContextMiddleware, ReadOnlyModeMiddleware, RequestLoggerMiddleware
from app.core.ws import ws_router
from app.db.session import engine, redis_client

configure_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await redis_client.ping()                      # Redis is REQUIRED: fail loudly
    import os; os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    yield
    await engine.dispose(); await redis_client.aclose()

app = FastAPI(title=settings.APP_NAME, version="0.1.0", lifespan=lifespan, default_response_class=ORJSONResponse,
              openapi_url="/api/v1/openapi.json", docs_url="/api/v1/docs", redoc_url="/api/v1/redoc")

# Middleware (added in reverse execution order): GZip → CORS → RequestLogger → InstitutionContext → ReadOnly → Audit
app.add_middleware(AuditMiddleware)
app.add_middleware(ReadOnlyModeMiddleware)
app.add_middleware(InstitutionContextMiddleware)
app.add_middleware(RequestLoggerMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=settings.ALLOWED_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)

@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError):
    return error_response(request, exc.status_code, exc.code, exc.message, exc.details)

@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return error_response(request, 422, "VALIDATION", "Request validation failed", {"errors": exc.errors()})

@app.exception_handler(IntegrityError)
async def integrity_handler(request: Request, exc: IntegrityError):
    return error_response(request, 409, "CONFLICT", "A record with the same key already exists")

@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    # error_response always attaches CORS headers (Orbit lesson: 500s were invisible to the browser)
    return error_response(request, 500, "INTERNAL", "Internal server error")

app.include_router(api_router, prefix="/api/v1")
app.include_router(ws_router)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok", "environment": settings.APP_ENV}

@app.get("/ready", include_in_schema=False)
async def ready():
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await redis_client.ping()
    return {"status": "ready"}
```

### 3.4 `backend/app/core/config.py`
```python
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    APP_NAME: str = "SeptronUniverse"; APP_ENV: str = "development"
    SECRET_KEY: str; JWT_KID: str = "k1"; JWT_PREVIOUS_KEYS: dict[str, str] = {}
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15; REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALLOWED_ORIGINS: list[str] = ["http://localhost:5173"]; PLATFORM_HOSTS: list[str] = ["localhost"]
    READ_ONLY_MODE: bool = False
    DATABASE_URL: str; PLATFORM_DATABASE_URL: str | None = None; DB_POOL_SIZE: int = 10; DB_MAX_OVERFLOW: int = 20
    REDIS_URL: str; CELERY_BROKER_URL: str; CELERY_RESULT_BACKEND: str
    STORAGE_BACKEND: str = "local"; UPLOAD_DIR: str = "./uploads"; S3_BUCKET: str | None = None; S3_REGION: str | None = None
    S3_ENDPOINT_URL: str | None = None; AWS_ACCESS_KEY_ID: str | None = None; AWS_SECRET_ACCESS_KEY: str | None = None; SIGNED_URL_TTL_SECONDS: int = 900
    SMS_PROVIDER: str = "mock"; WHATSAPP_PROVIDER: str = "mock"; EMAIL_PROVIDER: str = "mock"; PUSH_PROVIDER: str = "mock"; PAYMENT_PROVIDER: str = "mock"
    INTEGRATION_ENCRYPTION_KEY: str; CAPTCHA_PROVIDER: str = "none"; CAPTCHA_SECRET: str | None = None
    SENTRY_DSN: str | None = None; LOG_LEVEL: str = "INFO"
    INSTALL_SECRET_KEY: str; SUPERADMIN_EMAIL: str = "superadmin@universe.local"

    @field_validator("DATABASE_URL", "PLATFORM_DATABASE_URL", mode="before")
    @classmethod
    def _asyncpg(cls, v):
        return v.replace("postgres://", "postgresql+asyncpg://").replace("postgresql://", "postgresql+asyncpg://") if v else v

settings = Settings()
```

### 3.5 `backend/app/db/session.py`
```python
import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from fastapi import Request
from app.core.config import settings

engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_size=settings.DB_POOL_SIZE, max_overflow=settings.DB_MAX_OVERFLOW, pool_recycle=1800)
platform_engine = create_async_engine(settings.PLATFORM_DATABASE_URL or settings.DATABASE_URL, pool_pre_ping=True, pool_size=2, max_overflow=2)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
PlatformSessionLocal = async_sessionmaker(platform_engine, class_=AsyncSession, expire_on_commit=False)
redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

class Base(DeclarativeBase):
    pass

async def get_db(request: Request):
    """Tenant session: sets the RLS context from request.state.institution_id inside the transaction."""
    async with SessionLocal() as session:
        try:
            inst = getattr(request.state, "institution_id", None)
            if inst:
                await session.execute(text("SET LOCAL app.institution_id = :i"), {"i": str(inst)})
            yield session
            await session.commit()
        except Exception:
            await session.rollback(); raise

async def get_platform_db():
    """Cross-tenant session (super admin / support): BYPASSRLS role; every use is audited."""
    async with PlatformSessionLocal() as session:
        try:
            yield session; await session.commit()
        except Exception:
            await session.rollback(); raise

async def tenant_session(institution_id):
    """For Celery tasks: `async with tenant_session(iid) as db:` — sets RLS context explicitly."""
    session = SessionLocal()
    await session.execute(text("SET LOCAL app.institution_id = :i"), {"i": str(institution_id)})
    return session
```

### 3.6 `backend/app/models/base.py`
```python
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

class SoftDeleteMixin:
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

class OptimisticLockMixin:
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __mapper_args__ = {"version_id_col": None}   # version is bumped by the DB trigger; services compare on update

class TenantMixin:
    @declared_attr
    def institution_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True)

class CollegeScopedMixin:
    @declared_attr
    def college_id(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("colleges.id", ondelete="CASCADE"), index=True)

class CreatedByMixin:
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

# Standard base for editable tenant masters
class TenantModelMixin(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, OptimisticLockMixin, CreatedByMixin):
    pass
```

### 3.7 `backend/app/core/errors.py`
```python
from fastapi import Request
from fastapi.responses import ORJSONResponse
from app.core.config import settings

class ErrorCode:
    VALIDATION = "VALIDATION"; NOT_FOUND = "NOT_FOUND"; CONFLICT = "CONFLICT"; STALE_VERSION = "STALE_VERSION"
    PERMISSION_DENIED = "PERMISSION_DENIED"; FEATURE_DISABLED = "FEATURE_DISABLED"; UNAUTHENTICATED = "UNAUTHENTICATED"
    READ_ONLY = "READ_ONLY"; RATE_LIMITED = "RATE_LIMITED"; IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"
    HOLD_BLOCKED = "HOLD_BLOCKED"; RECORD_LOCKED = "RECORD_LOCKED"; RULE_VIOLATION = "RULE_VIOLATION"
    INTEGRATION_FAILED = "INTEGRATION_FAILED"; MFA_REQUIRED = "MFA_REQUIRED"; INTERNAL = "INTERNAL"

class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict | None = None):
        self.status_code, self.code, self.message, self.details = status_code, code, message, details or {}

def error_response(request: Request, status: int, code: str, message: str, details: dict | None = None) -> ORJSONResponse:
    body = {"success": False, "error": {"code": code, "message": message, "details": details or {}}, "request_id": getattr(request.state, "request_id", None)}
    resp = ORJSONResponse(status_code=status, content=body)
    origin = request.headers.get("origin")
    if origin and (origin in settings.ALLOWED_ORIGINS or "*" in settings.ALLOWED_ORIGINS):
        resp.headers["Access-Control-Allow-Origin"] = origin; resp.headers["Access-Control-Allow-Credentials"] = "true"; resp.headers["Vary"] = "Origin"
    return resp
```

### 3.8 `backend/app/utils/response.py` and `pagination.py`
```python
# response.py
from typing import Any
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

class PaginationMeta(BaseModel):
    page: int; page_size: int; total: int; total_pages: int

class VisibilityMeta(BaseModel):
    self: bool = False; scopes: list[str] = []; default: str = "self"; pii: bool = False

def ok(data: Any = None, message: str | None = None, *, pagination: PaginationMeta | None = None, visibility: VisibilityMeta | None = None, extra: dict | None = None) -> dict:
    meta: dict = {}
    if pagination: meta["pagination"] = pagination.model_dump()
    if visibility: meta["visibility"] = visibility.model_dump()
    if extra: meta.update(extra)
    return {"success": True, "data": jsonable_encoder(data), "message": message, "meta": meta}

# pagination.py
from fastapi import Query
from pydantic import BaseModel

class PageParams(BaseModel):
    page: int = 1; page_size: int = 25; sort: str | None = None
    @property
    def offset(self) -> int: return (self.page - 1) * self.page_size

def page_params(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200), sort: str | None = Query(None, pattern=r"^-?[a-z_]+$")) -> PageParams:
    return PageParams(page=page, page_size=page_size, sort=sort)
```
API conventions enforced everywhere: `page/page_size ≤ 200`, `sort=-field`, `filter[field][op]=value` (`eq, ne, in, lt, lte, gt, gte, like`), `include=` expansions, `fields=` sparse fields, `/bulk` endpoints return `{succeeded:[], failed:[{index, code, message}]}`, downloads via job → signed URL, `Idempotency-Key` on non-idempotent POSTs, `If-Match: <version>` on masters (`409 STALE_VERSION`).

### 3.9 `backend/app/core/middleware.py`
```python
import time, uuid, structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from app.core.config import settings
from app.core.errors import error_response
log = structlog.get_logger()

class RequestLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:16]
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        log.info("http", method=request.method, path=request.url.path, status=response.status_code, ms=round((time.perf_counter()-start)*1000, 1),
                 request_id=request.state.request_id, institution_id=str(getattr(request.state, "institution_id", "")), user_id=str(getattr(request.state, "user_id", "")))
        return response

class InstitutionContextMiddleware(BaseHTTPMiddleware):
    """Resolves the tenant from X-Institution-Id / X-Institution-Slug / custom host. get_current_user later overrides with the JWT claim."""
    async def dispatch(self, request: Request, call_next):
        request.state.institution_id = request.headers.get("X-Institution-Id") or None
        request.state.institution_slug = request.headers.get("X-Institution-Slug") or None
        request.state.college_id = request.headers.get("X-College-Id") or None
        return await call_next(request)

class ReadOnlyModeMiddleware(BaseHTTPMiddleware):
    SAFE = {"GET", "HEAD", "OPTIONS"}
    async def dispatch(self, request: Request, call_next):
        if request.method not in self.SAFE and settings.READ_ONLY_MODE and not request.url.path.startswith("/api/v1/auth"):
            return error_response(request, 503, "READ_ONLY", "The platform is in read-only mode")
        return await call_next(request)

class AuditMiddleware(BaseHTTPMiddleware):
    """Fallback audit for 2xx mutations that did not call log_audit() explicitly (services should always call it)."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and 200 <= response.status_code < 300 and not getattr(request.state, "audited", False):
            from app.core.audit import audit_fallback; await audit_fallback(request, response.status_code)
        return response
```
Per-tenant read-only mode is checked in `ReadOnlyModeMiddleware` via `read_only_modes` (cached in Redis) after the tenant is known.

### 3.10 `backend/app/core/features.py`
```python
from dataclasses import dataclass, field
from fastapi import Depends, Request
from app.core.errors import APIError, ErrorCode
from app.db.session import redis_client

@dataclass(frozen=True)
class FeatureDef:
    key: str; group: str; name: str; description: str = ""; default_enabled: bool = True
    min_plan_tier: str = "starter"; depends_on: tuple[str, ...] = field(default_factory=tuple); is_core: bool = False

FEATURE_REGISTRY: dict[str, FeatureDef] = {}

def register_feature(**kw) -> FeatureDef:
    f = FeatureDef(**kw); assert f.key not in FEATURE_REGISTRY, f"duplicate feature {f.key}"; FEATURE_REGISTRY[f.key] = f; return f

async def effective_features(institution_id) -> set[str]:
    """Cached per institution (60 s); invalidated by the feature_flag.changed event."""
    cached = await redis_client.smembers(f"features:{institution_id}")
    if cached: return set(cached)
    from app.services.feature_service import compute_effective_features
    keys = await compute_effective_features(institution_id)
    if keys:
        await redis_client.sadd(f"features:{institution_id}", *keys); await redis_client.expire(f"features:{institution_id}", 60)
    return keys

def feature_required(key: str):
    assert key in FEATURE_REGISTRY, f"unregistered feature {key}"
    async def _dep(request: Request):
        inst = getattr(request.state, "institution_id", None)
        if FEATURE_REGISTRY[key].is_core: return
        if not inst or key not in await effective_features(inst):
            raise APIError(403, ErrorCode.FEATURE_DISABLED, f"Feature '{key}' is not enabled", {"feature": key})
    return Depends(_dep)

# Core keys registered here; every phase registers its own keys in app/features/<module>.py (imported by app/features/__init__.py)
for k, g, n in [("core.auth","core","Authentication"),("core.rbac","core","Roles & permissions"),("core.institution","core","Institution structure"),
                ("core.settings","core","Settings"),("core.audit_logs","core","Audit logs"),("core.dashboard","core","Dashboards"),
                ("core.notifications_inapp","core","In-app notifications"),("core.background_jobs","core","Background jobs")]:
    register_feature(key=k, group=g, name=n, is_core=True)
```

### 3.11 `backend/app/core/authz/dependencies.py`
```python
import uuid
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import APIError, ErrorCode
from app.core.security import decode_token
from app.db.session import get_db, redis_client

bearer = HTTPBearer(auto_error=False)

class Principal:
    """Resolved once per request: user row, role slugs, flat permissions ('module:action'), scopes [(scope_type, scope_id)], features."""
    def __init__(self, user, roles, permissions: set[str], scopes: list[tuple[str, uuid.UUID | None]], features: set[str], impersonator_id=None):
        self.user, self.roles, self.permissions, self.scopes, self.features, self.impersonator_id = user, roles, permissions, scopes, features, impersonator_id
    @property
    def id(self): return self.user.id
    @property
    def institution_id(self): return self.user.institution_id
    @property
    def is_super_admin(self): return bool(self.user.is_super_admin)
    def has(self, module: str, action: str) -> bool:
        return self.is_super_admin or f"{module}:{action}" in self.permissions or f"{module}:manage" in self.permissions
    def has_feature(self, key: str) -> bool: return key in self.features

async def get_current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: AsyncSession = Depends(get_db)) -> Principal:
    if not creds: raise APIError(401, ErrorCode.UNAUTHENTICATED, "Missing bearer token")
    claims = decode_token(creds.credentials, expected_type="access")
    if await redis_client.exists(f"blacklist:jti:{claims['jti']}"): raise APIError(401, ErrorCode.UNAUTHENTICATED, "Token revoked")
    from app.services.auth_service import load_principal
    principal = await load_principal(db, uuid.UUID(claims["sub"]), request)
    # Tenant context comes from the user row (super admins may override via X-Institution-Id); re-apply RLS for this transaction
    request.state.institution_id = principal.institution_id if not principal.is_super_admin else (request.state.institution_id or principal.institution_id)
    request.state.user_id = principal.id
    from sqlalchemy import text
    if request.state.institution_id: await db.execute(text("SET LOCAL app.institution_id = :i"), {"i": str(request.state.institution_id)})
    return principal

def permission_required(module: str, action: str):
    async def _dep(principal: Principal = Depends(get_current_user)) -> Principal:
        if not principal.has(module, action):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, f"Requires {module}:{action}", {"module": module, "action": action})
        return principal
    return _dep

def any_permission_required(*pairs: tuple[str, str]):
    async def _dep(principal: Principal = Depends(get_current_user)) -> Principal:
        if not any(principal.has(m, a) for m, a in pairs): raise APIError(403, ErrorCode.PERMISSION_DENIED, "Insufficient permissions")
        return principal
    return _dep
```

### 3.12 `backend/app/core/authz/visibility.py`
```python
"""Row-level visibility: predicate = self ∪ ownership ∪ (scope if module:view_all). See docs/Authorization_and_Visibility.md."""
from dataclasses import dataclass
from typing import Callable
from sqlalchemy import false, or_
from app.utils.response import VisibilityMeta

@dataclass
class OwnershipLink:
    module: str; name: str; predicate: Callable  # predicate(principal, model) -> SQLAlchemy expression

@dataclass
class ModuleVisibility:
    module: str; model: type
    self_predicate: Callable | None = None                   # (principal, model) -> expr
    scope_columns: dict[str, str] | None = None              # {"institution": "institution_id", "college": "college_id", "department": "department_id"}

MODULES: dict[str, ModuleVisibility] = {}
LINKS: dict[str, list[OwnershipLink]] = {}

def register_module(mv: ModuleVisibility): MODULES[mv.module] = mv
def register_link(link: OwnershipLink): LINKS.setdefault(link.module, []).append(link)

class VisibilityResolver:
    def __init__(self, principal): self.p = principal

    def scopes_for(self, module: str) -> list[str]:
        if not self.p.has(module, "view_all"): return []
        names = ["institution" if st == "institution" else st for st, _ in self.p.scopes]
        return sorted(set(names))

    def predicate(self, module: str):
        mv = MODULES[module]; parts = []
        if self.p.is_super_admin: return None                     # RLS + platform role still apply
        if mv.self_predicate: parts.append(mv.self_predicate(self.p, mv.model))
        for link in LINKS.get(module, []): parts.append(link.predicate(self.p, mv.model))
        if self.p.has(module, "view_all"):
            for scope_type, scope_id in self.p.scopes:
                col = (mv.scope_columns or {}).get(scope_type)
                if scope_type == "institution": parts.append(getattr(mv.model, "institution_id") == self.p.institution_id)
                elif col and scope_id is not None: parts.append(getattr(mv.model, col) == scope_id)
        return or_(*parts) if parts else false()

    def meta(self, module: str) -> VisibilityMeta:
        mv = MODULES[module]
        return VisibilityMeta(self=bool(mv.self_predicate) or bool(LINKS.get(module)), scopes=self.scopes_for(module), pii=self.p.has(module, "view_pii"))
```
Each phase registers its module (`register_module`) and its ownership links (`register_link`) in `app/services/<module>/visibility.py`; the resolver is applied by `BaseRepository.list()` and `get()`.

### 3.13 `backend/app/repositories/base.py`
```python
from typing import Generic, TypeVar
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.authz.visibility import VisibilityResolver
from app.core.errors import APIError, ErrorCode
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta

M = TypeVar("M")

class BaseRepository(Generic[M]):
    model: type[M]; module: str

    def __init__(self, db: AsyncSession, principal=None):
        self.db, self.principal = db, principal

    def _base(self, include_deleted=False):
        q = select(self.model)
        if hasattr(self.model, "deleted_at") and not include_deleted: q = q.where(self.model.deleted_at.is_(None))
        if self.principal and not self.principal.is_super_admin and hasattr(self.model, "institution_id"):
            q = q.where(self.model.institution_id == self.principal.institution_id)   # belt and braces (RLS is the backstop)
        return q

    def visible(self, q, scope: str | None = None):
        """Apply the row-level visibility predicate; `scope` narrows to self/own/department/college/all when requested."""
        if not self.principal or self.principal.is_super_admin: return q
        pred = VisibilityResolver(self.principal).predicate(self.module)
        return q.where(pred) if pred is not None else q

    async def get(self, id, *, for_update=False) -> M:
        q = self.visible(self._base()).where(self.model.id == id)
        if for_update: q = q.with_for_update()
        obj = (await self.db.execute(q)).scalar_one_or_none()
        if not obj: raise APIError(404, ErrorCode.NOT_FOUND, f"{self.model.__name__} not found")   # 404, never 403 (no existence leak)
        return obj

    async def paginate(self, q, params: PageParams) -> tuple[list[M], PaginationMeta]:
        total = (await self.db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        if params.sort:
            col = getattr(self.model, params.sort.lstrip("-"), None)
            if col is not None: q = q.order_by(col.desc() if params.sort.startswith("-") else col.asc())
        rows = (await self.db.execute(q.offset(params.offset).limit(params.page_size))).scalars().all()
        return rows, PaginationMeta(page=params.page, page_size=params.page_size, total=total, total_pages=max(1, -(-total // params.page_size)))

    async def create(self, **values) -> M:
        obj = self.model(**values); self.db.add(obj); await self.db.flush(); return obj

    async def update(self, obj: M, expected_version: int | None = None, **values) -> M:
        if expected_version is not None and getattr(obj, "version", None) not in (None, expected_version):
            raise APIError(409, ErrorCode.STALE_VERSION, "Record was modified by someone else", {"current_version": obj.version})
        for k, v in values.items(): setattr(obj, k, v)
        await self.db.flush(); return obj

    async def soft_delete(self, obj: M, by) -> None:
        from datetime import datetime, timezone
        obj.is_active, obj.deleted_at, obj.deleted_by = False, datetime.now(timezone.utc), by; await self.db.flush()
```

### 3.14 `backend/app/core/events.py` (transactional outbox) and `tasks/outbox.py`
```python
# events.py
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.platform import DomainEvent

async def emit(db: AsyncSession, *, institution_id, event_type: str, payload: dict, aggregate_type: str | None = None, aggregate_id=None, actor_user_id=None) -> uuid.UUID:
    """Write the event in the SAME transaction as the business change. The relay dispatches it after commit."""
    ev = DomainEvent(institution_id=institution_id, event_type=event_type, payload=payload, aggregate_type=aggregate_type, aggregate_id=aggregate_id, actor_user_id=actor_user_id)
    db.add(ev); await db.flush(); return ev.id

# tasks/outbox.py — Beat every 5 s (plus LISTEN/NOTIFY wake-up in Phase 01)
CONSUMERS: dict[str, list[str]] = {}          # event_type → [celery task names]; phases register with subscribe()
def subscribe(event_type: str, task_name: str): CONSUMERS.setdefault(event_type, []).append(task_name)

@celery.task(name="outbox.relay", queue="scheduled")
def relay(batch: int = 500):
    """SELECT … FOR UPDATE SKIP LOCKED pending events → send to consumers (at-least-once) → mark dispatched; failures → next_attempt_at with backoff; dead after 10 attempts."""
```
Consumers must be idempotent: they insert into `event_consumptions(consumer, event_id)` first and skip duplicates.

### 3.15 `backend/app/core/idempotency.py`
```python
import hashlib, json
from fastapi import Depends, Request
from app.core.errors import APIError, ErrorCode
from app.db.session import redis_client

async def idempotency_key(request: Request):
    key = request.headers.get("Idempotency-Key")
    if not key: return None
    body = await request.body()
    digest = hashlib.sha256(body).hexdigest()
    user = getattr(request.state, "user_id", "anon")
    redis_key = f"idem:{user}:{request.url.path}:{key}"
    stored = await redis_client.get(redis_key)
    if stored:
        data = json.loads(stored)
        if data["hash"] != digest: raise APIError(409, ErrorCode.CONFLICT, "Idempotency-Key reused with a different payload")
        raise APIError(200, ErrorCode.IDEMPOTENT_REPLAY, "Replay", {"response": data["response"]})   # handler converts to the stored response
    request.state.idem = (redis_key, digest)
    return key
```
Routes that accept the header call `await idempotency.store(request, response_body)` after success (24 h TTL, mirrored to `idempotency_keys`).

### 3.16 `backend/app/core/jobs.py`
```python
from functools import wraps
from app.models.platform import BackgroundJob

def job(job_type: str, queue: str = "reports"):
    """Wrap a Celery task: creates/updates the background_jobs row, streams progress on ws channel jobs:{user}, honours cancel_requested."""
    def deco(fn):
        @wraps(fn)
        def wrapper(job_id, *args, **kwargs):
            # mark running → run fn(job_ctx, *args) where job_ctx.progress(pct, message) → mark succeeded/failed with result_url/error
            ...
        return wrapper
    return deco
```
Service helper: `await jobs.enqueue(db, principal, job_type, params)` → row + Celery `apply_async(args=[job_id], queue=…)`; API: `GET /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel`.

### 3.17 `backend/app/core/workflow/engine.py` (API surface)
```python
class WorkflowEngine:
    async def start(self, db, *, institution_id, key: str, entity_type: str, entity_id, started_by, context: dict) -> WorkflowInstance: ...
    async def act(self, db, *, instance_id, actor, decision: str, comment: str | None) -> WorkflowInstance: ...   # approve | reject | delegate
    async def inbox(self, db, principal) -> list[WorkflowStep]: ...
    def on(self, key: str, event: str): ...   # decorator: modules register on_approved / on_rejected hooks
```
Approver resolution: `{"type":"role","value":"hod"}` → users holding the role whose scope contains the entity (department/college); `{"type":"scope_rule","value":"entity.department.hod"}`; `{"type":"user","value":<uuid>}`; delegation table consulted; SLA escalations by Beat `workflow.escalate`.

### 3.18 `backend/app/core/security.py`
bcrypt (cost 12) via `bcrypt`; JWT HS256 with `kid` header (`SECRET_KEY` + `JWT_PREVIOUS_KEYS` for rotation); `create_access_token(sub, institution_id, is_super_admin, jti)`; `create_refresh_token(sub, family, jti)` with rotation + reuse detection (family revoked on reuse); `decode_token(token, expected_type)`; TOTP via `pyotp` (`mfa_secrets`), recovery codes hashed; device/API-key hashing `sha256`; signed QR tokens (`itsdangerous`-style HMAC with expiry) for hall tickets, credentials and session QR.

### 3.19 `backend/app/core/audit.py`
```python
async def log_audit(db, *, principal, module: str, action: str, record_type: str, record_id, old: dict | None = None, new: dict | None = None, request=None):
    """Explicit audit call from services. The DB trigger computes the hash chain."""
```
`audit_fallback(request, status)` is used by the middleware when a mutation route forgot to call `log_audit`.

### 3.20 `backend/app/core/packs/`
`base.py` defines `RegulatoryPack` (see `docs/Regulatory_Pack_IN.md`); `registry.py` `@register_pack("IN")`; `in_pack.py` and `generic_pack.py` supply categories, quotas, id validators, grading/assessment defaults, NBA POs, frameworks, metric definitions, templates, comms/privacy/tax rules. `seed_institution_defaults(db, institution)` copies pack defaults into institution tables.

### 3.21 `backend/app/tasks/celery_app.py`
```python
from celery import Celery
from app.core.config import settings
celery = Celery("universe", broker=settings.CELERY_BROKER_URL, backend=settings.CELERY_RESULT_BACKEND, include=["app.tasks.outbox","app.tasks.beat","app.tasks.notifications","app.tasks.documents","app.tasks.reports","app.tasks.integrations"])
celery.conf.update(task_serializer="json", result_serializer="json", accept_content=["json"], timezone="UTC", enable_utc=True, task_acks_late=True, worker_prefetch_multiplier=1,
                   task_ignore_result=True, broker_connection_retry_on_startup=True,
                   task_routes={"notifications.*": {"queue": "notifications"}, "emails.*": {"queue": "emails"}, "documents.*": {"queue": "documents"},
                                "reports.*": {"queue": "reports"}, "integrations.*": {"queue": "integrations"}, "outbox.*": {"queue": "scheduled"}, "beat.*": {"queue": "scheduled"}})
```
Every task signature starts with `institution_id`; the task opens `tenant_session(institution_id)` (RLS context) and checks `features.is_enabled(institution_id, key)` before acting.

### 3.22 `backend/alembic/env.py`
Async pattern (as Orbit): `async_engine_from_config`, `compare_type=True`, `include_object` skips partitions' default children; `target_metadata = Base.metadata` with `import app.models`. `alembic.ini` uses `DATABASE_URL` from settings. **Rules**: one revision per phase named `NNNN_phaseNN_<module>.py` with a real `down_revision` chain; CI fails if `alembic heads` returns more than one; `Base.metadata.create_all` is forbidden outside `scripts/check_schema_drift.py`.

### 3.23 `backend/scripts/check_schema_drift.py`
Parses `Database_Schema.sql` (`CREATE TABLE name (…)` blocks → table → column names) and compares with `Base.metadata` (tables and columns present in models). Exit 1 with a readable diff (`missing in models`, `extra in models`, `column mismatch`). Run in CI and after every phase.

### 3.24 `backend/scripts/check_authz_coverage.py`
Walks `app.routes`; for each route under `/api/v1` asserts the dependency chain contains `permission_required`/`any_permission_required` **and** `feature_required` (module-level include counts), unless the route is listed in `app/api/v1/public.py:PUBLIC_ROUTES`. Exit 1 listing offenders.

### 3.25 `backend/scripts/scaffold_module.py`
`python scripts/scaffold_module.py hostel --feature hostel.core --permissions hostel` generates: `models/hostel.py` stub, `schemas/hostel.py`, `repositories/hostel_repository.py` (BaseRepository subclass with `module="hostel"`), `services/hostel_service.py`, `api/v1/endpoints/hostel.py` (router with `feature_required` + `permission_required` on a list/get/create/update/delete skeleton using `ok()`), `features/hostel.py` (register_feature), `services/hostel/visibility.py` (register_module), frontend `features/hostel/{api.ts,hooks.ts,pages/HostelPage.tsx,types.ts}`, nav entry stub, `scripts/verify/NN_hostel.ps1` template, Flutter feature folder stub.

### 3.26 `backend/scripts/verify/_common.ps1` (API verification helper)
```powershell
param([string]$BaseUrl = "http://localhost:8000/api/v1")
function Login($identifier, $password) { (Invoke-RestMethod -Method Post -Uri "$BaseUrl/auth/login" -ContentType 'application/json' -Body (@{identifier=$identifier; password=$password} | ConvertTo-Json)).data.access_token }
function Call($token, $method, $path, $body = $null, $expect = 200, $headers = @{}) {
  $h = @{ Authorization = "Bearer $token" } + $headers
  try { $r = Invoke-WebRequest -Method $method -Uri "$BaseUrl$path" -Headers $h -ContentType 'application/json' -Body ($(if ($body) { $body | ConvertTo-Json -Depth 8 })) -SkipHttpErrorCheck }
  catch { throw "$method $path failed: $_" }
  if ($r.StatusCode -ne $expect) { throw "$method $path expected $expect got $($r.StatusCode): $($r.Content)" }
  Write-Host "OK $method $path -> $($r.StatusCode)"; return ($r.Content | ConvertFrom-Json)
}
function Assert($cond, $msg) { if (-not $cond) { throw "ASSERT FAILED: $msg" } }
```
Each phase script dot-sources this file, logs in as each demo role, and asserts status codes, `data`, and `meta.visibility`.

### 3.27 Docker
`Dockerfile` (python:3.12-slim + WeasyPrint libs `libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi8`, non-root user, `docker-entrypoint.sh` runs `alembic upgrade head` when `RUN_MIGRATIONS=1` then `gunicorn -k uvicorn.workers.UvicornWorker -w 4 main:app`); `docker-compose.yml` services: `postgres:15-alpine` (init script creates `universe_app`/`universe_platform` roles), `redis:7-alpine`, `backend` (uvicorn --reload), `celery_worker` (`-Q notifications,emails,documents,reports,integrations,scheduled -c 4`), `celery_beat`, `flower :5555`, `frontend` (node:20-alpine dev), `nginx`. `nginx/nginx.conf`: `/api/` → backend:8000 (pass `X-Institution-Slug $host` when a custom domain is used), `/ws/` upgrade, `/uploads/`, security headers, 25M body.

---

## 4. Frontend files to generate

### 4.1 `frontend/package.json` (key dependencies)
`react@^18.3`, `react-dom@^18.3`, `react-router-dom@^6.23`, `@tanstack/react-query@^5.40`, `@tanstack/react-table@^8.17`, `@tanstack/react-virtual@^3.5`, `zustand@^4.5`, `axios@^1.7`, `react-hook-form@^7.51`, `@hookform/resolvers@^3.6`, `zod@^3.23`, `tailwindcss@^3.4`, `class-variance-authority`, `clsx`, `tailwind-merge`, `@radix-ui/react-{dialog,dropdown-menu,popover,select,tabs,tooltip,checkbox,switch,avatar,separator,label}`, `lucide-react`, `recharts@^2.12`, `@fullcalendar/{react,daygrid,timegrid,list,interaction}@^6.1`, `@dnd-kit/{core,sortable}`, `@tiptap/{react,starter-kit}@^2.4`, `date-fns@^3.6`, `sonner`, `qrcode.react`, `react-to-print`, `react-i18next`, `i18next`, `cmdk` (command palette). Dev: `typescript@^5.4`, `vite@^5.2`, `@vitejs/plugin-react`, `openapi-typescript@^7`, `eslint`, `prettier`, `@playwright/test` (in `e2e/`). Scripts: `dev`, `build`, `preview`, `lint`, `gen:api` (`openapi-typescript http://localhost:8000/api/v1/openapi.json -o src/api/generated/openapi.d.ts`).

### 4.2 `frontend/src/api/axios.ts`
```ts
import axios from 'axios';
import { useAuthStore } from '@/store/authStore';
import { useSessionStore } from '@/store/sessionStore';

export const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || '/api/v1', withCredentials: true });

api.interceptors.request.use((config) => {
  const { accessToken, currentUser } = useAuthStore.getState();
  const { institutionId, collegeId } = useSessionStore.getState();
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`;
  const inst = institutionId || currentUser?.institution_id;
  if (inst) config.headers['X-Institution-Id'] = inst;
  if (collegeId) config.headers['X-College-Id'] = collegeId;
  if (['post', 'put', 'patch', 'delete'].includes(config.method ?? '') && config.idempotent !== false && !config.headers['Idempotency-Key']) {
    config.headers['Idempotency-Key'] = crypto.randomUUID();
  }
  return config;
});

let refreshing: Promise<string> | null = null;
api.interceptors.response.use(
  (res) => res.data,                                   // unwrap envelope: callers receive { success, data, message, meta }
  async (err) => {
    const original = err.config;
    if (err.response?.status === 401 && !original._retry && !original.url?.includes('/auth/')) {
      original._retry = true;
      refreshing ??= api.post('/auth/refresh').then((r: any) => { useAuthStore.getState().setAccessToken(r.data.access_token); return r.data.access_token; }).finally(() => (refreshing = null));
      const token = await refreshing.catch(() => { useAuthStore.getState().logout(); window.location.href = '/login'; throw err; });
      original.headers.Authorization = `Bearer ${token}`; return api(original);
    }
    const body = err.response?.data;
    if (body?.error?.code === 'IDEMPOTENT_REPLAY') return body.error.details.response;
    if (body?.error?.code === 'READ_ONLY') useSessionStore.getState().setReadOnly(true);
    return Promise.reject(err);
  }
);
export const getApiError = (e: any, fallback = 'Something went wrong') => e?.response?.data?.error?.message ?? fallback;
export const getApiErrorCode = (e: any) => e?.response?.data?.error?.code as string | undefined;
```

### 4.3 Stores
- `store/authStore.ts` (Zustand `persist`, key `universe-auth`, `partialize` excludes `accessToken`): `{ accessToken, currentUser: { id, institution_id, username, display_name, is_super_admin, role_slugs[], scopes[] }, permissions: string[], features: string[], isAuthenticated, setAccessToken, setSession(user, permissions, features), logout() }`; `logout` clears `queryClient` and session store.
- `store/sessionStore.ts`: `{ institutionId, institutionName, collegeId, collegeName, academicYearId, termId, years[], terms[], readOnly, setInstitution, setCollege, setYear, setTerm, setReadOnly, reset }` — switching institution/college calls `queryClient.clear()`.
- `store/notificationStore.ts`: unread count + recent items fed by WebSocket `notifications:{user}` with polling fallback.

### 4.4 Hooks and guards
```ts
// hooks/usePermission.ts
export const usePermission = () => { const { permissions, currentUser } = useAuthStore(); const can = (m: string, a = 'view') => !!currentUser?.is_super_admin || permissions.includes(`${m}:${a}`) || permissions.includes(`${m}:manage`); return { can, canAny: (pairs: [string, string][]) => pairs.some(([m, a]) => can(m, a)) }; };
// hooks/useFeature.ts
export const useFeature = (key: string) => useAuthStore((s) => s.features.includes(key) || key.startsWith('core.'));
// hooks/useVisibility.ts — reads meta.visibility from the last list response of a module (React Query cache) and exposes { self, scopes, active, setActive }
```
`routes/FeatureRoute.tsx`, `PermissionRoute.tsx` (renders `AccessDeniedPage`), `PrivateRoute.tsx`, `PortalRoute.tsx` (by `role_slugs`), `SuperAdminRoute.tsx`, `AdminShellRoute.tsx` (renders `AppLayout`; bounces portal-only roles to their portal home). `components/shared/{PermissionGuard,FeatureGuard,ScopeTabs}.tsx` — `ScopeTabs` renders **Mine | Department | College | All** from `meta.visibility` and writes `?scope=` into the query key.

### 4.5 `frontend/src/nav.ts`
```ts
export type NavItem = { label: string; to: string; icon: LucideIcon; module: string; action?: string; altActions?: string[]; feature?: string; roles?: string[] };
export const NAV_GROUPS: { title: string; items: NavItem[] }[] = [
  { title: 'MAIN', items: [{ label: 'Dashboard', to: '/dashboard', icon: LayoutDashboard, module: 'dashboard' }] },
  { title: 'ACADEMICS', items: [] }, { title: 'EXAMINATIONS', items: [] }, { title: 'ADMISSIONS', items: [] }, { title: 'STUDENTS', items: [] },
  { title: 'PEOPLE', items: [] }, { title: 'CAMPUS', items: [] }, { title: 'FINANCE', items: [] }, { title: 'ENGAGEMENT', items: [] },
  { title: 'QUALITY & GOVERNANCE', items: [] }, { title: 'COMMUNICATION', items: [] }, { title: 'ADMIN', items: [] },
];
```
Sidebar filters items by `can(module, action ?? 'view') || canAny(altActions)` **and** `useFeature(feature)`.

### 4.6 `frontend/src/utils/constants.ts`
`ROLES` (slugs from `docs/Roles_and_Permissions.md`), `MODULES`, `ACTIONS`, `PORTAL_HOME` map (`student → /student`, `parent → /parent`, `faculty → /faculty`, `alumni → /alumni`, `hostel_warden → /warden`, `hostel_gate_staff → /warden/gate`, `driver → /driver`, `external_examiner → /evaluator`, `research_scholar → /scholar`, `recruiter → /recruiter`, `applicant → /apply`), `GENDER`, `CATEGORY` (from pack via `/public/config`), `BLOOD_GROUP`.

### 4.7 Shared UI
`components/ui/` (Button, Card, Input/Select/Textarea, Badge, Modal, Dropdown, Tabs, Tooltip, Switch, Checkbox, Avatar, Skeleton, Toast via sonner), `components/shared/` (`DataTable` — server-side pagination/sort/filter/column chooser/export hooks; `PageHeader`; `EmptyState`; `ErrorBoundary`; `PermissionGuard`; `FeatureGuard`; `ScopeTabs`; `JobsTray`; `NotificationCenter`; `CommandPalette`; `FormField` wrappers for RHF+Zod; `MoneyInput` (paise); `DateField` (institution TZ)), `components/layout/` (`AppLayout`, `Sidebar`, `Navbar` with institution/college switcher, year/term selector, global search, jobs tray, bell, impersonation banner, read-only banner; `PortalLayout`), `components/charts/` (Recharts wrappers with mandatory table view, as Orbit).

### 4.8 Theme
`index.css` with `--brand-*` ramps and semantic tokens; 5 named themes (Indigo, Ocean, Grove, Sunset, Plum) as data in `styles/themes.ts`; 6 table styles; `data-theme`/`.dark`; institution branding from settings; inline anti-flash script in `index.html`. Tokens exported as JSON (`styles/tokens.json`) for Flutter.

### 4.9 `frontend/src/lib/i18n.ts`
`react-i18next` with `en` resources only; all UI strings go through `t()` so locale packs can be added later (feature `i18n.web`).

---

## 5. Flutter bootstrap (Phase 42 builds it; create the skeleton now)
`flutter/pubspec.yaml` with `flutter_riverpod ^2.5`, `go_router ^14`, `dio ^5.5`, `flutter_secure_storage ^9`, `drift ^2.20` + `sqlite3_flutter_libs`, `firebase_core/messaging`, `flutter_local_notifications`, `local_auth`, `mobile_scanner`, `qr_flutter`, `intl`, `fl_chart`, `cached_network_image`, `url_launcher`, `share_plus`, `path_provider`, `open_filex`, `esc_pos_utils` + `print_bluetooth_thermal`, `web_socket_channel`, `sentry_flutter`, `razorpay_flutter`, `upi_india` (or intent); `l10n.yaml` (11 locales); `lib/core/*` folders as in `docs/Mobile_App_UI_Structure.md` §1 with `screen_registry.dart`, `role_shells.dart`, `deeplinks.dart`, `offline/` stubs.

---

## 6. CI (`.github/workflows/guards.yml`)
On every push/PR: `ruff` + `black --check` + `mypy` (backend), `eslint` + `tsc --noEmit` (frontend), `import-linter`, `python scripts/check_schema_drift.py`, `python scripts/check_authz_coverage.py`, `python scripts/check_feature_registry.py`, `alembic heads` count = 1 (fail otherwise), `pip-audit`, `npm audit --audit-level=high`, `bandit -r app`, `gitleaks`, `trivy` on the built image. `build.yml` builds and pushes `ghcr.io/septronr/universe-api:{env}-{sha}` and dispatches `orbit-infra`. `frontend-build.yml`/`frontend-deploy.yml` mirror Orbit (branch → mode → deploy target).

---

## 7. Coding standards (apply throughout ALL phases)

**Backend**
1. Route → Service → Repository → Model. Routes only validate, call one service method, return `ok()`. All SQL lives in repositories on `BaseRepository`. Business rules live in services with numbered docstrings.
2. Every protected route declares `permission_required(module, action)`; every module router is included with `feature_required(key)`; public routes are listed in `PUBLIC_ROUTES`. CI enforces both.
3. Responses: always the envelope; errors always `APIError(code)` from the catalogue; HTTP codes 200/201/202/204/400/401/403/404/409/422/429/503/500 only.
4. Money = `INTEGER`/`BIGINT` paise; timestamps UTC; academic dates in institution timezone; statuses `VARCHAR(30)` + Python `str` enums; soft delete via mixin; optimistic `version` on masters (`If-Match`).
5. Tenant: `institution_id` on every model via `TenantMixin`; `college_id` via `CollegeScopedMixin` where scoped; never query without `BaseRepository` (RLS is the backstop, not the filter).
6. Visibility: each module registers `ModuleVisibility` + ownership links; list responses include `meta.visibility`; sensitive fields masked unless `module:view_pii`.
7. Every mutation calls `log_audit()` and emits domain events through `events.emit()` in the same transaction; long work goes through `jobs.enqueue()`; approvals go through the workflow engine.
8. Non-idempotent POSTs accept `Idempotency-Key`; seat/money/sequence changes use `SELECT … FOR UPDATE` / `number_sequences`.
9. Names come from `Database_Schema.sql` — copy, never retype; one Alembic revision per phase; `scripts/check_schema_drift.py` must pass.
10. Celery tasks take `institution_id` first, open `tenant_session`, check feature flags, are idempotent.
11. Schemas by domain; `from_attributes=True`; camelCase is NOT used — JSON keys are snake_case end-to-end (Orbit convention kept for generated types).
12. Never log PII; never commit secrets; `.env` only.

**Frontend**
1. Generated types from OpenAPI; API calls only in `features/<module>/api.ts`; hooks wrap TanStack Query with keys `[module, params]`; invalidate by `[module]`.
2. Every form: react-hook-form + zod; every async result: toast; every fetch: skeleton; every list: `DataTable` with server pagination + `ScopeTabs` when `meta.visibility.scopes.length > 0`.
3. Guards: route (`FeatureRoute` + `PermissionRoute`), nav (`NAV_GROUPS` gates), inline (`PermissionGuard`/`FeatureGuard`); portals are self-only.
4. No `any` (except axios adapters); strict TS; WCAG AA; dark mode; print stylesheets for documents.

**Verification**
1. No unit tests. Each phase ships `scripts/verify/NN_<module>.ps1` (per-role API assertions) and a UI checklist; Playwright suites per round in `e2e/`.
2. Structural guards in CI are mandatory and green before the next phase.

---

## 8. Database setup
```
createuser universe_app; createuser universe_platform --bypassrls (or via psql: CREATE ROLE … NOLOGIN; then LOGIN roles that inherit)
createdb universe
psql -d universe -f Database_Schema.sql        # canonical DDL + seeds (or alembic upgrade head once Phase 01 exists)
GRANT ALL ON ALL TABLES IN SCHEMA public TO universe_app;  GRANT USAGE ON ALL SEQUENCES …
```
Then `python scripts/seed_platform.py` (permissions, role templates, features from `docs/Feature_Flags.md`, plans, packs) and `python scripts/seed_demo_institution.py --type university` (creates demo institution, colleges, roles, demo users per role — credentials printed to `LOCAL_TEST_CREDENTIALS.md`).

---

## 9. Deliverables checklist
- [ ] Monorepo tree created exactly as in §2 with all boilerplate files from §3–§6
- [ ] `docker compose up` starts 8 services; `GET /health` and `GET /ready` return ok
- [ ] `alembic upgrade head` on an empty DB reproduces `Database_Schema.sql` (drift check = 0) — Phase 01 provides the initial revision
- [ ] `python scripts/check_authz_coverage.py`, `check_feature_registry.py`, `check_schema_drift.py` run (and pass on the skeleton)
- [ ] Vite dev server starts; axios interceptor (envelope unwrap, refresh, tenant headers, Idempotency-Key) works against `/health` proxy
- [ ] Stores, hooks (`usePermission`, `useFeature`, `useVisibility`), guards, `NAV_GROUPS`, `ScopeTabs`, `JobsTray` exist and compile
- [ ] `scripts/verify/_common.ps1` works against a running backend (login placeholder returns 401 until Phase 02)
- [ ] Flutter skeleton compiles (`flutter analyze`) with the core folders and l10n config
- [ ] CI `guards.yml` runs green
- [ ] README updated with run instructions

## 10. README content
Product summary; institution types; stack; repo map; environment setup (Windows/Linux); running backend/frontend/worker; database bootstrap; how to run the phase prompts; verification philosophy (API + UI); deployment pointer to `orbit-infra`.
