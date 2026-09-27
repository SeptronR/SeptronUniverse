"""IP allow-list dependency for exam operations — Prompts/02 §02.6 rule 10 (``security.ip_allowlist_exam_ops``).

``ip_allowlisted("exam_decode")`` is declared by Phase 15 routes next to ``permission_required``. When the tenant has
``security.ip_allowlist_exam_ops`` enabled the client IP (first ``X-Forwarded-For`` hop or the socket peer) must fall
inside an active ``ip_allowlists`` CIDR of that purpose; otherwise the request is refused with ``403
PERMISSION_DENIED`` (``reason: ip_not_allowed``). With the flag off (or no rows for the purpose) the check passes.
"""

import ipaddress
from typing import Any

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, get_current_user
from app.core.errors import APIError, ErrorCode
from app.core.features import FEATURE_REGISTRY, is_enabled
from app.db.session import get_db
from app.models.platform import IpAllowlist

FEATURE_KEY = "security.ip_allowlist_exam_ops"


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


async def check_ip_allowlisted(db: AsyncSession, principal: Principal, purpose: str, ip: str | None) -> bool:
    """True when the purpose has no allow-list (or the feature is off) or the IP matches an active CIDR."""
    inst = principal.institution_id
    if inst is None or FEATURE_KEY not in FEATURE_REGISTRY or not await is_enabled(inst, FEATURE_KEY):
        return True
    rows = (
        (
            await db.execute(
                select(IpAllowlist.cidr).where(
                    IpAllowlist.institution_id == inst, IpAllowlist.purpose == purpose, IpAllowlist.is_active.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return True
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in ipaddress.ip_network(str(c), strict=False) for c in rows)


def ip_allowlisted(purpose: str) -> Any:
    async def _dep(
        request: Request, principal: Principal = Depends(get_current_user), db: AsyncSession = Depends(get_db)
    ) -> None:
        if not await check_ip_allowlisted(db, principal, purpose, client_ip(request)):
            raise APIError(
                403,
                ErrorCode.PERMISSION_DENIED,
                f"This operation ({purpose}) is restricted to allow-listed IP addresses",
                {"reason": "ip_not_allowed", "purpose": purpose},
            )

    return Depends(_dep)
