"""``academics`` demo seeder (Prompts/05 §05.2) — ``seed_demo_institution.py --type university --only academics``.

On top of ``institution`` (colleges A/B/C, ENG faculty, CSE/ECE/MBA departments, the pack grading scale):

* programmes **BTECH-CSE** (college A, CSE, 8 semesters) and **MBA** (college B, 4 semesters);
* regulation **R2022** built through the services (pack scheme ``CIA40_SEE60`` + the schemes ``THEORY-40-60``,
  ``LAB-50-50``, ``PROJECT`` with their components; 40 courses with prerequisites; the full B.Tech structure for
  Sem 1–8 with core courses, PE-I/PE-II/PE-III and OE-I baskets, exit points after Sem 2/4/6; the MBA structure),
  approved and activated; then **cloned to R2024** (two course edits so the diff tab has content) and activated —
  R2022 becomes ``superseded``;
* the institution's 10-point grading scale is the default one (pack ``UGC 10-point absolute``);
* batches 2024 and 2025 of both programmes (bound to R2024) with sections A/B;
* an Academic Council committee and the demo user ``ac.secretary`` (``committee_secretary`` @committee) so the
  ``regulation.approval`` workflow (dean → academic-council secretary) has a holder for every step.

Idempotent: when R2022 exists the regulation/course part is skipped; batches and the committee are get-or-create.
The services run as ``inst.admin`` (audit rows and outbox events are written as for the API).
"""

import secrets
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import select, text

from app.core.security import hash_password
from app.models.academic import Batch, Program, ProgramRegulation, Regulation
from app.models.curriculum import Course
from app.models.platform import College, Department, Institution, Role, User, UserRole

