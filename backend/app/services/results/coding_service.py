# mypy: disable-error-code="arg-type,var-annotated"
"""Coding & custody — Prompts/15 §15.6 ``coding_service`` / ``custody_service``.

* bundles per paper × room (or centre) from the paper's ``exam_attendance(present|malpractice)`` items, ``size`` scripts
  each (setting ``exams.bundle_size``, default 30); one ``answer_scripts`` row per item (``UNIQUE`` item) — items
  already scripted are skipped, so re-running only adds new bundles;
* ``code(bundle)`` replaces the provisional numbers with random dummy numbers (paper prefix + 6 digits, unique per
  bundle and — by retry — per paper); scripts become ``coded``; the mapping (script → item) is never returned by any
  evaluator route and only ``decode`` (``exams:decode``) joins it;
* custody log: ``created`` on bundle creation, then dispatched / received / handed_over / returned (``exams:custody``);
  the bundle status follows (``dispatched`` / ``received``) and the holder / location are stored on the bundle;
* retention: ``archive`` after publication (setting ``exams.script_retention_months``, default 6, checked weekly by
  Beat and enforceable on demand), ``destroy`` needs ``exams:manage`` (COE) and an archived bundle.
"""

import secrets
import uuid
from collections import defaultdict
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.models.exams import (
    ExamAttendance,
    ExamPaper,
    ExamRegistrationItem,
    ExamSeatAllocation,
    ExamSeatingPlan,
    ExamSession,
)
from app.models.results import ResultPublication
from app.models.timetable import Room
from app.models.valuation import AnswerScript, AnswerScriptBundle, ScriptCustodyLog
from app.schemas.valuation import (
    BundleCreateRequest,
    BundleResponse,
    CodeBundleResponse,
    CustodyLogCreate,
    CustodyLogResponse,
    DummyScript,
    ScriptRegisterRow,
    ScriptRetentionRequest,
)
from app.services.exams.common import ExamBase, now_utc, rule

CUSTODY_STATUS = {"dispatched": "dispatched", "received": "received"}


