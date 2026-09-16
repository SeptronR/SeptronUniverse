"""Engine, Base and sessions — Prompts/00_PREREQUISITE_Project_Setup.md §3.5.

Every tenant session runs ``SET LOCAL app.institution_id`` inside its transaction so PostgreSQL RLS is the backstop
for every query (ADR 0002). ``universe_app`` is NOT BYPASSRLS; ``universe_platform`` (super admin / ops) is.
"""

from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as aioredis
from fastapi import Request
from sqlalchemy import text
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


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Tenant session: sets the RLS context from request.state.institution_id inside the transaction."""
    async with SessionLocal() as session:
        try:
            inst = getattr(request.state, "institution_id", None)
            if inst:
                await session.execute(text("SET LOCAL app.institution_id = :i"), {"i": str(inst)})
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
    """For Celery tasks: ``db = await tenant_session(iid)`` — sets the RLS context explicitly; caller closes."""
    session = SessionLocal()
    await session.execute(text("SET LOCAL app.institution_id = :i"), {"i": str(institution_id)})
    return session
