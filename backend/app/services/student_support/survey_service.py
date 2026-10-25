"""Surveys — Prompts/27 §27.6 ``survey_service`` ({surveys.core}, {surveys.sss}).

1. Surveys by type with question templates (course feedback, faculty, SSS — the NAAC 20 + 1 items, hostel, parent;
   programme exit / alumni / employer with PO tags); targets are derived per respondent (course / course exit → each
   offering the student is registered in that term, faculty → each teacher of those offerings, hostel → the
   resident's hostel, programme surveys → the programme, institution / SSS / parent → one institution target);
   ``audience_rules`` narrow the students (``department_ids`` / ``program_ids`` / ``batch_ids``). Respondent identity
   is stored only as ``respondent_hash`` = HMAC(user_id, survey_id, secret) — UNIQUE (survey, hash, target) → 409.
   Reminders go to expected respondents whose hash has no row for a target. Alumni / employer respond through
   single-use tokenised links (``<institution hex>.<secret>``; only the hash of the secret is kept).
2. Analytics per target: n, per-question mean / distribution, overall, PII-scrubbed comments, CO / PO means; faculty
   read their own offerings only once ``min_responses`` (5) responses exist (403 ``MIN_RESPONSES``); department
   comparison; SSS score (mean of the 20 item means on the 0–4 scale) → ``surveys.sss_score`` event for Phase 32;
   ``analyse`` emits ``obe.indirect_survey_scores`` (Phase 17 also reads the responses directly).
"""

import csv
import io
import re
import secrets
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.enums.student_support import EXTERNAL_SURVEYS, SURVEY_TARGET_TYPE, SURVEY_TEMPLATES
from app.models.academic import Program
from app.models.curriculum import Course
from app.models.hostel import Hostel, HostelAllocation
from app.models.hr import Staff
from app.models.obe_attainment import FeedbackResponse, FeedbackSurvey
from app.models.offerings import CourseOffering, CourseOfferingFaculty
from app.models.registration import CourseRegistration, CourseRegistrationItem
from app.models.students import Student, StudentGuardian, StudentProgramEnrollment
from app.schemas.surveys import (
    SvyAnalytics,
    SvyCompare,
    SvyCompareRow,
    SvyCompletion,
    SvyCreate,
    SvyExternalLinks,
    SvyExternalLinksOut,
    SvyForm,
    SvyOut,
    SvyPending,
    SvyQuestionStats,
    SvyRespond,
    SvyRespondResult,
    SvySssScore,
    SvyTarget,
    SvyUpdate,
)
from app.services.student_support.common import (
    SupportBase,
    all_access,
    forbidden,
    module_reader,
    not_found,
    now_utc,
    respondent_hash,
    rule,
    scope_ids,
    sha,
)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"\+?\d[\d\s-]{7,}\d")
_CAPS_NAME = re.compile(r"\b(Mr|Mrs|Ms|Dr|Prof)\.?\s+[A-Z][a-z]+(\s+[A-Z][a-z]+)?")


def scrub(text: str) -> str:
    text = _EMAIL.sub("[email]", text)
    text = _PHONE.sub("[phone]", text)
    return _CAPS_NAME.sub("[name]", text)