# (code, title, type, L, T, P, credits, dept, term, basket)
BTECH: list[tuple[str, str, str, int, int, int, str, str, int, str | None]] = [
    ("CS101", "Programming for Problem Solving", "core", 3, 0, 2, "4", "CSE", 1, None),
    ("MA101", "Engineering Mathematics I", "core", 3, 1, 0, "4", "CSE", 1, None),
    ("PH101", "Engineering Physics", "core", 3, 0, 2, "4", "ECE", 1, None),
    ("EE101", "Basic Electrical Engineering", "core", 3, 0, 2, "4", "ECE", 1, None),
    ("HS101", "Communicative English", "ability_enhancement", 2, 0, 2, "3", "CSE", 1, None),
    ("CS102", "Data Structures", "core", 3, 0, 2, "4", "CSE", 2, None),
    ("MA102", "Engineering Mathematics II", "core", 3, 1, 0, "4", "CSE", 2, None),
    ("CH101", "Engineering Chemistry", "core", 3, 0, 2, "4", "ECE", 2, None),
    ("EC101", "Basic Electronics", "core", 3, 0, 2, "4", "ECE", 2, None),
    ("MC101", "Environmental Science", "mandatory_non_credit", 2, 0, 0, "0", "CSE", 2, None),
    ("CS201", "Discrete Mathematics", "core", 3, 1, 0, "4", "CSE", 3, None),
    ("CS202", "Object-Oriented Programming", "core", 3, 0, 2, "4", "CSE", 3, None),
    ("CS203", "Computer Organization", "core", 3, 0, 0, "3", "CSE", 3, None),
    ("CS204", "Database Management Systems", "integrated_lab", 3, 0, 2, "4", "CSE", 3, None),
    ("MA201", "Probability and Statistics", "core", 3, 1, 0, "4", "CSE", 3, None),
    ("CS301", "Design and Analysis of Algorithms", "core", 3, 1, 0, "4", "CSE", 4, None),
    ("CS302", "Operating Systems", "integrated_lab", 3, 0, 2, "4", "CSE", 4, None),
    ("CS303", "Theory of Computation", "core", 3, 1, 0, "4", "CSE", 4, None),
    ("CS304", "Software Engineering", "core", 3, 0, 0, "3", "CSE", 4, None),
    ("CS305", "Computer Networks", "integrated_lab", 3, 0, 2, "4", "CSE", 5, None),
    ("CS306", "Compiler Design", "core", 3, 0, 0, "3", "CSE", 5, None),
    ("CS307", "Web Technologies", "lab", 0, 0, 4, "2", "CSE", 5, None),
    ("CS351", "Computer Graphics", "program_elective", 3, 0, 0, "3", "CSE", 5, "PE-I"),
    ("CS352", "Distributed Systems", "program_elective", 3, 0, 0, "3", "CSE", 5, "PE-I"),
    ("CS308", "Machine Learning", "integrated_lab", 3, 0, 2, "4", "CSE", 6, None),
    ("CS309", "Cloud Computing", "core", 3, 0, 0, "3", "CSE", 6, None),
    ("CS361", "Natural Language Processing", "program_elective", 3, 0, 0, "3", "CSE", 6, "PE-II"),
    ("CS362", "Big Data Analytics", "program_elective", 3, 0, 0, "3", "CSE", 6, "PE-II"),
    ("EC351", "Internet of Things", "open_elective", 3, 0, 0, "3", "ECE", 6, "OE-I"),
    ("CS310", "Information Security", "core", 3, 0, 0, "3", "CSE", 7, None),
    ("CS371", "Blockchain Technologies", "program_elective", 3, 0, 0, "3", "CSE", 7, "PE-III"),
    ("CS372", "Computer Vision", "program_elective", 3, 0, 0, "3", "CSE", 7, "PE-III"),
    ("CS491", "Project Work Phase I", "project", 0, 0, 6, "3", "CSE", 7, None),
    ("CS492", "Project Work Phase II", "project", 0, 0, 16, "8", "CSE", 8, None),
    ("CS481", "Industry Internship", "internship", 0, 0, 4, "2", "CSE", 8, None),
]
MBA: list[tuple[str, str, str, int, int, int, str, str, int, str | None]] = [
    ("MB101", "Principles of Management", "core", 4, 0, 0, "4", "MBA", 1, None),
    ("MB102", "Managerial Economics", "core", 4, 0, 0, "4", "MBA", 1, None),
    ("MB201", "Marketing Management", "core", 4, 0, 0, "4", "MBA", 2, None),
    ("MB202", "Financial Management", "core", 4, 0, 0, "4", "MBA", 3, None),
    ("MB401", "Dissertation", "project", 0, 0, 12, "6", "MBA", 4, None),
]
PREREQS: list[tuple[str, str]] = [
    ("CS102", "CS101"),
    ("CS202", "CS102"),
    ("CS301", "CS102"),
    ("CS301", "CS201"),
    ("CS302", "CS203"),
    ("CS303", "CS201"),
    ("CS306", "CS303"),
    ("CS308", "MA201"),
    ("CS361", "CS308"),
    ("CS492", "CS491"),
    ("MA102", "MA101"),
]
BASKETS: dict[str, tuple[str, str, int]] = {  # code → (name, type, term)
    "PE-I": ("Professional Elective I", "program_elective", 5),
    "PE-II": ("Professional Elective II", "program_elective", 6),
    "OE-I": ("Open Elective I", "open_elective", 6),
    "PE-III": ("Professional Elective III", "program_elective", 7),
}
SCHEMES: list[dict[str, Any]] = [
    {
        "code": "THEORY-40-60",
        "name": "Theory: CIA 40 / ESE 60",
        "applies_to_course_types": ["core", "program_elective", "open_elective", "ability_enhancement"],
        "cia_weight": 40,
        "ese_weight": 60,
        "cia_max": 40,
        "ese_max": 60,
        "pass_rules": {"ese_min_pct": 45, "total_min_pct": 50},
        "is_default": True,
        "components": [
            {"code": "CAT1", "name": "Continuous Assessment Test 1", "category": "cia", "max_marks": 50,
             "scaled_to": 15, "best_of": {"take": 2, "of": 3, "group": "CAT"}, "sequence": 1},
            {"code": "CAT2", "name": "Continuous Assessment Test 2", "category": "cia", "max_marks": 50,
             "scaled_to": 15, "best_of": {"take": 2, "of": 3, "group": "CAT"}, "sequence": 2},
            {"code": "CAT3", "name": "Continuous Assessment Test 3", "category": "cia", "max_marks": 50,
             "scaled_to": 15, "best_of": {"take": 2, "of": 3, "group": "CAT"}, "sequence": 3},
            {"code": "ASSIGN", "name": "Assignments", "category": "cia", "max_marks": 10, "scaled_to": 10,
             "sequence": 4},
            {"code": "ESE", "name": "End-semester examination", "category": "ese_theory", "max_marks": 100,
             "scaled_to": 60, "sequence": 5, "co_mappable": True},
        ],
    },
    {
        "code": "LAB-50-50",
        "name": "Laboratory: CIA 50 / ESE 50",
        "applies_to_course_types": ["lab", "integrated_lab"],
        "cia_weight": 50,
        "ese_weight": 50,
        "cia_max": 50,
        "ese_max": 50,
        "pass_rules": {"ese_min_pct": 50, "total_min_pct": 50},
        "components": [
            {"code": "RECORD", "name": "Lab record & observation", "category": "cia", "max_marks": 50,
             "scaled_to": 25, "sequence": 1},
            {"code": "LABTEST", "name": "Internal lab test", "category": "cia", "max_marks": 50, "scaled_to": 25,
             "sequence": 2},
            {"code": "ESEP", "name": "End-semester practical", "category": "ese_practical", "max_marks": 100,
             "scaled_to": 50, "sequence": 3},
        ],
    },
    {
        "code": "PROJECT",
        "name": "Project / internship: reviews 50 / viva 50",
        "applies_to_course_types": ["project", "internship", "seminar"],
        "cia_weight": 50,
        "ese_weight": 50,
        "cia_max": 50,
        "ese_max": 50,
        "pass_rules": {"total_min_pct": 50},
        "components": [
            {"code": "REVIEW1", "name": "Review 1", "category": "cia", "max_marks": 100, "scaled_to": 20,
             "sequence": 1},
            {"code": "REVIEW2", "name": "Review 2", "category": "cia", "max_marks": 100, "scaled_to": 30,
             "sequence": 2},
            {"code": "VIVA", "name": "Final viva voce", "category": "viva", "max_marks": 100, "scaled_to": 50,
             "sequence": 3},
        ],
    },
]


