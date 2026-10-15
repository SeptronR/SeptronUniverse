"""Counselling rounds, seat allotment, decisions, offers and admission — Prompts/08 §08.6 ``counselling_service.py``.

Rules
1. Rounds per cycle (``round_number`` unique — 409) with a choice-filling window; ``choice_filling`` replaces the
   applicant's preferences only while a round of the cycle is ``choice_filling`` and inside its window (else 409
   ``RECORD_LOCKED``). ``is_final`` is kept in ``admission_cycles.de_reservation_policy.final_round_number`` (the DDL
   has no round column).
2. ``run_allotment(round, dry_run)`` — the dry run answers inline; the real run is the job ``admissions.allotment_run``
   (202). The round row and the cycle's seat rows are locked ``FOR UPDATE`` (a concurrent run waits, then skips the
   applicants already allotted in the round → total filled ≤ seats). Applicants are taken by overall merit rank (the
   cycle's newest cycle-wide merit list; merit score otherwise); for each, preferences in priority order; a PwD
   applicant first tries the ``PWD`` (horizontal / earmarked) rows; then for each vertical quota the **GEN** seat first
   and, for a reserved-category applicant, the own-category seat; lateral applicants only ``LATERAL`` rows. A
   ``float`` applicant keeps the earlier seat unless a higher preference frees up (old allotment → ``upgraded``, seat
   released); ``freeze`` / ``accepted`` / undecided ``allotted`` holders are skipped. In the final round vacant
   reserved seats convert per ``de_reservation_policy.convert`` ({"SC": "GEN"}) after a first pass and a second pass
   fills them; the summary lists the conversions.
3. Decisions (applicant): ``accept`` → admission-fee payment (mock; Phase 12 invoice) → on payment ``accepted``;
   ``float`` / ``freeze``; ``decline`` releases the seat. Beat ``admissions.lapse_allotments`` (hourly) lapses
   undecided allotments past the round's ``reporting_deadline`` and releases their seats.
4. ``admit`` (admissions office / registrar): ``accepted`` (fee paid) + required documents verified; calls Phase 07
   ``StudentService.create_record(source="admission")`` (seat limit, batch auto-created, least-filled section,
   ``regno:{year}:{programme}`` number, student + guardian users); lateral admits pass ``entry_type`` /
   ``entry_term_number``. Links ``admitted_student_id``, allotment → ``admitted``, applicant → ``admitted``.
   ``seat_matrix.filled`` counts held seats from the allotment on (an offer-only admit increments it here).
5. Open enrolment (``programs.is_open_enrolment`` + ``admissions.open_enrolment``): ``verified`` → admitted directly
   once the application fee is paid.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.core import jobs
from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.enums.admissions import GEN, MERIT_ELIGIBLE, ROUND_TRANSITIONS
from app.models.academic import AcademicYear
from app.models.admissions import (
    AdmissionCycle,
    AdmissionOffer,
    Applicant,
    ApplicantPreference,
    CounsellingRound,
    SeatAllotment,
    SeatMatrix,
)
from app.models.platform import AuditLog
from app.schemas.admissions import (
    AdmitRequest,
    AdmitResult,
    AllotmentDecision,
    AllotmentPreviewRow,
    AllotmentResponse,
    AllotmentSummary,
    Conversion,
    OfferCreate,
    OfferResponse,
    PreferencesReplace,
    RoundCreate,
    RoundResponse,
    RoundStatusChange,
    RoundUpdate,
    SummaryRow,
)
from app.services.admissions.common import AdmissionsBase, utcnow

HORIZONTAL = {"PWD", "SPORTS", "WOMEN", "DEFENCE", "EWS_SUPER"}
VERTICAL_ORDER = ["STATE", "ALL_INDIA", "MANAGEMENT", "NRI"]


@dataclass
class _Seat:
    row: SeatMatrix
    avail: int
    allotted_now: int = 0
    delta: int = 0  # seats moved in / out by de-reservation (dry run shows them without writing)


@dataclass
class _Plan:
    allotments: list[tuple[Applicant, _Seat, int, SeatAllotment | None]] = field(default_factory=list)
    conversions: list[Conversion] = field(default_factory=list)
    considered: int = 0
    retained: int = 0


class CounsellingService(AdmissionsBase):
    # ---- rule 1: rounds -------------------------------------------------------------------------------------------
    def _final(self, cycle: AdmissionCycle) -> int | None:
        value = (cycle.de_reservation_policy or {}).get("final_round_number")
        return int(value) if value is not None else None

    async def _round_out(self, rows: list[CounsellingRound]) -> list[RoundResponse]:
        counts = await self.counselling.allotment_counts([r.id for r in rows])
        out = []
        for r in rows:
            cycle = await self.cycles.cycle(r.cycle_id)
            item = RoundResponse.model_validate(r)
            item.is_final = self._final(cycle) == r.round_number
            item.allotments_count = counts.get(r.id, 0)
            out.append(item)
        return out

    async def rounds(self, cycle_id: uuid.UUID) -> list[RoundResponse]:
        return await self._round_out(list(await self.counselling.rounds(cycle_id)))

    async def _set_final(self, cycle: AdmissionCycle, number: int, is_final: bool | None) -> None:
        if is_final is None:
            return
        policy = dict(cycle.de_reservation_policy or {})
        if is_final:
            policy["final_round_number"] = number
        elif policy.get("final_round_number") == number:
            policy.pop("final_round_number")
        cycle.de_reservation_policy = policy

    async def create_round(self, cycle_id: uuid.UUID, body: RoundCreate) -> RoundResponse:
        cycle = await self.cycles.cycle(cycle_id, for_update=True)
        if any(r.round_number == body.round_number for r in await self.counselling.rounds(cycle.id)):
            raise APIError(
                409, ErrorCode.CONFLICT, f"Round {body.round_number} already exists", {"field": "round_number"}
            )
        self._check_window(body.choice_filling_start, body.choice_filling_end)
        rnd = CounsellingRound(
            institution_id=self.inst,
            cycle_id=cycle.id,
            round_number=body.round_number,
            name=body.name or f"Round {body.round_number}",
            choice_filling_start=body.choice_filling_start,
            choice_filling_end=body.choice_filling_end,
            allotment_at=body.allotment_at,
            reporting_deadline=body.reporting_deadline,
            status="planned",
        )
        self.db.add(rnd)
        await self._set_final(cycle, body.round_number, body.is_final)
        await self.db.flush()
        await self._audit(
            "create", "counselling_round", rnd.id, None, {"round_number": rnd.round_number, "is_final": body.is_final}
        )
        return (await self._round_out([rnd]))[0]

    @staticmethod
    def _check_window(start: Any, end: Any) -> None:
        if start and end and end <= start:
            raise APIError(
                422, ErrorCode.VALIDATION, "Choice filling must end after it starts", {"field": "choice_filling_end"}
            )

    async def update_round(self, round_id: uuid.UUID, body: RoundUpdate) -> RoundResponse:
        rnd = await self.counselling.round(round_id, for_update=True)
        if rnd.status == "closed":
            raise APIError(409, ErrorCode.RECORD_LOCKED, "A closed round is read-only")
        data = body.model_dump(exclude_unset=True, exclude={"is_final"})
        for k, v in data.items():
            setattr(rnd, k, v)
        self._check_window(rnd.choice_filling_start, rnd.choice_filling_end)
        await self._set_final(await self.cycles.cycle(rnd.cycle_id, for_update=True), rnd.round_number, body.is_final)
        await self.db.flush()
        await self._audit(
            "update",
            "counselling_round",
            rnd.id,
            None,
            {**{k: str(v) for k, v in data.items()}, "is_final": body.is_final},
        )
        return (await self._round_out([rnd]))[0]

    async def round_status(self, round_id: uuid.UUID, body: RoundStatusChange) -> RoundResponse:
        rnd = await self.counselling.round(round_id, for_update=True)
        to = body.status.value
        if to not in ROUND_TRANSITIONS.get(rnd.status, set()):
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                f"A {rnd.status} round cannot move to {to}",
                {"allowed": sorted(ROUND_TRANSITIONS.get(rnd.status, set()))},
            )
        old, rnd.status = rnd.status, to
        cycle = await self.cycles.cycle(rnd.cycle_id, for_update=True)
        if to == "choice_filling" and cycle.status in ("closed", "merit_processing"):
            cycle.status = "counselling"
        await self.db.flush()
        await self._audit("status", "counselling_round", rnd.id, {"status": old}, {"status": to})
        return (await self._round_out([rnd]))[0]

    async def choice_filling(self, a: Applicant, body: PreferencesReplace) -> None:
        from app.services.admissions.application_service import ApplicationService

        now = utcnow()
        open_round = next(
            (
                r
                for r in await self.counselling.rounds(a.cycle_id)
                if r.status == "choice_filling"
                and (r.choice_filling_start is None or r.choice_filling_start <= now)
                and (r.choice_filling_end is None or r.choice_filling_end >= now)
            ),
            None,
        )
        if open_round is None:
            raise APIError(409, ErrorCode.RECORD_LOCKED, "Choice filling is closed", {"reason": "outside_window"})
        if a.status not in MERIT_ELIGIBLE | {"allotted"}:
            raise APIError(409, ErrorCode.CONFLICT, f"A {a.status} application cannot fill choices")
        await ApplicationService(self.db, self.principal, self.request, self.inst).set_preferences(
            a, body, choice_filling=True
        )

    # ---- rule 2: allotment -----------------------------------------------------------------------------------------
    async def run_allotment(self, round_id: uuid.UUID, dry_run: bool) -> AllotmentSummary:
        rnd = await self.counselling.round(round_id)
        if rnd.status == "closed":
            raise APIError(409, ErrorCode.RECORD_LOCKED, "The round is closed")
        if dry_run:
            return await self.allot(rnd.id, persist=False)
        job = await jobs.enqueue(
            self.db, self.principal, "admissions.allotment_run", {"round_id": str(rnd.id)}, queue="reports"
        )
        await self._audit("allotment_enqueued", "counselling_round", rnd.id, None, {"job_id": str(job.id)})
        cycle = await self.cycles.cycle(rnd.cycle_id)
        return AllotmentSummary(
            round_id=rnd.id,
            round_number=rnd.round_number,
            dry_run=False,
            is_final=self._final(cycle) == rnd.round_number,
            job_id=job.id,
        )

    def _quotas(self, a: Applicant, seats: list[_Seat]) -> list[str]:
        present = {s.row.quota for s in seats}
        if a.quota_claimed and a.quota_claimed not in HORIZONTAL | {"LATERAL"} and a.quota_claimed in present:
            return [a.quota_claimed]
        vertical = [q for q in VERTICAL_ORDER if q in present]
        vertical += sorted(q for q in present if q not in VERTICAL_ORDER and q not in HORIZONTAL and q != "LATERAL")
        return vertical

    def _attempts(self, a: Applicant, seats: list[_Seat]) -> list[tuple[str, str]]:
        own = a.category or GEN
        cats = [GEN] if own == GEN else [GEN, own]
        if a.entry_type == "lateral":
            return [("LATERAL", c) for c in cats]
        out: list[tuple[str, str]] = []
        if a.is_pwd:
            out += [("PWD", c) for c in cats]
        for q in self._quotas(a, seats):
            out += [(q, c) for c in cats]
        return out

    def _place(
        self,
        a: Applicant,
        prefs: list[ApplicantPreference],
        by_prog: dict[tuple[uuid.UUID, uuid.UUID], list[_Seat]],
        below: int | None,
    ) -> tuple[_Seat, int] | None:
        for p in prefs:
            if below is not None and p.priority >= below:
                break
            seats = by_prog.get((p.program_id, p.college_id), [])
            index = {(s.row.quota, s.row.category): s for s in seats}
            for key in self._attempts(a, seats):
                s = index.get(key)
                if s is not None and s.avail > 0:
                    return s, p.priority
        return None

    async def allot(
        self, round_id: uuid.UUID, *, persist: bool, progress: Callable[[int, str], Awaitable[None]] | None = None
    ) -> AllotmentSummary:
        rnd = await self.counselling.round(round_id, for_update=persist)
        cycle = await self.cycles.cycle(rnd.cycle_id, for_update=persist)
        is_final = self._final(cycle) == rnd.round_number
        rows = list(await self.cycles.seat_rows(cycle.id, for_update=persist))
        state = {r.id: _Seat(r, max(r.seats - r.filled, 0)) for r in rows}
        by_prog: dict[tuple[uuid.UUID, uuid.UUID], list[_Seat]] = {}
        for s in state.values():
            by_prog.setdefault((s.row.program_id, s.row.college_id), []).append(s)
        round_ids = select(CounsellingRound.id).where(CounsellingRound.cycle_id == cycle.id)
        holding = await self.counselling.holding(None, round_ids)
        candidates = list(
            (
                await self.db.execute(
                    select(Applicant).where(
                        Applicant.cycle_id == cycle.id,
                        Applicant.deleted_at.is_(None),
                        Applicant.status.in_(sorted(MERIT_ELIGIBLE | {"allotted"})),
                    )
                )
            )
            .scalars()
            .all()
        )
        ranks = await self.merit.ranks_for_cycle(cycle.id)
        candidates.sort(
            key=lambda a: (
                ranks.get(a.id, 10**9),
                -(float(a.merit_score) if a.merit_score is not None else -1),
                a.application_number,
            )
        )
        prefs = await self.applicants.preferences([a.id for a in candidates])
        plan = _Plan()
        pending: list[tuple[Applicant, SeatAllotment | None, int | None]] = []
        for a in candidates:
            held = holding.get(a.id)
            if held is not None:
                if held.round_id == rnd.id or held.status != "float":
                    plan.retained += 1
                    continue
                cur = next(
                    (
                        p.priority
                        for p in prefs[a.id]
                        if p.program_id == held.program_id and p.college_id == held.college_id
                    ),
                    None,
                )
                pending.append((a, held, cur))
            elif a.status in MERIT_ELIGIBLE:
                pending.append((a, None, None))
        plan.considered = len(pending)

        def run_pass(
            queue: list[tuple[Applicant, SeatAllotment | None, int | None]],
        ) -> list[tuple[Applicant, SeatAllotment | None, int | None]]:
            left = []
            for a, held, cur in queue:
                hit = self._place(a, prefs[a.id], by_prog, cur if held is not None else None)
                if hit is None:
                    left.append((a, held, cur))
                    if held is not None:
                        plan.retained += 1
                    continue
                seat, priority = hit
                seat.avail -= 1
                seat.allotted_now += 1
                if held is not None and held.seat_matrix_id in state:
                    state[held.seat_matrix_id].avail += 1
                plan.allotments.append((a, seat, priority, held))
            return left

        remaining = run_pass(pending)
        if is_final:
            convert = {
                str(k).upper().replace("_", "-"): str(v).upper().replace("_", "-")
                for k, v in ((cycle.de_reservation_policy or {}).get("convert") or {}).items()
            }
            programs = await self.cycles.program_rows([r.program_id for r in rows])
            for s in list(state.values()):
                target = convert.get(s.row.category)
                if not target or s.avail <= 0 or target == s.row.category:
                    continue
                key = (s.row.program_id, s.row.college_id)
                dest = next((t for t in by_prog[key] if t.row.quota == s.row.quota and t.row.category == target), None)
                if dest is None:
                    new_row = SeatMatrix(
                        id=uuid.uuid4(),
                        institution_id=self.inst,
                        cycle_id=cycle.id,
                        program_id=s.row.program_id,
                        college_id=s.row.college_id,
                        quota=s.row.quota,
                        category=target,
                        seats=0,
                        filled=0,
                    )
                    if persist:
                        self.db.add(new_row)
                    dest = _Seat(new_row, 0)
                    state[new_row.id] = dest
                    by_prog[key].append(dest)
                moved = s.avail
                s.avail -= moved
                dest.avail += moved
                s.delta -= moved
                dest.delta += moved
                if persist:
                    s.row.seats -= moved
                    dest.row.seats += moved
                plan.conversions.append(
                    Conversion(
                        program_id=s.row.program_id,
                        program_code=programs[s.row.program_id].code if s.row.program_id in programs else None,
                        quota=s.row.quota,
                        from_category=s.row.category,
                        to_category=target,
                        seats=moved,
                    )
                )
            if plan.conversions:
                plan.retained -= sum(1 for _, held, _ in remaining if held is not None)
                remaining = run_pass(remaining)
        programs = await self.cycles.program_rows([s.row.program_id for s in state.values()])
        if persist:
            await self._persist(rnd, plan, progress)
        summary = AllotmentSummary(
            round_id=rnd.id,
            round_number=rnd.round_number,
            dry_run=not persist,
            is_final=is_final,
            considered=plan.considered,
            allotted=sum(1 for _, _, _, held in plan.allotments if held is None),
            upgraded=sum(1 for _, _, _, held in plan.allotments if held is not None),
            retained=plan.retained,
            unallotted=sum(1 for _, held, _ in remaining if held is None),
            rows=[
                SummaryRow(
                    program_id=s.row.program_id,
                    program_code=programs[s.row.program_id].code if s.row.program_id in programs else None,
                    college_id=s.row.college_id,
                    quota=s.row.quota,
                    category=s.row.category,
                    seats=s.row.seats if persist else s.row.seats + s.delta,
                    filled=(s.row.filled if persist else s.row.filled + s.allotted_now),
                    allotted_now=s.allotted_now,
                )
                for s in sorted(state.values(), key=lambda x: (str(x.row.program_id), x.row.quota, x.row.category))
            ],
            conversions=plan.conversions,
            allotments=[
                AllotmentPreviewRow(
                    application_number=a.application_number,
                    applicant_id=a.id,
                    program_id=s.row.program_id,
                    program_code=programs[s.row.program_id].code if s.row.program_id in programs else None,
                    quota=s.row.quota,
                    category=s.row.category,
                    priority=priority,
                    kind="upgrade" if held is not None else "new",
                )
                for a, s, priority, held in plan.allotments
            ],
        )
        return summary

    async def _persist(
        self, rnd: CounsellingRound, plan: _Plan, progress: Callable[[int, str], Awaitable[None]] | None
    ) -> None:
        cycle = await self.cycles.cycle(rnd.cycle_id)
        fee = int(self.form_value(cycle, "admission_fee_paise") or await self.adm_setting("admission_fee_paise", 0))
        for n, (a, seat, priority, held) in enumerate(plan.allotments, start=1):
            if held is not None:
                held.status = "upgraded"
                old_seat = await self.cycles.seat_row(held.seat_matrix_id, for_update=True)
                if old_seat is not None and old_seat.filled > 0:
                    old_seat.filled -= 1
            seat.row.filled += 1
            row = SeatAllotment(
                institution_id=self.inst,
                round_id=rnd.id,
                applicant_id=a.id,
                program_id=seat.row.program_id,
                college_id=seat.row.college_id,
                seat_matrix_id=seat.row.id,
                quota=seat.row.quota,
                category=seat.row.category,
                status="allotted",
                admission_fee_paise=fee,
            )
            self.db.add(row)
            await self.db.flush()
            extra = {
                "round": rnd.round_number,
                "quota": seat.row.quota,
                "category": seat.row.category,
                "priority": priority,
            }
            if held is not None:
                await self._audit(
                    "upgrade", "applicant", a.id, {"allotment_id": str(held.id)}, {**extra, "allotment_id": str(row.id)}
                )
                if a.user_id:
                    await self._notify(
                        "admissions.status_changed",
                        [a.user_id],
                        {"application_no": a.application_number, "status": f"upgraded to preference {priority}"},
                    )
            else:
                await self.transition(a, "allotted", extra=extra, force=a.status == "verified")
            if progress and n % 25 == 0:
                await progress(
                    min(95, int(n * 100 / max(len(plan.allotments), 1))), f"{n}/{len(plan.allotments)} allotted"
                )
        if rnd.status in ("planned", "choice_filling"):
            rnd.status = "allotted"
        rnd.allotment_at = utcnow()
        if cycle.status in ("closed", "merit_processing"):
            cycle.status = "counselling"
        await self.db.flush()
        await self._audit(
            "allotment_run",
            "counselling_round",
            rnd.id,
            None,
            {"allotted": len(plan.allotments), "conversions": [c.model_dump(mode="json") for c in plan.conversions]},
        )

    async def allotments(self, round_id: uuid.UUID, status: str | None = None) -> list[AllotmentResponse]:
        rows = await self.counselling.allotments(round_id, status)
        return [await self.allotment_out(r) for r in rows]

    async def summary(self, round_id: uuid.UUID) -> AllotmentSummary:
        rnd = await self.counselling.round(round_id)
        cycle = await self.cycles.cycle(rnd.cycle_id)
        rows = await self.cycles.seat_rows(cycle.id)
        now_counts: dict[uuid.UUID, int] = {}
        allots = await self.counselling.allotments(rnd.id)
        for r in allots:
            now_counts[r.seat_matrix_id] = now_counts.get(r.seat_matrix_id, 0) + 1
        programs = await self.cycles.program_rows([r.program_id for r in rows])
        conversions = []
        last = (
            (
                await self.db.execute(
                    select(AuditLog.new_values)
                    .where(AuditLog.record_id == rnd.id, AuditLog.action == "allotment_run")
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
        for values in last:
            conversions += [Conversion(**c) for c in (values or {}).get("conversions") or []]
        return AllotmentSummary(
            round_id=rnd.id,
            round_number=rnd.round_number,
            dry_run=False,
            is_final=self._final(cycle) == rnd.round_number,
            allotted=sum(1 for r in allots if r.status != "upgraded"),
            upgraded=sum(1 for r in allots if r.status == "upgraded"),
            rows=[
                SummaryRow(
                    program_id=r.program_id,
                    program_code=programs[r.program_id].code if r.program_id in programs else None,
                    college_id=r.college_id,
                    quota=r.quota,
                    category=r.category,
                    seats=r.seats,
                    filled=r.filled,
                    allotted_now=now_counts.get(r.id, 0),
                )
                for r in sorted(rows, key=lambda x: (str(x.program_id), x.quota, x.category))
            ],
            conversions=conversions,
        )

    # ---- rule 3: decisions -------------------------------------------------------------------------------------------
    async def release(self, allotment: SeatAllotment, status: str) -> None:
        seat = await self.cycles.seat_row(allotment.seat_matrix_id, for_update=True)
        if seat is not None and seat.filled > 0 and allotment.status in ("allotted", "accepted", "float", "freeze"):
            seat.filled -= 1
        allotment.status = status
        await self.db.flush()

    async def my_allotment(self, a: Applicant) -> AllotmentResponse | None:
        row = (await self.counselling.holding([a.id])).get(a.id) or await self.counselling.latest_for(a.id)
        return await self.allotment_out(row, a) if row else None

    async def decide(self, a: Applicant, allotment_id: uuid.UUID, body: AllotmentDecision) -> AllotmentResponse:
        row = await self.counselling.allotment(allotment_id, for_update=True)
        if row.applicant_id != a.id:
            raise APIError(404, ErrorCode.NOT_FOUND, "Allotment not found")
        rnd = await self.counselling.round(row.round_id)
        if rnd.reporting_deadline and rnd.reporting_deadline < utcnow():
            raise APIError(409, ErrorCode.RULE_VIOLATION, "The reporting deadline has passed", {"reason": "deadline"})
        action = body.action.value
        allowed = {
            "accept": {"allotted", "float", "freeze"},
            "float": {"allotted"},
            "freeze": {"allotted", "float"},
            "decline": {"allotted", "float", "freeze"},
        }
        if row.status not in allowed[action]:
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                f"An allotment in status {row.status} cannot be {action}ed",
                {"status": row.status},
            )
        await self._audit(
            "allotment_" + action, "applicant", a.id, {"allotment_status": row.status}, {"allotment_id": str(row.id)}
        )
        if action == "decline":
            await self.release(row, "declined")
            await self.transition(a, "declined", reason="seat declined")
        elif action in ("float", "freeze"):
            row.status = action
            await self.db.flush()
            await self._emit(
                f"applicant.{action}", {"applicant_id": str(a.id), "allotment_id": str(row.id)}, "applicant", a.id
            )
        else:
            from app.services.admissions.application_service import ApplicationService

            pay = await self.create_payment(a, "admission", int(row.admission_fee_paise or 0))
            if pay["status"] == "paid":
                await ApplicationService(self.db, self.principal, self.request, self.inst).mark_paid(a, "admission")
        return await self.allotment_out(row, a)

    async def on_admission_fee_paid(self, a: Applicant) -> None:
        row = (await self.counselling.holding([a.id])).get(a.id)
        if row is None or row.status == "accepted":
            return
        row.status, row.accepted_at = "accepted", utcnow()
        await self.db.flush()
        await self.transition(a, "accepted", extra={"allotment_id": str(row.id)})

    async def lapse_due(self) -> int:
        n = 0
        for row, _ in await self.counselling.lapsable(utcnow()):
            await self.release(row, "lapsed")
            a = await self.applicants.get_any(row.applicant_id, for_update=True)
            if a is not None and a.status == "allotted":
                await self.transition(a, "lapsed", reason="reporting deadline passed")
            n += 1
        return n

    # ---- offers ------------------------------------------------------------------------------------------------------
    async def _offer_out(self, rows: list[AdmissionOffer]) -> list[OfferResponse]:
        programs = await self.cycles.program_rows([r.program_id for r in rows])
        out = []
        for r in rows:
            a = await self.applicants.get_any(r.applicant_id)
            item = OfferResponse.model_validate(r)
            p = programs.get(r.program_id)
            item.program_code = p.code if p else None
            item.application_number = a.application_number if a else None
            item.applicant_name = a.full_name if a else None
            item.letter_html = (
                f"<h2>{'Provisional' if r.offer_type == 'provisional' else 'Confirmed'} offer of admission</h2>"
                f"<p>Dear {item.applicant_name}, you are offered admission to {p.name if p else ''} ({item.program_code}) "
                f"under application {item.application_number}. Valid until {r.valid_until}.</p>"
            )
            out.append(item)
        return out

    async def offer(self, applicant_id: uuid.UUID, body: OfferCreate) -> OfferResponse:
        a = await self.applicants.get_visible(applicant_id, for_update=True)
        if a.status not in ("allotted", "accepted", "verified", "merit_listed", "provisionally_admitted"):
            raise APIError(409, ErrorCode.CONFLICT, f"An offer cannot be issued to a {a.status} application")
        held = (await self.counselling.holding([a.id])).get(a.id)
        program_id = body.program_id or (held.program_id if held else None)
        if program_id is None:
            prefs = (await self.applicants.preferences([a.id]))[a.id]
            program_id = prefs[0].program_id if prefs else None
        if program_id is None:
            raise APIError(422, ErrorCode.VALIDATION, "Programme required", {"field": "program_id"})
        cp = next((p for p in await self.cycles.programs(a.cycle_id) if p.program_id == program_id), None)
        if cp is None:
            raise APIError(422, ErrorCode.VALIDATION, "Programme is not in the cycle", {"field": "program_id"})
        for old in await self.counselling.offers([a.id]):
            if old.status == "issued":
                old.status = "withdrawn"
        row = AdmissionOffer(
            institution_id=self.inst,
            applicant_id=a.id,
            program_id=program_id,
            college_id=cp.college_id,
            offer_type=body.offer_type.value,
            valid_until=body.valid_until or (await self.today()) + timedelta(days=14),
            conditions=body.conditions,
            status="issued",
        )
        self.db.add(row)
        await self.db.flush()
        await self._audit("offer", "applicant", a.id, None, {"offer_id": str(row.id), "offer_type": row.offer_type})
        if a.user_id:
            await self._notify(
                "admissions.status_changed",
                [a.user_id],
                {"application_no": a.application_number, "status": f"{row.offer_type} offer issued"},
            )
        return (await self._offer_out([row]))[0]

    async def offers(self, cycle_id: uuid.UUID | None) -> list[OfferResponse]:
        ids = select(Applicant.id).where(Applicant.institution_id == self.inst)
        if cycle_id is not None:
            ids = ids.where(Applicant.cycle_id == cycle_id)
        return await self._offer_out(list(await self.counselling.offers(ids)))

    async def _retire_applicant_account(self, a: Applicant) -> None:
        """Users carry a unique phone / e-mail per institution: the applicant account hands both over to the new
        student account and expires (``admitted`` is terminal for the applicant)."""
        from app.models.platform import User

        if a.user_id is None:
            return
        user = (await self.db.execute(select(User).where(User.id == a.user_id))).scalar_one_or_none()
        if user is not None and user.user_type == "applicant":
            user.phone, user.email, user.valid_to = None, None, utcnow()
            await self.db.flush()

    # ---- rule 4 / 5: admit -------------------------------------------------------------------------------------------
    async def admit(self, applicant_id: uuid.UUID, body: AdmitRequest) -> AdmitResult:
        from app.enums.students import EntryType, Gender
        from app.schemas.students import GuardianIn, StudentCreate
        from app.services.student_service import StudentService

        a = await self.applicants.get_visible(applicant_id, for_update=True)
        if a.admitted_student_id is not None or a.status == "admitted":
            raise APIError(
                409, ErrorCode.CONFLICT, "The applicant is already admitted", {"student_id": str(a.admitted_student_id)}
            )
        cycle = await self.cycles.cycle(a.cycle_id)
        held = (await self.counselling.holding([a.id])).get(a.id)
        program_id = held.program_id if held else None
        open_enrolment = False
        if a.status == "verified":
            prefs = (await self.applicants.preferences([a.id]))[a.id]
            program = await self.cycles.program(prefs[0].program_id) if prefs else None
            paid = self.payments(a).get("application", {}).get("status") == "paid"
            open_enrolment = bool(
                program
                and program.is_open_enrolment
                and paid
                and await is_enabled(self.inst, "admissions.open_enrolment")
            )
            program_id = program.id if open_enrolment and program else None
        if a.status not in ("accepted", "provisionally_admitted") and not open_enrolment:
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                "Only an accepted applicant (admission fee paid) can be admitted",
                {"reason": "not_accepted", "status": a.status},
            )
        if program_id is None:
            offer = next((o for o in await self.counselling.offers([a.id]) if o.status in ("issued", "accepted")), None)
            program_id = offer.program_id if offer else None
        if program_id is None:
            raise APIError(409, ErrorCode.RULE_VIOLATION, "No seat or offer to admit against", {"reason": "no_seat"})
        docs = (await self.applicants.documents([a.id]))[a.id]
        required = {d["doc_type"] for d in self.required_documents(cycle, a.entry_type) if d.get("required", True)}
        unverified = sorted(t for t in required if not any(d.doc_type == t and d.status == "verified" for d in docs))
        if unverified and a.source != "counselling_import":
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                "Documents are not verified",
                {"reason": "documents", "documents": unverified},
            )
        if a.dob is None or not a.gender:
            raise APIError(
                422, ErrorCode.VALIDATION, "Date of birth and gender are required to admit", {"field": "dob"}
            )
        year = (
            await self.db.execute(select(AcademicYear).where(AcademicYear.id == cycle.academic_year_id))
        ).scalar_one_or_none()
        contact = a.contact or {}
        guardians = []
        if contact.get("guardian_name"):
            guardians.append(
                GuardianIn(
                    relation=contact.get("guardian_relation") or "father",
                    name=contact["guardian_name"],
                    phone=contact.get("guardian_phone"),
                    email=contact.get("guardian_email"),
                    is_primary=True,
                )
            )
        lateral = a.entry_type == "lateral"
        body_in = StudentCreate(
            first_name=a.first_name,
            middle_name=a.middle_name,
            last_name=a.last_name,
            dob=a.dob,
            gender=Gender(a.gender),
            category=a.category,
            is_pwd=a.is_pwd,
            nationality=a.nationality or "Indian",
            domicile_state=a.domicile_state,
            phone=contact.get("phone"),
            email=contact.get("email"),
            program_id=program_id,
            admission_year=year.start_date.year if year else None,
            section_id=body.section_id,
            entry_type=EntryType.LATERAL if lateral else EntryType.REGULAR,
            entry_term_number=int(await self.adm_setting("lateral_entry_term", 3)) if lateral else None,
            admission_mode="counselling" if a.source == "counselling_import" else "admission",
            admission_quota=held.quota if held else a.quota_claimed,
            registration_number=body.registration_number,
            status="admitted",
            guardians=guardians,
        )
        await self._retire_applicant_account(a)
        created = await StudentService(self.db, self.principal, self.request, self.inst).create_record(
            body_in, source="admission"
        )
        a.admitted_student_id = created.student.id
        if held is not None:
            held.status, held.reported_at = "admitted", utcnow()
        else:
            seat = next(
                (
                    r
                    for r in await self.cycles.seat_rows(cycle.id, for_update=True)
                    if r.program_id == program_id and r.filled < r.seats and r.category in (a.category, GEN)
                ),
                None,
            )
            if seat is not None:
                seat.filled += 1
        for o in await self.counselling.offers([a.id]):
            if o.status == "issued" and o.program_id == program_id:
                o.status = "accepted"
        await self.db.flush()
        await self.transition(
            a,
            "admitted",
            force=open_enrolment,
            extra={
                "student_id": str(created.student.id),
                "registration_number": created.student.registration_number,
                "entrance": a.entrance,
                "merit_score": float(a.merit_score) if a.merit_score is not None else None,
            },
        )
        return AdmitResult(
            student_id=created.student.id,
            registration_number=created.student.registration_number,
            username=created.user.username if created.user else None,
            temp_password=created.temp_password,
            applicant=await self.respond(a),
        )
