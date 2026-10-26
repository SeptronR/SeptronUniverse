"""Viva-voce — Prompts/31 §31.6 ``viva_service`` ({phd.viva}).

Scheduled once the examiner recommendations consolidate to ``viva_eligible`` (409 ``NOT_VIVA_ELIGIBLE``): date,
venue / link, panel (guide + external examiner(s) + DC members per policy); an open defence publishes a notice
(``GET /phd/viva/upcoming`` public list and ``phd.viva_scheduled`` for the Phase 25 calendar). The result
``recommended | re_viva | not_recommended`` is recorded with the report; ``re_viva`` reschedules at most
``phd.rules.re_viva_max`` times; ``recommended`` makes the scholar eligible for the award request.
"""

import uuid
from typing import Any

from sqlalchemy import select

from app.models.phd import ResearchScholar, ThesisSubmission, VivaVoce
from app.schemas.phd import VivaNotice, VivaOut, VivaResultIn, VivaSchedule, VivaUpdate
from app.services.phd.common import PhdBase, forbidden, not_found, now_utc, rule

ENTITY = "viva_voce"


class VivaService(PhdBase):
    def examiner_desk(self) -> bool:
        p = self.principal
        return self.cell("examine") or (p is not None and p.has("phd", "examine") and not self.can("phd", "self"))

    async def outs(self, rows: list[VivaVoce]) -> list[VivaOut]:
        if not rows:
            return []
        theses = {
            t.id: t
            for t in (
                await self.db.execute(
                    select(ThesisSubmission).where(ThesisSubmission.id.in_([r.thesis_id for r in rows]))
                )
            ).scalars()
        }
        scholars = {
            s.id: s
            for s in (
                await self.db.execute(
                    select(ResearchScholar).where(ResearchScholar.id.in_([t.scholar_id for t in theses.values()]))
                )
            ).scalars()
        }
        cards = await self.enrollment_cards([s.student_program_enrollment_id for s in scholars.values()])
        metas = await self.metas("viva", [r.id for r in rows])
        out = []
        for r in rows:
            t = theses.get(r.thesis_id)
            s = scholars.get(t.scholar_id) if t else None
            m = metas.get(str(r.id)) or {}
            out.append(
                VivaOut(
                    id=r.id,
                    thesis_id=r.thesis_id,
                    scholar_id=s.id if s else None,
                    scholar_name=(cards.get(s.student_program_enrollment_id) or {}).get("name") if s else None,
                    title=t.title if t else None,
                    scheduled_at=r.scheduled_at,
                    venue_or_link=r.venue_or_link,
                    panel=list(r.panel or []),
                    held_at=r.held_at,
                    result=r.result,
                    report_url=r.report_url,
                    re_viva_count=int(m.get("re_viva_count") or 0),
                    open_defence=bool(m.get("open_defence", True)),
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

    async def get_for_thesis(self, tid: uuid.UUID) -> VivaOut | None:
        t, _ = await self._thesis(tid)
        v = (await self.db.execute(select(VivaVoce).where(VivaVoce.thesis_id == t.id))).scalar_one_or_none()
        return (await self.outs([v]))[0] if v is not None else None

    async def schedule(self, tid: uuid.UUID, body: VivaSchedule) -> VivaOut:
        self.require_writer()
        if not self.examiner_desk():
            raise forbidden("phd:examine required")
        t, s = await self._thesis(tid)
        if (await self.meta("thesis", t.id)).get("consolidated") != "viva_eligible":
            raise rule("Examiner recommendations do not allow a viva yet", "NOT_VIVA_ELIGIBLE")
        if not any(p.role == "external_examiner" for p in body.panel):
            raise rule("The panel needs an external examiner", "EXTERNAL_REQUIRED", 422)
        v = (
            await self.db.execute(select(VivaVoce).where(VivaVoce.thesis_id == t.id).with_for_update())
        ).scalar_one_or_none()
        if v is not None and v.result != "re_viva":
            raise rule("A viva is already scheduled — update it instead", "VIVA_EXISTS")
        m: dict[str, Any] = {}
        if v is None:
            v = VivaVoce(institution_id=self.inst, thesis_id=t.id)
            self.db.add(v)
        else:
            await self.db.flush()
            m = await self.meta("viva", v.id)
            if int(m.get("re_viva_count") or 0) > await self.rule_int("re_viva_max"):
                raise rule("The re-viva allowance is used", "RE_VIVA_LIMIT")
            v.result, v.held_at, v.report_url = None, None, None
        v.scheduled_at, v.venue_or_link = body.scheduled_at, body.venue_or_link
        v.panel = [p.model_dump(mode="json") for p in body.panel]
        await self.db.flush()
        m["open_defence"] = body.open_defence
        await self.put_meta("viva", v.id, m)
        from app.services.phd.scholar_service import ScholarService

        await ScholarService(self.db, self.principal, self.request, self.inst).set_status(
            s, "viva_scheduled", reason="viva scheduled", force=s.status == "viva_scheduled"
        )
        await self._emit(
            "phd.viva_scheduled",
            {
                "viva_id": str(v.id),
                "thesis_id": str(t.id),
                "scholar_id": str(s.id),
                "scheduled_at": v.scheduled_at.isoformat() if v.scheduled_at else None,
                "venue": v.venue_or_link,
                "open_defence": body.open_defence,
                "title": t.title,
            },
            ENTITY,
            v.id,
        )
        await self._notify(
            "phd.viva_scheduled",
            [await self.scholar_user(s), *await self.guide_users(s)],
            {
                "scholar": await self.scholar_name(s),
                "title": t.title or "",
                "scheduled_at": v.scheduled_at.strftime("%d-%m-%Y %H:%M") if v.scheduled_at else "",
                "venue": v.venue_or_link or "",
            },
        )
        return (await self.outs([v]))[0]

    async def _row(self, vid: uuid.UUID) -> VivaVoce:
        v = (
            await self.db.execute(
                select(VivaVoce).where(VivaVoce.id == vid, VivaVoce.institution_id == self.inst).with_for_update()
            )
        ).scalar_one_or_none()
        if v is None:
            raise not_found("Viva")
        await self._thesis(v.thesis_id)
        return v

    async def update(self, vid: uuid.UUID, body: VivaUpdate) -> VivaOut:
        self.require_writer()
        if not self.examiner_desk():
            raise forbidden("phd:examine required")
        v = await self._row(vid)
        if v.held_at is not None:
            raise rule("A held viva is not rescheduled", "VIVA_HELD")
        data = body.model_dump(exclude_unset=True, mode="json")
        if "scheduled_at" in data and body.scheduled_at:
            v.scheduled_at = body.scheduled_at
        if "venue_or_link" in data:
            v.venue_or_link = body.venue_or_link
        if body.panel is not None:
            v.panel = [p.model_dump(mode="json") for p in body.panel]
        await self.db.flush()
        return (await self.outs([v]))[0]

    async def result(self, vid: uuid.UUID, body: VivaResultIn) -> VivaOut:
        self.require_writer()
        p = self.principal
        if not (self.examiner_desk() or (p is not None and p.has("phd", "examine"))):
            raise forbidden("phd:examine required")
        v = await self._row(vid)
        if v.result and v.result != "re_viva":
            raise rule("The result is recorded", "RESULT_RECORDED")
        v.result, v.report_url, v.held_at = body.result.value, body.report_url, body.held_at
        m = await self.meta("viva", v.id)
        m["attendance"] = body.attendance
        if v.result == "re_viva":
            m["re_viva_count"] = int(m.get("re_viva_count") or 0) + 1
        m.setdefault("history", []).append(
            {"result": v.result, "held_at": body.held_at.isoformat(), "at": now_utc().isoformat()}
        )
        await self.put_meta("viva", v.id, m)
        await self.db.flush()
        await self._emit(
            "phd.viva_held", {"viva_id": str(v.id), "thesis_id": str(v.thesis_id), "result": v.result}, ENTITY, v.id
        )
        return (await self.outs([v]))[0]

    async def upcoming(self, *, public: bool = False, limit: int = 50) -> list[VivaNotice] | list[VivaOut]:
        rows = list(
            (
                await self.db.execute(
                    select(VivaVoce)
                    .where(
                        VivaVoce.institution_id == self.inst,
                        VivaVoce.held_at.is_(None),
                        VivaVoce.scheduled_at >= now_utc(),
                    )
                    .order_by(VivaVoce.scheduled_at)
                    .limit(limit)
                )
            ).scalars()
        )
        outs = await self.outs(rows)
        if not public:
            return outs
        return [
            VivaNotice(
                scholar_name=o.scholar_name,
                title=o.title,
                scheduled_at=o.scheduled_at,
                venue_or_link=o.venue_or_link,
            )
            for o in outs
            if o.open_defence
        ]
