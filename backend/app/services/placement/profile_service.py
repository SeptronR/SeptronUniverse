"""Student placement profiles — Prompts/28 §28.6 ``profile_service`` ({placement.core}; render {placement.resume_builder}).

Academics are computed read-only (CGPA, active / history backlogs, attendance, 10th / 12th — the eligibility engine's
facts) together with Phase 27 **verified** ``student_achievements``, internships and training scores; the student edits
skills, resume sections (``resume_json``), consent (``consent_share_profile`` — DPDP, required for recruiter
visibility) and, only without an applicant record, 10th / 12th values (stored unverified under
``resume_json.academics_entered``). The resume renders through Phase 26 ``documents.render('custom',
'placement_profile', id)`` with one of the ``resume_*`` layouts (versions kept in ``resume_json.versions``). Opt-out
with reason (``higher_studies`` details feed NAAC 5.2.2 / NIRF) sets ``placement_status = opted_out``. Officers list
profiles with ScopeTabs; the auditor sees contacts masked; completeness is a 0–100 score.
"""

import uuid
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError
from app.enums.placement import RESUME_SECTIONS, RESUME_TEMPLATES
from app.models.placement import Internship, StudentPlacementProfile, TrainingAttendance
from app.models.post_result import StudentAchievement
from app.models.students import Student, StudentProgramEnrollment
from app.schemas.placement import PlcOptOut, PlcProfileIn, PlcProfileOut, PlcResumeRender
from app.services.documents.render_service import RenderService, register_resolver
from app.services.placement.common import PlacementBase, forbidden, is_auditor, not_found, rule
from app.services.placement.eligibility_service import EligibilityService, PolicyService


def _mask(v: str | None) -> str | None:
    if not v:
        return v
    return v[:2] + "•" * max(len(v) - 4, 2) + v[-2:]