def _questions(s: FeedbackSurvey) -> list[dict[str, Any]]:
    q = s.questions
    if isinstance(q, dict):
        q = q.get("questions") or []
    return [x for x in (q or []) if isinstance(x, dict)]


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class SurveyService(SupportBase):
    audit_module = "surveys"
    module = "surveys"

    # ---- helpers --------------------------------------------------------------------------------------------------------
    def rules(self, s: FeedbackSurvey) -> dict[str, Any]:
        return dict(s.audience_rules or {})

    def min_responses(self, s: FeedbackSurvey) -> int:
        return int(self.rules(s).get("min_responses") or 5)

    async def _survey(self, sid: uuid.UUID, *, lock: bool = False) -> FeedbackSurvey:
        stmt = select(FeedbackSurvey).where(FeedbackSurvey.id == sid, FeedbackSurvey.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        s = (await self.db.execute(stmt)).scalar_one_or_none()
        if s is None:
            raise not_found("Survey")
        return s

    def manager(self) -> bool:
        return self.can("surveys", "manage")

    async def outs(self, rows: list[FeedbackSurvey], *, completion: bool = False) -> list[SvyOut]:
        counts = {
            k: int(v)
            for k, v in (
                await self.db.execute(
                    select(FeedbackResponse.survey_id, func.count())
                    .where(FeedbackResponse.survey_id.in_([r.id for r in rows] or [uuid.uuid4()]))
                    .group_by(FeedbackResponse.survey_id)
                )
            ).all()
        }
        out = []
        for r in rows:
            ru = self.rules(r)
            o = SvyOut(
                id=r.id,
                survey_type=r.survey_type,
                term_id=r.term_id,
                college_id=r.college_id,
                title=r.title,
                questions=_questions(r),
                audience_rules={
                    k: v for k, v in ru.items() if k not in ("targets", "reminder_days", "min_responses", "external")
                },
                targets=ru.get("targets") or {},
                is_anonymous=r.is_anonymous,
                opens_at=r.opens_at,
                closes_at=r.closes_at,
                status=r.status,
                reminder_days=list(ru.get("reminder_days") or []),
                min_responses=int(ru.get("min_responses") or 5),
                responses=counts.get(r.id, 0),
                created_at=r.created_at,
            )
            if completion:
                exp = await self._expected_pairs(r)
                o.expected = len(exp) if exp is not None else None
                o.completion_pct = round(100.0 * o.responses / len(exp), 1) if exp else None
            out.append(o)
        return out

    # ---- CRUD -----------------------------------------------------------------------------------------------------------
    async def create(self, body: SvyCreate) -> SvyOut:
        self.require_writer()
        if not self.manager():
            raise forbidden("surveys:manage required")
        if body.survey_type == "sss":
            await self.require_feature("surveys.sss")
        questions = [q.model_dump(exclude_none=True) for q in body.questions or []]
        if not questions and body.use_template:
            tpl = await self.setting("surveys", "sss_template") if body.survey_type == "sss" else None
            questions = list(tpl) if isinstance(tpl, list) and tpl else list(SURVEY_TEMPLATES.get(body.survey_type, []))
        if not questions:
            raise rule("A survey needs at least one question", "NO_QUESTIONS")
        rules = dict(body.audience_rules)
        rules.update(
            {
                "targets": body.targets.model_dump(mode="json"),
                "reminder_days": body.reminder_days,
                "min_responses": body.min_responses or await self.int_setting("surveys", "min_responses", 5),
            }
        )
        s = FeedbackSurvey(
            institution_id=self.inst,
            college_id=body.college_id,
            survey_type=body.survey_type,
            term_id=body.term_id,
            title=body.title,
            questions=questions,
            audience_rules=rules,
            is_anonymous=body.is_anonymous,
            opens_at=body.opens_at,
            closes_at=body.closes_at,
            status="draft",
            created_by=self.actor_id,
        )
        if s.survey_type in ("course", "course_exit", "faculty") and s.term_id is None:
            term = await self.current_term(body.college_id)
            s.term_id = term.id if term else None
        self.db.add(s)
        await self.db.flush()
        await self._audit("create", "feedback_survey", s.id, None, {"type": s.survey_type})
        return (await self.outs([s]))[0]

    async def update(self, sid: uuid.UUID, body: SvyUpdate) -> SvyOut:
        self.require_writer()
        if not self.manager():
            raise forbidden("surveys:manage required")
        s = await self._survey(sid, lock=True)
        if s.status not in ("draft", "open"):
            raise rule("Only a draft or open survey is edited", "BAD_STATUS")
        data = body.model_dump(exclude_unset=True)
        if "questions" in data and s.status != "draft":
            raise rule("Questions are frozen once the survey opens", "QUESTIONS_FROZEN")
        rules = self.rules(s)
        if body.title is not None:
            s.title = body.title
        if body.questions is not None:
            s.questions = [q.model_dump(exclude_none=True) for q in body.questions]
        if body.audience_rules is not None:
            rules.update(body.audience_rules)
        if body.targets is not None:
            rules["targets"] = body.targets.model_dump(mode="json")
        if body.reminder_days is not None:
            rules["reminder_days"] = body.reminder_days
        if body.min_responses is not None:
            rules["min_responses"] = body.min_responses
        s.audience_rules = rules
        if "opens_at" in data:
            s.opens_at = body.opens_at
        if "closes_at" in data:
            s.closes_at = body.closes_at
        await self.db.flush()
        return (await self.outs([s]))[0]

    async def list_surveys(self, status: str | None, survey_type: str | None) -> list[SvyOut]:
        stmt = select(FeedbackSurvey).where(FeedbackSurvey.institution_id == self.inst)
        if (
            not (all_access(self.principal, self.module) or self.manager())
            and scope_ids(self.principal, "college")
            and module_reader(self.principal, self.module)
        ):
            stmt = stmt.where(
                or_(
                    FeedbackSurvey.college_id.is_(None),
                    FeedbackSurvey.college_id.in_(scope_ids(self.principal, "college")),
                )
            )
        if status:
            stmt = stmt.where(FeedbackSurvey.status == status)
        if survey_type:
            stmt = stmt.where(FeedbackSurvey.survey_type == survey_type)
        rows = (await self.db.execute(stmt.order_by(FeedbackSurvey.created_at.desc()).limit(300))).scalars().all()
        return await self.outs(list(rows))

    async def get(self, sid: uuid.UUID) -> SvyOut:
        return (await self.outs([await self._survey(sid)], completion=True))[0]

    async def transition(self, sid: uuid.UUID, action: str) -> SvyOut:
        self.require_writer()
        if not self.manager():
            raise forbidden("surveys:manage required")
        s = await self._survey(sid, lock=True)
        allowed = {"open": ("draft", "closed"), "close": ("open",), "analyse": ("closed", "open")}
        if s.status not in allowed[action]:
            raise rule(f"A {s.status} survey cannot {action}", "BAD_STATUS")
        if action == "open":
            s.status = "open"
            s.opens_at = s.opens_at or now_utc()
            await self.db.flush()
            await self._emit("survey.opened", {"survey_id": str(s.id), "type": s.survey_type}, "feedback_survey", s.id)
            await self._notify_audience(s, "survey.open")
        elif action == "close":
            s.status = "closed"
            s.closes_at = min(s.closes_at or now_utc(), now_utc())
            await self.db.flush()
            await self._emit("survey.closed", {"survey_id": str(s.id)}, "feedback_survey", s.id)
        else:
            if s.status == "open":
                s.closes_at = now_utc()
            s.status = "analysed"
            await self.db.flush()
            await self._obe_feed(s)
            await self._emit("survey.analysed", {"survey_id": str(s.id)}, "feedback_survey", s.id)
        await self._audit(action, "feedback_survey", s.id, None, {"status": s.status})
        return (await self.outs([s]))[0]

    # ---- audience / targets ----------------------------------------------------------------------------------------------
    async def _audience_students(
        self, s: FeedbackSurvey
    ) -> list[tuple[uuid.UUID, uuid.UUID, StudentProgramEnrollment]]:
        """``[(user_id, enrolment id, enrolment)]`` of the student audience."""
        ru = self.rules(s)
        stmt = (
            select(Student.user_id, StudentProgramEnrollment)
            .join(Student, Student.id == StudentProgramEnrollment.student_id)
            .where(
                StudentProgramEnrollment.institution_id == self.inst,
                StudentProgramEnrollment.status == "active",
                Student.user_id.is_not(None),
            )
        )
        if s.college_id:
            stmt = stmt.where(StudentProgramEnrollment.college_id == s.college_id)
        for key, col in (
            ("department_ids", StudentProgramEnrollment.department_id),
            ("program_ids", StudentProgramEnrollment.program_id),
            ("batch_ids", StudentProgramEnrollment.batch_id),
        ):
            vals = ru.get(key)
            if vals:
                stmt = stmt.where(col.in_([uuid.UUID(str(v)) for v in vals]))
        return [(u, e.id, e) for u, e in (await self.db.execute(stmt)).all()]

    async def _offerings_of(
        self, enrol_ids: list[uuid.UUID], term_id: uuid.UUID | None
    ) -> dict[uuid.UUID, set[uuid.UUID]]:
        if not enrol_ids:
            return {}
        stmt = (
            select(CourseRegistration.student_program_enrollment_id, CourseRegistrationItem.offering_id)
            .join(CourseRegistrationItem, CourseRegistrationItem.registration_id == CourseRegistration.id)
            .where(
                CourseRegistration.student_program_enrollment_id.in_(enrol_ids),
                CourseRegistrationItem.status.not_in(("dropped", "withdrawn")),
            )
        )
        if term_id:
            stmt = stmt.where(CourseRegistration.term_id == term_id)
        out: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
        for eid, oid in (await self.db.execute(stmt)).all():
            out[eid].add(oid)
        return out

    async def _targets_for(
        self, s: FeedbackSurvey, enrolments: list[StudentProgramEnrollment]
    ) -> dict[uuid.UUID, list[tuple[str, uuid.UUID | None]]]:
        """Targets per enrolment for the survey type (auto targets, optionally limited to ``targets.ids``)."""
        ttype = SURVEY_TARGET_TYPE.get(s.survey_type, "institution")
        tcfg = self.rules(s).get("targets") or {}
        only = {uuid.UUID(str(x)) for x in (tcfg.get("ids") or [])}
        ids = [e.id for e in enrolments]
        out: dict[uuid.UUID, list[tuple[str, uuid.UUID | None]]] = {}
        if ttype in ("offering", "staff"):
            offs = await self._offerings_of(ids, s.term_id)
            staff_of: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
            if ttype == "staff":
                all_offs = {o for v in offs.values() for o in v}
                for oid, sid in (
                    await self.db.execute(
                        select(CourseOfferingFaculty.offering_id, CourseOfferingFaculty.staff_id).where(
                            CourseOfferingFaculty.offering_id.in_(all_offs or [uuid.uuid4()])
                        )
                    )
                ).all():
                    staff_of[oid].add(sid)
            for e in enrolments:
                if ttype == "offering":
                    tg: set[uuid.UUID] = set(offs.get(e.id, set()))
                else:
                    tg = {sid for o in offs.get(e.id, set()) for sid in staff_of.get(o, set())}
                if only:
                    tg &= only
                out[e.id] = [(ttype, t) for t in sorted(tg, key=str)]
        elif ttype == "hostel":
            alloc: dict[uuid.UUID, uuid.UUID] = dict(
                (
                    await self.db.execute(
                        select(HostelAllocation.student_program_enrollment_id, HostelAllocation.hostel_id).where(
                            HostelAllocation.student_program_enrollment_id.in_(ids or [uuid.uuid4()]),
                            HostelAllocation.status == "active",
                        )
                    )
                )
                .tuples()
                .all()
            )
            for e in enrolments:
                h = alloc.get(e.id)
                out[e.id] = [("hostel", h)] if h and (not only or h in only) else []
        elif ttype == "program":
            for e in enrolments:
                out[e.id] = [("program", e.program_id)] if not only or e.program_id in only else []
        else:
            for e in enrolments:
                out[e.id] = [("institution", None)]
        return out

    async def _expected_pairs(self, s: FeedbackSurvey) -> list[tuple[uuid.UUID, str, uuid.UUID | None]] | None:
        """``[(user_id, target_type, target_id)]`` of the expected responses (None for external surveys)."""
        if s.survey_type in EXTERNAL_SURVEYS:
            return None
        if s.survey_type == "parent":
            rows = await self._audience_students(s)
            guardians = (
                await self.db.execute(
                    select(StudentGuardian.user_id)
                    .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == StudentGuardian.student_id)
                    .where(
                        StudentProgramEnrollment.id.in_([eid for _, eid, _ in rows] or [uuid.uuid4()]),
                        StudentGuardian.user_id.is_not(None),
                    )
                    .distinct()
                )
            ).all()
            return [(g[0], "institution", None) for g in guardians]
        rows = await self._audience_students(s)
        targets = await self._targets_for(s, [e for _, _, e in rows])
        return [(u, tt, tid) for u, eid, _ in rows for tt, tid in targets.get(eid, [])]

    async def _my_targets(self, s: FeedbackSurvey) -> list[tuple[str, uuid.UUID | None]]:
        if self.actor_id is None:
            return []
        if s.survey_type == "parent":
            return [("institution", None)] if await self.ward_enrollment_ids() else []
        if s.survey_type in EXTERNAL_SURVEYS:
            return []
        e = await self.my_enrollment()
        if e is None:
            if s.survey_type in ("institution",) and await self.my_staff_id():
                return [("institution", None)]
            return []
        rows = [r for r in await self._audience_students(s) if r[1] == e.id]
        if not rows:
            return []
        return (await self._targets_for(s, [e])).get(e.id, [])

    async def _labels(self, pairs: list[tuple[str, uuid.UUID | None]]) -> dict[uuid.UUID, str]:
        out: dict[uuid.UUID, str] = {}
        offs = [t for tt, t in pairs if tt == "offering" and t]
        if offs:
            for oid, code, title, sec in (
                await self.db.execute(
                    select(CourseOffering.id, Course.code, Course.title, CourseOffering.section_code)
                    .join(Course, Course.id == CourseOffering.course_id)
                    .where(CourseOffering.id.in_(offs))
                )
            ).all():
                out[oid] = f"{code} {title} ({sec})"
        staff = [t for tt, t in pairs if tt == "staff" and t]
        if staff:
            for k, v in (await self.staff_cards(staff)).items():
                out[k] = v.get("name") or ""
        progs = [t for tt, t in pairs if tt == "program" and t]
        if progs:
            for pid, name in (
                await self.db.execute(select(Program.id, Program.name).where(Program.id.in_(progs)))
            ).all():
                out[pid] = name
        hostels = [t for tt, t in pairs if tt == "hostel" and t]
        if hostels:
            for hid, name in (
                await self.db.execute(select(Hostel.id, Hostel.name).where(Hostel.id.in_(hostels)))
            ).all():
                out[hid] = name
        return out

    async def _responded(self, s: FeedbackSurvey, h: str) -> set[uuid.UUID | None]:
        return {
            r[0]
            for r in (
                await self.db.execute(
                    select(FeedbackResponse.target_id).where(
                        FeedbackResponse.survey_id == s.id, FeedbackResponse.respondent_hash == h
                    )
                )
            ).all()
        }

    # ---- respondent side -------------------------------------------------------------------------------------------------
    async def pending(self) -> list[SvyPending]:
        rows = (
            (
                await self.db.execute(
                    select(FeedbackSurvey).where(
                        FeedbackSurvey.institution_id == self.inst,
                        FeedbackSurvey.status == "open",
                        or_(FeedbackSurvey.closes_at.is_(None), FeedbackSurvey.closes_at > now_utc()),
                    )
                )
            )
            .scalars()
            .all()
        )
        secret = await self.secret()
        out = []
        for s in rows:
            targets = await self._my_targets(s)
            if not targets:
                continue
            done = await self._responded(s, respondent_hash(secret, self.actor_id or "", s.id))
            labels = await self._labels(targets)
            items = [
                SvyTarget(target_type=tt, target_id=tid, label=labels.get(tid) if tid else None, responded=tid in done)
                for tt, tid in targets
            ]
            if all(i.responded for i in items):
                continue
            out.append(
                SvyPending(
                    survey_id=s.id, survey_type=s.survey_type, title=s.title, closes_at=s.closes_at, targets=items
                )
            )
        return out

    async def form(self, sid: uuid.UUID, target_id: uuid.UUID | None) -> SvyForm:
        s = await self._survey(sid)
        target = None
        if s.status == "open" and self.actor_id is not None:
            targets = await self._my_targets(s)
            hit = next(((tt, t) for tt, t in targets if t == target_id), None)
            if hit is None and not self.manager():
                raise not_found("Survey form")
            if hit:
                labels = await self._labels([hit])
                target = SvyTarget(target_type=hit[0], target_id=hit[1], label=labels.get(hit[1]) if hit[1] else None)
        elif not self.manager():
            raise not_found("Survey form")
        return SvyForm(
            survey_id=s.id,
            title=s.title,
            survey_type=s.survey_type,
            is_anonymous=s.is_anonymous,
            questions=_questions(s),
            target=target,
        )

    def _validate(self, s: FeedbackSurvey, answers: dict[str, Any]) -> dict[str, Any]:
        qs = _questions(s)
        clean: dict[str, Any] = {}
        for q in qs:
            qid = str(q.get("id"))
            v = answers.get(qid)
            if v in (None, "") and q.get("required", True) and q.get("type") != "text":
                raise rule(f"Question {qid} is required", "ANSWER_REQUIRED", question=qid)
            if v in (None, ""):
                continue
            t = q.get("type", "likert5")
            if t in ("likert5", "likert4"):
                n = _num(v)
                top = int(q.get("scale") or (5 if t == "likert5" else 4))
                if n is None or n < 0 or n > top:
                    raise rule(f"Question {qid} expects 0–{top}", "BAD_ANSWER", question=qid)
                clean[qid] = n
            elif t == "yesno":
                clean[qid] = bool(v) if not isinstance(v, str) else v.lower() in ("yes", "true", "1")
            else:
                clean[qid] = str(v)[:2000]
        return clean

    async def respond(self, sid: uuid.UUID, body: SvyRespond) -> SvyRespondResult:
        s = await self._survey(sid)
        if s.status != "open" or (s.closes_at and s.closes_at < now_utc()):
            raise rule("The survey is not open", "SURVEY_CLOSED")
        targets = await self._my_targets(s)
        hit = next(((tt, t) for tt, t in targets if t == body.target_id), None)
        if hit is None:
            raise forbidden("You are not a respondent of this survey / target")
        h = respondent_hash(await self.secret(), self.actor_id or "", s.id)
        return await self._insert(s, h, hit[0], hit[1], self._validate(s, body.answers))

    async def _insert(
        self, s: FeedbackSurvey, h: str, ttype: str, tid: uuid.UUID | None, answers: dict[str, Any]
    ) -> SvyRespondResult:
        dup = (
            await self.db.execute(
                select(func.count())
                .select_from(FeedbackResponse)
                .where(
                    FeedbackResponse.survey_id == s.id,
                    FeedbackResponse.respondent_hash == h,
                    FeedbackResponse.target_id.is_(None) if tid is None else FeedbackResponse.target_id == tid,
                )
            )
        ).scalar_one()
        if dup:
            raise rule("You already responded for this target", "ALREADY_RESPONDED")
        r = FeedbackResponse(
            institution_id=self.inst,
            survey_id=s.id,
            respondent_hash=h,
            target_type=ttype,
            target_id=tid,
            answers=answers,
        )
        self.db.add(r)
        try:
            await self.db.flush()
        except IntegrityError:
            raise rule("You already responded for this target", "ALREADY_RESPONDED") from None
        return SvyRespondResult(survey_id=s.id, target_id=tid, submitted_at=r.submitted_at or now_utc())

    # ---- external (alumni / employer) -----------------------------------------------------------------------------------
    async def external_links(self, sid: uuid.UUID, body: SvyExternalLinks) -> SvyExternalLinksOut:
        if not self.manager():
            raise forbidden("surveys:manage required")
        s = await self._survey(sid)
        if s.survey_type not in EXTERNAL_SURVEYS:
            raise rule("External links are for alumni / employer surveys", "NOT_EXTERNAL")
        meta = await self.meta("survey_tokens", s.id)
        tokens = []
        for _ in range(body.count):
            sec = secrets.token_urlsafe(18)
            meta[sha(sec)] = {"used": False, "target_id": str(body.target_id) if body.target_id else None}
            tokens.append(f"{self.inst.hex}.{sec}")
        await self.put_meta("survey_tokens", s.id, meta)
        return SvyExternalLinksOut(survey_id=s.id, tokens=tokens)

    async def _token(self, token: str) -> tuple[FeedbackSurvey, str, dict[str, Any], dict[str, Any]]:
        sec = token.split(".", 1)[1] if "." in token else token
        h = sha(sec)
        for key, meta in (await self.metas("survey_tokens")).items():
            if h in meta:
                s = await self._survey(uuid.UUID(key))
                return s, h, meta, meta[h]
        raise not_found("Survey link")

    async def external_form(self, token: str) -> SvyForm:
        s, _h, _m, entry = await self._token(token)
        if entry.get("used") or s.status != "open":
            raise not_found("Survey link")
        return SvyForm(
            survey_id=s.id, title=s.title, survey_type=s.survey_type, is_anonymous=True, questions=_questions(s)
        )

    async def external_respond(self, token: str, body: SvyRespond) -> SvyRespondResult:
        s, h, meta, entry = await self._token(token)
        if entry.get("used") or s.status != "open":
            raise not_found("Survey link")
        tid = entry.get("target_id") or ((self.rules(s).get("targets") or {}).get("ids") or [None])[0]
        res = await self._insert(s, h, "program", uuid.UUID(str(tid)) if tid else None, self._validate(s, body.answers))
        meta[h] = {**entry, "used": True, "used_at": now_utc().isoformat()}
        await self.put_meta("survey_tokens", s.id, meta)
        return res

    # ---- completion / reminders -----------------------------------------------------------------------------------------
    async def completion(self, sid: uuid.UUID) -> SvyCompletion:
        if not (self.manager() or self.reader()):
            raise forbidden("surveys:manage required")
        s = await self._survey(sid)
        rows = (
            await self.db.execute(
                select(FeedbackResponse.target_id, FeedbackResponse.respondent_hash).where(
                    FeedbackResponse.survey_id == s.id
                )
            )
        ).all()
        exp = await self._expected_pairs(s)
        by_target: dict[Any, dict[str, int]] = defaultdict(lambda: {"expected": 0, "responses": 0})
        for _u, _tt, tid in exp or []:
            by_target[tid]["expected"] += 1
        for tid, _ in rows:
            by_target[tid]["responses"] += 1
        labels = await self._labels([(SURVEY_TARGET_TYPE.get(s.survey_type, "institution"), t) for t in by_target if t])
        return SvyCompletion(
            survey_id=s.id,
            expected=len(exp) if exp is not None else None,
            responses=len(rows),
            respondents=len({h for _, h in rows}),
            completion_pct=round(100.0 * len(rows) / len(exp), 1) if exp else None,
            by_target=[
                {"target_id": str(t) if t else None, "label": labels.get(t) if t else "Institution", **v}
                for t, v in by_target.items()
            ][:500],
        )

    async def remind(self, sid: uuid.UUID) -> int:
        if not self.manager():
            raise forbidden("surveys:manage required")
        return await self._remind(await self._survey(sid))

    async def _remind(self, s: FeedbackSurvey) -> int:
        if s.status != "open":
            return 0
        exp = await self._expected_pairs(s) or []
        secret = await self.secret()
        hashes = {
            (h, t)
            for h, t in (
                await self.db.execute(
                    select(FeedbackResponse.respondent_hash, FeedbackResponse.target_id).where(
                        FeedbackResponse.survey_id == s.id
                    )
                )
            ).all()
        }
        pending_users = {u for u, _tt, tid in exp if (respondent_hash(secret, u, s.id), tid) not in hashes}
        if pending_users:
            await self._notify(
                "survey.reminder",
                list(pending_users),
                {"title": s.title, "closes_on": s.closes_at.date().isoformat() if s.closes_at else "soon"},
            )
            await self._emit(
                "survey.reminder", {"survey_id": str(s.id), "count": len(pending_users)}, "feedback_survey", s.id
            )
        return len(pending_users)

    async def _notify_audience(self, s: FeedbackSurvey, event: str) -> None:
        exp = await self._expected_pairs(s)
        users = list({u for u, _, _ in exp or []})
        if users:
            await self._notify(
                event, users, {"title": s.title, "closes_on": s.closes_at.date().isoformat() if s.closes_at else "—"}
            )

    async def reminders(self) -> int:
        """Beat ``surveys.reminders`` — open surveys whose ``reminder_days`` (days before close) match today."""
        today = await self.today()
        n = 0
        for s in (
            await self.db.execute(
                select(FeedbackSurvey).where(
                    FeedbackSurvey.institution_id == self.inst, FeedbackSurvey.status == "open"
                )
            )
        ).scalars():
            days = self.rules(s).get("reminder_days") or []
            if s.closes_at and (s.closes_at.date() - today).days in days:
                n += await self._remind(s)
        return n

    async def auto_close(self) -> int:
        """Beat ``surveys.auto_close`` (hourly) — open drafts whose window started, close lapsed ones."""
        now = now_utc()
        n = 0
        for s in (
            await self.db.execute(
                select(FeedbackSurvey).where(
                    FeedbackSurvey.institution_id == self.inst, FeedbackSurvey.status.in_(("draft", "open"))
                )
            )
        ).scalars():
            if s.status == "open" and s.closes_at and s.closes_at < now:
                s.status = "closed"
                await self._emit("survey.closed", {"survey_id": str(s.id), "auto": True}, "feedback_survey", s.id)
                n += 1
            elif (
                s.status == "draft"
                and s.opens_at
                and s.opens_at <= now
                and (s.closes_at is None or s.closes_at > now)
                and self.rules(s).get("auto_open")
            ):
                s.status = "open"
                await self._emit("survey.opened", {"survey_id": str(s.id), "auto": True}, "feedback_survey", s.id)
                n += 1
        await self.db.flush()
        return n

    # ---- analytics -------------------------------------------------------------------------------------------------------
    async def _own_targets(self) -> set[uuid.UUID]:
        staff_id = await self.my_staff_id()
        if staff_id is None:
            return set()
        offs = {
            r[0]
            for r in (
                await self.db.execute(
                    select(CourseOfferingFaculty.offering_id).where(CourseOfferingFaculty.staff_id == staff_id)
                )
            ).all()
        }
        offs |= {
            r[0]
            for r in (
                await self.db.execute(select(CourseOffering.id).where(CourseOffering.coordinator_staff_id == staff_id))
            ).all()
        }
        return offs | {staff_id}

    async def _dept_targets_ok(self, target_id: uuid.UUID | None) -> bool:
        p = self.principal
        depts = scope_ids(p, "department")
        if not depts or not module_reader(p, self.module) or target_id is None:
            return False
        hit = (
            await self.db.execute(
                select(func.count())
                .select_from(CourseOffering)
                .where(CourseOffering.id == target_id, CourseOffering.department_id.in_(depts))
            )
        ).scalar_one()
        if hit:
            return True
        hit = (
            await self.db.execute(
                select(func.count()).select_from(Staff).where(Staff.id == target_id, Staff.department_id.in_(depts))
            )
        ).scalar_one()
        return bool(hit)

    def _stats(
        self, s: FeedbackSurvey, answers: list[dict[str, Any]]
    ) -> tuple[list[SvyQuestionStats], float | None, list[str]]:
        per: list[SvyQuestionStats] = []
        comments: list[str] = []
        means: list[float] = []
        for q in _questions(s):
            qid, t = str(q.get("id")), q.get("type", "likert5")
            vals = [a.get(qid) for a in answers if isinstance(a, dict) and a.get(qid) not in (None, "")]
            if t == "text":
                comments += [scrub(str(v))[:500] for v in vals]
                per.append(SvyQuestionStats(id=qid, text=str(q.get("text")), type=t, n=len(vals)))
                continue
            nums = [n for n in (_num(v) for v in vals) if n is not None]
            dist: dict[str, int] = defaultdict(int)
            for v in vals:
                dist[str(v if not isinstance(v, float) or not v.is_integer() else int(v))] += 1
            mean = round(sum(nums) / len(nums), 2) if nums and t != "choice" else None
            if mean is not None and t in ("likert5", "likert4"):
                means.append(mean)
            per.append(
                SvyQuestionStats(
                    id=qid, text=str(q.get("text")), type=t, n=len(vals), mean=mean, distribution=dict(dist)
                )
            )
        overall = round(sum(means) / len(means), 2) if means else None
        return per, overall, comments

    async def analytics(self, sid: uuid.UUID, target_type: str | None, target_id: uuid.UUID | None) -> SvyAnalytics:
        s = await self._survey(sid)
        privileged = (
            all_access(self.principal, self.module)
            or self.manager()
            or self.can("surveys", "view_all")
            and not scope_ids(self.principal, "department")
        )
        if not privileged:
            if target_id is None:
                raise forbidden("Pick one of your own targets")
            if target_id not in await self._own_targets() and not await self._dept_targets_ok(target_id):
                raise not_found("Survey target")
        stmt = select(FeedbackResponse.answers).where(FeedbackResponse.survey_id == s.id)
        if target_id is not None:
            stmt = stmt.where(FeedbackResponse.target_id == target_id)
        if target_type:
            stmt = stmt.where(FeedbackResponse.target_type == target_type)
        answers = [a for (a,) in (await self.db.execute(stmt)).all()]
        if not privileged and len(answers) < self.min_responses(s):
            raise rule(
                f"Results are shown once at least {self.min_responses(s)} responses exist",
                "MIN_RESPONSES",
                status=403,
                n=len(answers),
            )
        per, overall, comments = self._stats(s, answers)
        from app.services.obe.co_service import survey_means

        co, _ = survey_means(_questions(s), answers, "co")
        po, _ = survey_means(_questions(s), answers, "po")
        labels = (
            await self._labels([(target_type or SURVEY_TARGET_TYPE.get(s.survey_type, "institution"), target_id)])
            if target_id
            else {}
        )
        prev = await self._previous_overall(s, target_id)
        return SvyAnalytics(
            survey_id=s.id,
            target_type=target_type,
            target_id=target_id,
            target_label=labels.get(target_id) if target_id else None,
            n=len(answers),
            per_question=per,
            overall=overall,
            comments_masked=comments[:200],
            co_scores={k: round(v, 2) for k, v in co.items()} or None,
            po_scores={k: round(v, 2) for k, v in po.items()} or None,
            previous_overall=prev,
        )

    async def _previous_overall(self, s: FeedbackSurvey, target_id: uuid.UUID | None) -> float | None:
        prev = (
            await self.db.execute(
                select(FeedbackSurvey)
                .where(
                    FeedbackSurvey.institution_id == self.inst,
                    FeedbackSurvey.survey_type == s.survey_type,
                    FeedbackSurvey.id != s.id,
                    FeedbackSurvey.created_at < s.created_at,
                )
                .order_by(FeedbackSurvey.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if prev is None:
            return None
        stmt = select(FeedbackResponse.answers).where(FeedbackResponse.survey_id == prev.id)
        if target_id is not None and s.survey_type not in ("course", "course_exit"):
            stmt = stmt.where(FeedbackResponse.target_id == target_id)
        answers = [a for (a,) in (await self.db.execute(stmt)).all()]
        return self._stats(prev, answers)[1] if answers else None

    async def compare(self, sid: uuid.UUID, department_id: uuid.UUID | None) -> SvyCompare:
        if not (self.manager() or self.reader()):
            raise forbidden("surveys:analyse required")
        s = await self._survey(sid)
        rows = (
            await self.db.execute(
                select(FeedbackResponse.target_type, FeedbackResponse.target_id, FeedbackResponse.answers).where(
                    FeedbackResponse.survey_id == s.id
                )
            )
        ).all()
        dept_of: dict[uuid.UUID, uuid.UUID | None] = {}
        offs = [t for tt, t, _ in rows if tt == "offering" and t]
        for oid, dep in (
            await self.db.execute(
                select(CourseOffering.id, CourseOffering.department_id).where(
                    CourseOffering.id.in_(offs or [uuid.uuid4()])
                )
            )
        ).all():
            dept_of[oid] = dep
        staff = [t for tt, t, _ in rows if tt == "staff" and t]
        for sid2, dep in (
            await self.db.execute(select(Staff.id, Staff.department_id).where(Staff.id.in_(staff or [uuid.uuid4()])))
        ).all():
            dept_of[sid2] = dep
        groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        for _tt, t, a in rows:
            key = (t if department_id else dept_of.get(t)) if t else None
            if department_id and dept_of.get(t) != department_id:  # type: ignore[arg-type]
                continue
            groups[key].append(a)
        labels = (
            await self.department_codes([k for k in groups if k])
            if not department_id
            else await self._labels([(SURVEY_TARGET_TYPE.get(s.survey_type, "institution"), k) for k in groups if k])
        )
        inst_overall = self._stats(s, [a for _, _, a in rows])[1]
        return SvyCompare(
            survey_id=s.id,
            institution_overall=inst_overall,
            rows=[
                SvyCompareRow(
                    key=str(k) if k else "—", label=labels.get(k) if k else None, n=len(v), overall=self._stats(s, v)[1]
                )
                for k, v in groups.items()
            ],
        )

    async def sss_score(self, period: str | None) -> SvySssScore:
        stmt = select(FeedbackSurvey).where(
            FeedbackSurvey.institution_id == self.inst, FeedbackSurvey.survey_type == "sss"
        )
        if period and period[:4].isdigit():
            stmt = stmt.where(func.extract("year", FeedbackSurvey.created_at) == int(period[:4]))
        s = (await self.db.execute(stmt.order_by(FeedbackSurvey.created_at.desc()).limit(1))).scalar_one_or_none()
        if s is None:
            return SvySssScore(respondents=0, period=period)
        answers = [
            a
            for (a,) in (
                await self.db.execute(select(FeedbackResponse.answers).where(FeedbackResponse.survey_id == s.id))
            ).all()
        ]
        items = [q for q in _questions(s) if q.get("type") != "text"][:20]
        per: dict[str, float] = {}
        for q in items:
            qid = str(q.get("id"))
            vals = [n for n in (_num(a.get(qid)) for a in answers if isinstance(a, dict)) if n is not None]
            if vals:
                per[qid] = round(sum(vals) / len(vals), 3)
        # NAAC: Σ scores of the quantitative items over all respondents ÷ (respondents × items) on the 0–4 scale
        score = round(sum(per.values()) / len(per), 3) if per else None
        if score is not None:
            await self._emit(
                "surveys.sss_score",
                {"survey_id": str(s.id), "score": score, "respondents": len(answers), "metric": "surveys.sss_score"},
                "feedback_survey",
                s.id,
            )
        return SvySssScore(
            survey_id=s.id, period=period, respondents=len(answers), score=score, per_item=per, metric_recorded=False
        )

    async def _obe_feed(self, s: FeedbackSurvey) -> None:
        """``obe.indirect_survey_scores`` — outcome → mean per target (Phase 17 consumer)."""
        from app.services.obe.co_service import survey_means

        rows = (
            await self.db.execute(
                select(FeedbackResponse.target_id, FeedbackResponse.answers).where(FeedbackResponse.survey_id == s.id)
            )
        ).all()
        by_target: dict[Any, list[Any]] = defaultdict(list)
        for t, a in rows:
            by_target[t].append(a)
        for t, answers in by_target.items():
            for key in ("co", "po", "outcome"):
                means, n = survey_means(_questions(s), answers, key)
                if means:
                    await self._emit(
                        "obe.indirect_survey_scores",
                        {
                            "survey_id": str(s.id),
                            "survey_type": s.survey_type,
                            "target_id": str(t) if t else None,
                            "kind": key,
                            "scores": {k: round(v, 3) for k, v in means.items()},
                            "n": n,
                        },
                        "feedback_survey",
                        s.id,
                    )

    async def export_rows(self, sid: uuid.UUID) -> str:
        s = await self._survey(sid)
        qs = _questions(s)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["target_type", "target_id", "submitted_at"] + [str(q.get("id")) for q in qs])
        for r in (await self.db.execute(select(FeedbackResponse).where(FeedbackResponse.survey_id == s.id))).scalars():
            a = r.answers or {}
            w.writerow(
                [r.target_type, str(r.target_id or ""), r.submitted_at.isoformat() if r.submitted_at else ""]
                + [
                    scrub(str(a.get(str(q.get("id")), ""))) if q.get("type") == "text" else a.get(str(q.get("id")), "")
                    for q in qs
                ]
            )
        return buf.getvalue()

    async def stats(self) -> dict[str, Any]:
        by_status = {
            st: int(n)
            for st, n in (
                await self.db.execute(
                    select(FeedbackSurvey.status, func.count())
                    .where(FeedbackSurvey.institution_id == self.inst)
                    .group_by(FeedbackSurvey.status)
                )
            ).all()
        }
        responses = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(FeedbackResponse)
                    .where(FeedbackResponse.institution_id == self.inst)
                )
            ).scalar_one()
            or 0
        )
        open_rows = (
            (
                await self.db.execute(
                    select(FeedbackSurvey)
                    .where(FeedbackSurvey.institution_id == self.inst, FeedbackSurvey.status == "open")
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )
        completion = [
            o.completion_pct for o in await self.outs(list(open_rows), completion=True) if o.completion_pct is not None
        ]
        return {
            "surveys": sum(by_status.values()),
            "by_status": by_status,
            "responses": responses,
            "open_completion_pct": round(sum(completion) / len(completion), 1) if completion else None,
        }
