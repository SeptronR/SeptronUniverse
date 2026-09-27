"""Engine, Base and sessions — Prompts/00_PREREQUISITE_Project_Setup.md §3.5.

Every tenant session pins ``app.institution_id`` inside its transaction so PostgreSQL RLS is the backstop for every
query (ADR 0002). ``universe_app`` is NOT BYPASSRLS; ``universe_platform`` (super admin / ops) is. The setting is
applied with ``SELECT set_config('app.institution_id', :i, true)`` — the transaction-local equivalent of ``SET LOCAL``
that accepts a bind parameter (``SET`` itself cannot be parameterised under asyncpg).
"""

from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as aioredis
from fastapi import Request
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=1800,
)
platform_engine = create_async_engine(
    settings.PLATFORM_DATABASE_URL or settings.DATABASE_URL, pool_pre_ping=True, pool_size=2, max_overflow=2
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
PlatformSessionLocal = async_sessionmaker(platform_engine, class_=AsyncSession, expire_on_commit=False)
redis_client: aioredis.Redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)


class Base(DeclarativeBase):
    pass


SET_TENANT_SQL = text("SELECT set_config('app.institution_id', :i, true)")


async def set_tenant(session: AsyncSession, institution_id: Any) -> None:
    """Pin the RLS context for the current transaction (``SET LOCAL`` semantics, parameterised)."""
    await session.execute(SET_TENANT_SQL, {"i": str(institution_id)})


def bind_tenant(session: AsyncSession, institution_id: Any) -> None:
    """Re-apply the tenant setting at the start of EVERY transaction of this session.

    The setting dies with the transaction, so a session that commits mid-way (job progress checkpoints, chunked
    imports) would silently lose its RLS context; the ``after_begin`` hook keeps the tenant pinned for the session's
    whole life. Calling it again re-points the same hook (Phase 02: ``get_current_user`` binds the tenant from the
    token claims before the principal is loaded, then re-binds once the user row is known).
    """
    session.info["tenant_id"] = str(institution_id)
    if session.info.get("tenant_hook"):
        return
    session.info["tenant_hook"] = True

    @event.listens_for(session.sync_session, "after_begin")
    def _set_tenant(sync_session: Any, _transaction: Any, connection: Any) -> None:
        connection.execute(SET_TENANT_SQL, {"i": sync_session.info["tenant_id"]})


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Tenant session: sets the RLS context from request.state.institution_id inside the transaction."""
    async with SessionLocal() as session:
        try:
            inst = getattr(request.state, "institution_id", None)
            if inst:
                bind_tenant(session, inst)
                await set_tenant(session, inst)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_platform_db() -> AsyncIterator[AsyncSession]:
    """Cross-tenant session (super admin / support): BYPASSRLS role; every use is audited."""
    async with PlatformSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def tenant_session(institution_id: Any) -> AsyncSession:
    """For Celery tasks: ``db = await tenant_session(iid)`` — RLS context pinned for every transaction; caller closes."""
    session = SessionLocal()
    bind_tenant(session, institution_id)
    await set_tenant(session, institution_id)
    return session
