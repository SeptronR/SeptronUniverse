"""API / CAS score, research profile and statistics — Prompts/30 §30.6 ``api_score_service`` ({research.api_score})
and ``stats_service``.

* API score per faculty for a period with ``research.api_score_scheme`` (UGC CAS 2018 category tables): research papers
  (indexing points + impact-factor bonus, author share — sole author 100 %, first / corresponding authors share 70 %,
  the others 30 %), books / chapters, sponsored projects (by sanctioned lakh slab, PI), consultancy, patents (by status),
  FDP (by role, capped), awards (by level), co-curricular (in-house events organised, capped); teaching-learning is
  taken from the latest Phase 06 appraisal breakdown when present. Only verified publications count. The total lands on
  ``faculty_profiles.api_score / api_updated_at`` with the breakdown in the side store (``api:<staff>``) and an index in
  ``institution_settings['research.api_snapshots']`` ({staff: {period: total}}) for Phase 06 CAS eligibility; rankings
  per department.
* Profile: counts, h-index proxy from citations, projects / funding, consultancy, patents, FDP hours, awards.
* Stats (verified only): publications per teacher, by indexing, grants, consultancy revenue, patents, FDP participation,
  MoUs (functional = with a collaboration that year), start-ups, by department; NAAC 3.x and NIRF RP (PU, QP, IPR, FPPP)
  values published as ``research.stats_published`` for Phase 32 ``metric_values``.
"""

import csv
import io
import uuid
import zipfile
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import extract, func, select

from app.enums.research import DEFAULT_API_SCHEME, INDEXED
from app.models.events import Event
from app.models.hr import Appraisal, FacultyProfile, Staff
from app.models.platform import InstitutionSetting
from app.models.research import (
    Collaboration,
    Consultancy,
    FacultyAward,
    FacultyDevelopment,
    IncubationStartup,
    Mou,
    Patent,
    Publication,
    ResearchProject,
)
from app.schemas.research import ApiRankingRow, ApiScoreOut, ResearchProfileOut, ResearchStats
from app.services.research.common import ResearchBase, forbidden, not_found, now_utc, rule, staff_name


def h_index(citations: list[int]) -> int:
    cs = sorted((c for c in citations if c), reverse=True)
    return max((i + 1 for i, c in enumerate(cs) if c >= i + 1), default=0)


def _author_share(p: Publication, staff_id: uuid.UUID) -> float:
    authors = list(p.authors or [])
    n = len(authors)
    if n <= 1:
        return 1.0
    primary = [i for i, a in enumerate(authors) if i == 0 or a.get("is_corresponding")]
    idx = next((i for i, a in enumerate(authors) if str(a.get("staff_id")) == str(staff_id)), None)
    if idx is None:
        idx = (p.author_position or 1) - 1 if p.staff_id == staff_id else n - 1
    if idx in primary:
        return 0.7 / max(1, len(primary))
    return 0.3 / max(1, n - len(primary))


