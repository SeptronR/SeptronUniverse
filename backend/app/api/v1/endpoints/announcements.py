"""Announcements — Prompts/04 §04.8 (router included with ``feature_required("comms.announcements")``).

Reads ``communication:view`` (every role; audience-filtered in the service), create/update/delete the matching
``communication`` actions, publish ``communication:send`` (creators also hold ``manage`` in the templates), stats for the
creator or ``communication:view_all``; acknowledge is any audience member {comms.announcement_ack}.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, authenticated, permission_required
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.communication import (
    AcknowledgeRequest,
    AckStats,
    AnnouncementCreate,
    AnnouncementPublish,
    AnnouncementResponse,
    AnnouncementUpdate,
)
from app.services.announcement_service import AnnouncementService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(prefix="/announcements", tags=["announcements"])


@router.get(
    "",
    summary="Announcements (audience-filtered; managers see drafts)",
    response_model=Envelope[list[AnnouncementResponse]],
)
async def list_announcements(
    request: Request,
    params: PageParams = Depends(page_params),
    scope: str | None = Query(default=None, pattern="^(self|own|all)$"),
    q: str | None = Query(default=None, max_length=120),
    status: str | None = Query(default=None, pattern="^(draft|scheduled|published|expired)$"),
    principal: Principal = Depends(permission_required("communication", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await AnnouncementService(db, principal, request).list_page(params, scope, q, status)
    return ok(rows, pagination=pagination, visibility=visibility)


@router.post("", status_code=201, summary="Draft an announcement", response_model=Envelope[AnnouncementResponse])
async def create_announcement(
    body: AnnouncementCreate,
    request: Request,
    principal: Principal = Depends(permission_required("communication", "create")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AnnouncementService(db, principal, request).create(body), message="Draft saved")


@router.get("/{id}", summary="Announcement (records the read)", response_model=Envelope[AnnouncementResponse])
async def get_announcement(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("communication", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AnnouncementService(db, principal, request).get(id))


@router.put("/{id}", summary="Edit a draft", response_model=Envelope[AnnouncementResponse])
async def update_announcement(
    id: uuid.UUID,
    body: AnnouncementUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("communication", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AnnouncementService(db, principal, request).update(id, body), message="Announcement updated")


@router.delete("/{id}", summary="Delete an announcement", response_model=Envelope[None])
async def delete_announcement(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("communication", "delete")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await AnnouncementService(db, principal, request).delete(id)
    return ok(None, message="Announcement deleted")


@router.post("/{id}/publish", summary="Publish (notifies the audience)", response_model=Envelope[AnnouncementResponse])
async def publish_announcement(
    id: uuid.UUID,
    request: Request,
    body: AnnouncementPublish | None = None,
    principal: Principal = Depends(permission_required("communication", "send")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await AnnouncementService(db, principal, request).publish(id, body or AnnouncementPublish()),
        message="Published",
    )


@router.get("/{id}/stats", summary="Read / acknowledgement statistics", response_model=Envelope[AckStats])
async def announcement_stats(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("communication", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AnnouncementService(db, principal, request).stats(id))


@router.post(
    "/{id}/acknowledge",
    summary="Mark read / acknowledge",
    dependencies=[feature_required("comms.announcement_ack")],
    response_model=Envelope[AnnouncementResponse],
)
async def acknowledge(
    id: uuid.UUID,
    request: Request,
    body: AcknowledgeRequest | None = None,
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ack = body.acknowledge if body else True
    return ok(await AnnouncementService(db, principal, request).acknowledge(id, ack), message="Acknowledged")
