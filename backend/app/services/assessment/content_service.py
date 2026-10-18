"""Question bank, blueprints, paper builder and study materials (carried from Orbit) — Prompts/13 §13.6
``content_service``.

* Syllabus topics per course; questions (bilingual bodies, options with exactly one correct for MCQ, answer keys,
  tags, CO / topic / Bloom / difficulty, usage counts). Authors own their questions (edit / delete); with
  ``lms:view_all`` the department's questions are shared; ``exams:view_all`` (COE / exam cell) reads everything.
* CSV import (``body,type,marks,difficulty,bloom,co_code,option_a..d,correct``) → ``{created, failed[]}``.
* Blueprints: ``pattern.parts[] = {title, count, marks, question_types?, co_ids?, bloom?, difficulty?}``; generation
  picks random (or least-used) questions within each part's constraints and reports shortfalls; papers are edited
  while ``draft`` (409 after freeze); ``print?lang=primary|secondary|both`` renders a PDF.
* Study materials publish to a course / offering; students read published ones of their offerings.
"""

import csv
import io
import random
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select

from app.core.errors import APIError, ErrorCode
from app.models.content import Question, QuestionBlueprint, QuestionOption, QuestionPaper, StudyMaterial, SyllabusTopic
from app.models.curriculum import Course
from app.models.obe import CourseOutcome
from app.models.offerings import CourseOffering
from app.repositories.assessment_scope import learner_offering_ids, visible_offering_ids
from app.schemas.content import (
    BlueprintIn,
    BlueprintOut,
    OptionIn,
    OptionOut,
    PaperGenerateRequest,
    PaperOut,
    PaperUpdate,
    QuestionImportReport,
    QuestionIn,
    QuestionOut,
    StudyMaterialIn,
    StudyMaterialOut,
    SyllabusTopicIn,
    SyllabusTopicOut,
)
from app.services.assessment.common import AssessmentBase, now_utc


