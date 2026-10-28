"""Support tickets — Prompts/38 §38.8 ``/support/tickets`` (tenant: own institution; platform: every tenant).

Tenants raise with ``support:create`` (institution admin via ``support:manage``) on their RLS session; super admins
and support agents work the desk on the platform session (``dual_db``). ``scope=mine`` → tickets I raised (tenant) or
assigned to me (platform). Internal notes never reach tenants; diagnostics are platform-only.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.saas_deps import dual_db
from app.core.authz.dependencies import Principal, any_permission_required, platform_permission
from app.schemas.common import Envelope
from app.schemas.saas import (
    DiagnosticsOut,
    JobAccepted,
    TicketAssign,
    TicketCreate,
    TicketOut,
    TicketRate,
    TicketReply,
    TicketStatusChange,
)
from app.services.saas.support_service import SupportService
from app.utils.response import ok

router = APIRouter(prefix="/support/tickets", tags=["support"])
READ = any_permission_required(
    ("support", "view"), ("support", "create"), ("support", "view_all"), ("support", "manage")
)
RAISE = any_permission_required(("support", "create"), ("support", "manage"))
DESK = platform_permission("platform", "support")


@router.get("", summary="Support tickets (Mine | All)", response_model=Envelope[list[TicketOut]])
async def list_tickets(
    scope: str | None = Query(default=None, pattern="^(own|mine|all)$"),
    status: str | None = Query(default=None, pattern="^(open|in_progress|waiting|resolved|closed)$"),
    priority: str | None = Query(default=None, pattern="^(urgent|high|normal|low)$"),
    institution_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=120),
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(dual_db),
) -> dict[str, Any]:
    rows, visibility = await SupportService(db, principal).list_tickets(scope, status, priority, institution_id, q)
    return ok(rows, extra={"visibility": visibility})


@router.post(
    "",
    status_code=201,
    summary="Raise a ticket (SLA from priority, auto-assigned to on-call)",
    response_model=Envelope[TicketOut],
)
async def create_ticket(
    body: TicketCreate, request: Request, principal: Principal = Depends(RAISE), db: AsyncSession = Depends(dual_db)
) -> dict[str, Any]:
    return ok(await SupportService(db, principal, request).create(body), message="Ticket raised")


@router.get("/{id}", summary="Ticket with its thread", response_model=Envelope[TicketOut])
async def get_ticket(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(dual_db)
) -> dict[str, Any]:
    return ok(await SupportService(db, principal, request).get(id))


@router.post("/{id}/reply", summary="Reply (platform staff may add internal notes)", response_model=Envelope[TicketOut])
async def reply(
    id: uuid.UUID,
    body: TicketReply,
    request: Request,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(dual_db),
) -> dict[str, Any]:
    return ok(await SupportService(db, principal, request).reply(id, body), message="Reply posted")


@router.post("/{id}/assign", summary="Assign to a super admin / support agent", response_model=Envelope[TicketOut])
async def assign(
    id: uuid.UUID,
    body: TicketAssign,
    request: Request,
    principal: Principal = Depends(DESK),
    db: AsyncSession = Depends(dual_db),
) -> dict[str, Any]:
    return ok(await SupportService(db, principal, request).assign(id, body), message="Ticket assigned")


@router.post(
    "/{id}/status",
    summary="Change status (open → in_progress → waiting → resolved → closed; reopen ≤ 14 days)",
    response_model=Envelope[TicketOut],
)
async def change_status(
    id: uuid.UUID,
    body: TicketStatusChange,
    request: Request,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(dual_db),
) -> dict[str, Any]:
    return ok(await SupportService(db, principal, request).change_status(id, body), message="Status changed")


@router.post("/{id}/rate", summary="Rate a resolved ticket (CSAT; closes it)", response_model=Envelope[TicketOut])
async def rate(
    id: uuid.UUID,
    body: TicketRate,
    request: Request,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(dual_db),
) -> dict[str, Any]:
    return ok(await SupportService(db, principal, request).rate(id, body), message="Thanks for rating")


@router.get(
    "/{id}/diagnostics",
    summary="Diagnostics (versions, flags diff, failing connections, last errors)",
    response_model=Envelope[DiagnosticsOut],
)
async def diagnostics(
    id: uuid.UUID, request: Request, principal: Principal = Depends(DESK), db: AsyncSession = Depends(dual_db)
) -> dict[str, Any]:
    return ok(await SupportService(db, principal, request).diagnostics(id))


@router.post(
    "/{id}/diagnostics/snapshot",
    status_code=202,
    summary="Attach a diagnostics snapshot as an internal note (job)",
    response_model=Envelope[JobAccepted],
)
async def diagnostics_snapshot(
    id: uuid.UUID, request: Request, principal: Principal = Depends(DESK), db: AsyncSession = Depends(dual_db)
) -> dict[str, Any]:
    from app.core.jobs import enqueue

    svc = SupportService(db, principal, request)
    t = await svc.get(id)
    job = await enqueue(db, principal, "support.diagnostics_snapshot", {"ticket_id": str(id)}, queue="reports")
    return ok(
        JobAccepted(job_id=job.id, job_type="support.diagnostics_snapshot", detail={"ticket": t.ticket_number}),
        message="Snapshot queued",
    )