class CodingService(ExamBase):
    audit_module = "exams"

    async def _staff_id(self) -> uuid.UUID | None:
        from app.models.hr import Staff

        if self.actor_id is None:
            return None
        return (
            await self.db.execute(select(Staff.id).where(Staff.user_id == self.actor_id, Staff.deleted_at.is_(None)))
        ).scalar_one_or_none()

    async def bundle(self, bid: uuid.UUID, *, for_update: bool = False) -> AnswerScriptBundle:
        q = select(AnswerScriptBundle).where(
            AnswerScriptBundle.id == bid, AnswerScriptBundle.institution_id == self.inst
        )
        if for_update:
            q = q.with_for_update()
        b = (await self.db.execute(q)).scalar_one_or_none()
        if b is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Bundle not found")
        await self.paper(b.exam_paper_id)  # session visibility (college scope)
        return b

    async def _out(self, rows: list[AnswerScriptBundle]) -> list[BundleResponse]:
        from app.models.valuation import ValuationAssignment

        if not rows:
            return []
        papers = dict(
            (
                await self.db.execute(
                    select(ExamPaper.id, ExamPaper.paper_code).where(ExamPaper.id.in_({b.exam_paper_id for b in rows}))
                )
            ).all()
        )
        rooms = dict(
            (
                await self.db.execute(
                    select(Room.id, Room.code).where(Room.id.in_({b.room_id for b in rows if b.room_id}))
                )
            ).all()
        )
        rounds: dict[uuid.UUID, list[dict[str, Any]]] = defaultdict(list)
        for a in (
            await self.db.execute(
                select(ValuationAssignment).where(ValuationAssignment.bundle_id.in_([b.id for b in rows]))
            )
        ).scalars():
            rounds[a.bundle_id].append(
                {"round": a.valuation_round, "status": a.status, "evaluator_type": a.evaluator_type, "id": str(a.id)}
            )
        return [
            BundleResponse(
                id=b.id,
                exam_paper_id=b.exam_paper_id,
                paper_code=papers.get(b.exam_paper_id),
                room_id=b.room_id,
                room_code=rooms.get(b.room_id) if b.room_id else None,
                exam_centre_id=b.exam_centre_id,
                bundle_number=b.bundle_number,
                script_count=b.script_count,
                status=b.status,
                coded_at=b.coded_at,
                custody_holder_staff_id=b.custody_holder_staff_id,
                custody_location=b.custody_location,
                rounds=sorted(rounds.get(b.id, []), key=lambda r: r["round"]),
            )
            for b in rows
        ]

    async def list_bundles(self, pid: uuid.UUID) -> list[BundleResponse]:
        p, _ = await self.paper(pid)
        rows = list(
            (
                await self.db.execute(
                    select(AnswerScriptBundle)
                    .where(AnswerScriptBundle.exam_paper_id == p.id)
                    .order_by(AnswerScriptBundle.bundle_number)
                )
            ).scalars()
        )
        return await self._out(rows)

    async def get_bundle(self, bid: uuid.UUID) -> BundleResponse:
        return (await self._out([await self.bundle(bid)]))[0]

    async def create_bundles(self, pid: uuid.UUID, body: BundleCreateRequest) -> list[BundleResponse]:
        p, s = await self.paper(pid, for_update=True)
        if s.status in ("draft", "registration_open", "registration_closed"):
            raise rule("Bundles are created after the paper is conducted", "PAPER_NOT_CONDUCTED")
        size = body.size or int(await self.setting("exams", "bundle_size") or 30)
        scripted = select(AnswerScript.exam_registration_item_id)
        q = (
            select(ExamRegistrationItem.id, ExamSeatingPlan.room_id)
            .join(ExamAttendance, ExamAttendance.exam_registration_item_id == ExamRegistrationItem.id)
            .outerjoin(ExamSeatAllocation, ExamSeatAllocation.exam_registration_item_id == ExamRegistrationItem.id)
            .outerjoin(ExamSeatingPlan, ExamSeatingPlan.id == ExamSeatAllocation.seating_plan_id)
            .where(
                ExamRegistrationItem.exam_paper_id == p.id,
                ExamAttendance.status.in_(("present", "malpractice")),
                ExamRegistrationItem.id.notin_(scripted),
            )
            .order_by(ExamSeatingPlan.room_id, ExamSeatAllocation.seat_number, ExamRegistrationItem.id)
        )
        if body.room_id:
            q = q.where(ExamSeatingPlan.room_id == body.room_id)
        groups: dict[uuid.UUID | None, list[uuid.UUID]] = defaultdict(list)
        for item_id, room_id in (await self.db.execute(q)).all():
            groups[room_id].append(item_id)
        if not groups:
            raise rule("No present candidates without a script for this paper", "NOTHING_TO_BUNDLE", 422)
        existing = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(AnswerScriptBundle).where(AnswerScriptBundle.exam_paper_id == p.id)
                )
            ).scalar_one()
        )
        prefix = (p.paper_code or "P")[:12]
        created: list[AnswerScriptBundle] = []
        holder = await self._staff_id()
        for room_id, items in groups.items():
            for i in range(0, len(items), size):
                existing += 1
                chunk = items[i : i + size]
                b = AnswerScriptBundle(
                    institution_id=self.inst,
                    exam_paper_id=p.id,
                    room_id=room_id,
                    exam_centre_id=body.centre_id,
                    bundle_number=f"{prefix}-B{existing:03d}",
                    script_count=len(chunk),
                    status="created",
                    custody_holder_staff_id=holder,
                )
                self.db.add(b)
                await self.db.flush()
                for n, item_id in enumerate(chunk, start=1):
                    # provisional number until coded (seat order — never shown to evaluators before coding)
                    self.db.add(
                        AnswerScript(
                            institution_id=self.inst,
                            exam_registration_item_id=item_id,
                            bundle_id=b.id,
                            dummy_number=f"T{n:04d}",
                            status="received",
                        )
                    )
                self.db.add(
                    ScriptCustodyLog(
                        institution_id=self.inst, bundle_id=b.id, action="created", to_staff_id=holder, location=None
                    )
                )
                created.append(b)
        await self.db.flush()
        await self._audit("bundles_create", "exam_paper", p.id, None, {"bundles": len(created), "size": size})
        await self._emit("custody.logged", {"paper_id": str(p.id), "bundles": len(created)}, "exam_paper", p.id)
        return await self._out(created)

    async def code(self, bid: uuid.UUID) -> CodeBundleResponse:
        b = await self.bundle(bid, for_update=True)
        if b.status != "created":
            raise rule("Only a freshly created bundle can be coded", "BUNDLE_ALREADY_CODED")
        p, _ = await self.paper(b.exam_paper_id)
        prefix = "".join(c for c in (p.paper_code or "") if c.isalnum())[:4].upper() or "D"
        used = set(
            (
                await self.db.execute(
                    select(AnswerScript.dummy_number)
                    .join(AnswerScriptBundle, AnswerScriptBundle.id == AnswerScript.bundle_id)
                    .where(AnswerScriptBundle.exam_paper_id == p.id)
                )
            ).scalars()
        )
        scripts = list(
            (
                await self.db.execute(select(AnswerScript).where(AnswerScript.bundle_id == b.id).with_for_update())
            ).scalars()
        )
        # random order so the dummy sequence leaks nothing about the seat order
        secrets.SystemRandom().shuffle(scripts)
        for sc in scripts:
            while True:
                num = f"{prefix}{secrets.randbelow(900000) + 100000}"
                if num not in used:
                    used.add(num)
                    break
            sc.dummy_number = num
            sc.status = "coded"
        b.status, b.coded_by, b.coded_at = "coded", self.actor_id, now_utc()
        await self.db.flush()
        await self._audit("code", "answer_script_bundle", b.id, None, {"scripts": len(scripts)})
        await self._emit("scripts.coded", {"bundle_id": str(b.id), "paper_id": str(p.id)}, "answer_script_bundle", b.id)
        return CodeBundleResponse(
            bundle=(await self._out([b]))[0],
            scripts=[
                DummyScript(id=sc.id, dummy_number=sc.dummy_number, status=sc.status)
                for sc in sorted(scripts, key=lambda x: x.dummy_number)
            ],
        )

    async def custody(self, bid: uuid.UUID, body: CustodyLogCreate) -> CustodyLogResponse:
        b = await self.bundle(bid, for_update=True)
        if b.status in ("archived",):
            raise APIError(409, ErrorCode.RECORD_LOCKED, "The bundle is archived")
        if b.status == "created" and body.action == "dispatched":
            raise rule("Code the bundle before it leaves the exam cell", "BUNDLE_NOT_CODED")
        row = ScriptCustodyLog(
            institution_id=self.inst,
            bundle_id=b.id,
            action=body.action,
            from_staff_id=b.custody_holder_staff_id,
            to_staff_id=body.to_staff_id,
            location=body.location,
            remarks=body.remarks,
        )
        self.db.add(row)
        if body.action in CUSTODY_STATUS and b.status in ("coded", "dispatched", "received"):
            b.status = CUSTODY_STATUS[body.action]
        if body.to_staff_id:
            b.custody_holder_staff_id = body.to_staff_id
        if body.location:
            b.custody_location = body.location
        await self.db.flush()
        await self._emit(
            "custody.logged", {"bundle_id": str(b.id), "action": body.action}, "answer_script_bundle", b.id
        )
        return CustodyLogResponse.model_validate(row, from_attributes=True)

    async def custody_log(self, bid: uuid.UUID) -> list[CustodyLogResponse]:
        b = await self.bundle(bid)
        rows = (
            await self.db.execute(
                select(ScriptCustodyLog).where(ScriptCustodyLog.bundle_id == b.id).order_by(ScriptCustodyLog.at)
            )
        ).scalars()
        return [CustodyLogResponse.model_validate(r, from_attributes=True) for r in rows]

    # ---- retention ---------------------------------------------------------------------------------------------------
    async def _session_bundles(self, s: ExamSession, ids: list[uuid.UUID] | None) -> list[AnswerScriptBundle]:
        q = (
            select(AnswerScriptBundle)
            .join(ExamPaper, ExamPaper.id == AnswerScriptBundle.exam_paper_id)
            .where(ExamPaper.exam_session_id == s.id)
            .with_for_update(of=AnswerScriptBundle)
        )
        if ids:
            q = q.where(AnswerScriptBundle.id.in_(ids))
        return list((await self.db.execute(q)).scalars())

    async def retention(self, sid: uuid.UUID, body: ScriptRetentionRequest) -> dict[str, Any]:
        s = await self.session(sid)
        if body.action == "destroy":
            if not self.can("exams", "manage"):
                raise APIError(
                    403,
                    ErrorCode.PERMISSION_DENIED,
                    "Destroying scripts needs the controller of examinations' approval (exams:manage)",
                )
            bundles = [b for b in await self._session_bundles(s, body.bundle_ids) if b.status == "archived"]
            new_status, action = "destroyed", "destroyed"
        else:
            if s.status not in ("results_published", "closed"):
                raise rule("Scripts are archived after the results are published", "RESULTS_NOT_PUBLISHED")
            bundles = [b for b in await self._session_bundles(s, body.bundle_ids) if b.status not in ("archived",)]
            new_status, action = "archived", "archived"
        n = 0
        for b in bundles:
            n += 1
            if action == "archived":
                b.status = "archived"
            self.db.add(
                ScriptCustodyLog(
                    institution_id=self.inst,
                    bundle_id=b.id,
                    action=action,
                    from_staff_id=b.custody_holder_staff_id,
                    remarks=body.approval_note,
                )
            )
            for sc in (await self.db.execute(select(AnswerScript).where(AnswerScript.bundle_id == b.id))).scalars():
                sc.status = new_status
        await self.db.flush()
        await self._audit(f"scripts_{body.action}", "exam_session", s.id, None, {"bundles": n})
        await self._emit(f"scripts.{action}", {"session_id": str(s.id), "bundles": n}, "exam_session", s.id)
        return {"action": body.action, "bundles": n}

    async def register(self, sid: uuid.UUID) -> list[ScriptRegisterRow]:
        s = await self.session(sid)
        rows = (
            await self.db.execute(
                select(AnswerScriptBundle, ExamPaper.paper_code)
                .join(ExamPaper, ExamPaper.id == AnswerScriptBundle.exam_paper_id)
                .where(ExamPaper.exam_session_id == s.id)
                .order_by(ExamPaper.paper_code, AnswerScriptBundle.bundle_number)
            )
        ).all()
        last: dict[uuid.UUID, ScriptCustodyLog] = {}
        if rows:
            for log in (
                await self.db.execute(
                    select(ScriptCustodyLog)
                    .where(ScriptCustodyLog.bundle_id.in_([b.id for b, _ in rows]))
                    .order_by(ScriptCustodyLog.at)
                )
            ).scalars():
                last[log.bundle_id] = log
        return [
            ScriptRegisterRow(
                bundle_id=b.id,
                bundle_number=b.bundle_number,
                paper_code=code,
                status=b.status,
                script_count=b.script_count,
                last_action=last[b.id].action if b.id in last else None,
                last_action_at=last[b.id].at if b.id in last else None,
            )
            for b, code in rows
        ]

    async def retention_check(self) -> int:
        """Beat (weekly): archive bundles of sessions published longer than the retention window ago."""
        months = int(await self.setting("exams", "script_retention_months") or 6)
        cutoff = now_utc() - timedelta(days=30 * months)
        sessions = (
            await self.db.execute(
                select(ResultPublication.exam_session_id)
                .where(
                    ResultPublication.institution_id == self.inst,
                    ResultPublication.exam_session_id.is_not(None),
                )
                .group_by(ResultPublication.exam_session_id)
                .having(func.max(ResultPublication.published_at) < cutoff)
            )
        ).scalars()
        n = 0
        for sid in sessions:
            if sid is None:
                continue
            s = (await self.db.execute(select(ExamSession).where(ExamSession.id == sid))).scalar_one()
            if s.status in ("results_published", "closed"):
                n += int((await self.retention(sid, ScriptRetentionRequest(action="archive")))["bundles"])
        return n