class ContentService(AssessmentBase):
    audit_module = "lms"

    def _dept_ids(self) -> list[uuid.UUID]:
        return [sid for st, sid in getattr(self.principal, "scopes", []) if st == "department" and sid is not None]

    def _question_scope(self) -> Any:
        if (
            self.principal is None
            or getattr(self.principal, "is_super_admin", False)
            or self.can("exams", "view_all")
            or self.can("lms", "manage")
            and any(st == "institution" for st, _ in self.principal.scopes)
        ):
            return Question.institution_id == self.inst
        parts = [Question.created_by == self.actor_id]
        if self.can("lms", "view_all") and self._dept_ids():
            parts.append(Question.course_id.in_(select(Course.id).where(Course.department_id.in_(self._dept_ids()))))
        return or_(*parts)

    # ---- topics ---------------------------------------------------------------------------------------------------------
    async def topics(self, course_id: uuid.UUID) -> list[SyllabusTopicOut]:
        await self.course(course_id)
        rows = (
            (
                await self.db.execute(
                    select(SyllabusTopic)
                    .where(SyllabusTopic.course_id == course_id)
                    .order_by(SyllabusTopic.unit_no, SyllabusTopic.sequence)
                )
            )
            .scalars()
            .all()
        )
        return [SyllabusTopicOut.model_validate(r) for r in rows]

    async def add_topic(self, course_id: uuid.UUID, body: SyllabusTopicIn) -> SyllabusTopicOut:
        await self.course(course_id)
        data = body.model_dump()
        data["hours"] = Decimal(str(data["hours"])) if data.get("hours") is not None else None
        t = SyllabusTopic(institution_id=self.inst, course_id=course_id, **data)
        self.db.add(t)
        await self.db.flush()
        return SyllabusTopicOut.model_validate(t)

    # ---- questions -----------------------------------------------------------------------------------------------------
    async def q_outs(self, rows: list[Question]) -> list[QuestionOut]:
        opts: dict[uuid.UUID, list[QuestionOption]] = {}
        for o in (
            await self.db.execute(
                select(QuestionOption)
                .where(QuestionOption.question_id.in_([r.id for r in rows] or [uuid.uuid4()]))
                .order_by(QuestionOption.sequence)
            )
        ).scalars():
            opts.setdefault(o.question_id, []).append(o)
        out = []
        for r in rows:
            qo = QuestionOut.model_validate(r)
            qo.options = [OptionOut.model_validate(x) for x in opts.get(r.id, [])]
            out.append(qo)
        return out

    async def questions(
        self,
        course_id: uuid.UUID | None,
        co_id: uuid.UUID | None,
        difficulty: str | None,
        q: str | None,
        limit: int = 200,
    ) -> list[QuestionOut]:
        stmt = select(Question).where(
            Question.institution_id == self.inst, Question.deleted_at.is_(None), self._question_scope()
        )
        if course_id:
            stmt = stmt.where(Question.course_id == course_id)
        if co_id:
            stmt = stmt.where(Question.co_id == co_id)
        if difficulty:
            stmt = stmt.where(Question.difficulty == difficulty)
        if q:
            stmt = stmt.where(Question.body_primary.ilike(f"%{q}%"))
        return await self.q_outs(
            list((await self.db.execute(stmt.order_by(Question.created_at.desc()).limit(limit))).scalars().all())
        )

    async def _validate_refs(self, body: QuestionIn) -> None:
        if body.co_id and body.course_id:
            ok = (
                await self.db.execute(
                    select(CourseOutcome.id).where(
                        CourseOutcome.id == body.co_id, CourseOutcome.course_id == body.course_id
                    )
                )
            ).first()
            if not ok:
                raise APIError(422, ErrorCode.VALIDATION, "The CO belongs to another course")

    async def _set_options(self, qid: uuid.UUID, options: list[OptionIn] | None) -> None:
        for old in (await self.db.execute(select(QuestionOption).where(QuestionOption.question_id == qid))).scalars():
            await self.db.delete(old)
        await self.db.flush()
        for i, o in enumerate(options or []):
            self.db.add(
                QuestionOption(
                    institution_id=self.inst,
                    question_id=qid,
                    label=o.label or "ABCDEFGH"[i],
                    body_primary=o.body_primary,
                    body_secondary=o.body_secondary,
                    is_correct=o.is_correct,
                    sequence=i + 1,
                )
            )
        await self.db.flush()

    async def create_question(self, body: QuestionIn) -> QuestionOut:
        await self._validate_refs(body)
        data = body.model_dump(exclude={"options"})
        data["marks"] = Decimal(str(data["marks"]))
        row = Question(institution_id=self.inst, created_by=self.actor_id, **data)
        self.db.add(row)
        await self.db.flush()
        await self._set_options(row.id, body.options)
        return (await self.q_outs([row]))[0]

    async def _own_question(self, qid: uuid.UUID) -> Question:
        row = (
            await self.db.execute(
                select(Question)
                .where(
                    Question.id == qid,
                    Question.institution_id == self.inst,
                    Question.deleted_at.is_(None),
                    self._question_scope(),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Question not found")
        if row.created_by != self.actor_id and not self.can("lms", "manage"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the author may change this question")
        return row

    async def update_question(self, qid: uuid.UUID, body: QuestionIn) -> QuestionOut:
        row = await self._own_question(qid)
        await self._validate_refs(body)
        for k, v in body.model_dump(exclude={"options"}).items():
            setattr(row, k, Decimal(str(v)) if k == "marks" else v)
        await self.db.flush()
        if body.options is not None:
            await self._set_options(row.id, body.options)
        return (await self.q_outs([row]))[0]

    async def delete_question(self, qid: uuid.UUID) -> None:
        row = await self._own_question(qid)
        row.deleted_at, row.deleted_by, row.is_active = now_utc(), self.actor_id, False
        await self.db.flush()

    async def import_csv(self, course_id: uuid.UUID | None, text: str) -> QuestionImportReport:
        out = QuestionImportReport()
        cos = (
            {
                c.code: c.id
                for c in (
                    await self.db.execute(select(CourseOutcome).where(CourseOutcome.course_id == course_id))
                ).scalars()
            }
            if course_id
            else {}
        )
        for n, rec in enumerate(csv.DictReader(io.StringIO(text)), start=2):
            low = {(k or "").strip().lower(): (v or "").strip() for k, v in rec.items()}
            try:
                qtype = low.get("type") or "mcq"
                letters = [x for x in "abcd" if low.get(f"option_{x}")]
                correct = {c.strip().lower() for c in (low.get("correct") or "").split(",") if c.strip()}
                body = QuestionIn(
                    course_id=course_id,
                    co_id=cos.get(low.get("co_code", "")),
                    question_type=qtype,  # type: ignore[arg-type]
                    body_primary=low["body"],
                    body_secondary=low.get("body_secondary") or None,
                    marks=float(low.get("marks") or 1),
                    difficulty=(low.get("difficulty") or "medium"),  # type: ignore[arg-type]
                    bloom_level=low.get("bloom") or None,
                    answer_key=low.get("answer") or None,
                    options=[
                        OptionIn(label=x.upper(), body_primary=low[f"option_{x}"], is_correct=x in correct)
                        for x in letters
                    ]
                    or None,
                )
                await self.create_question(body)
                out.created += 1
            except (KeyError, ValueError, APIError) as exc:
                out.failed.append({"row": n, "error": str(getattr(exc, "message", exc))[:200]})
        await self._audit(
            "question_import", "question", None, None, {"created": out.created, "failed": len(out.failed)}
        )
        return out

    # ---- blueprints / papers ---------------------------------------------------------------------------------------------
    async def blueprints(self, course_id: uuid.UUID | None) -> list[BlueprintOut]:
        q = select(QuestionBlueprint).where(QuestionBlueprint.institution_id == self.inst)
        if course_id:
            q = q.where(QuestionBlueprint.course_id == course_id)
        return [
            BlueprintOut.model_validate(b)
            for b in (await self.db.execute(q.order_by(QuestionBlueprint.created_at.desc()))).scalars()
        ]

    async def create_blueprint(self, body: BlueprintIn) -> BlueprintOut:
        parts = body.pattern.get("parts") or []
        if not parts:
            raise APIError(422, ErrorCode.VALIDATION, "pattern.parts is required")
        total = sum(Decimal(str(p.get("count") or 0)) * Decimal(str(p.get("marks") or 0)) for p in parts)
        if total != Decimal(str(body.total_marks)):
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"Parts add up to {total}, total_marks is {body.total_marks}",
                {"code": "SUM_MISMATCH"},
            )
        b = QuestionBlueprint(
            institution_id=self.inst,
            created_by=self.actor_id,
            course_id=body.course_id,
            name=body.name,
            total_marks=Decimal(str(body.total_marks)),
            duration_minutes=body.duration_minutes,
            pattern=body.pattern,
        )
        self.db.add(b)
        await self.db.flush()
        return BlueprintOut.model_validate(b)

    async def generate(self, body: PaperGenerateRequest) -> PaperOut:
        b = (
            await self.db.execute(
                select(QuestionBlueprint).where(
                    QuestionBlueprint.id == body.blueprint_id, QuestionBlueprint.institution_id == self.inst
                )
            )
        ).scalar_one_or_none()
        if b is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Blueprint not found")
        rng = random.Random(body.seed)
        used: set[uuid.UUID] = set()
        sections, shortfall = [], []
        for part in b.pattern.get("parts") or []:
            q = select(Question).where(
                Question.institution_id == self.inst, Question.deleted_at.is_(None), Question.is_active.is_(True)
            )
            if b.course_id:
                q = q.where(Question.course_id == b.course_id)
            if part.get("question_types"):
                q = q.where(Question.question_type.in_(part["question_types"]))
            if part.get("co_ids"):
                q = q.where(Question.co_id.in_([uuid.UUID(str(c)) for c in part["co_ids"]]))
            if part.get("bloom"):
                q = q.where(
                    Question.bloom_level.in_(part["bloom"] if isinstance(part["bloom"], list) else [part["bloom"]])
                )
            if part.get("difficulty"):
                q = q.where(
                    Question.difficulty.in_(
                        part["difficulty"] if isinstance(part["difficulty"], list) else [part["difficulty"]]
                    )
                )
            pool = [x for x in (await self.db.execute(q)).scalars().all() if x.id not in used]
            if body.strategy == "least_used":
                pool.sort(key=lambda x: (x.usage_count, rng.random()))
            else:
                rng.shuffle(pool)
            want = int(part.get("count") or 0)
            pick = pool[:want]
            if len(pick) < want:
                shortfall.append({"part": part.get("title"), "wanted": want, "found": len(pick)})
            used.update(x.id for x in pick)
            sections.append(
                {
                    "title": part.get("title") or "Part",
                    "questions": [
                        {"question_id": str(x.id), "marks": float(part.get("marks") or x.marks), "sequence": i + 1}
                        for i, x in enumerate(pick)
                    ],
                }
            )
        for x in (
            await self.db.execute(
                select(Question).where(Question.id.in_(list(used) or [uuid.uuid4()])).with_for_update()
            )
        ).scalars():
            x.usage_count += 1
        paper = QuestionPaper(
            institution_id=self.inst,
            course_id=b.course_id,
            blueprint_id=b.id,
            title=body.title or b.name,
            purpose=body.purpose,
            total_marks=b.total_marks,
            duration_minutes=b.duration_minutes,
            sections=sections,
            status="draft",
            created_by=self.actor_id,
        )
        self.db.add(paper)
        await self.db.flush()
        out = PaperOut.model_validate(paper)
        out.shortfall = shortfall
        return out

    async def _paper(self, pid: uuid.UUID, *, for_update: bool = False) -> QuestionPaper:
        q = select(QuestionPaper).where(QuestionPaper.id == pid, QuestionPaper.institution_id == self.inst)
        if for_update:
            q = q.with_for_update()
        p = (await self.db.execute(q)).scalar_one_or_none()
        if p is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Question paper not found")
        return p

    async def paper(self, pid: uuid.UUID) -> PaperOut:
        return PaperOut.model_validate(await self._paper(pid))

    async def update_paper(self, pid: uuid.UUID, body: PaperUpdate) -> PaperOut:
        p = await self._paper(pid, for_update=True)
        if p.status != "draft":
            raise APIError(409, ErrorCode.CONFLICT, f"The paper is {p.status}", {"code": "PAPER_FROZEN"})
        for k, v in body.model_dump(exclude_none=True).items():
            setattr(p, k, v)
        if body.sections is not None:
            p.total_marks = Decimal(
                str(sum(float(q.get("marks") or 0) for s in body.sections for q in s.get("questions") or []))
            )
        await self.db.flush()
        return PaperOut.model_validate(p)

    async def freeze(self, pid: uuid.UUID) -> PaperOut:
        p = await self._paper(pid, for_update=True)
        if p.status != "draft":
            raise APIError(409, ErrorCode.CONFLICT, f"The paper is {p.status}")
        p.status, p.frozen_at = "frozen", now_utc()
        await self.db.flush()
        await self._audit("freeze", "question_paper", p.id, None, {"title": p.title})
        return PaperOut.model_validate(p)

    async def print_pdf(self, pid: uuid.UUID, lang: str = "primary") -> tuple[bytes, str]:
        from app.utils.pdf import render_pdf

        p = await self._paper(pid)
        ids = [uuid.UUID(str(q["question_id"])) for s in p.sections for q in s.get("questions") or []]
        qs = {
            q.id: q
            for q in (await self.db.execute(select(Question).where(Question.id.in_(ids or [uuid.uuid4()])))).scalars()
        }
        opts: dict[uuid.UUID, list[QuestionOption]] = {}
        for o in (
            await self.db.execute(
                select(QuestionOption)
                .where(QuestionOption.question_id.in_(ids or [uuid.uuid4()]))
                .order_by(QuestionOption.sequence)
            )
        ).scalars():
            opts.setdefault(o.question_id, []).append(o)
        lines = [p.title, f"Max marks: {p.total_marks}   Duration: {p.duration_minutes or '-'} min", ""]
        n = 0
        for s in p.sections:
            lines.append(str(s.get("title") or ""))
            for ref in s.get("questions") or []:
                q = qs.get(uuid.UUID(str(ref["question_id"])))
                if q is None:
                    continue
                n += 1
                bodies = (
                    [q.body_primary]
                    if lang == "primary"
                    else [q.body_secondary or q.body_primary]
                    if lang == "secondary"
                    else [q.body_primary, *([q.body_secondary] if q.body_secondary else [])]
                )
                for i, text in enumerate(bodies):
                    lines.append(f"{'' if i else f'{n}. '}{text}  [{ref.get('marks')}]")
                for o in opts.get(q.id, []):
                    lines.append(
                        f"    ({o.label}) {o.body_primary if lang != 'secondary' else (o.body_secondary or o.body_primary)}"
                    )
            lines.append("")
        html = "<html><body>" + "".join(f"<p>{x}</p>" for x in lines) + "</body></html>"
        return render_pdf(html, lines, title=p.title), p.title

    # ---- study materials ---------------------------------------------------------------------------------------------------
    async def materials(self, course_id: uuid.UUID | None, offering_id: uuid.UUID | None) -> list[StudyMaterialOut]:
        q = select(StudyMaterial).where(StudyMaterial.institution_id == self.inst)
        if course_id:
            q = q.where(StudyMaterial.course_id == course_id)
        if offering_id:
            q = q.where(StudyMaterial.offering_id == offering_id)
        if not (self.can("lms", "manage") or self.can("lms", "view_all")):
            q = q.where(or_(StudyMaterial.created_by == self.actor_id, StudyMaterial.is_published.is_(True)))
        return [
            StudyMaterialOut.model_validate(m)
            for m in (await self.db.execute(q.order_by(StudyMaterial.created_at.desc()))).scalars()
        ]

    async def my_materials(self) -> list[StudyMaterialOut]:
        offs = learner_offering_ids(self.principal)
        q = select(StudyMaterial).where(
            StudyMaterial.institution_id == self.inst,
            StudyMaterial.is_published.is_(True),
            or_(
                StudyMaterial.offering_id.in_(offs),
                StudyMaterial.course_id.in_(select(CourseOffering.course_id).where(CourseOffering.id.in_(offs))),
            ),
        )
        return [
            StudyMaterialOut.model_validate(m)
            for m in (await self.db.execute(q.order_by(StudyMaterial.published_at.desc()))).scalars()
        ]

    async def save_material(self, body: StudyMaterialIn, mid: uuid.UUID | None = None) -> StudyMaterialOut:
        if body.offering_id:
            await self.offering(body.offering_id, "lms")
        if mid:
            m = (
                await self.db.execute(
                    select(StudyMaterial)
                    .where(StudyMaterial.id == mid, StudyMaterial.institution_id == self.inst)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if m is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Material not found")
            if m.created_by != self.actor_id and not self.can("lms", "manage"):
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the author may edit this material")
            for k, v in body.model_dump().items():
                setattr(m, k, v)
        else:
            m = StudyMaterial(institution_id=self.inst, created_by=self.actor_id, **body.model_dump())
            self.db.add(m)
        await self.db.flush()
        return StudyMaterialOut.model_validate(m)

    async def publish_material(self, mid: uuid.UUID) -> StudyMaterialOut:
        m = (
            await self.db.execute(
                select(StudyMaterial)
                .where(StudyMaterial.id == mid, StudyMaterial.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if m is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Material not found")
        if m.created_by != self.actor_id and not self.can("lms", "manage"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the author may publish this material")
        m.is_published, m.published_at = True, now_utc()
        await self.db.flush()
        await self._emit("lms.content_published", {"study_material_id": str(m.id)}, "study_material", m.id)
        return StudyMaterialOut.model_validate(m)


__all__ = ["ContentService", "visible_offering_ids"]