class ScoreService(ResearchBase):
    # ---- API score ---------------------------------------------------------------------------------------------------
    async def scheme(self) -> dict[str, Any]:
        v = await self.json_setting("api_score_scheme", DEFAULT_API_SCHEME)
        return v if isinstance(v, dict) and v.get("categories") else DEFAULT_API_SCHEME

    async def compute_one(self, staff_id: uuid.UUID, d1: date, d2: date) -> ApiScoreOut:
        sch = await self.scheme()
        cats: dict[str, Any] = sch["categories"]
        mine = Publication.authors.contains([{"staff_id": str(staff_id)}]) | (Publication.staff_id == staff_id)
        pubs = list(
            (
                await self.db.execute(
                    select(Publication).where(
                        Publication.institution_id == self.inst,
                        Publication.is_verified.is_(True),
                        mine,
                        Publication.year >= d1.year,
                        Publication.year <= d2.year,
                    )
                )
            ).scalars()
        )
        breakdown: dict[str, Any] = {}

        def put(cat: str, items: list[dict[str, Any]]) -> None:
            cfg = cats.get(cat) or {}
            pts = round(sum(float(i["points"]) for i in items), 2)
            cap = cfg.get("max")
            breakdown[cat] = {"label": cfg.get("label", cat), "items": items, "points": min(pts, cap) if cap else pts}

        pp = cats.get("publications", {})
        paper_items, book_items = [], []
        for p in pubs:
            if p.pub_type in ("book", "chapter"):
                base = float((cats.get("books", {}).get("points") or {}).get(p.pub_type, 0))
                book_items.append(
                    {"id": str(p.id), "title": p.title[:120], "points": round(base * _author_share(p, staff_id), 2)}
                )
                continue
            base = float((pp.get("points") or {}).get(p.indexing or "none", 0))
            for threshold, bonus in pp.get("impact_factor_bonus") or []:
                if p.impact_factor is not None and float(p.impact_factor) >= float(threshold):
                    base += float(bonus)
                    break
            share = _author_share(p, staff_id)
            paper_items.append(
                {
                    "id": str(p.id),
                    "title": p.title[:120],
                    "indexing": p.indexing,
                    "share": round(share, 3),
                    "points": round(base * share, 2),
                }
            )
        put("publications", paper_items)
        put("books", book_items)

        projects = list(
            (
                await self.db.execute(
                    select(ResearchProject).where(
                        ResearchProject.institution_id == self.inst,
                        ResearchProject.pi_staff_id == staff_id,
                        ResearchProject.status.in_(("sanctioned", "ongoing", "completed", "closed")),
                        (ResearchProject.start_on.is_(None)) | (ResearchProject.start_on <= d2),
                        (ResearchProject.end_on.is_(None)) | (ResearchProject.end_on >= d1),
                    )
                )
            ).scalars()
        )
        slabs = cats.get("projects", {}).get("per_project_lakh") or [[10, 10], [0, 5]]
        put(
            "projects",
            [
                {
                    "id": str(p.id),
                    "title": p.title[:120],
                    "points": next(
                        (float(pts) for lakh, pts in slabs if int(p.sanctioned_paise or 0) >= int(lakh) * 10_000_000),
                        0.0,
                    ),
                }
                for p in projects
            ],
        )
        cons = list(
            (
                await self.db.execute(
                    select(Consultancy).where(
                        Consultancy.institution_id == self.inst,
                        Consultancy.staff_id == staff_id,
                        (Consultancy.start_on.is_(None)) | (Consultancy.start_on.between(d1, d2)),
                    )
                )
            ).scalars()
        )
        per = float(cats.get("consultancy", {}).get("per_project", 3))
        put("consultancy", [{"id": str(c.id), "title": (c.title or c.client)[:120], "points": per} for c in cons])
        pats = list(
            (
                await self.db.execute(
                    select(Patent).where(
                        Patent.institution_id == self.inst,
                        (Patent.staff_id == staff_id) | Patent.co_inventors.contains([{"staff_id": str(staff_id)}]),
                        (Patent.filed_on.is_(None)) | (Patent.filed_on <= d2),
                    )
                )
            ).scalars()
        )
        pp2 = cats.get("patents", {}).get("points") or {}
        put(
            "patents",
            [
                {"id": str(p.id), "title": p.title[:120], "status": p.status, "points": float(pp2.get(p.status, 0))}
                for p in pats
            ],
        )
        fdps = list(
            (
                await self.db.execute(
                    select(FacultyDevelopment).where(
                        FacultyDevelopment.institution_id == self.inst,
                        FacultyDevelopment.staff_id == staff_id,
                        FacultyDevelopment.from_on.between(d1, d2),
                    )
                )
            ).scalars()
        )
        fp = cats.get("fdp", {}).get("points") or {}
        put(
            "fdp",
            [
                {"id": str(f.id), "title": f.title[:120], "role": f.role, "points": float(fp.get(f.role, 0))}
                for f in fdps
            ],
        )
        awards = list(
            (
                await self.db.execute(
                    select(FacultyAward).where(
                        FacultyAward.institution_id == self.inst,
                        FacultyAward.staff_id == staff_id,
                        FacultyAward.year.between(d1.year, d2.year),
                    )
                )
            ).scalars()
        )
        ap = cats.get("awards", {}).get("points") or {}
        put(
            "awards",
            [{"id": str(a.id), "title": a.title[:120], "points": float(ap.get(a.level or "", 0))} for a in awards],
        )
        evs = (
            await self.db.execute(
                select(func.count()).where(
                    Event.institution_id == self.inst,
                    Event.organiser_staff_id == staff_id,
                    Event.from_on.between(d1, d2),
                )
            )
        ).scalar_one()
        put(
            "co_curricular",
            [
                {
                    "title": "Events organised",
                    "count": int(evs),
                    "points": int(evs) * float(cats.get("co_curricular", {}).get("per_activity", 3)),
                }
            ],
        )
        put("teaching", await self._teaching(staff_id, d2))
        total = round(sum(float(c["points"]) for c in breakdown.values()), 2)
        s = await self.staff_row(staff_id)
        period = f"{d1.isoformat()}..{d2.isoformat()}"
        computed = now_utc()
        prof = (
            await self.db.execute(select(FacultyProfile).where(FacultyProfile.staff_id == staff_id).with_for_update())
        ).scalar_one_or_none()
        if prof is not None:
            prof.api_score, prof.api_updated_at = Decimal(str(min(total, 9999.99))), computed
        m = await self.meta("api", staff_id)
        m[period] = {
            "total": total,
            "breakdown": breakdown,
            "scheme": sch.get("name"),
            "computed_at": computed.isoformat(),
        }
        m["latest"] = period
        await self.put_meta("api", staff_id, m)
        await self._snapshot_index(staff_id, period, total)
        await self.db.flush()
        return ApiScoreOut(
            staff_id=staff_id,
            staff_name=staff_name(s),
            department_id=s.department_id,
            period=period,
            total=total,
            breakdown=breakdown,
            scheme=str(sch.get("name") or "UGC_CAS_2018"),
            computed_at=computed,
        )

    async def _teaching(self, staff_id: uuid.UUID, d2: date) -> list[dict[str, Any]]:
        """Teaching-learning points from the latest Phase 06 appraisal self-assessment (``teaching`` category)."""
        a = (
            await self.db.execute(
                select(Appraisal).where(Appraisal.staff_id == staff_id).order_by(Appraisal.created_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
        sa = a.self_assessment if a is not None else None
        teaching = sa.get("teaching") if isinstance(sa, dict) else None
        if isinstance(teaching, dict):
            pts = sum(float(v) for v in teaching.values() if isinstance(v, int | float))
            return [{"title": "Phase 06 appraisal (teaching-learning)", "points": pts}]
        return []

    async def _snapshot_index(self, staff_id: uuid.UUID, period: str, total: float) -> None:
        row = (
            await self.db.execute(
                select(InstitutionSetting)
                .where(
                    InstitutionSetting.institution_id == self.inst,
                    InstitutionSetting.college_id.is_(None),
                    InstitutionSetting.category == "research",
                    InstitutionSetting.key == "api_snapshots",
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            row = InstitutionSetting(
                institution_id=self.inst,
                college_id=None,
                category="research",
                key="api_snapshots",
                value={},
                value_type="json",
            )
            self.db.add(row)
        v = dict(row.value or {})
        v.setdefault(str(staff_id), {})[period] = total
        row.value = v

    async def compute(
        self, staff_id: uuid.UUID | None, department_id: uuid.UUID | None, d1: date, d2: date
    ) -> list[ApiScoreOut]:
        if d2 < d1:
            raise rule("period_to precedes period_from", "BAD_DATES", 422)
        self.require_writer()
        if staff_id is not None:
            if not (self.cell() or await self.is_mine(staff_id) or await self.in_my_units(staff_id)):
                raise not_found("Staff")
            ids = [staff_id]
        else:
            stmt = select(Staff.id).where(
                Staff.institution_id == self.inst, Staff.staff_category == "teaching", Staff.deleted_at.is_(None)
            )
            if department_id is not None:
                stmt = stmt.where(Staff.department_id == department_id)
            if not self.cell():
                sub = self.staff_scope_subquery()
                if sub is None:
                    raise forbidden("research:manage required for a batch computation")
                stmt = stmt.where(Staff.id.in_(sub))
            ids = [r[0] for r in (await self.db.execute(stmt)).all()]
        out = [await self.compute_one(sid, d1, d2) for sid in ids]
        await self._emit(
            "research.api_computed",
            {"staff_ids": [str(i) for i in ids][:500], "period": f"{d1}..{d2}", "count": len(ids)},
            "institution",
            self.inst,
        )
        for o in out[:200]:
            await self._notify(
                "research.api_updated", [await self.staff_user(o.staff_id)], {"period": o.period, "total": str(o.total)}
            )
        return out

    async def get_score(self, staff_id: uuid.UUID, period: str | None = None) -> ApiScoreOut:
        p = self.principal
        if not (
            self.reader_all()
            or await self.is_mine(staff_id)
            or await self.in_my_units(staff_id)
            or (p is not None and p.has("hr", "view_all") and all_hr(p))
        ):
            raise not_found("API score")
        m = await self.meta("api", staff_id)
        key = period or m.get("latest")
        if not key or key not in m:
            raise not_found("API score")
        snap = m[key]
        s = await self.staff_row(staff_id)
        return ApiScoreOut(
            staff_id=staff_id,
            staff_name=staff_name(s),
            department_id=s.department_id,
            period=key,
            total=float(snap["total"]),
            breakdown=snap["breakdown"],
            scheme=str(snap.get("scheme") or "UGC_CAS_2018"),
            computed_at=snap.get("computed_at"),
        )

    async def rankings(self, department_id: uuid.UUID | None = None) -> list[ApiRankingRow]:
        stmt = (
            select(Staff, FacultyProfile)
            .join(FacultyProfile, FacultyProfile.staff_id == Staff.id)
            .where(Staff.institution_id == self.inst, FacultyProfile.api_score.is_not(None))
        )
        if department_id is not None:
            stmt = stmt.where(Staff.department_id == department_id)
        if not self.reader_all():
            sub = self.staff_scope_subquery()
            if sub is None:
                raise forbidden("Rankings need department or institution research access")
            stmt = stmt.where(Staff.id.in_(sub))
        rows = (await self.db.execute(stmt.order_by(FacultyProfile.api_score.desc()))).all()
        metas = await self.metas("api", [s.id for s, _ in rows]) if rows else {}
        return [
            ApiRankingRow(
                rank=i + 1,
                staff_id=s.id,
                name=staff_name(s) or "",
                department_id=s.department_id,
                total=float(fp.api_score or 0),
                period=str(metas.get(str(s.id), {}).get("latest") or ""),
            )
            for i, (s, fp) in enumerate(rows)
        ]

    # ---- profile ---------------------------------------------------------------------------------------------------------
    async def profile(self, staff_id: uuid.UUID) -> ResearchProfileOut:
        if not await self.can_read_staff(staff_id):
            raise not_found("Research profile")
        s = await self.staff_row(staff_id)
        prof = (
            await self.db.execute(select(FacultyProfile).where(FacultyProfile.staff_id == staff_id))
        ).scalar_one_or_none()
        mine = Publication.authors.contains([{"staff_id": str(staff_id)}]) | (Publication.staff_id == staff_id)
        pubs = list(
            (await self.db.execute(select(Publication).where(Publication.institution_id == self.inst, mine))).scalars()
        )
        by_idx: dict[str, int] = {}
        for p in pubs:
            if p.is_verified:
                by_idx[p.indexing or "none"] = by_idx.get(p.indexing or "none", 0) + 1
        projects = list(
            (
                await self.db.execute(
                    select(ResearchProject).where(
                        ResearchProject.institution_id == self.inst,
                        (ResearchProject.pi_staff_id == staff_id)
                        | ResearchProject.co_pi.contains([{"staff_id": str(staff_id)}]),
                    )
                )
            ).scalars()
        )
        cons = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(Consultancy.amount_paise), 0)).where(Consultancy.staff_id == staff_id)
                )
            ).scalar_one()
            or 0
        )
        pats = list((await self.db.execute(select(Patent.status).where(Patent.staff_id == staff_id))).scalars())
        hours = (
            await self.db.execute(
                select(func.coalesce(func.sum(FacultyDevelopment.hours), 0)).where(
                    FacultyDevelopment.staff_id == staff_id
                )
            )
        ).scalar_one()
        awards = (await self.db.execute(select(func.count()).where(FacultyAward.staff_id == staff_id))).scalar_one()
        return ResearchProfileOut(
            staff_id=staff_id,
            name=staff_name(s),
            department_id=s.department_id,
            orcid=prof.orcid if prof else None,
            scopus_id=prof.scopus_id if prof else None,
            publications=len(pubs),
            verified_publications=sum(1 for p in pubs if p.is_verified),
            by_indexing=by_idx,
            citations=sum(int(p.citations or 0) for p in pubs),
            h_index=h_index([int(p.citations or 0) for p in pubs]),
            projects=len(projects),
            ongoing_projects=sum(1 for p in projects if p.status in ("sanctioned", "ongoing")),
            funding_paise=sum(int(p.sanctioned_paise or 0) for p in projects if p.status != "applied"),
            consultancy_paise=cons,
            patents=len(pats),
            patents_granted=sum(1 for x in pats if x in ("granted", "commercialised")),
            fdp_hours=float(hours or 0),
            awards=int(awards),
            api_score=float(prof.api_score) if prof and prof.api_score is not None else None,
            api_updated_at=prof.api_updated_at if prof else None,
        )

    # ---- stats -------------------------------------------------------------------------------------------------------------
    async def stats(
        self, *, year: int | None = None, department_id: uuid.UUID | None = None, college_id: uuid.UUID | None = None
    ) -> ResearchStats:
        staff_stmt = select(Staff.id, Staff.department_id).where(
            Staff.institution_id == self.inst, Staff.staff_category == "teaching", Staff.deleted_at.is_(None)
        )
        if department_id:
            staff_stmt = staff_stmt.where(Staff.department_id == department_id)
        if college_id:
            staff_stmt = staff_stmt.where(Staff.college_id == college_id)
        if not self.reader_all():
            sub = self.staff_scope_subquery()
            if sub is None:
                raise forbidden("research:view_all required")
            staff_stmt = staff_stmt.where(Staff.id.in_(sub))
        staff_rows = (await self.db.execute(staff_stmt)).all()
        sids = [r[0] for r in staff_rows]
        dept_of = {r[0]: r[1] for r in staff_rows}
        teachers = len(sids)
        pub_stmt = select(Publication).where(
            Publication.institution_id == self.inst,
            Publication.is_verified.is_(True),
            Publication.staff_id.in_(sids or [uuid.uuid4()]),
        )
        if year:
            pub_stmt = pub_stmt.where(Publication.year == year)
        pubs = list((await self.db.execute(pub_stmt)).scalars())
        by_idx: dict[str, int] = {}
        by_dept: dict[str, dict[str, Any]] = {}
        for p in pubs:
            by_idx[p.indexing or "none"] = by_idx.get(p.indexing or "none", 0) + 1
            d = str(dept_of.get(p.staff_id))
            by_dept.setdefault(d, {"department_id": d, "publications": 0, "teachers": 0, "grants_paise": 0})
            by_dept[d]["publications"] += 1
        for sid in sids:
            d = str(dept_of.get(sid))
            by_dept.setdefault(d, {"department_id": d, "publications": 0, "teachers": 0, "grants_paise": 0})
            by_dept[d]["teachers"] += 1
        proj_stmt = select(ResearchProject).where(
            ResearchProject.institution_id == self.inst, ResearchProject.pi_staff_id.in_(sids or [uuid.uuid4()])
        )
        if year:
            proj_stmt = proj_stmt.where(extract("year", ResearchProject.start_on) == year)
        projects = list((await self.db.execute(proj_stmt)).scalars())
        by_status: dict[str, int] = {}
        grants = 0
        for pr in projects:
            by_status[pr.status] = by_status.get(pr.status, 0) + 1
            if pr.status != "applied":
                grants += int(pr.received_paise or 0) or int(pr.sanctioned_paise or 0)
                d = str(dept_of.get(pr.pi_staff_id))
                if d in by_dept:
                    by_dept[d]["grants_paise"] += int(pr.sanctioned_paise or 0)
        cons_stmt = select(func.coalesce(func.sum(Consultancy.amount_paise), 0)).where(
            Consultancy.institution_id == self.inst, Consultancy.staff_id.in_(sids or [uuid.uuid4()])
        )
        if year:
            cons_stmt = cons_stmt.where(extract("year", Consultancy.start_on) == year)
        consultancy = int((await self.db.execute(cons_stmt)).scalar_one() or 0)
        pat_stmt = select(Patent.status, func.count()).where(
            Patent.institution_id == self.inst, Patent.staff_id.in_(sids or [uuid.uuid4()])
        )
        if year:
            pat_stmt = pat_stmt.where(extract("year", Patent.filed_on) == year)
        patents = {k: int(v) for k, v in (await self.db.execute(pat_stmt.group_by(Patent.status))).all()}
        fdp_stmt = select(
            func.count(func.distinct(FacultyDevelopment.staff_id)),
            func.count(FacultyDevelopment.id),
            func.coalesce(func.sum(FacultyDevelopment.hours), 0),
        ).where(FacultyDevelopment.institution_id == self.inst, FacultyDevelopment.staff_id.in_(sids or [uuid.uuid4()]))
        if year:
            fdp_stmt = fdp_stmt.where(extract("year", FacultyDevelopment.from_on) == year)
        participants, records, hours = (await self.db.execute(fdp_stmt)).one()
        mou_rows = list((await self.db.execute(select(Mou).where(Mou.institution_id == self.inst))).scalars())
        functional_q = select(func.count(func.distinct(Collaboration.mou_id))).where(
            Collaboration.institution_id == self.inst, Collaboration.mou_id.is_not(None)
        )
        if year:
            functional_q = functional_q.where(extract("year", Collaboration.from_on) == year)
        functional = int((await self.db.execute(functional_q)).scalar_one())
        startups = int(
            (
                await self.db.execute(select(func.count()).where(IncubationStartup.institution_id == self.inst))
            ).scalar_one()
        )
        per_teacher = round(len(pubs) / teachers, 2) if teachers else 0.0
        indexed = sum(v for k, v in by_idx.items() if k in INDEXED)
        citations = sum(int(p.citations or 0) for p in pubs)
        return ResearchStats(
            year=year,
            teachers=teachers,
            publications=len(pubs),
            publications_by_indexing=by_idx,
            per_teacher=per_teacher,
            grants_amount_paise=grants,
            projects_by_status=by_status,
            consultancy_revenue_paise=consultancy,
            patents=patents,
            fdp={
                "participants": int(participants),
                "records": int(records),
                "hours": float(hours or 0),
                "participation_pct": round(100 * int(participants) / teachers, 1) if teachers else 0.0,
            },
            mous={
                "total": len(mou_rows),
                "active": sum(1 for m in mou_rows if m.status == "active"),
                "functional": functional,
            },
            startups=startups,
            by_department=sorted(by_dept.values(), key=lambda r: -r["publications"]),
            nirf_rp={
                "PU": per_teacher,
                "QP": {
                    "indexed_publications": indexed,
                    "citations": citations,
                    "citations_per_paper": round(citations / len(pubs), 2) if pubs else 0.0,
                },
                "IPR": {
                    "published": patents.get("published", 0),
                    "granted": patents.get("granted", 0) + patents.get("commercialised", 0),
                },
                "FPPP": {"sponsored_research_paise": grants, "consultancy_paise": consultancy},
            },
        )

    async def publish(self, year: int) -> ResearchStats:
        """NAAC 3.x / NIRF RP metric values for Phase 32 (``metric_values``)."""
        s = await self.stats(year=year)
        await self._emit(
            "research.stats_published",
            {
                "year": year,
                "metrics": {
                    "research.publications_per_teacher": s.per_teacher,
                    "research.grants_amount": s.grants_amount_paise,
                    "research.consultancy_revenue": s.consultancy_revenue_paise,
                    "research.patents": sum(s.patents.values()),
                    "research.fdp_participation": s.fdp.get("participation_pct", 0),
                    "nirf.pu": s.nirf_rp["PU"],
                    "nirf.qp": s.nirf_rp["QP"]["indexed_publications"],
                    "nirf.ipr": s.nirf_rp["IPR"]["granted"],
                    "nirf.fppp": s.grants_amount_paise + s.consultancy_revenue_paise,
                },
            },
            "institution",
            self.inst,
        )
        return s

    # ---- exports ----------------------------------------------------------------------------------------------------------
    async def report_rows(self, kind: str, year: int | None = None) -> list[dict[str, Any]]:
        if kind in ("publications", "nirf_rp"):
            stmt = select(Publication).where(Publication.institution_id == self.inst)
            if year:
                stmt = stmt.where(Publication.year == year)
            staff = {
                s.id: s
                for s in (await self.db.execute(select(Staff).where(Staff.institution_id == self.inst))).scalars()
            }
            return [
                {
                    "title": p.title,
                    "venue": p.venue,
                    "year": p.year,
                    "doi": p.doi,
                    "indexing": p.indexing,
                    "impact_factor": float(p.impact_factor) if p.impact_factor is not None else None,
                    "faculty": staff_name(staff.get(p.staff_id)) if p.staff_id else None,
                    "citations": p.citations,
                    "verified": p.is_verified,
                    "evidence_url": p.evidence_url,
                }
                for p in (await self.db.execute(stmt)).scalars()
            ]
        model: Any = {
            "projects": ResearchProject,
            "consultancy": Consultancy,
            "patents": Patent,
            "fdp": FacultyDevelopment,
            "mous": Mou,
        }.get(kind)
        if model is None:
            raise rule(f"Unknown report {kind}", "UNKNOWN_REPORT", 422)
        rows = (await self.db.execute(select(model).where(model.institution_id == self.inst))).scalars()
        cols = [c.name for c in model.__table__.columns if c.name not in ("institution_id",)]
        return [{c: (str(getattr(r, c)) if getattr(r, c) is not None else None) for c in cols} for r in rows]

    async def evidence_pack(self, criterion: str, year: int | None) -> bytes:
        rows = [r for r in await self.report_rows("publications", year) if r["verified"]]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            s = io.StringIO()
            w = csv.DictWriter(s, fieldnames=list(rows[0].keys()) if rows else ["title"])
            w.writeheader()
            for r in rows:
                w.writerow(r)
            z.writestr(f"NAAC_{criterion}_publications.csv", s.getvalue())
            z.writestr(
                "README.txt",
                f"NAAC criterion {criterion} evidence — {len(rows)} verified publication(s)"
                f"{f' of {year}' if year else ''}. Evidence links are listed per row.\n",
            )
        return buf.getvalue()


def all_hr(p: Any) -> bool:
    return any(t == "institution" for t, _ in getattr(p, "scopes", []))
