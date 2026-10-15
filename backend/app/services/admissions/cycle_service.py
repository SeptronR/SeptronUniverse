"""Admission cycles, programme intakes and the seat matrix — Prompts/08 §08.6 ``cycle_service.py``.

Rules
1. CRUD (``admissions:manage``; a college-scoped office creates cycles of its college only); ``slug`` unique per
   institution (409). ``form_config`` is validated: ``steps`` a list, ``max_preferences`` 1–20, ``refund_policy``
   ``{processing_fee_paise, after_acceptance_pct}``.
2. Status machine ``draft → open → closed → merit_processing → counselling → completed → archived`` (``closed → open``
   re-opens). Opening needs ≥ 1 programme and, per programme, seat-matrix rows summing to ``intake + lateral_intake``
   (409 ``RULE_VIOLATION`` with the unbalanced programmes). Archiving expires the applicant accounts of the cycle
   (time-boxed ``applicant`` role).
3. Programmes are replaced as a set (programmes holding applicant preferences cannot be dropped — 409). The seat
   matrix is replaced as a set of (programme, college, quota, category) rows; quota / category must be pack codes;
   rows with filled seats cannot drop below ``filled`` (409).
4. ``public_info(slug)``: programmes, fee, windows, required documents, pack categories / quotas and the published
   merit lists (when ``admissions.public_merit_lists``).
"""

import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import update

from app.core.errors import APIError, ErrorCode
from app.enums.admissions import CYCLE_TRANSITIONS
from app.models.admissions import AdmissionCycle, AdmissionCycleProgram, Applicant, ApplicantPreference, SeatMatrix
from app.models.platform import User
from app.schemas.admissions import (
    CycleCreate,
    CycleProgramOut,
    CycleProgramsReplace,
    CycleResponse,
    CycleStatusChange,
    CycleUpdate,
    ProgramSeatTotal,
    PublicCycleInfo,
    PublicCycleProgram,
    SeatMatrixReplace,
    SeatRowOut,
    SeatStatusResponse,
)
from app.services.admissions.common import AdmissionsBase, utcnow
from app.services.institution.context import check_college_writable

CYCLE_KEYS = ("name", "slug", "level", "status", "application_fee_paise", "opens_at", "closes_at", "college_id")


