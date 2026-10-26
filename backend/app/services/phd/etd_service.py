"""ETD upload — Prompts/31 §31.6 ``etd_service`` ({phd.etd_upload}).

Within ``phd.rules.etd_deadline_days`` of the award the final thesis is packaged with Dublin Core metadata (title,
author, guide, department, year, keywords, abstract, embargo) and deposited through the ``koha_dspace_shodhganga``
adapter (Shodhganga via INFLIBNET, or the institutional DSpace of Phase 19 — mocks until Phase 41: the mock returns a
handle ``10603/<n>``; a file URL carrying ``#etd=fail`` simulates a failure). ``pending → uploaded | failed``; failed
uploads are retried. Embargo requests (patent-related) are approved by the research cell before the upload goes
public. Weekly reminders from day 25 for an awarded thesis without an upload.
"""

import hashlib
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from app.models.phd import EtdUpload, ResearchScholar, ThesisSubmission
from app.schemas.phd import EtdEmbargo, EtdOut, EtdUploadRequest
from app.services.phd.common import PhdBase, forbidden, not_found, now_utc, rule, staff_name

ENTITY = "etd_upload"


class EtdService(PhdBase):
    async def outs(self, rows: list[EtdUpload]) -> list[EtdOut]:
        metas = await self.metas("etd", [r.id for r in rows])
        out = []
        for r in rows:
            m = metas.get(str(r.id)) or {}
            out.append(
                EtdOut(
                    id=r.id,
                    thesis_id=r.thesis_id,
                    repository=r.repository,
                    handle=r.handle,
                    uploaded_at=r.uploaded_at,
                    status=r.status,
                    job_id=r.job_id,
                    due_on=date.fromisoformat(m["due_on"]) if m.get("due_on") else None,
                    embargo=m.get("embargo"),
                    error=m.get("error"),
                )
            )
        return out

    async def _thesis(self, tid: uuid.UUID) -> tuple[ThesisSubmission, ResearchScholar]:
        t = (
            await self.db.execute(
                select(ThesisSubmission).where(ThesisSubmission.id == tid, ThesisSubmission.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if t is None:
            raise not_found("Thesis submission")
        return t, await self.scholar(t.scholar_id)

    async def for_thesis(self, tid: uuid.UUID) -> list[EtdOut]:
        t, _ = await self._thesis(tid)
        rows = list((await self.db.execute(select(EtdUpload).where(EtdUpload.thesis_id == t.id))).scalars())
        return await self.outs(rows)

    async def request_upload(self, tid: uuid.UUID, body: EtdUploadRequest) -> EtdOut:
        self.require_cell("etd")
        t, s = await self._thesis(tid)
        if s.status != "awarded":
            raise rule("ETD upload follows the award", "NOT_AWARDED")
        existing = (
            await self.db.execute(
                select(EtdUpload).where(EtdUpload.thesis_id == t.id, EtdUpload.repository == body.repository.value)
            )
        ).scalar_one_or_none()
        if existing is not None and existing.status != "failed":
            raise rule("An upload exists for this repository", "ETD_EXISTS")
        if existing is None:
            existing = EtdUpload(institution_id=self.inst, thesis_id=t.id, repository=body.repository.value)
            self.db.add(existing)
            await self.db.flush()
        due = (await self.meta("scholar", s.id)).get("etd_due_on")
        m = await self.meta("etd", existing.id)
        m["due_on"] = due
        await self.put_meta("etd", existing.id, m)
        return (await self.outs([existing]))[0]

    async def _metadata(self, t: ThesisSubmission, s: ResearchScholar) -> dict[str, Any]:
        cards = await self.enrollment_cards([s.student_program_enrollment_id])
        c = cards.get(s.student_program_enrollment_id) or {}
        tm = await self.meta("thesis", t.id)
        guide = await self.staff_map([s.guide_staff_id])
        dep_id: uuid.UUID | None = c.get("department_id")
        dept = (await self.department_codes([dep_id])).get(dep_id) if dep_id else None
        return {
            "dc.title": t.title,
            "dc.creator": c.get("name"),
            "dc.contributor.guide": staff_name(guide.get(s.guide_staff_id)),
            "dc.publisher.department": dept,
            "dc.date.awarded": (tm.get("award") or {}).get("date_of_award"),
            "dc.subject": tm.get("keywords") or [],
            "dc.description.abstract": tm.get("abstract"),
            "dc.rights.embargo": tm.get("embargo"),
        }

    async def upload(self, eid: uuid.UUID, job_id: uuid.UUID | None = None) -> EtdOut:
        """Body of the ``phd.etd_upload`` job (``EtdRepository.upload`` — mock returns a handle)."""
        from app.integrations.registry import get_adapter

        r = (
            await self.db.execute(
                select(EtdUpload).where(EtdUpload.id == eid, EtdUpload.institution_id == self.inst).with_for_update()
            )
        ).scalar_one_or_none()
        if r is None:
            raise not_found("ETD upload")
        if r.status == "uploaded":
            return (await self.outs([r]))[0]
        t = (await self.db.execute(select(ThesisSubmission).where(ThesisSubmission.id == r.thesis_id))).scalar_one()
        s = await self.scholar_raw(t.scholar_id)
        m = await self.meta("etd", r.id)
        emb = m.get("embargo") or {}
        if emb and emb.get("status") == "requested":
            raise rule("The embargo request is pending", "EMBARGO_PENDING")
        meta = await self._metadata(t, s)
        r.job_id = job_id or r.job_id
        if "#etd=fail" in (t.file_url or ""):
            r.status = "failed"
            m["error"] = "Repository rejected the package (simulated)"
            r.response = {"error": m["error"]}
            await self.put_meta("etd", r.id, m)
            await self.db.flush()
            await self._emit("phd.etd_failed", {"etd_id": str(r.id), "thesis_id": str(t.id)}, ENTITY, r.id)
            return (await self.outs([r]))[0]
        adapter = get_adapter("koha_dspace_shodhganga", "mock")
        res = await adapter.send(repository=r.repository, file_url=t.file_url, metadata=meta)
        n = int(hashlib.sha256(str(t.id).encode()).hexdigest()[:6], 16) % 999_999
        r.handle = f"10603/{n}" if r.repository == "shodhganga" else f"123456789/{n}"
        r.status, r.uploaded_at = "uploaded", now_utc()
        r.response = {"provider": res.get("provider") if isinstance(res, dict) else "mock", "metadata": meta}
        m.pop("error", None)
        await self.put_meta("etd", r.id, m)
        await self.db.flush()
        await self._emit(
            "phd.etd_uploaded", {"etd_id": str(r.id), "thesis_id": str(t.id), "handle": r.handle}, ENTITY, r.id
        )
        await self._notify(
            "phd.etd_uploaded",
            [await self.scholar_user(s), *await self.guide_users(s)],
            {
                "repository": "Shodhganga" if r.repository == "shodhganga" else "the institutional repository",
                "handle": r.handle,
            },
        )
        return (await self.outs([r]))[0]

    async def retry(self, eid: uuid.UUID) -> EtdOut:
        self.require_cell("etd")
        r = (
            await self.db.execute(select(EtdUpload).where(EtdUpload.id == eid, EtdUpload.institution_id == self.inst))
        ).scalar_one_or_none()
        if r is None:
            raise not_found("ETD upload")
        if r.status != "failed":
            raise rule("Only a failed upload is retried", "NOT_FAILED")
        r.status = "pending"
        await self.db.flush()
        return (await self.outs([r]))[0]

    async def embargo(self, eid: uuid.UUID, body: EtdEmbargo) -> EtdOut:
        self.require_writer()
        r = (
            await self.db.execute(
                select(EtdUpload).where(EtdUpload.id == eid, EtdUpload.institution_id == self.inst).with_for_update()
            )
        ).scalar_one_or_none()
        if r is None:
            raise not_found("ETD upload")
        t, s = await self._thesis(r.thesis_id)
        m = await self.meta("etd", r.id)
        if body.approve is None:
            if not (await self.is_self(s) or await self.is_guide_of(s) or self.cell("etd")):
                raise forbidden("The scholar, guide or research cell requests an embargo")
            m["embargo"] = {
                "months": body.months,
                "reason": body.reason,
                "remarks": body.remarks,
                "status": "requested",
                "requested_at": now_utc().isoformat(),
            }
        else:
            if not self.cell("etd"):
                raise forbidden("The research cell decides embargoes")
            emb = dict(m.get("embargo") or {})
            if emb.get("status") != "requested":
                raise rule("No embargo request is pending", "NO_EMBARGO_REQUEST")
            emb["status"] = "approved" if body.approve else "rejected"
            if body.approve:
                emb["until"] = (await self.today() + timedelta(days=30 * body.months)).isoformat()
            m["embargo"] = emb
            tm = await self.meta("thesis", t.id)
            tm["embargo"] = emb
            await self.put_meta("thesis", t.id, tm)
        await self.put_meta("etd", r.id, m)
        await self.db.flush()
        return (await self.outs([r]))[0]

    async def status_board(self) -> list[dict[str, Any]]:
        if not (self.cell("etd") or self.can("phd", "view_all")):
            raise forbidden("phd:etd required")
        from app.services.phd.award_service import AwardService

        rows = await AwardService(self.db, self.principal, self.request, self.inst).awards()
        ups: dict[str, list[EtdUpload]] = {}
        for u in (await self.db.execute(select(EtdUpload).where(EtdUpload.institution_id == self.inst))).scalars():
            ups.setdefault(str(u.thesis_id), []).append(u)
        out = []
        for a in rows:
            sid = uuid.UUID(a["scholar_id"])
            th = (
                await self.db.execute(
                    select(ThesisSubmission.id)
                    .where(ThesisSubmission.scholar_id == sid, ThesisSubmission.stage.in_(("thesis", "revised_thesis")))
                    .order_by(ThesisSubmission.submitted_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            found = ups.get(str(th), []) if th else []
            out.append(
                {
                    **a,
                    "thesis_id": str(th) if th else None,
                    "etd": [{"repository": x.repository, "status": x.status, "handle": x.handle} for x in found],
                }
            )
        return out

    async def deadline_reminders(self) -> int:
        today = await self.today()
        n = 0
        days = await self.rule_int("etd_deadline_days")
        for s in (
            await self.db.execute(
                select(ResearchScholar).where(
                    ResearchScholar.institution_id == self.inst, ResearchScholar.status == "awarded"
                )
            )
        ).scalars():
            sm = await self.meta("scholar", s.id)
            due = sm.get("etd_due_on")
            if not due or sm.get("etd_reminded"):
                continue
            due_d = date.fromisoformat(due)
            if (due_d - today).days > max(0, days - 25):
                continue
            uploaded = (
                await self.db.execute(
                    select(EtdUpload.id)
                    .join(ThesisSubmission, ThesisSubmission.id == EtdUpload.thesis_id)
                    .where(ThesisSubmission.scholar_id == s.id, EtdUpload.status == "uploaded")
                )
            ).first()
            if uploaded is not None:
                continue
            sm["etd_reminded"] = today.isoformat()
            await self.put_meta("scholar", s.id, sm)
            await self._notify(
                "phd.duration_warning",
                [await self.scholar_user(s), *await self.guide_users(s)],
                {"scholar": await self.scholar_name(s), "max_end": f"ETD upload due {due}", "months": 0},
            )
            n += 1
        return n

    async def pending_ids(self) -> list[uuid.UUID]:
        return [
            r[0]
            for r in (
                await self.db.execute(
                    select(EtdUpload.id).where(EtdUpload.institution_id == self.inst, EtdUpload.status == "pending")
                )
            ).all()
        ]
