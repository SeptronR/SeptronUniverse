"""DPDP consents and data-subject requests — Prompts/02 §02.6 ``privacy_service``.

Business rules
1. ``record_consent`` (``privacy.dpdp_consent``): one ``consent_records`` row per decision; withdrawing closes the
   open grant(s) of the purpose (``withdrawn_at``); the caller's IP is kept for the audit trail; emits
   ``consent.changed``.
2. ``my_consents`` — the latest decision per purpose (self only).
3. ``create_request`` (``privacy.data_subject_requests``): access / export / correction / erasure with a 30-day SLA
   (``due_at``); status ``received``; emits ``data_subject_request.created`` (Phase 41's ``data.export_portability``
   completes the export job; Phase 37 tracks SLAs). ``my_requests`` — self; ``all_requests`` — the privacy officer
   (``settings:manage``).
"""

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.authz.dependencies import Principal
from app.core.errors import APIError, ErrorCode
from app.repositories.consent_repository import ConsentRepository, DataSubjectRequestRepository
from app.schemas.privacy import ConsentRequest, ConsentResponse, DataSubjectRequestCreate, DataSubjectRequestResponse


class PrivacyService:
    def __init__(self, db: AsyncSession, principal: Principal):
        self.db, self.principal = db, principal
        self.consents = ConsentRepository(db)
        self.requests = DataSubjectRequestRepository(db)

    def _institution(self) -> uuid.UUID:
        if self.principal.institution_id is None:
            raise APIError(422, ErrorCode.VALIDATION, "Consents are recorded per institution; platform users have none")
        return self.principal.institution_id

    async def record_consent(self, body: ConsentRequest, request: Request | None = None) -> ConsentResponse:
        inst = self._institution()
        ip = _ip(request)
        row = await self.consents.record(
            institution_id=inst,
            user_id=self.principal.id,
            purpose=body.purpose,
            granted=body.granted,
            text_version=body.text_version,
            granted_by_user_id=self.principal.impersonator_id or self.principal.id,
            ip=ip,
        )
        await log_audit(
            self.db,
            principal=self.principal,
            module="settings",
            action="consent",
            record_type="consent_record",
            record_id=row.id,
            new={"purpose": body.purpose, "granted": body.granted, "text_version": body.text_version},
            request=request,
        )
        await events.emit(
            self.db,
            institution_id=inst,
            event_type="consent.changed",
            payload={"user_id": str(self.principal.id), "purpose": body.purpose, "granted": body.granted},
            aggregate_type="consent_record",
            aggregate_id=row.id,
            actor_user_id=self.principal.id,
        )
        return ConsentResponse.model_validate(row)

    async def my_consents(self) -> list[ConsentResponse]:
        latest: dict[str, Any] = {}
        for row in await self.consents.latest_for_user(self.principal.id):  # newest first
            latest.setdefault(row.purpose, row)
        return [ConsentResponse.model_validate(r) for r in sorted(latest.values(), key=lambda r: r.purpose)]

    async def create_request(
        self, body: DataSubjectRequestCreate, request: Request | None = None
    ) -> DataSubjectRequestResponse:
        inst = self._institution()
        row = await self.requests.create(
            institution_id=inst, user_id=self.principal.id, request_type=body.request_type, details=body.details
        )
        await log_audit(
            self.db,
            principal=self.principal,
            module="settings",
            action="dsr_create",
            record_type="data_subject_request",
            record_id=row.id,
            new={"request_type": body.request_type},
            request=request,
        )
        await events.emit(
            self.db,
            institution_id=inst,
            event_type="data_subject_request.created",
            payload={"request_id": str(row.id), "user_id": str(self.principal.id), "request_type": body.request_type},
            aggregate_type="data_subject_request",
            aggregate_id=row.id,
            actor_user_id=self.principal.id,
        )
        return DataSubjectRequestResponse.model_validate(row)

    async def my_requests(self) -> list[DataSubjectRequestResponse]:
        return [DataSubjectRequestResponse.model_validate(r) for r in await self.requests.for_user(self.principal.id)]

    async def all_requests(self) -> list[DataSubjectRequestResponse]:
        return [DataSubjectRequestResponse.model_validate(r) for r in await self.requests.all_open(self._institution())]


def _ip(request: Request | None) -> str | None:
    if request is None:
        return None
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None
