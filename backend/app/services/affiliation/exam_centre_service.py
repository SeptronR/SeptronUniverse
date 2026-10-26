"""Exam centres — Prompts/34 §34.6 ``exam_centre_service`` + ``centre_repository`` {affiliation.exam_centres}.

Centres per central session (``exam_sessions.college_id IS NULL``): a college acting as centre, a code, the chief
superintendent (centre college staff or a university observer), capacity with ``affiliation.centre_capacity_buffer_pct``.
The allocation run assigns the session's registering colleges to centres — ``nearest`` (college ``address.lat/lng``,
falling back to code order), ``capacity`` (largest remaining capacity first) or ``manual`` — and writes
``exam_centres.assigned_colleges``; routing is derived (registrations of the assigned colleges, Phase 14 seating in the
centre's rooms, Phase 15 ``answer_script_bundles.exam_centre_id``). Lowering the capacity below the routed count →
409 ``CAPACITY_BELOW_ROUTED``. Appointment letters render through Phase 26 ``centre_appointment``. The Phase 14
``/exam-sessions/{id}/centres`` routes delegate here.
"""

import math
import uuid
from typing import Any

from sqlalchemy import func, select, text

from app.core.errors import APIError, ErrorCode
from app.models.affiliation import ExamCentre
from app.models.exams import ExamRegistration, ExamSession
from app.models.platform import College
from app.schemas.affiliation import (
    AllocationSummary,
    CentreAllocationRun,
    CentreDashboard,
    DocumentRef,
    ExamCentreIn,
    ExamCentreOut,
)
from app.services.affiliation.common import AffiliationBase, forbidden, not_found, pairs, rule
from app.services.documents.render_service import register_resolver

ENTITY = "exam_centre"


def _geo(c: College) -> tuple[float, float] | None:
    a = c.address or {}
    try:
        return float(a["lat"]), float(a["lng"])
    except (KeyError, TypeError, ValueError):
        return None


def _distance(a: tuple[float, float] | None, b: tuple[float, float] | None) -> float:
    if a is None or b is None:
        return math.inf
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


