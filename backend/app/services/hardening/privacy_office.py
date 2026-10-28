"""DPDP privacy office — Prompts/43 §43.6 ``privacy_service`` (extends Phase 02 ``privacy_service.py``).

Business rules
1. **Purposes / banner**: registry from ``platform_settings['privacy.purposes']`` (fallback
   ``app/core/privacy_registry.py``); the banner ``requires_update`` when the user has no current-version decision for
   any purpose or the published ``dpdp_notice`` version is newer than the one recorded in ``users.preferences``.
2. **Bulk consents**: one ``consent_records`` row per purpose (``text_version`` = purpose version); mandatory purposes
   are informational (always recorded granted). A **minor** (``students.dob`` < 18 years) cannot grant optional purposes
   (422 ``GUARDIAN_CONSENT_REQUIRED``) — a linked guardian (``student_guardians.user_id``) records them with
   ``on_behalf_student_id`` (``granted_by_user_id`` = guardian). Emits ``privacy.consent_granted|withdrawn``.
3. **Consent gate** :func:`has_consent` / :func:`require_consent` for modules (geo attendance → ``location``, face →
   ``biometric``, recruiter views → ``third_party_placement``, campaigns → ``communication_marketing``): the latest
   decision wins; no decision = not granted for optional purposes.
4. **Notices**: versions in ``platform_settings['privacy.notices']`` with institution overrides
   (``institution_settings`` category ``privacy`` key ``notice:<key>``); publish bumps the minor version and emits
   ``privacy.consent_version_published`` (re-consent prompt through rule 1).
5. **DSR workflow** (status machine owned by the privacy officer, ``privacy:manage``): ``received`` →
   ``identity_pending`` (OTP sent to the requester's notification channels, or a document reviewed by the officer) →
   ``in_progress`` (``start``; due date from ``privacy.dsr.due_days``) → ``completed`` | ``rejected``; one
   ``extend`` (+``extension_days``, status ``extended``; a second answers 409). Types: access / export → job
   ``privacy.dsr_export`` (Phase 41 ``export_user``, signed link 7 days); correction → work items routed per table
   (students → registrar, staff → HR officer, results → COE) that record owners close; erasure → job
   ``privacy.dsr_erase`` (refused with active dues / legal hold; Phase 37 ``retention_service.erase`` + anonymised
   identity fields, sessions revoked, manifest id on the timeline). Requesters see their own requests (and those they
   filed for a ward); anyone else's id answers 404. Timeline / identity / work items in ``privacy_meta dsr:<id>``.
"""

from __future__ import annotations

import builtins
import hashlib
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select, text

from app.core import events
from app.core.audit import log_audit
from app.core.errors import APIError, ErrorCode
from app.core.notifications.notify import notify_event
from app.core.privacy_registry import DSR_DEFAULTS, notices_json, purposes_json
from app.models.platform import ConsentRecord, DataSubjectRequest
from app.schemas.privacy import (
    ConsentBannerOut,
    ConsentBulkIn,
    ConsentPurposeOut,
    ConsentReportOut,
    DataSubjectRequestCreate,
    DsrAction,
    DsrIdentityVerify,
    DsrOut,
    NoticeIn,
    NoticeOut,
)
from app.services.hardening.common import HardeningBase, forbidden

OFFICER = ("privacy:manage",)
ROUTE_BY_TABLE = {
    "students": ("registrar", "students:update"),
    "student_guardians": ("registrar", "students:update"),
    "users": ("registrar", "users:update"),
    "staff": ("hr_officer", "hr:update"),
    "student_course_results": ("controller_of_examinations", "results:update"),
    "applicants": ("admissions_officer", "admissions:update"),
}


def _age(dob: date | None, today: date | None = None) -> int | None:
    if dob is None:
        return None
    t = today or date.today()
    return t.year - dob.year - ((t.month, t.day) < (dob.month, dob.day))