class ProfileService(PlacementBase):
    async def achievements(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict[str, Any]]]:
        out: dict[uuid.UUID, list[dict[str, Any]]] = {i: [] for i in ids}
        if not ids:
            return out
        for a in (
            await self.db.execute(
                select(StudentAchievement)
                .where(
                    StudentAchievement.student_program_enrollment_id.in_(ids),
                    StudentAchievement.verified_at.is_not(None),
                )
                .order_by(StudentAchievement.held_on.desc().nullslast())
            )
        ).scalars():
            out[a.student_program_enrollment_id].append(
                {
                    "category": a.category,
                    "title": a.title,
                    "level": a.level,
                    "position": a.position,
                    "held_on": a.held_on.isoformat() if a.held_on else None,
                }
            )
        return out

    async def outs(self, rows: list[StudentPlacementProfile], *, detail: bool = False) -> list[PlcProfileOut]:
        ids = [p.student_program_enrollment_id for p in rows]
        enrols = {
            e.id: e
            for e in (
                await self.db.execute(
                    select(StudentProgramEnrollment).where(StudentProgramEnrollment.id.in_(ids or [uuid.uuid4()]))
                )
            ).scalars()
        }
        students = {
            s.id: s
            for s in (
                await self.db.execute(
                    select(Student).where(Student.id.in_([e.student_id for e in enrols.values()] or [uuid.uuid4()]))
                )
            ).scalars()
        }
        facts = await EligibilityService(self.db, self.principal, self.request, self.inst).facts(list(enrols.values()))
        ach = await self.achievements(ids)
        depts = await self.department_codes([e.department_id for e in enrols.values()])
        bl = await self.metas("blacklist", [str(i) for i in ids])
        training: dict[uuid.UUID, dict[str, Any]] = {}
        for eid, n, avg in (
            await self.db.execute(
                select(
                    TrainingAttendance.student_program_enrollment_id,
                    func.sum(TrainingAttendance.sessions_attended),
                    func.avg(TrainingAttendance.score),
                )
                .where(TrainingAttendance.student_program_enrollment_id.in_(ids or [uuid.uuid4()]))
                .group_by(TrainingAttendance.student_program_enrollment_id)
            )
        ).all():
            training[eid] = {
                "sessions_attended": int(n or 0),
                "readiness_score": round(float(avg), 1) if avg is not None else None,
            }
        interns: dict[uuid.UUID, list[dict[str, Any]]] = {i: [] for i in ids}
        if detail:
            for it in (
                await self.db.execute(
                    select(Internship).where(Internship.student_program_enrollment_id.in_(ids or [uuid.uuid4()]))
                )
            ).scalars():
                interns[it.student_program_enrollment_id].append(
                    {
                        "id": str(it.id),
                        "company": it.company_name,
                        "role": it.role,
                        "from_on": it.from_on.isoformat(),
                        "to_on": it.to_on.isoformat() if it.to_on else None,
                        "status": it.status,
                    }
                )
        mask = is_auditor(self.principal)
        out = []
        for p in rows:
            e = enrols.get(p.student_program_enrollment_id)
            s = students.get(e.student_id) if e else None
            f = facts.get(p.student_program_enrollment_id, {})
            mine = s is not None and s.user_id is not None and s.user_id == self.actor_id
            o = PlcProfileOut(
                id=p.id,
                student_program_enrollment_id=p.student_program_enrollment_id,
                student_name=s.full_name if s else None,
                registration_number=s.registration_number if s else None,
                program_id=e.program_id if e else None,
                batch_id=e.batch_id if e else None,
                department_code=depts.get(e.department_id) if e else None,
                email=(_mask(s.email) if mask and not mine else s.email) if s else None,
                phone=(_mask(s.phone) if mask and not mine else s.phone) if s else None,
                resume_url=p.resume_url,
                resume_json=p.resume_json if detail else None,
                skills=list(p.skills or []),
                is_opted_out=p.is_opted_out,
                opt_out_reason=p.opt_out_reason,
                higher_studies=p.higher_studies,
                placement_status=p.placement_status,
                is_blacklisted=p.is_blacklisted,
                blacklist_reason=p.blacklist_reason,
                blacklist_until=(bl.get(str(p.student_program_enrollment_id)) or {}).get("until"),
                consent_share_profile=p.consent_share_profile,
                academics={
                    k: f.get(k)
                    for k in (
                        "cgpa",
                        "active_backlogs",
                        "history_backlogs",
                        "attendance_pct",
                        "pct_10",
                        "pct_12",
                        "pct_verified",
                        "gap_years",
                    )
                },
                achievements=ach.get(p.student_program_enrollment_id, []),
                internships=interns.get(p.student_program_enrollment_id, []),
                training=training.get(p.student_program_enrollment_id, {}),
            )
            o.completeness = self.completeness(p, o)
            out.append(o)
        return out

    @staticmethod
    def completeness(p: StudentPlacementProfile, o: PlcProfileOut) -> int:
        rj = p.resume_json or {}
        checks = [
            bool(p.skills),
            bool(p.resume_url or rj.get("versions")),
            bool(rj.get("summary")),
            bool(rj.get("education")),
            bool(rj.get("projects")),
            bool(o.internships or rj.get("internships")),
            bool(o.achievements or rj.get("achievements")),
            bool(rj.get("certifications")),
            bool(o.email and o.phone),
            o.academics.get("pct_12") is not None,
        ]
        return round(100 * sum(checks) / len(checks))

    # ---- self -------------------------------------------------------------------------------------------------------
    async def me(self) -> PlcProfileOut:
        e = await self.require_my_enrollment()
        p = await self.profile_of(e.id)
        return (await self.outs([p], detail=True))[0]

    async def update_me(self, body: PlcProfileIn) -> PlcProfileOut:
        e = await self.require_my_enrollment()
        p = await self.profile_of(e.id, lock=True)
        rj = dict(p.resume_json or {})
        if body.resume_json is not None:
            for k, v in body.resume_json.items():
                if k in RESUME_SECTIONS:
                    rj[k] = v
        if body.pct_10 is not None or body.pct_12 is not None or body.year_12 is not None:
            facts = (await EligibilityService(self.db, self.principal, self.request, self.inst).facts([e]))[e.id]
            if facts.get("pct_verified") and (facts.get("pct_10") is not None or facts.get("pct_12") is not None):
                raise rule("10th / 12th come from the verified admission record", "ACADEMICS_READ_ONLY", status=422)
            entered = dict(rj.get("academics_entered") or {})
            entered.update(
                {
                    k: v
                    for k, v in (("pct_10", body.pct_10), ("pct_12", body.pct_12), ("year_12", body.year_12))
                    if v is not None
                }
            )
            rj["academics_entered"] = entered
        p.resume_json = rj
        if body.resume_url is not None:
            p.resume_url = body.resume_url
        if body.skills is not None:
            p.skills = sorted({s.strip() for s in body.skills if s and s.strip()})
        if body.consent_share_profile is not None:
            p.consent_share_profile = body.consent_share_profile
        await self.db.flush()
        await self._audit(
            "update", "student_placement_profile", p.id, None, body.model_dump(mode="json", exclude_unset=True)
        )
        await self._emit("placement.profile_updated", {"enrollment_id": str(e.id)}, "student_placement_profile", p.id)
        return (await self.outs([p], detail=True))[0]

    async def render_resume(self, body: PlcResumeRender) -> dict[str, Any]:
        await self.require_feature("placement.resume_builder")
        e = await self.require_my_enrollment()
        p = await self.profile_of(e.id, lock=True)
        try:
            res = await RenderService(self.db, self.principal, self.request, self.inst).render(
                "custom",
                "placement_profile",
                p.id,
                allow_multiple=True,
                variables_override={"title": "Resume", "template_key": body.template_key},
            )
        except APIError:
            raise
        rj = dict(p.resume_json or {})
        versions = list(rj.get("versions") or [])
        versions.append(
            {"document_id": str(res.issued_document_id), "template_key": body.template_key, "url": res.pdf_url}
        )
        rj["versions"] = versions[-10:]
        p.resume_json = rj
        if res.pdf_url:
            p.resume_url = res.pdf_url
        await self.db.flush()
        await self._emit(
            "placement.profile_updated", {"enrollment_id": str(e.id), "resume": True}, "student_placement_profile", p.id
        )
        return {"document_id": str(res.issued_document_id), "pdf_url": res.pdf_url, "template_key": body.template_key}

    async def opt_out(self, body: PlcOptOut) -> PlcProfileOut:
        e = await self.require_my_enrollment()
        p = await self.profile_of(e.id, lock=True)
        pol = await PolicyService(self.db, self.principal, self.request, self.inst).effective(e.batch_id, e.program_id)
        if body.opt_out:
            if not pol.opt_out_allowed:
                raise rule("The placement policy does not allow opting out", "OPT_OUT_NOT_ALLOWED")
            if body.reason is None:
                raise rule("Opt-out reason required", "REASON_REQUIRED", status=422)
            if body.reason == "higher_studies" and body.higher_studies is None:
                raise rule("Higher studies details required", "HIGHER_STUDIES_REQUIRED", status=422)
            p.is_opted_out, p.opt_out_reason = True, body.reason
            p.higher_studies = body.higher_studies.model_dump() if body.higher_studies else None
            p.placement_status = "opted_out"
            await self._emit(
                "placement.opted_out",
                {"enrollment_id": str(e.id), "reason": body.reason},
                "student_placement_profile",
                p.id,
            )
        else:
            p.is_opted_out, p.opt_out_reason = False, None
            from app.services.placement.offer_service import OfferService

            await OfferService(self.db, self.principal, self.request, self.inst)._recompute_status(e.id)
        await self.db.flush()
        await self._audit("opt_out", "student_placement_profile", p.id, None, body.model_dump(mode="json"))
        return (await self.outs([p], detail=True))[0]

    # ---- officers / readers -----------------------------------------------------------------------------------------
    async def list_profiles(
        self,
        batch_id: uuid.UUID | None,
        status: str | None,
        department_id: uuid.UUID | None,
        scope: str | None,
        q: str | None = None,
    ) -> list[PlcProfileOut]:
        if not (self.officer() or self.reader() or self.can("placement", "view_all")):
            raise forbidden()
        stmt = (
            select(StudentPlacementProfile)
            .join(
                StudentProgramEnrollment,
                StudentProgramEnrollment.id == StudentPlacementProfile.student_program_enrollment_id,
            )
            .where(
                StudentPlacementProfile.institution_id == self.inst,
                await self.enrolment_predicate(StudentPlacementProfile.student_program_enrollment_id, scope),
            )
        )
        if batch_id:
            stmt = stmt.where(StudentProgramEnrollment.batch_id == batch_id)
        if department_id:
            stmt = stmt.where(StudentProgramEnrollment.department_id == department_id)
        if status == "blacklisted":
            stmt = stmt.where(StudentPlacementProfile.is_blacklisted.is_(True))
        elif status:
            stmt = stmt.where(StudentPlacementProfile.placement_status == status)
        if q:
            stmt = stmt.join(Student, Student.id == StudentProgramEnrollment.student_id).where(
                Student.registration_number.ilike(f"%{q}%") | Student.first_name.ilike(f"%{q}%")
            )
        rows = list((await self.db.execute(stmt.limit(3000))).scalars())
        return await self.outs(rows)

    async def get(self, enrollment_id: uuid.UUID) -> PlcProfileOut:
        stmt = select(StudentPlacementProfile).where(
            StudentPlacementProfile.student_program_enrollment_id == enrollment_id,
            StudentPlacementProfile.institution_id == self.inst,
            await self.enrolment_predicate(StudentPlacementProfile.student_program_enrollment_id),
        )
        p = (await self.db.execute(stmt)).scalar_one_or_none()
        if p is None:
            raise not_found("Profile")
        return (await self.outs([p], detail=True))[0]

    async def ensure_profiles(self, enrollment_ids: list[uuid.UUID]) -> int:
        have = {
            r[0]
            for r in (
                await self.db.execute(
                    select(StudentPlacementProfile.student_program_enrollment_id).where(
                        StudentPlacementProfile.student_program_enrollment_id.in_(enrollment_ids or [uuid.uuid4()])
                    )
                )
            ).all()
        }
        n = 0
        for eid in enrollment_ids:
            if eid not in have:
                self.db.add(StudentPlacementProfile(institution_id=self.inst, student_program_enrollment_id=eid))
                n += 1
        await self.db.flush()
        return n


