"""Merit lists — Prompts/08 §08.6 ``merit_service.py``.

``generate`` creates the draft list and enqueues the job ``admissions.merit_generate`` (202 + ``job_id``); the job
ranks the eligible applicants (``verified | waitlisted | merit_listed``, narrowed by programme preference / quota /
category): score = Σ weight × normalised field / 100 (``entrance_score`` normalised by the component ``max`` or the
entrance ``max_score``, ``qualifying_pct`` as is, ``institution_test_score`` by its max), ties broken in the order of
``tie_break`` (default ``entrance_score`` desc, ``dob_asc``, ``submitted_at``), category rank within the category.
The ``formula_snapshot`` keeps the formula and tie-breaks; older lists with the same scope become ``superseded``.
``publish`` notifies every listed applicant and exposes the masked public list (application number + rank) when
``admissions.public_merit_lists`` allows it.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import delete

from app.core import jobs
from app.core.errors import APIError, ErrorCode
from app.enums.admissions import MERIT_ELIGIBLE
from app.models.admissions import Applicant, MeritList, MeritListEntry
from app.schemas.admissions import (
    MeritEntry,
    MeritGenerateRequest,
    MeritListDetail,
    MeritListResponse,
    PublicMeritEntry,
    PublicMeritList,
)
from app.services.admissions.common import AdmissionsBase, utcnow

DEFAULT_FORMULA = [{"field": "entrance_score", "weight": 60}, {"field": "qualifying_pct", "weight": 40}]
DEFAULT_TIE_BREAK = ["entrance_score", "dob_asc", "submitted_at"]
ENTRANCE_MAX = {"jee": 300, "neet": 720, "cuet": 800, "gate": 100, "cat": 100, "state_cet": 200}


def best_pct(a: Applicant) -> float:
    pcts = [float(e.get("pct") or 0) for e in (a.qualifying_exams or []) if isinstance(e, dict)]
    return max(pcts) if pcts else 0.0


class MeritService(AdmissionsBase):
    async def _out(self, rows: list[MeritList]) -> list[MeritListResponse]:
        counts = await self.merit.entry_counts([r.id for r in rows])
        out = []
        for r in rows:
            item = MeritListResponse.model_validate(r)
            item.entries_count = counts.get(r.id, 0)
            out.append(item)
        return out

    async def lists(self, cycle_id: uuid.UUID | None, status: str | None = None) -> list[MeritListResponse]:
        return await self._out(list(await self.merit.lists(cycle_id, status)))

    async def detail(self, list_id: uuid.UUID) -> MeritListDetail:
        ml = await self.merit.get(list_id)
        base = (await self._out([ml]))[0]
        entries = [
            MeritEntry(
                rank=e.rank,
                category_rank=e.category_rank,
                score=e.score,
                applicant_id=a.id,
                application_number=a.application_number,
                name=a.full_name,
                category=a.category,
                is_pwd=a.is_pwd,
                tie_break=e.tie_break,
            )
            for e, a in await self.merit.entries(ml.id)
        ]
        return MeritListDetail(**base.model_dump(), entries=entries)

    # ---- generate --------------------------------------------------------------------------------------------------
    async def generate(self, cycle_id: uuid.UUID, body: MeritGenerateRequest) -> MeritListResponse:
        cycle = await self.cycles.cycle(cycle_id)
        if cycle.status in ("draft", "archived"):
            raise APIError(409, ErrorCode.CONFLICT, f"Merit lists cannot be generated for a {cycle.status} cycle")
        offered = {p.program_id: p for p in await self.cycles.programs(cycle.id)}
        for pid in body.program_ids or []:
            if pid not in offered:
                raise APIError(422, ErrorCode.VALIDATION, "Programme is not in the cycle", {"field": "program_ids"})
        single = body.program_ids[0] if body.program_ids and len(body.program_ids) == 1 else None
        ml = MeritList(
            institution_id=self.inst,
            cycle_id=cycle.id,
            program_id=single,
            college_id=offered[single].college_id if single else None,
            name=body.name,
            quota=body.quota.upper() if body.quota else None,
            category=body.category.upper().replace("_", "-") if body.category else None,
            status="draft",
            formula_snapshot={"program_ids": [str(p) for p in body.program_ids or []]},
            created_by=self.actor_id,
        )
        self.db.add(ml)
        await self.db.flush()
        job = await jobs.enqueue(
            self.db, self.principal, "admissions.merit_generate", {"merit_list_id": str(ml.id)}, queue="reports"
        )
        ml.job_id = job.id
        await self.db.flush()
        await self._audit("merit_generate", "merit_list", ml.id, None, {"name": ml.name, "job_id": str(job.id)})
        return (await self._out([ml]))[0]

    async def run_generate(self, list_id: uuid.UUID, progress: Callable[[int, str], Awaitable[None]]) -> dict[str, Any]:
        ml = await self.merit.get(list_id, for_update=True)
        cycle = await self.cycles.cycle(ml.cycle_id)
        offered = {p.program_id: p for p in await self.cycles.programs(cycle.id)}
        program_ids = [uuid.UUID(p) for p in (ml.formula_snapshot or {}).get("program_ids") or []]
        cp = offered.get(program_ids[0]) if program_ids else next(iter(offered.values()), None)
        formula = (cp.merit_formula if cp and cp.merit_formula else None) or DEFAULT_FORMULA
        tie_break = (cp.tie_break if cp and cp.tie_break else None) or DEFAULT_TIE_BREAK
        stmt = self.applicants.filtered(
            cycle_id=cycle.id, statuses=sorted(MERIT_ELIGIBLE), quota=ml.quota, category=ml.category
        )
        candidates = list((await self.db.execute(stmt)).scalars().all())
        if program_ids:
            prefs = await self.applicants.preferences([a.id for a in candidates])
            candidates = [a for a in candidates if any(p.program_id in program_ids for p in prefs.get(a.id, []))]
        await progress(20, f"{len(candidates)} eligible applicant(s)")
        default_max = ENTRANCE_MAX.get(cp.entrance_source if cp else "", 100)

        def norm(a: Applicant, comp: dict[str, Any]) -> float:
            field = comp.get("field")
            ent = a.entrance or {}
            if field == "entrance_score":
                mx = float(comp.get("max") or ent.get("max_score") or default_max)
                return min(float(ent.get("score") or 0) / mx * 100, 100.0) if mx else 0.0
            if field == "qualifying_pct":
                return best_pct(a)
            if field == "institution_test_score":
                mx = float(comp.get("max") or 100)
                return min(float(ent.get("institution_test_score") or 0) / mx * 100, 100.0)
            return float(ent.get(str(field)) or 0)

        scored: list[tuple[Applicant, Decimal]] = []
        for a in candidates:
            total = sum(float(str(c.get("weight") or 0)) * norm(a, c) for c in formula) / 100.0
            scored.append((a, Decimal(str(total)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)))

        def key(item: tuple[Applicant, Decimal]) -> tuple[Any, ...]:
            a, score = item
            parts: list[Any] = [-score]
            for t in tie_break:
                if t == "entrance_score":
                    parts.append(-float((a.entrance or {}).get("score") or 0))
                elif t in ("dob_asc", "dob"):
                    parts.append(a.dob or date.max)
                elif t == "dob_desc":
                    parts.append(-(a.dob or date.min).toordinal())
                elif t == "qualifying_pct":
                    parts.append(-best_pct(a))
                elif t == "submitted_at":
                    parts.append(a.submitted_at.timestamp() if a.submitted_at else float("inf"))
            parts.append(a.application_number)
            return tuple(parts)

        scored.sort(key=key)
        await self.db.execute(delete(MeritListEntry).where(MeritListEntry.merit_list_id == ml.id))
        cat_rank: dict[str, int] = {}
        for rank, (a, score) in enumerate(scored, start=1):
            cat = a.category or "GEN"
            cat_rank[cat] = cat_rank.get(cat, 0) + 1
            self.db.add(
                MeritListEntry(
                    institution_id=self.inst,
                    merit_list_id=ml.id,
                    applicant_id=a.id,
                    rank=rank,
                    category_rank=cat_rank[cat],
                    score=score,
                    tie_break={
                        "entrance_score": (a.entrance or {}).get("score"),
                        "dob": a.dob.isoformat() if a.dob else None,
                        "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
                    },
                )
            )
            a.merit_score = score
            if a.status in ("verified", "waitlisted"):
                await self.transition(
                    a, "merit_listed", notify=False, extra={"merit_list_id": str(ml.id), "rank": rank}
                )
        superseded = 0
        for old in await self.merit.same_scope(ml):
            old.status = "superseded"
            superseded += 1
        ml.generated_at = utcnow()
        ml.formula_snapshot = {
            **(ml.formula_snapshot or {}),
            "formula": formula,
            "tie_break": tie_break,
            "entrance_source": cp.entrance_source if cp else None,
            "eligible_statuses": sorted(MERIT_ELIGIBLE),
            "count": len(scored),
        }
        await self.db.flush()
        await self._audit(
            "merit_generated", "merit_list", ml.id, None, {"count": len(scored), "superseded": superseded}
        )
        await progress(100, f"{len(scored)} ranked")
        return {"merit_list_id": str(ml.id), "count": len(scored), "superseded": superseded}

    async def publish(self, list_id: uuid.UUID) -> MeritListResponse:
        ml = await self.merit.get(list_id, for_update=True)
        if ml.status != "draft" or ml.generated_at is None:
            raise APIError(
                409, ErrorCode.CONFLICT, f"Only a generated draft list can be published (status {ml.status})"
            )
        ml.status, ml.published_at = "published", utcnow()
        await self.db.flush()
        await self._audit("publish", "merit_list", ml.id, {"status": "draft"}, {"status": "published"})
        await self._emit(
            "merit_list.published", {"merit_list_id": str(ml.id), "cycle_id": str(ml.cycle_id)}, "merit_list", ml.id
        )
        for e, a in await self.merit.entries(ml.id):
            if a.user_id:
                await self._notify(
                    "admissions.status_changed",
                    [a.user_id],
                    {
                        "application_no": a.application_number,
                        "status": f"on the merit list “{ml.name}” — rank {e.rank}",
                    },
                )
        return (await self._out([ml]))[0]

    async def public_list(self, slug: str, list_id: uuid.UUID) -> PublicMeritList:
        cycle = await self.cycles.by_slug(slug)
        if cycle is None or not await self.adm_setting("public_merit_lists", True):
            raise APIError(404, ErrorCode.NOT_FOUND, "Merit list not found")
        ml = await self.merit.get(list_id)
        if ml.cycle_id != cycle.id or ml.status != "published":
            raise APIError(404, ErrorCode.NOT_FOUND, "Merit list not found")
        return PublicMeritList(
            name=ml.name,
            cycle=cycle.name,
            published_at=ml.published_at,
            entries=[
                PublicMeritEntry(rank=e.rank, application_number=a.application_number)
                for e, a in await self.merit.entries(ml.id)
            ],
        )