async def has_consent(db: Any, user_id: uuid.UUID, purpose: str) -> bool:
    """Latest decision for the purpose; mandatory purposes are always true."""
    from app.core.privacy_registry import PURPOSES

    if PURPOSES.get(purpose, (False,))[0]:
        return True
    row = (
        await db.execute(
            select(ConsentRecord.granted, ConsentRecord.withdrawn_at)
            .where(ConsentRecord.user_id == user_id, ConsentRecord.purpose == purpose)
            .order_by(ConsentRecord.recorded_at.desc())
            .limit(1)
        )
    ).first()
    return bool(row and row[0] and row[1] is None)


async def require_consent(db: Any, user_id: uuid.UUID, purpose: str) -> None:
    if not await has_consent(db, user_id, purpose):
        raise APIError(
            403,
            ErrorCode.PERMISSION_DENIED,
            f"Consent for '{purpose}' is required — grant it under Profile › Privacy",
            {"code": "CONSENT_REQUIRED", "purpose": purpose},
        )


class PrivacyOfficeService(HardeningBase):
    # ---- registry -------------------------------------------------------------------------------------------------
    async def purposes(self) -> builtins.list[ConsentPurposeOut]:
        raw = await self.platform_value("privacy.purposes", None) or purposes_json()
        return [ConsentPurposeOut(**p) for p in raw]

    async def _notices(self) -> dict[str, Any]:
        base = dict(await self.platform_value("privacy.notices", None) or notices_json())
        for key in list(base):
            override = await self.meta(f"notice:{key}", "privacy")
            if isinstance(override, dict) and override.get("version"):
                base[key] = {**base[key], **override}
        return base

    async def _student_of(self, user_id: uuid.UUID) -> Any:
        return (
            await self.db.execute(
                text("SELECT id, dob, user_id FROM students WHERE user_id = :u AND deleted_at IS NULL LIMIT 1"),
                {"u": user_id},
            )
        ).first()

    async def _latest(self, user_id: uuid.UUID) -> dict[str, ConsentRecord]:
        rows = (
            await self.db.execute(
                select(ConsentRecord).where(ConsentRecord.user_id == user_id).order_by(ConsentRecord.recorded_at.desc())
            )
        ).scalars()
        out: dict[str, ConsentRecord] = {}
        for r in rows:
            out.setdefault(r.purpose, r)
        return out

    async def banner(self) -> ConsentBannerOut:
        purposes = await self.purposes()
        latest = await self._latest(self.principal.id)
        notice = (await self._notices()).get("dpdp_notice", {})
        seen = ((getattr(self.principal, "preferences", None) or {}).get("privacy") or {}).get("notice_version")
        if seen is None:
            seen = (
                await self.db.execute(
                    text("SELECT preferences -> 'privacy' ->> 'notice_version' FROM users WHERE id = :u"),
                    {"u": self.principal.id},
                )
            ).scalar_one_or_none()
        stale = any(p.key not in latest or (latest[p.key].text_version or "") != p.text_version for p in purposes)
        student = await self._student_of(self.principal.id)
        age = _age(student.dob) if student else None
        return ConsentBannerOut(
            purposes=purposes,
            notice_version=str(notice.get("version") or "1.0"),
            requires_update=stale or seen != notice.get("version"),
            current={k: bool(v.granted and v.withdrawn_at is None) for k, v in latest.items()},
            is_minor=age is not None and age < 18,
        )

    # ---- consents ---------------------------------------------------------------------------------------------------
    async def bulk(self, body: ConsentBulkIn) -> dict[str, Any]:
        purposes = {p.key: p for p in await self.purposes()}
        unknown = sorted(set(body.grants) - set(purposes))
        if unknown:
            raise APIError(422, ErrorCode.VALIDATION, "Unknown consent purposes", {"purposes": unknown})
        subject_user = self.principal.id
        by = self.principal.id
        if body.on_behalf_student_id:
            ward = (
                await self.db.execute(
                    text(
                        "SELECT s.user_id, s.dob FROM students s JOIN student_guardians g ON g.student_id = s.id "
                        "WHERE s.id = :s AND g.user_id = :u AND s.deleted_at IS NULL"
                    ),
                    {"s": body.on_behalf_student_id, "u": self.principal.id},
                )
            ).first()
            if ward is None or ward[0] is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Ward not found")
            subject_user = ward[0]
        else:
            student = await self._student_of(self.principal.id)
            age = _age(student.dob) if student else None
            if age is not None and age < 18 and any(v and not purposes[k].mandatory for k, v in body.grants.items()):
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    "A parent or guardian must grant optional consents for students under 18",
                    {"code": "GUARDIAN_CONSENT_REQUIRED"},
                )
        latest = await self._latest(subject_user)
        changed: dict[str, bool] = {}
        now = datetime.now(UTC)
        ip = _ip(self.request)
        for key, granted in body.grants.items():
            p = purposes[key]
            granted = True if p.mandatory else granted
            prev = latest.get(key)
            if prev and prev.granted == granted and prev.withdrawn_at is None and prev.text_version == p.text_version:
                continue
            if prev and prev.granted and prev.withdrawn_at is None and not granted:
                prev.withdrawn_at = now
            self.db.add(
                ConsentRecord(
                    institution_id=self.inst,
                    user_id=subject_user,
                    purpose=key,
                    granted=granted,
                    text_version=p.text_version,
                    granted_by_user_id=by,
                    ip=ip,
                )
            )
            changed[key] = granted
        if body.notice_version and not body.on_behalf_student_id:
            await self.db.execute(
                text(
                    "UPDATE users SET preferences = jsonb_set(coalesce(preferences, '{}'::jsonb), '{privacy}', "
                    "coalesce(preferences -> 'privacy', '{}'::jsonb) || jsonb_build_object('notice_version', CAST(:v AS text)))"
                    " WHERE id = :u"
                ),
                {"v": body.notice_version, "u": subject_user},
            )
        await self.db.flush()
        for key, granted in changed.items():
            await events.emit(
                self.db,
                institution_id=self.inst,
                event_type="privacy.consent_granted" if granted else "privacy.consent_withdrawn",
                payload={"user_id": str(subject_user), "purpose": key, "by": str(by)},
                aggregate_type="user",
                aggregate_id=subject_user,
                actor_user_id=by,
            )
        if changed:
            await log_audit(
                self.db,
                principal=self.principal,
                module="privacy",
                action="consent",
                record_type="user",
                record_id=subject_user,
                new={
                    "grants": changed,
                    "on_behalf": str(body.on_behalf_student_id) if body.on_behalf_student_id else None,
                },
                request=self.request,
            )
        return {"changed": changed, "user_id": str(subject_user)}

    async def withdraw(self, purpose: str) -> dict[str, Any]:
        return await self.bulk(ConsentBulkIn(grants={purpose: False}))

    async def wards(self) -> builtins.list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                text(
                    "SELECT s.id, s.first_name, s.dob, s.user_id FROM students s JOIN student_guardians g ON g.student_id = s.id "
                    "WHERE g.user_id = :u AND s.deleted_at IS NULL ORDER BY s.first_name"
                ),
                {"u": self.principal.id},
            )
        ).all()
        out = []
        for sid, name, dob, uid in rows:
            latest = await self._latest(uid) if uid else {}
            age = _age(dob)
            out.append(
                {
                    "student_id": str(sid),
                    "name": name,
                    "is_minor": age is not None and age < 18,
                    "consents": {k: bool(v.granted and v.withdrawn_at is None) for k, v in latest.items()},
                }
            )
        return out

    async def report(self, purpose: str | None, granted: bool | None, college_id: uuid.UUID | None) -> ConsentReportOut:
        self.require("privacy:view_all", "privacy:manage", "security:view_all")
        rows = (
            await self.db.execute(
                text(
                    "SELECT DISTINCT ON (c.user_id, c.purpose) c.user_id, c.purpose, c.granted, c.withdrawn_at, "
                    "c.text_version, c.recorded_at, u.display_name FROM consent_records c JOIN users u ON u.id = c.user_id "
                    "WHERE c.institution_id = :i AND (CAST(:p AS text) IS NULL OR c.purpose = :p) "
                    "ORDER BY c.user_id, c.purpose, c.recorded_at DESC"
                ),
                {"i": self.inst, "p": purpose},
            )
        ).all()
        counts: dict[str, dict[str, int]] = {}
        out: list[dict[str, object]] = []
        for uid, pur, g, wd, ver, at, name in rows:
            ok = bool(g and wd is None)
            bucket = counts.setdefault(pur, {"granted": 0, "denied": 0})
            bucket["granted" if ok else "denied"] += 1
            if granted is None or granted == ok:
                masked = (name or "")[:1] + "***" if name else "***"
                out.append(
                    {"user": masked, "user_id": str(uid)[:8], "purpose": pur, "granted": ok, "version": ver, "at": at}
                )
        return ConsentReportOut(counts=counts, rows=out[:500])

    # ---- notices ----------------------------------------------------------------------------------------------------
    async def notices(self) -> builtins.list[NoticeOut]:
        out = []
        for key, n in (await self._notices()).items():
            draft = await self.meta(f"notice_draft:{key}", "privacy")
            out.append(
                NoticeOut(
                    key=key,
                    version=str(n.get("version")),
                    texts=n.get("texts") or {},
                    effective_from=n.get("effective_from"),
                    draft=draft,
                )
            )
        return out

    async def save_notice(self, body: NoticeIn) -> NoticeOut:
        self.require(*OFFICER)
        notices = await self._notices()
        if body.key not in notices:
            raise APIError(422, ErrorCode.VALIDATION, "Unknown notice", {"key": body.key})
        await self.put_meta(
            f"notice_draft:{body.key}", {"texts": body.texts, "effective_from": body.effective_from}, "privacy"
        )
        cur = notices[body.key]
        return NoticeOut(
            key=body.key, version=str(cur.get("version")), texts=cur.get("texts") or {}, draft={"texts": body.texts}
        )

    async def publish_notice(self, key: str) -> NoticeOut:
        self.require(*OFFICER)
        notices = await self._notices()
        draft = await self.meta(f"notice_draft:{key}", "privacy")
        if key not in notices or not draft:
            raise APIError(422, ErrorCode.VALIDATION, "Nothing to publish", {"key": key})
        major, _, minor = str(notices[key].get("version") or "1.0").partition(".")
        version = f"{major}.{int(minor or 0) + 1}"
        value = {
            "key": key,
            "version": version,
            "texts": draft["texts"],
            "effective_from": draft.get("effective_from") or datetime.now(UTC),
        }
        await self.put_meta(f"notice:{key}", value, "privacy")
        await self.db.execute(
            text("DELETE FROM institution_settings WHERE institution_id = :i AND category = 'privacy' AND key = :k"),
            {"i": self.inst, "k": f"notice_draft:{key}"},
        )
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="privacy.consent_version_published",
            payload={"notice": key, "version": version},
            aggregate_type="notice",
            aggregate_id=None,
            actor_user_id=self.principal.id,
        )
        if key == "dpdp_notice":
            await notify_event(
                self.db,
                self.inst,
                "privacy.consent_version_changed",
                audience={"all_users": True},
                context={"version": version},
            )
        await log_audit(
            self.db,
            principal=self.principal,
            module="privacy",
            action="notice_publish",
            record_type="notice",
            record_id=None,
            new={"key": key, "version": version},
            request=self.request,
        )
        return NoticeOut(key=key, version=version, texts=value["texts"], effective_from=value["effective_from"])  # type: ignore[arg-type]

    async def public_notice(self, institution_id: uuid.UUID | None, key: str) -> dict[str, Any]:
        base = dict(await self.platform_value("privacy.notices", None) or notices_json())
        if key not in base:
            raise APIError(404, ErrorCode.NOT_FOUND, "Notice not found")
        n = base[key]
        if institution_id:
            o = await self.meta(f"notice:{key}", "privacy", inst=institution_id)
            if isinstance(o, dict):
                n = {**n, **o}
        return dict(n)

    # ---- DSRs -------------------------------------------------------------------------------------------------------
    async def _dsr_meta(self, rid: uuid.UUID) -> dict[str, Any]:
        return dict(
            await self.meta(f"dsr:{rid}")
            or {"timeline": [], "identity_verified": False, "extensions": 0, "work_items": []}
        )

    async def _note(self, rid: uuid.UUID, meta: dict[str, Any], event: str, **extra: Any) -> None:
        meta.setdefault("timeline", []).append(
            {"at": datetime.now(UTC).isoformat(), "event": event, "by": str(self.principal.id), **extra}
        )
        await self.put_meta(f"dsr:{rid}", meta)

    async def _out(self, r: DataSubjectRequest) -> DsrOut:
        m = await self._dsr_meta(r.id)
        return DsrOut(
            id=r.id,
            user_id=r.user_id,
            request_type=r.request_type,
            status=r.status,
            details=r.details,
            due_at=r.due_at,
            result_url=r.result_url,
            created_at=r.created_at,
            closed_at=r.closed_at,
            identity_verified=bool(m.get("identity_verified")),
            extensions=int(m.get("extensions") or 0),
            filed_by=uuid.UUID(m["filed_by"]) if m.get("filed_by") else None,
            timeline=m.get("timeline") or [],
            work_items=m.get("work_items") or [],
            manifest_id=m.get("manifest_id"),
        )

    def officer(self) -> bool:
        return self.can("privacy", "manage")

    async def _get(self, rid: uuid.UUID) -> DataSubjectRequest:
        r = await self.db.get(DataSubjectRequest, rid)
        if r is None or r.institution_id != self.inst:
            raise APIError(404, ErrorCode.NOT_FOUND, "Request not found")
        if self.officer() or self.can("privacy", "view_all") or r.user_id == self.principal.id:
            return r
        m = await self._dsr_meta(rid)
        if m.get("filed_by") == str(self.principal.id):
            return r
        if any(self.can(*w["permission"].split(":", 1)) for w in m.get("work_items") or [] if w.get("permission")):
            return r
        raise APIError(404, ErrorCode.NOT_FOUND, "Request not found")

    async def create(self, body: DataSubjectRequestCreate) -> DsrOut:
        subject = self.principal.id
        filed_by = None
        if body.on_behalf_student_id:
            ward = (
                await self.db.execute(
                    text(
                        "SELECT s.user_id FROM students s JOIN student_guardians g ON g.student_id = s.id "
                        "WHERE s.id = :s AND g.user_id = :u AND s.deleted_at IS NULL"
                    ),
                    {"s": body.on_behalf_student_id, "u": self.principal.id},
                )
            ).first()
            if ward is None or ward[0] is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Ward not found")
            subject, filed_by = ward[0], self.principal.id
        cfg = {**DSR_DEFAULTS, **(await self.platform_value("privacy.dsr", None) or {})}
        r = DataSubjectRequest(
            institution_id=self.inst,
            user_id=subject,
            request_type=body.request_type,
            status="received",
            details=body.details,
            due_at=datetime.now(UTC) + timedelta(days=int(cfg["due_days"])),
        )
        self.db.add(r)
        await self.db.flush()
        otp = f"{secrets.randbelow(10**6):06d}"
        meta = {
            "timeline": [],
            "identity_verified": False,
            "extensions": 0,
            "work_items": [],
            "filed_by": str(filed_by) if filed_by else None,
            "otp_hash": hashlib.sha256(f"{r.id}:{otp}".encode()).hexdigest(),
        }
        await self._note(r.id, meta, "received", request_type=body.request_type)
        await notify_event(
            self.db,
            self.inst,
            "privacy.dsr_received",
            audience={"user_ids": [str(self.principal.id)]},
            context={"request_id": str(r.id), "otp": otp, "due_at": r.due_at.isoformat() if r.due_at else None},
        )
        await notify_event(
            self.db,
            self.inst,
            "privacy.dsr_due_soon",
            audience={"roles": ["privacy_officer"]},
            context={"request_id": str(r.id), "request_type": body.request_type, "new": True},
        )
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="privacy.dsr_created",
            payload={"request_id": str(r.id), "request_type": body.request_type, "user_id": str(subject)},
            aggregate_type="data_subject_request",
            aggregate_id=r.id,
            actor_user_id=self.principal.id,
        )
        await log_audit(
            self.db,
            principal=self.principal,
            module="privacy",
            action="dsr_create",
            record_type="data_subject_request",
            record_id=r.id,
            new={"request_type": body.request_type, "on_behalf": bool(filed_by)},
            request=self.request,
        )
        return await self._out(r)

    async def get(self, rid: uuid.UUID) -> DsrOut:
        return await self._out(await self._get(rid))

    async def mine(self) -> builtins.list[DsrOut]:
        rows = (
            (
                await self.db.execute(
                    select(DataSubjectRequest)
                    .where(DataSubjectRequest.user_id == self.principal.id)
                    .order_by(DataSubjectRequest.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return [await self._out(r) for r in rows]

    async def list(self, scope: str = "all", status: str | None = None) -> builtins.list[DsrOut]:
        if scope == "mine" or not (self.officer() or self.can("privacy", "view_all")):
            return await self.mine()
        q = select(DataSubjectRequest).where(DataSubjectRequest.institution_id == self.inst)
        if status:
            q = q.where(DataSubjectRequest.status == status)
        rows = (await self.db.execute(q.order_by(DataSubjectRequest.due_at).limit(500))).scalars().all()
        return [await self._out(r) for r in rows]

    async def identity(self, rid: uuid.UUID, body: DsrIdentityVerify) -> DsrOut:
        r = await self._get(rid)
        m = await self._dsr_meta(rid)
        if body.method == "otp":
            if not body.otp or hashlib.sha256(f"{rid}:{body.otp}".encode()).hexdigest() != m.get("otp_hash"):
                raise APIError(422, ErrorCode.VALIDATION, "Invalid code", {"field": "otp"})
            m["identity_verified"] = True
            await self._note(rid, m, "identity_verified", method="otp")
            await events.emit(
                self.db,
                institution_id=self.inst,
                event_type="privacy.dsr_identity_verified",
                payload={"request_id": str(rid)},
                aggregate_type="data_subject_request",
                aggregate_id=rid,
                actor_user_id=self.principal.id,
            )
        else:
            if not body.document_url:
                raise APIError(422, ErrorCode.VALIDATION, "document_url required", {"field": "document_url"})
            m["identity_document"] = body.document_url
            r.status = "identity_pending"
            await self._note(rid, m, "identity_document_uploaded")
        return await self._out(r)

    async def act(self, rid: uuid.UUID, body: DsrAction) -> DsrOut:  # noqa: C901, PLR0912 - one status machine
        self.require(*OFFICER)
        r = await self._get(rid)
        m = await self._dsr_meta(rid)
        if r.status in ("completed", "rejected"):
            raise APIError(409, ErrorCode.CONFLICT, f"Request already {r.status}")
        cfg = {**DSR_DEFAULTS, **(await self.platform_value("privacy.dsr", None) or {})}
        notify = None
        if body.action == "verify_identity":
            m["identity_verified"] = True
            r.status = "received"
            await self._note(rid, m, "identity_verified", method="document")
        elif body.action == "start":
            if not m.get("identity_verified"):
                raise APIError(
                    409, ErrorCode.CONFLICT, "Verify the requester's identity first", {"code": "IDENTITY_REQUIRED"}
                )
            r.status, r.handled_by = "in_progress", self.principal.id
            if r.request_type == "correction":
                m["work_items"] = [
                    {
                        "n": n,
                        "table": c.table,
                        "record_id": str(c.record_id) if c.record_id else None,
                        "field": c.field,
                        "new_value": c.new_value,
                        "owner_role": ROUTE_BY_TABLE.get(c.table, ("registrar", "students:update"))[0],
                        "permission": ROUTE_BY_TABLE.get(c.table, ("registrar", "students:update"))[1],
                        "status": "open",
                    }
                    for n, c in enumerate(body.corrections, start=1)
                ]
                for role in {w["owner_role"] for w in m["work_items"]}:
                    await notify_event(
                        self.db,
                        self.inst,
                        "privacy.dsr_in_progress",
                        audience={"roles": [role]},
                        context={"request_id": str(rid), "work_item": True},
                    )
            await self._note(rid, m, "started")
            from app.core.jobs import enqueue

            if r.request_type in ("access", "export"):
                await enqueue(self.db, self.principal, "privacy.dsr_export", {"request_id": str(rid)}, queue="reports")
            elif r.request_type == "erasure":
                await enqueue(self.db, self.principal, "privacy.dsr_erase", {"request_id": str(rid)}, queue="reports")
            notify = "privacy.dsr_in_progress"
        elif body.action == "extend":
            if int(m.get("extensions") or 0) >= 1:
                raise APIError(409, ErrorCode.CONFLICT, "A request can be extended once", {"code": "ALREADY_EXTENDED"})
            m["extensions"] = 1
            r.due_at = (r.due_at or datetime.now(UTC)) + timedelta(days=int(cfg["extension_days"]))
            r.status = "extended"
            await self._note(rid, m, "extended", reason=body.reason)
            notify = "privacy.dsr_extended"
        elif body.action == "complete":
            if any(w.get("status") != "done" for w in m.get("work_items") or []):
                raise APIError(409, ErrorCode.CONFLICT, "Open work items remain", {"code": "WORK_ITEMS_OPEN"})
            r.status, r.closed_at = "completed", datetime.now(UTC)
            await self._note(rid, m, "completed")
            notify = "privacy.dsr_completed"
        elif body.action == "reject":
            if not body.reason:
                raise APIError(422, ErrorCode.VALIDATION, "A reason is required", {"field": "reason"})
            r.status, r.closed_at = "rejected", datetime.now(UTC)
            await self._note(rid, m, "rejected", reason=body.reason)
            notify = "privacy.dsr_rejected"
        await self.db.flush()
        if notify:
            await notify_event(
                self.db,
                self.inst,
                notify,
                audience={"user_ids": [str(r.user_id)] + ([m["filed_by"]] if m.get("filed_by") else [])},
                context={"request_id": str(rid), "reason": body.reason},
            )
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type=f"privacy.dsr_{'started' if body.action == 'start' else body.action}",
            payload={"request_id": str(rid), "action": body.action},
            aggregate_type="data_subject_request",
            aggregate_id=rid,
            actor_user_id=self.principal.id,
        )
        await log_audit(
            self.db,
            principal=self.principal,
            module="privacy",
            action=f"dsr_{body.action}",
            record_type="data_subject_request",
            record_id=rid,
            new={"status": r.status, "reason": body.reason},
            request=self.request,
        )
        return await self._out(r)

    async def work_items(self, rid: uuid.UUID) -> builtins.list[dict[str, Any]]:
        await self._get(rid)
        return list((await self._dsr_meta(rid)).get("work_items") or [])

    async def work_item_done(self, rid: uuid.UUID, n: int) -> DsrOut:
        r = await self._get(rid)
        m = await self._dsr_meta(rid)
        items = m.get("work_items") or []
        item = next((w for w in items if int(w.get("n", 0)) == n), None)
        if item is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Work item not found")
        if not (self.officer() or self.can(*str(item["permission"]).split(":", 1))):
            raise forbidden(f"{item['permission']} required")
        item["status"], item["done_by"], item["done_at"] = "done", str(self.principal.id), datetime.now(UTC).isoformat()
        await self._note(rid, m, "work_item_done", n=n)
        await log_audit(
            self.db,
            principal=self.principal,
            module="privacy",
            action="dsr_work_item",
            record_type="data_subject_request",
            record_id=rid,
            new={"n": n, "table": item["table"]},
            request=self.request,
        )
        return await self._out(r)

    async def dashboard(self) -> dict[str, Any]:
        self.require("privacy:manage", "privacy:view_all")
        rows = (
            await self.db.execute(
                text(
                    "SELECT request_type, status, due_at, closed_at FROM data_subject_requests WHERE institution_id = :i"
                ),
                {"i": self.inst},
            )
        ).all()
        now = datetime.now(UTC)
        by_status: dict[str, int] = {}
        by_type: dict[str, int] = {}
        overdue = closed = on_time = 0
        for typ, st, due, closed_at in rows:
            by_status[st] = by_status.get(st, 0) + 1
            by_type[typ] = by_type.get(typ, 0) + 1
            if st not in ("completed", "rejected") and due and due < now:
                overdue += 1
            if closed_at:
                closed += 1
                on_time += 1 if (due is None or closed_at <= due) else 0
        return {
            "total": len(rows),
            "by_status": by_status,
            "by_type": by_type,
            "overdue": overdue,
            "sla_pct": round(100 * on_time / closed, 1) if closed else None,
        }

    async def register(self) -> builtins.list[dict[str, Any]]:
        """Annual DSR register (rows; the web exports them as CSV)."""
        self.require("privacy:manage", "privacy:view_all")
        rows = (
            (
                await self.db.execute(
                    text(
                        "SELECT id, request_type, status, created_at, due_at, closed_at FROM data_subject_requests "
                        "WHERE institution_id = :i ORDER BY created_at"
                    ),
                    {"i": self.inst},
                )
            )
            .mappings()
            .all()
        )
        return [{k: (str(v) if v is not None else None) for k, v in dict(r).items()} for r in rows]

    # ---- PII inventory / masking audit -------------------------------------------------------------------------------
    async def pii_inventory(self) -> builtins.list[dict[str, Any]]:
        self.require("privacy:manage", "privacy:view_all", "security:manage", "security:view_all")
        inv = await self.platform_value("privacy.pii_inventory", None)
        if inv:
            return list(inv)
        from app.core.pii_inventory import load_inventory

        return load_inventory()

    async def masking_audit(self) -> dict[str, Any]:
        self.require("privacy:manage", "security:manage")
        from app.core.pii_inventory import masking_audit

        result = masking_audit()
        await self.put_meta("masking_audit:latest", {**result, "at": datetime.now(UTC).isoformat()})
        await log_audit(
            self.db,
            principal=self.principal,
            module="privacy",
            action="masking_audit",
            record_type="privacy",
            record_id=None,
            new={"ok": result["ok"], "issues": len(result["issues"])},
            request=self.request,
        )
        return result

    async def masking_audit_latest(self) -> dict[str, Any]:
        self.require("privacy:manage", "privacy:view_all", "security:manage", "security:view_all")
        return dict(await self.meta("masking_audit:latest") or {"ok": None, "issues": []})


def _ip(request: Any) -> str | None:
    if request is None:
        return None
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return str(fwd.split(",")[0].strip())
    return request.client.host if request.client else None