class CycleService(AdmissionsBase):
    # ---- reads --------------------------------------------------------------------------------------------------
    async def _out(self, cycles: list[AdmissionCycle]) -> list[CycleResponse]:
        counts = await self.cycles.counts([c.id for c in cycles])
        out = []
        for c in cycles:
            item = CycleResponse.model_validate(c)
            item.programs_count, item.applicants_count, item.intake_total = counts.get(c.id, (0, 0, 0))
            out.append(item)
        return out

    async def list_all(self, status: str | None = None, level: str | None = None) -> list[CycleResponse]:
        return await self._out(list(await self.cycles.list_cycles(status, level)))

    async def get(self, cycle_id: uuid.UUID) -> CycleResponse:
        return (await self._out([await self.cycles.cycle(cycle_id)]))[0]

    # ---- rule 1 ---------------------------------------------------------------------------------------------------
    def _check_form(self, cfg: dict[str, Any] | None) -> None:
        if not cfg:
            return
        if "steps" in cfg and not isinstance(cfg["steps"], list):
            raise APIError(422, ErrorCode.VALIDATION, "form_config.steps must be a list", {"field": "form_config"})
        mp = cfg.get("max_preferences")
        if mp is not None and (not isinstance(mp, int) or not 1 <= mp <= 20):
            raise APIError(422, ErrorCode.VALIDATION, "max_preferences must be 1–20", {"field": "form_config"})
        rp = cfg.get("refund_policy")
        if rp is not None and (not isinstance(rp, dict) or not 0 <= int(rp.get("after_acceptance_pct", 0)) <= 100):
            raise APIError(422, ErrorCode.VALIDATION, "refund_policy is invalid", {"field": "form_config"})

    async def create(self, body: CycleCreate) -> CycleResponse:
        if body.college_id is not None:
            check_college_writable(self.principal, body.college_id)
        if await self.cycles.slug_taken(body.slug):
            raise APIError(409, ErrorCode.CONFLICT, f"Cycle slug '{body.slug}' already exists", {"field": "slug"})
        self._check_form(body.form_config)
        if body.opens_at and body.closes_at and body.closes_at <= body.opens_at:
            raise APIError(422, ErrorCode.VALIDATION, "closes_at must be after opens_at", {"field": "closes_at"})
        cycle = AdmissionCycle(
            institution_id=self.inst,
            college_id=body.college_id,
            academic_year_id=body.academic_year_id,
            name=body.name,
            slug=body.slug,
            level=body.level.value,
            application_fee_paise=body.application_fee_paise,
            opens_at=body.opens_at,
            closes_at=body.closes_at,
            status="draft",
            form_config=body.form_config,
            required_documents=[d.model_dump(mode="json") for d in body.required_documents]
            if body.required_documents
            else None,
            de_reservation_policy=body.de_reservation_policy,
            created_by=self.actor_id,
        )
        self.db.add(cycle)
        await self.db.flush()
        await self._audit("create", "admission_cycle", cycle.id, None, _snap(cycle))
        return await self.get(cycle.id)

    async def update(self, cycle_id: uuid.UUID, body: CycleUpdate) -> CycleResponse:
        cycle = await self.cycles.cycle(cycle_id, for_update=True)
        if body.version is not None and body.version != cycle.version:
            raise APIError(409, ErrorCode.STALE_VERSION, "The cycle was changed by someone else — reload")
        if cycle.status == "archived":
            raise APIError(409, ErrorCode.RECORD_LOCKED, "An archived cycle is read-only")
        old = _snap(cycle)
        data = body.model_dump(exclude_unset=True, exclude={"version"})
        if "form_config" in data:
            self._check_form(data["form_config"])
        if "required_documents" in data and data["required_documents"] is not None:
            data["required_documents"] = [d.model_dump(mode="json") for d in body.required_documents or []]
        for k, v in data.items():
            setattr(cycle, k, v)
        await self.db.flush()
        await self._audit("update", "admission_cycle", cycle.id, old, _snap(cycle))
        return await self.get(cycle.id)

    # ---- rule 2 ---------------------------------------------------------------------------------------------------
    async def balance(self, cycle: AdmissionCycle) -> list[ProgramSeatTotal]:
        programs = await self.cycles.programs(cycle.id)
        seats: dict[tuple[uuid.UUID, uuid.UUID], tuple[int, int]] = defaultdict(lambda: (0, 0))
        for r in await self.cycles.seat_rows(cycle.id):
            s, f = seats[(r.program_id, r.college_id)]
            seats[(r.program_id, r.college_id)] = (s + r.seats, f + r.filled)
        prog_rows = await self.cycles.program_rows([p.program_id for p in programs])
        out = []
        for p in programs:
            s, f = seats.get((p.program_id, p.college_id), (0, 0))
            out.append(
                ProgramSeatTotal(
                    program_id=p.program_id,
                    college_id=p.college_id,
                    program_code=prog_rows[p.program_id].code if p.program_id in prog_rows else None,
                    intake=p.intake,
                    lateral_intake=p.lateral_intake,
                    seats=s,
                    filled=f,
                    balanced=s == p.intake + p.lateral_intake,
                )
            )
        return out

    async def change_status(self, cycle_id: uuid.UUID, body: CycleStatusChange) -> CycleResponse:
        cycle = await self.cycles.cycle(cycle_id, for_update=True)
        to = body.status.value
        if to not in CYCLE_TRANSITIONS.get(cycle.status, set()):
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                f"A cycle in status '{cycle.status}' cannot move to '{to}'",
                {"from": cycle.status, "to": to, "allowed": sorted(CYCLE_TRANSITIONS.get(cycle.status, set()))},
            )
        if to == "open":
            totals = await self.balance(cycle)
            if not totals:
                raise APIError(
                    409,
                    ErrorCode.RULE_VIOLATION,
                    "Add at least one programme before opening",
                    {"reason": "no_programs"},
                )
            bad = [t.model_dump(mode="json") for t in totals if not t.balanced]
            if bad:
                raise APIError(
                    409,
                    ErrorCode.RULE_VIOLATION,
                    "Seat matrix does not match the intake (Σ seats must equal intake + lateral intake)",
                    {"reason": "seat_matrix_unbalanced", "programs": bad},
                )
        old = cycle.status
        cycle.status = to
        await self.db.flush()
        if to == "archived":
            await self._expire_applicant_accounts(cycle)
        await self._audit("status", "admission_cycle", cycle.id, {"status": old}, {"status": to, "reason": body.reason})
        if to in ("open", "closed"):
            await self._emit(
                f"admissions.cycle_{'opened' if to == 'open' else 'closed'}",
                {"cycle_id": str(cycle.id), "slug": cycle.slug},
                "admission_cycle",
                cycle.id,
            )
        return await self.get(cycle.id)

    async def _expire_applicant_accounts(self, cycle: AdmissionCycle) -> None:
        from sqlalchemy import select

        user_ids = select(Applicant.user_id).where(
            Applicant.cycle_id == cycle.id, Applicant.user_id.is_not(None), Applicant.status != "admitted"
        )
        await self.db.execute(
            update(User).where(User.id.in_(user_ids), User.user_type == "applicant").values(valid_to=utcnow())
        )

    async def close_due(self) -> int:
        """Beat ``admissions.close_cycles``: open cycles past ``closes_at`` → ``closed``."""
        now = utcnow()
        n = 0
        for c in await self.cycles.list_cycles(status="open"):
            if c.closes_at and c.closes_at < now:
                c.status = "closed"
                await self._audit("status", "admission_cycle", c.id, {"status": "open"}, {"status": "closed"})
                await self._emit("admissions.cycle_closed", {"cycle_id": str(c.id)}, "admission_cycle", c.id)
                n += 1
        await self.db.flush()
        return n

    # ---- rule 3 ---------------------------------------------------------------------------------------------------
    async def programs_out(self, cycle_id: uuid.UUID) -> list[CycleProgramOut]:
        rows = await self.cycles.programs(cycle_id)
        progs = await self.cycles.program_rows([r.program_id for r in rows])
        colleges = await self.cycles.college_rows([r.college_id for r in rows])
        out = []
        for r in rows:
            item = CycleProgramOut.model_validate(r)
            p = progs.get(r.program_id)
            item.program_code, item.program_name = (p.code, p.name) if p else (None, None)
            item.department_id = p.department_id if p else None
            item.college_name = colleges[r.college_id].name if r.college_id in colleges else None
            out.append(item)
        return out

    async def replace_programs(self, cycle_id: uuid.UUID, body: CycleProgramsReplace) -> list[CycleProgramOut]:
        from sqlalchemy import select

        cycle = await self.cycles.cycle(cycle_id, for_update=True)
        if cycle.status in ("completed", "archived"):
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"A {cycle.status} cycle is read-only")
        existing = {(r.program_id, r.college_id): r for r in await self.cycles.programs(cycle.id)}
        wanted: dict[tuple[uuid.UUID, uuid.UUID], Any] = {}
        for p in body.programs:
            program = await self.cycles.program(p.program_id)
            college_id = p.college_id or program.college_id
            if cycle.college_id and college_id != cycle.college_id:
                raise APIError(422, ErrorCode.VALIDATION, "Programme belongs to another college", {"field": "programs"})
            if (p.program_id, college_id) in wanted:
                raise APIError(422, ErrorCode.VALIDATION, "Duplicate programme", {"field": "programs"})
            wanted[(p.program_id, college_id)] = p
        for key, row in existing.items():
            if key in wanted:
                continue
            used = (
                await self.db.execute(
                    select(ApplicantPreference.id)
                    .join(Applicant, Applicant.id == ApplicantPreference.applicant_id)
                    .where(
                        Applicant.cycle_id == cycle.id,
                        ApplicantPreference.program_id == key[0],
                        ApplicantPreference.college_id == key[1],
                    )
                    .limit(1)
                )
            ).first()
            if used:
                raise APIError(
                    409,
                    ErrorCode.CONFLICT,
                    "A programme with applicant preferences cannot be removed",
                    {"field": "programs"},
                )
            await self.db.delete(row)
        for key, p in wanted.items():
            prow = existing.get(key)
            if prow is None:
                prow = AdmissionCycleProgram(
                    institution_id=self.inst, cycle_id=cycle.id, program_id=key[0], college_id=key[1]
                )
                self.db.add(prow)
            prow.intake, prow.lateral_intake = p.intake, p.lateral_intake
            prow.entrance_source = p.entrance_source.value
            prow.eligibility_rules, prow.merit_formula, prow.tie_break = (
                p.eligibility_rules,
                p.merit_formula,
                p.tie_break,
            )
        await self.db.flush()
        await self._audit(
            "programs",
            "admission_cycle",
            cycle.id,
            None,
            {
                "programs": [
                    {"program_id": str(k[0]), "intake": v.intake, "lateral": v.lateral_intake}
                    for k, v in wanted.items()
                ]
            },
        )
        return await self.programs_out(cycle.id)

    async def seat_status(self, cycle_id: uuid.UUID) -> SeatStatusResponse:
        cycle = await self.cycles.cycle(cycle_id)
        rows = await self.cycles.seat_rows(cycle.id)
        progs = await self.cycles.program_rows([r.program_id for r in rows])
        out = []
        for r in sorted(rows, key=lambda r: (str(r.program_id), r.quota, r.category)):
            item = SeatRowOut.model_validate(r)
            item.program_code = progs[r.program_id].code if r.program_id in progs else None
            item.vacant = max(r.seats - r.filled, 0)
            out.append(item)
        pack = await self.pack()
        return SeatStatusResponse(
            cycle_id=cycle.id,
            rows=out,
            programs=await self.balance(cycle),
            quotas=[q.code for q in pack.quotas],
            categories=[c.code for c in pack.categories if c.code != "OBC-CL"],
        )

    async def replace_seat_matrix(self, cycle_id: uuid.UUID, body: SeatMatrixReplace) -> SeatStatusResponse:
        cycle = await self.cycles.cycle(cycle_id, for_update=True)
        if cycle.status in ("completed", "archived"):
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"A {cycle.status} cycle is read-only")
        pack = await self.pack()
        quotas = {q.code for q in pack.quotas}
        cats = {c.code for c in pack.categories}
        programs = {(p.program_id, p.college_id) for p in await self.cycles.programs(cycle.id)}
        prog_college = dict(programs)
        existing = {
            (r.program_id, r.college_id, r.quota, r.category): r
            for r in await self.cycles.seat_rows(cycle.id, for_update=True)
        }
        wanted: dict[tuple[uuid.UUID, uuid.UUID, str, str], int] = {}
        for i, row in enumerate(body.rows):
            college_id = row.college_id or prog_college.get(row.program_id)
            quota, category = row.quota.upper(), row.category.upper().replace("_", "-")
            if college_id is None or (row.program_id, college_id) not in programs:
                raise APIError(
                    422, ErrorCode.VALIDATION, f"Row {i + 1}: programme is not in the cycle", {"field": f"rows.{i}"}
                )
            if quota not in quotas:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    f"Row {i + 1}: unknown quota {row.quota}",
                    {"field": f"rows.{i}.quota", "allowed": sorted(quotas)},
                )
            if category not in cats:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    f"Row {i + 1}: unknown category {row.category}",
                    {"field": f"rows.{i}.category", "allowed": sorted(cats)},
                )
            key = (row.program_id, college_id, quota, category)
            wanted[key] = wanted.get(key, 0) + row.seats
        for key, r in existing.items():
            seats = wanted.get(key)
            if (seats is None or seats < r.filled) and r.filled > 0:
                raise APIError(
                    409,
                    ErrorCode.CONFLICT,
                    f"{key[2]}/{key[3]} has {r.filled} filled seat(s) — cannot go below that",
                    {"reason": "below_filled", "quota": key[2], "category": key[3]},
                )
            if seats is None:
                await self.db.delete(r)
        for key, seats in wanted.items():
            srow = existing.get(key)
            if srow is None:
                self.db.add(
                    SeatMatrix(
                        institution_id=self.inst,
                        cycle_id=cycle.id,
                        program_id=key[0],
                        college_id=key[1],
                        quota=key[2],
                        category=key[3],
                        seats=seats,
                        filled=0,
                    )
                )
            else:
                srow.seats = seats
        await self.db.flush()
        await self._audit(
            "seat_matrix", "admission_cycle", cycle.id, None, {"rows": len(wanted), "seats": sum(wanted.values())}
        )
        return await self.seat_status(cycle.id)

    # ---- rule 4 ---------------------------------------------------------------------------------------------------
    async def public_info(self, slug: str) -> PublicCycleInfo:
        cycle = await self.cycles.by_slug(slug)
        if cycle is None or cycle.status == "draft":
            raise APIError(404, ErrorCode.NOT_FOUND, "Admission cycle not found")
        inst = await self.institution()
        pack = await self.pack()
        progs = await self.programs_out(cycle.id)
        now = utcnow()
        is_open = (
            cycle.status == "open"
            and (cycle.opens_at is None or cycle.opens_at <= now)
            and (cycle.closes_at is None or cycle.closes_at > now)
        )
        lists = []
        if await self.adm_setting("public_merit_lists", True):
            lists = [
                {
                    "id": str(m.id),
                    "name": m.name,
                    "published_at": m.published_at.isoformat() if m.published_at else None,
                }
                for m in await self.merit.lists(cycle.id, "published")
            ]
        return PublicCycleInfo(
            name=cycle.name,
            slug=cycle.slug,
            level=cycle.level,
            status=cycle.status,
            application_fee_paise=cycle.application_fee_paise,
            opens_at=cycle.opens_at,
            closes_at=cycle.closes_at,
            is_open=is_open,
            institution={"name": inst.name, "slug": inst.slug},
            programs=[
                PublicCycleProgram(
                    program_id=p.program_id,
                    college_id=p.college_id,
                    code=p.program_code,
                    name=p.program_name,
                    college_name=p.college_name,
                    intake=p.intake,
                    lateral_intake=p.lateral_intake,
                    entrance_source=p.entrance_source,
                    eligibility_rules=p.eligibility_rules,
                )
                for p in progs
            ],
            required_documents=self.required_documents(cycle),
            form_config=cycle.form_config,
            categories=[{"code": c.code, "name": c.name} for c in pack.categories],
            quotas=[{"code": q.code, "name": q.name} for q in pack.quotas],
            published_merit_lists=lists,
        )

    async def public_cycles(self) -> list[dict[str, Any]]:
        out = []
        for c in await self.cycles.list_cycles():
            if c.status in ("draft", "archived"):
                continue
            out.append(
                {
                    "name": c.name,
                    "slug": c.slug,
                    "level": c.level,
                    "status": c.status,
                    "opens_at": c.opens_at,
                    "closes_at": c.closes_at,
                    "application_fee_paise": c.application_fee_paise,
                }
            )
        return out


def _snap(c: AdmissionCycle) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in CYCLE_KEYS:
        v = getattr(c, k)
        out[k] = v.isoformat() if hasattr(v, "isoformat") else (str(v) if isinstance(v, uuid.UUID) else v)
    return out