TEMPLATE_NAMES = {t["key"]: t["name"] for t in RESUME_TEMPLATES}


@register_resolver("placement_profile")
async def _profile_ctx(svc: RenderService, pid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    p = (await svc.db.execute(select(StudentPlacementProfile).where(StudentPlacementProfile.id == pid))).scalar_one()
    ctx, ptype, sid = await svc.enrolment_ctx(p.student_program_enrollment_id)
    rj = p.resume_json or {}
    parts: list[str] = []
    for sec in RESUME_SECTIONS:
        val = rj.get(sec) if sec != "skills" else (p.skills or rj.get("skills"))
        if not val:
            continue
        if isinstance(val, list):
            items = [", ".join(f"{v}" for v in x.values() if v) if isinstance(x, dict) else str(x) for x in val]
            parts.append(f"{sec.replace('_', ' ').title()}: " + "; ".join(items))
        else:
            parts.append(f"{sec.replace('_', ' ').title()}: {val}")
    ach = (
        await ProfileService(svc.db, svc.principal, svc.request, svc.inst).achievements(
            [p.student_program_enrollment_id]
        )
    )[p.student_program_enrollment_id]
    if ach:
        parts.append(
            "Verified achievements: " + "; ".join(f"{a['title']} ({a.get('level') or a['category']})" for a in ach)
        )
    ctx["resume"] = {"sections": rj, "skills": p.skills or []}
    ctx["title"] = "Resume"
    ctx["body"] = " | ".join(parts) or "Resume"
    return ctx, ptype, sid
