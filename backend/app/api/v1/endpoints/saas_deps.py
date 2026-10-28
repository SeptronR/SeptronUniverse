"""Shared dependencies of the Phase 38 routers (not a router module).

``dual_db`` gives platform users (super admin, support agent) the cross-tenant platform session and everyone else the
RLS tenant session of the request — routes serving both sides (support tickets, help authoring, read-only schedules)
keep one code path while a tenant can never reach another tenant's rows.
"""

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, get_current_user, is_support_agent
from app.db.session import PlatformSessionLocal, get_db


async def dual_db(
    principal: Principal = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> AsyncIterator[AsyncSession]:
    if principal.is_super_admin or is_support_agent(principal):
        async with PlatformSessionLocal() as pdb:
            try:
                yield pdb
                await pdb.commit()
            except Exception:
                await pdb.rollback()
                raise
    else:
        yield db


def client_ip(request: object) -> str | None:
    headers = getattr(request, "headers", {})
    fwd = headers.get("x-forwarded-for") if headers else None
    if fwd:
        return str(fwd).split(",")[0].strip()
    client = getattr(request, "client", None)
    return client.host if client else None