class ExamCentreService(AffiliationBase):
    def require_manager(self) -> None:
        self.require_writer()
        if not (self.exam_office() or self.office()):
            raise forbidden("exams:configure (COE) or affiliation:manage required")

    async def session(self, sid: uuid.UUID) -> ExamSession:
        s = (
            await self.db.execute(
                select(ExamSession).where(ExamSession.id == sid, ExamSession.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if s is None:
            raise not_found("Exam session")
        return s

    async def _routed(self, centres: list[ExamCentre]) -> dict[uuid.UUID, int]:
        out: dict[uuid.UUID, int] = {}
        for c in centres:
            ids = {str(c.college_id), *[str(x) for x in c.assigned_colleges or []]}
            out[c.id] = int(
                (
                    await self.db.execute(
                        select(func.count())
                        .select_from(ExamRegistration)
                        .where(
                            ExamRegistration.exam_session_id == c.exam_session_id,
                            ExamRegistration.college_id.in_([uuid.UUID(x) for x in ids]),
                            ExamRegistration.status.in_(("confirmed", "submitted")),
                        )
                    )
                ).scalar_one()
            )
        return out

    async def _bundles(self, cid: uuid.UUID) -> dict[str, int]:
        rows = await self.db.execute(
            text(
                "SELECT status, count(*) FROM answer_script_bundles WHERE exam_centre_id = :c AND institution_id = :i "
                "GROUP BY status"
            ),
            {"c": cid, "i": self.inst},
        )
        return {str(s): int(n) for s, n in rows.all()}

    async def outs(self, rows: list[ExamCentre], *, detail: bool = True) -> list[ExamCentreOut]:
        colleges = await self.colleges_map([r.college_id for r in rows])
        names = await self.staff_names([r.chief_superintendent_staff_id for r in rows])
        buffer = await self.aff_int("centre_capacity_buffer_pct")
        routed = await self._routed(rows) if detail else {}
        metas = await self.metas("centre", [r.id for r in rows])
        out = []
        for r in rows:
            c = colleges.get(r.college_id)
            m = metas.get(str(r.id)) or {}
            n = routed.get(r.id, 0)
            eff = int(r.capacity * (100 + buffer) / 100) if r.capacity else None
            out.append(
                ExamCentreOut(
                    id=r.id,
                    exam_session_id=r.exam_session_id,
                    college_id=r.college_id,
                    college_code=c.code if c else None,
                    college_name=c.name if c else None,
                    centre_code=r.centre_code,
                    chief_superintendent_staff_id=r.chief_superintendent_staff_id,
                    chief_superintendent_name=names.get(r.chief_superintendent_staff_id)
                    if r.chief_superintendent_staff_id
                    else None,
                    capacity=r.capacity,
                    effective_capacity=eff,
                    assigned_colleges=[str(x) for x in r.assigned_colleges or []],
                    registrations_routed=n,
                    seating_status=("over_capacity" if eff is not None and n > eff else "ok") if detail else None,
                    bundles=await self._bundles(r.id) if detail else {},
                    appointment_document_id=uuid.UUID(m["appointment_document_id"])
                    if m.get("appointment_document_id")
                    else None,
                )
            )
        return out

    async def _visible_centres(self, stmt: Any) -> Any:
        if self.system() or self.office_reader() or self.exam_office() or self.reader_all("exams"):
            return stmt
        mine = self.my_college_ids()
        if not mine:
            return stmt.where(ExamCentre.id.is_(None))
        return stmt.where(ExamCentre.college_id.in_(mine))

    async def list_centres(self, session_id: uuid.UUID | None) -> list[ExamCentreOut]:
        stmt = select(ExamCentre).where(ExamCentre.institution_id == self.inst)
        if session_id:
            stmt = stmt.where(ExamCentre.exam_session_id == session_id)
        stmt = await self._visible_centres(stmt)
        rows = list((await self.db.execute(stmt.order_by(ExamCentre.centre_code))).scalars())
        return await self.outs(rows)

    async def _row(self, cid: uuid.UUID, *, lock: bool = False) -> ExamCentre:
        stmt = select(ExamCentre).where(ExamCentre.id == cid, ExamCentre.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        stmt = await self._visible_centres(stmt)
        c: ExamCentre | None = (await self.db.execute(stmt)).scalar_one_or_none()
        if c is None:
            raise not_found("Centre")
        return c

    async def get(self, cid: uuid.UUID) -> ExamCentreOut:
        return (await self.outs([await self._row(cid)]))[0]

    async def save(self, body: ExamCentreIn, cid: uuid.UUID | None = None) -> ExamCentreOut:
        self.require_manager()
        await self.college(body.college_id)
        assigned = [str(x) for x in dict.fromkeys(body.assigned_colleges) if x != body.college_id]
        if cid is not None:
            c = await self._row(cid, lock=True)
            if body.capacity is not None:
                routed = (await self._routed([c]))[c.id]
                buffer = await self.aff_int("centre_capacity_buffer_pct")
                if routed > int(body.capacity * (100 + buffer) / 100):
                    raise rule(
                        f"{routed} registrations are routed to {c.centre_code}; capacity {body.capacity} is too low",
                        "CAPACITY_BELOW_ROUTED",
                        routed=routed,
                    )
            c.college_id, c.centre_code = body.college_id, body.centre_code
            c.chief_superintendent_staff_id, c.capacity = body.chief_superintendent_staff_id, body.capacity
            c.assigned_colleges = assigned
            event = "affiliation.centre_updated"
        else:
            if body.exam_session_id is None:
                raise APIError(422, ErrorCode.VALIDATION, "exam_session_id is required", {"field": "exam_session_id"})
            s = await self.session(body.exam_session_id)
            if s.college_id is not None:
                raise rule("Centres belong to central (university) sessions", "NOT_CENTRAL", 422)
            dup = (
                await self.db.execute(
                    select(ExamCentre.id).where(
                        ExamCentre.exam_session_id == s.id, ExamCentre.centre_code == body.centre_code
                    )
                )
            ).first()
            if dup:
                raise rule(f"Centre code {body.centre_code} exists in the session", "DUPLICATE_CENTRE")
            c = ExamCentre(
                institution_id=self.inst,
                exam_session_id=s.id,
                college_id=body.college_id,
                centre_code=body.centre_code,
                chief_superintendent_staff_id=body.chief_superintendent_staff_id,
                capacity=body.capacity,
                assigned_colleges=assigned,
            )
            self.db.add(c)
            event = "affiliation.centre_created"
        col = await self.college(body.college_id)
        if not col.is_exam_centre:
            col.is_exam_centre = True
            col.exam_centre_code = col.exam_centre_code or body.centre_code
        await self.db.flush()
        await self._emit(event, {"centre_id": str(c.id), "session_id": str(c.exam_session_id)}, ENTITY, c.id)
        return (await self.outs([c]))[0]

    async def allocate(self, body: CentreAllocationRun) -> AllocationSummary:
        self.require_manager()
        s = await self.session(body.exam_session_id)
        centres = list(
            (
                await self.db.execute(select(ExamCentre).where(ExamCentre.exam_session_id == s.id).with_for_update())
            ).scalars()
        )
        if not centres:
            raise rule("Create the session's centres first", "NO_CENTRES", 422)
        regs = pairs(
            (
                await self.db.execute(
                    select(ExamRegistration.college_id, func.count())
                    .where(
                        ExamRegistration.exam_session_id == s.id,
                        ExamRegistration.status.in_(("confirmed", "submitted")),
                    )
                    .group_by(ExamRegistration.college_id)
                )
            ).all()
        )
        colleges = await self.colleges_map([*regs.keys(), *[c.college_id for c in centres]])
        buffer = await self.aff_int("centre_capacity_buffer_pct")
        cap = {
            c.id: int((c.capacity or 10**6) * (100 + buffer) / 100) - int(regs.get(c.college_id, 0)) for c in centres
        }
        assigned: dict[uuid.UUID, list[str]] = {c.id: [] for c in centres}
        centre_colleges = {c.college_id for c in centres}
        unassigned: list[str] = []
        if body.strategy == "manual":
            for cid_s, ids in body.manual.items():
                cid = uuid.UUID(cid_s)
                if cid not in assigned:
                    raise APIError(422, ErrorCode.VALIDATION, f"Centre {cid_s} is not in the session")
                assigned[cid] = [str(x) for x in ids if x not in centre_colleges]
        else:
            pending = sorted(
                [cid for cid in regs if cid not in centre_colleges and colleges.get(cid) is not None],
                key=lambda x: -int(regs[x]),
            )
            for col_id in pending:
                need = int(regs[col_id])
                col = colleges[col_id]
                if body.strategy == "nearest":
                    order = sorted(
                        centres,
                        key=lambda c: (_distance(_geo(col), _geo(colleges[c.college_id])), c.centre_code),
                    )
                else:
                    order = sorted(centres, key=lambda c: -cap[c.id])
                pick = next((c for c in order if cap[c.id] >= need), None)
                if pick is None:
                    unassigned.append(col.code)
                    continue
                assigned[pick.id].append(str(col_id))
                cap[pick.id] -= need
        over = []
        for c in centres:
            c.assigned_colleges = assigned[c.id]
        await self.db.flush()
        routed = await self._routed(centres)
        for c in centres:
            if c.capacity and routed[c.id] > int(c.capacity * (100 + buffer) / 100):
                over.append(c.centre_code)
            await self._emit(
                "affiliation.centre_allocated",
                {"centre_id": str(c.id), "colleges": assigned[c.id]},
                ENTITY,
                c.id,
            )
            for col_id in assigned[c.id]:
                target = colleges.get(uuid.UUID(col_id))
                if target is not None:
                    await self.notify_college(
                        target,
                        "affiliation.centre_assigned",
                        {"centre": c.centre_code, "session": s.name},
                        "college_admin",
                        "college_exam_coordinator",
                    )
        await self._audit("centre_allocation", "exam_session", s.id, None, {"strategy": body.strategy})
        return AllocationSummary(
            exam_session_id=s.id,
            strategy=body.strategy,
            centres=len(centres),
            colleges_assigned=sum(len(v) for v in assigned.values()),
            unassigned=unassigned,
            over_capacity=over,
        )

    async def appointment(self, cid: uuid.UUID) -> DocumentRef:
        self.require_manager()
        c = await self._row(cid)
        if c.chief_superintendent_staff_id is None:
            raise rule("Name the chief superintendent first", "NO_CHIEF_SUPERINTENDENT", 422)
        doc = await self.render_doc("centre_appointment", ENTITY, c.id, None, allow_multiple=True)
        m = await self.meta("centre", c.id)
        m["appointment_document_id"] = str(doc.issued_document_id) if doc else None
        await self.put_meta("centre", c.id, m)
        await self._emit("affiliation.centre_appointed", {"centre_id": str(c.id)}, ENTITY, c.id)
        user = await self.staff_user(c.chief_superintendent_staff_id)
        s = await self.session(c.exam_session_id)
        await self._notify("affiliation.centre_assigned", [user], {"centre": c.centre_code, "session": s.name})
        return DocumentRef(
            issued_document_id=doc.issued_document_id if doc else None,
            document_number=doc.document_number if doc else None,
            url=doc.pdf_url if doc else None,
        )

    async def dashboard(self, cid: uuid.UUID) -> CentreDashboard:
        c = await self._row(cid)
        out = (await self.outs([c]))[0]
        ids = [c.college_id, *[uuid.UUID(x) for x in c.assigned_colleges or []]]
        by = pairs(
            (
                await self.db.execute(
                    select(ExamRegistration.college_id, func.count())
                    .where(
                        ExamRegistration.exam_session_id == c.exam_session_id,
                        ExamRegistration.college_id.in_(ids),
                        ExamRegistration.status.in_(("confirmed", "submitted")),
                    )
                    .group_by(ExamRegistration.college_id)
                )
            ).all()
        )
        colleges = await self.colleges_map(ids)
        p = {"s": c.exam_session_id, "c": c.college_id}
        seated = int(
            (
                await self.db.execute(
                    text(
                        "SELECT count(*) FROM exam_seat_allocations a JOIN exam_seating_plans sp ON sp.id = a.seating_plan_id "
                        "JOIN rooms r ON r.id = sp.room_id WHERE sp.exam_session_id = :s AND r.college_id = :c"
                    ),
                    p,
                )
            ).scalar_one()
            or 0
        )
        return CentreDashboard(
            centre=out,
            registrations_by_college={(colleges[k].code if k in colleges else str(k)): int(v) for k, v in by.items()},
            seating_allocated=seated,
            attendance_marked=0,
            bundles=out.bundles,
        )

    async def mine(self) -> list[CentreDashboard]:
        mine = self.my_college_ids()
        if not mine:
            return []
        from sqlalchemy import or_

        conds = [ExamCentre.college_id.in_(mine)] + [ExamCentre.assigned_colleges.contains([str(m)]) for m in mine]
        rows = list(
            (
                await self.db.execute(
                    select(ExamCentre).where(ExamCentre.institution_id == self.inst, or_(*conds)).limit(20)
                )
            ).scalars()
        )
        out = []
        for r in rows:
            if r.college_id in mine:
                out.append(await self.dashboard(r.id))
            else:
                centre = (await self.outs([r]))[0]
                out.append(CentreDashboard(centre=centre))
        return out


@register_resolver(ENTITY)
async def _centre_ctx(svc: Any, cid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    from app.models.hr import Staff

    c = (await svc.db.execute(select(ExamCentre).where(ExamCentre.id == cid))).scalar_one()
    s = (await svc.db.execute(select(ExamSession).where(ExamSession.id == c.exam_session_id))).scalar_one()
    col = (await svc.db.execute(select(College).where(College.id == c.college_id))).scalar_one()
    cs = (
        (await svc.db.execute(select(Staff).where(Staff.id == c.chief_superintendent_staff_id))).scalar_one_or_none()
        if c.chief_superintendent_staff_id
        else None
    )
    name = " ".join(x for x in (cs.first_name, cs.last_name) if x) if cs else ""
    return (
        {
            "centre": {"code": c.centre_code, "college": col.name, "capacity": c.capacity or ""},
            "session": {
                "name": s.name,
                "start": s.start_date.isoformat() if s.start_date else "",
                "end": s.end_date.isoformat() if s.end_date else "",
            },
            "appointee": {"name": name},
            "title": f"Appointment — chief superintendent, centre {c.centre_code}",
            "body": "",
        },
        "staff" if cs else None,
        cs.id if cs else None,
    )