@seeder("academics", after=["communication"])
async def seed_academics(ctx: SeedContext) -> None:
    from app.db.session import bind_tenant, set_tenant
    from app.services.auth_service import load_principal

    inst = (await ctx.db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(ctx.db, inst.id)
    await set_tenant(ctx.db, inst.id)
    admin = (
        await ctx.db.execute(select(User).where(User.institution_id == inst.id, User.username == "inst.admin"))
    ).scalar_one()
    principal = await load_principal(ctx.db, admin.id)

    colleges = {
        c.code: c
        for c in (await ctx.db.execute(select(College).where(College.institution_id == inst.id))).scalars()
    }
    depts = {
        d.code: d
        for d in (
            await ctx.db.execute(
                select(Department).where(Department.institution_id == inst.id, Department.deleted_at.is_(None))
            )
        ).scalars()
    }
    if "A" not in colleges or "CSE" not in depts:
        raise SystemExit("run --only institution first (colleges A/B and the CSE department are missing)")

    await _default_scale(ctx, inst.id)
    programs = await _programs(ctx, principal, colleges, depts)
    r2022 = (
        await ctx.db.execute(
            select(Regulation).where(
                Regulation.institution_id == inst.id, Regulation.code == "R2022", Regulation.college_id.is_(None)
            )
        )
    ).scalar_one_or_none()
    if r2022 is None:
        await _regulations(ctx, principal, programs, depts)
    await _batches(ctx, principal, inst.id, programs)
    await _academic_council(ctx, inst.id)
    await ctx.db.flush()


async def _default_scale(ctx: SeedContext, institution_id: uuid.UUID) -> None:
    from app.models.academic import GradingScale

    scales = (
        (await ctx.db.execute(select(GradingScale).where(GradingScale.institution_id == institution_id)))
        .scalars()
        .all()
    )
    if scales and not any(s.is_default for s in scales):
        scales[0].is_default = True
        ctx.count("grading_scales.default")


async def _programs(
    ctx: SeedContext, principal: Any, colleges: dict[str, College], depts: dict[str, Department]
) -> dict[str, Program]:
    from app.schemas.academics import ProgramCreate
    from app.services.program_service import ProgramService

    service = ProgramService(ctx.db, principal)
    specs = [
        dict(
            code="BTECH-CSE",
            name="B.Tech Computer Science & Engineering",
            degree_name="B.Tech",
            specialization="Computer Science & Engineering",
            level="ug",
            duration_years=Decimal("4"),
            total_terms=8,
            max_duration_years=Decimal("7"),
            sanctioned_intake=120,
            lateral_intake=12,
            approving_body="AICTE",
            college="A",
            dept="CSE",
        ),
        dict(
            code="MBA",
            name="Master of Business Administration",
            degree_name="MBA",
            level="pg",
            duration_years=Decimal("2"),
            total_terms=4,
            max_duration_years=Decimal("4"),
            sanctioned_intake=60,
            approving_body="AICTE",
            college="B" if "B" in colleges else "A",
            dept="MBA" if "MBA" in depts else "CSE",
        ),
    ]
    out: dict[str, Program] = {}
    for spec in specs:
        college, dept = colleges[spec.pop("college")], depts[spec.pop("dept")]
        existing = (
            await ctx.db.execute(
                select(Program).where(Program.college_id == college.id, Program.code == spec["code"])
            )
        ).scalar_one_or_none()
        if existing is None:
            created = await service.create(ProgramCreate(college_id=college.id, department_id=dept.id, **spec))
            existing = (await ctx.db.execute(select(Program).where(Program.id == created.id))).scalar_one()
            ctx.count("programs")
        out[existing.code] = existing
    return out


async def _regulations(
    ctx: SeedContext, principal: Any, programs: dict[str, Program], depts: dict[str, Department]
) -> None:
    from app.schemas.academics import (
        AssessmentSchemeCreate,
        ProgramRegulationCreate,
        RegulationCloneRequest,
        RegulationCreate,
    )
    from app.schemas.curriculum import (
        BasketIn,
        CourseCreate,
        CourseUpdate,
        CurriculumCourseIn,
        PrerequisiteIn,
        PrerequisiteSet,
        StructureReplaceRequest,
        StructureTermIn,
    )
    from app.services.course_service import CourseService
    from app.services.curriculum_service import CurriculumService
    from app.services.grading_service import GradingService
    from app.services.program_service import ProgramService
    from app.services.regulation_service import RegulationService

    regs = RegulationService(ctx.db, principal)
    grading = GradingService(ctx.db, principal)
    courses_svc = CourseService(ctx.db, principal)
    curriculum = CurriculumService(ctx.db, principal)
    programs_svc = ProgramService(ctx.db, principal)

    r2022 = await regs.create(
        RegulationCreate(code="R2022", name="Regulations 2022 (CBCS)", effective_from_admission_year=2022)
    )
    ctx.count("regulations")
    for scheme in SCHEMES:
        await grading.create_scheme(AssessmentSchemeCreate(regulation_id=r2022.id, **scheme))
        ctx.count("assessment_schemes")

    ids: dict[str, uuid.UUID] = {}
    for code, title, ctype, lh, th, ph, credits, dept, _term, _basket in BTECH + MBA:
        dept_row = depts.get(dept) or depts["CSE"]
        c = await courses_svc.create(
            CourseCreate(
                regulation_id=r2022.id,
                department_id=dept_row.id,
                code=code,
                title=title,
                course_type=ctype,
                lecture_hours=lh,
                tutorial_hours=th,
                practical_hours=ph,
                credits=Decimal(credits),
                syllabus=[
                    {"unit": u, "title": f"{title} — unit {u}", "topics": [f"Topic {u}.1", f"Topic {u}.2"], "hours": 9}
                    for u in range(1, 6)
                ],
                textbooks=[f"{title}: A Textbook (Demo Press)"],
                is_public_catalog=ctype != "mandatory_non_credit",
            ),
            emit=False,
        )
        ids[code] = c.id
    ctx.count("courses", len(ids))
    for course in dict.fromkeys(c for c, _ in PREREQS):
        items = [PrerequisiteIn(related_course_id=ids[p]) for c, p in PREREQS if c == course]
        await courses_svc.set_prerequisites(ids[course], PrerequisiteSet(items=items))
    ctx.count("course_prerequisites", len(PREREQS))
    for row in (await ctx.db.execute(select(Course).where(Course.regulation_id == r2022.id))).scalars():
        row.status = "approved"
    await ctx.db.flush()

    async def structure(program: Program, rows: list[Any], exits: set[int]) -> None:
        load: dict[int, Decimal] = {}
        baskets: dict[str, list[uuid.UUID]] = {}
        for code, _t, ctype, _l, _tt, _p, credits, _d, term, basket in rows:
            if basket:
                baskets.setdefault(basket, []).append(ids[code])
            elif ctype != "mandatory_non_credit":
                load[term] = load.get(term, Decimal("0")) + Decimal(credits)
        for code, (_name, _type, term) in BASKETS.items():
            if code in baskets:
                load[term] = load.get(term, Decimal("0")) + Decimal("3")
        total = sum(load.values(), Decimal("0"))
        binding = await programs_svc.create_binding(
            ProgramRegulationCreate(program_id=program.id, regulation_id=r2022.id, total_credits_required=total)
        )
        req = StructureReplaceRequest(
            terms=[
                StructureTermIn(
                    term_number=n,
                    min_credits=max(Decimal("0"), load.get(n, Decimal("0")) - 4),
                    normal_credits=load.get(n, Decimal("0")),
                    max_credits=load.get(n, Decimal("0")) + 4,
                    is_exit_point=n in exits,
                )
                for n in range(1, program.total_terms + 1)
            ],
            courses=[
                CurriculumCourseIn(term_number=term, course_id=ids[code], basket_code=basket, sequence=i + 1)
                for i, (code, *_rest, term, basket) in enumerate(rows)
            ],
            baskets=[
                BasketIn(
                    code=code,
                    name=name,
                    basket_type=btype,
                    term_number=term,
                    min_choose=1,
                    max_choose=1,
                    credits_required=Decimal("3"),
                    course_ids=baskets[code],
                )
                for code, (name, btype, term) in BASKETS.items()
                if code in baskets
            ],
        )
        await curriculum.replace_structure(binding.id, req)
        ctx.count("program_regulations")

    await structure(programs["BTECH-CSE"], BTECH, {2, 4, 6})
    await structure(programs["MBA"], MBA, set())

    reg_row = (await ctx.db.execute(select(Regulation).where(Regulation.id == r2022.id))).scalar_one()
    await regs.mark_approved(reg_row, principal.id)
    await regs.activate(r2022.id)

    # R2024: clone, two course edits for the diff, approve + activate → R2022 superseded
    r2024 = await regs.clone(
        r2022.id,
        RegulationCloneRequest(code="R2024", name="Regulations 2024 (NEP-aligned)", effective_from_admission_year=2024),
    )
    ctx.count("regulations")
    clone_courses = {
        c.code: c
        for c in (await ctx.db.execute(select(Course).where(Course.regulation_id == r2024.id))).scalars()
    }
    await courses_svc.update(clone_courses["CS308"].id, CourseUpdate(title="Machine Learning and Deep Learning"))
    await courses_svc.update(clone_courses["CS307"].id, CourseUpdate(title="Full-Stack Web Development"))
    reg_row = (await ctx.db.execute(select(Regulation).where(Regulation.id == r2024.id))).scalar_one()
    await regs.mark_approved(reg_row, principal.id)
    await regs.activate(r2024.id)


async def _batches(ctx: SeedContext, principal: Any, institution_id: uuid.UUID, programs: dict[str, Program]) -> None:
    from app.schemas.academics import BatchCreate
    from app.services.batch_service import BatchService

    service = BatchService(ctx.db, principal)
    for program in programs.values():
        binding = (
            await ctx.db.execute(
                select(ProgramRegulation)
                .join(Regulation, Regulation.id == ProgramRegulation.regulation_id)
                .where(ProgramRegulation.program_id == program.id, Regulation.code == "R2024")
            )
        ).scalar_one_or_none()
        if binding is None:
            continue
        for year in (2024, 2025):
            exists = (
                await ctx.db.execute(
                    select(Batch).where(
                        Batch.institution_id == institution_id,
                        Batch.program_id == program.id,
                        Batch.admission_year == year,
                        Batch.entry_type == "regular",
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                await service.create(
                    BatchCreate(
                        program_id=program.id,
                        program_regulation_id=binding.id,
                        admission_year=year,
                        section_count=2,
                        section_capacity=60 if program.code == "BTECH-CSE" else 30,
                    )
                )
                ctx.count("batches")


async def _academic_council(ctx: SeedContext, institution_id: uuid.UUID) -> None:
    """Committee row (Phase 27/33 own ``committees``; the demo needs one for the ``committee_secretary`` scope)."""
    row = (
        await ctx.db.execute(
            text(
                "SELECT id FROM committees WHERE institution_id = :i AND committee_type = 'academic_council' LIMIT 1"
            ),
            {"i": institution_id},
        )
    ).first()
    if row is None:
        row = (
            await ctx.db.execute(
                text(
                    "INSERT INTO committees (institution_id, name, committee_type, constituted_on) "
                    "VALUES (:i, 'Academic Council', 'academic_council', :d) RETURNING id"
                ),
                {"i": institution_id, "d": datetime.now(UTC).date()},
            )
        ).first()
        ctx.count("committees")
    assert row is not None
    committee_id = row[0]
    role = (
        await ctx.db.execute(
            select(Role).where(Role.institution_id == institution_id, Role.slug == "committee_secretary")
        )
    ).scalar_one_or_none()
    if role is None:
        return
    user = (
        await ctx.db.execute(
            select(User).where(User.institution_id == institution_id, User.username == "ac.secretary")
        )
    ).scalar_one_or_none()
    if user is None:
        password = f"Demo@{secrets.randbelow(10**6):06d}"
        user = User(
            institution_id=institution_id,
            username="ac.secretary",
            email=f"ac.secretary@{ctx.profile['slug']}.septronuniverse.in",
            display_name="Academic Council Secretary",
            user_type="staff",
            password_hash=hash_password(password),
            is_verified=True,
            must_change_password=False,
            locale="en-IN",
            timezone="Asia/Kolkata",
        )
        ctx.db.add(user)
        await ctx.db.flush()
        ctx.count("users")
        ctx.credentials.append(("committee_secretary", "ac.secretary", password))
    assigned = (
        await ctx.db.execute(
            select(UserRole).where(
                UserRole.user_id == user.id, UserRole.role_id == role.id, UserRole.scope_id == committee_id
            )
        )
    ).scalar_one_or_none()
    if assigned is None:
        ctx.db.add(
            UserRole(
                institution_id=institution_id,
                user_id=user.id,
                role_id=role.id,
                scope_type="committee",
                scope_id=committee_id,
            )
        )
        ctx.count("user_roles")
