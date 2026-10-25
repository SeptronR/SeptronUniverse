"""``student_support`` demo seeder (Prompts/27 §27.2) — ``seed_demo_institution.py --only student_support``.

Enables the Phase 27 features, makes sure the stub committees exist (grievance / ICC / anti-ragging / SC-ST / OBC /
discipline, with a chair and two members each), then: mentor assignments for every active student of the current term
(round robin within the department, ratio 20), 300 sessions with action items (some confidential / shared with the
guardian), 40 counselling referrals, risk flags for the term (≈12 % high), 150 grievances across categories /
statuses (10 anonymous, 6 ICC), 25 disciplinary cases (2 staff), 8 surveys (course feedback, SSS, hostel, parent …)
with responses at ≈60 % completion, 20 clubs with members / events, 1,200 activity-hour rows (400 verified) and 150
achievements. Idempotent: skipped when mentor assignments exist for the institution.
"""

import random
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select

CLUBS = (
    ("NSS Unit", "nss"),
    ("NCC Wing", "ncc"),
    ("Coding Club", "technical"),
    ("Robotics Club", "technical"),
    ("AI & ML Society", "technical"),
    ("IEEE Student Branch", "professional_chapter"),
    ("CSI Chapter", "professional_chapter"),
    ("ISTE Chapter", "professional_chapter"),
    ("Music Club", "cultural"),
    ("Dance Club", "cultural"),
    ("Drama Society", "cultural"),
    ("Fine Arts Club", "cultural"),
    ("Literary Club", "cultural"),
    ("Photography Club", "cultural"),
    ("Cricket Club", "sports"),
    ("Athletics Club", "sports"),
    ("Chess Club", "sports"),
    ("Eco Club", "social"),
    ("Rotaract Club", "social"),
    ("Unnat Bharat Abhiyan", "extension"),
)
CATS = ("academic", "exam", "fee", "hostel", "infrastructure", "other", "harassment", "ragging", "discrimination")
STATUSES = ("open", "acknowledged", "under_review", "resolved", "closed", "escalated", "reopened")


@seeder("student_support", after=["students", "hr", "offerings", "attendance", "fees", "facilities"])
async def seed_student_support(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.db.session import bind_tenant, set_tenant
    from app.enums.student_support import COURSE_FEEDBACK_QUESTIONS, HOSTEL_QUESTIONS, PARENT_QUESTIONS, SSS_QUESTIONS
    from app.models.academic import AcademicTerm
    from app.models.clubs import ActivityHour, Club, ClubEvent, ClubMember
    from app.models.discipline import DisciplinaryCase
    from app.models.grievances import Grievance, GrievanceUpdate
    from app.models.hostel import HostelAllocation
    from app.models.hr import Staff
    from app.models.mentoring import (
        CounsellingReferral,
        MentorAssignment,
        MentoringBooking,
        MentoringSession,
        MentoringSlot,
        RiskFlag,
    )
    from app.models.obe_attainment import FeedbackResponse, FeedbackSurvey
    from app.models.platform import Institution, User
    from app.models.post_result import Committee, CommitteeMember, StudentAchievement
    from app.models.registration import CourseRegistration, CourseRegistrationItem
    from app.models.students import Student, StudentGuardian, StudentProgramEnrollment
    from app.services.feature_service import FeatureService
    from app.services.student_support.common import respondent_hash, sha
    from app.services.student_support.survey_service import SurveyService

    db = ctx.db
    rng = random.Random(27)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if (
        await db.execute(
            select(func.count()).select_from(MentorAssignment).where(MentorAssignment.institution_id == inst.id)
        )
    ).scalar_one():
        return

    features = FeatureService(db)
    effective = await features.effective(inst.id)
    for key in (
        "governance.committees",
        "mentoring.core",
        "mentoring.appointment_slots",
        "mentoring.counselling",
        "mentoring.early_warning",
        "grievances.core",
        "grievances.anonymous",
        "grievances.committees",
        "discipline.core",
        "surveys.core",
        "surveys.sss",
        "clubs.core",
        "clubs.achievements",
        "clubs.activity_hours_credits",
    ):
        if key in effective:
            continue
        try:
            await features.set_platform_flag(
                inst.id, key, enabled=True, reason="demo seed (Phase 27)", config=None, confirm_dependencies=True
            )
            ctx.count("feature_overrides")
        except (APIError, KeyError) as exc:
            print(f"   student_support: {key} not enabled ({exc})")

    now = datetime.now(UTC)
    today = now.date()
    term = (
        await db.execute(
            select(AcademicTerm)
            .where(AcademicTerm.institution_id == inst.id)
            .order_by(AcademicTerm.is_current.desc(), AcademicTerm.start_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if term is None:
        print("   student_support: no academic term — skipped")
        return
    users = {u.username: u for u in (await db.execute(select(User).where(User.institution_id == inst.id))).scalars()}
    actor = users.get("registrar")
    actor_id = actor.id if actor else None
    staff = list(
        (
            await db.execute(
                select(Staff)
                .where(Staff.institution_id == inst.id, Staff.deleted_at.is_(None))
                .order_by(Staff.employee_id)
            )
        ).scalars()
    )
    teaching = [s for s in staff if s.staff_category == "teaching"] or staff
    if not teaching:
        print("   student_support: no staff — skipped")
        return
    rows = (
        await db.execute(
            select(StudentProgramEnrollment, Student)
            .join(Student, Student.id == StudentProgramEnrollment.student_id)
            .where(StudentProgramEnrollment.institution_id == inst.id, StudentProgramEnrollment.status == "active")
            .order_by(Student.registration_number)
        )
    ).all()
    enrols = [e for e, _ in rows]
    student_of = {e.id: s for e, s in rows}
    if not enrols:
        print("   student_support: no active students — skipped")
        return

    # ---- committees -------------------------------------------------------------------------------------------------------
    committees: dict[str, Committee] = {}
    for ctype, name in (
        ("grievance", "Grievance Redressal Cell"),
        ("icc", "Internal Complaints Committee"),
        ("anti_ragging", "Anti-Ragging Committee"),
        ("sc_st_cell", "SC/ST Cell"),
        ("obc_cell", "OBC Cell"),
        ("discipline", "Discipline Committee"),
    ):
        c = (
            await db.execute(
                select(Committee).where(Committee.institution_id == inst.id, Committee.committee_type == ctype).limit(1)
            )
        ).scalar_one_or_none()
        if c is None:
            c = Committee(institution_id=inst.id, name=name, committee_type=ctype, is_active=True, constituted_on=today)
            db.add(c)
            await db.flush()
            ctx.count("committees")
        if c.chair_staff_id is None:
            chair, *mem = rng.sample(staff, k=min(3, len(staff)))
            c.chair_staff_id = chair.id
            for m in [chair, *mem]:
                db.add(
                    CommitteeMember(
                        institution_id=inst.id,
                        committee_id=c.id,
                        member_type="staff",
                        staff_id=m.id,
                        user_id=m.user_id,
                        role="chair" if m is chair else "member",
                        from_on=today,
                    )
                )
                ctx.count("committee_members")
        committees[ctype] = c
    await db.flush()

    # ---- mentor assignments (round robin per department, ratio 20) -------------------------------------------------------
    by_dept: dict[uuid.UUID, list[Staff]] = defaultdict(list)
    for s in teaching:
        if s.department_id:
            by_dept[s.department_id].append(s)
    load: dict[uuid.UUID, int] = defaultdict(int)
    assignments: list[MentorAssignment] = []
    for e in enrols:
        pool = by_dept.get(e.department_id) or teaching
        cands = [m for m in pool if load[m.id] < 20] or pool
        m = min(cands, key=lambda x: load[x.id])
        load[m.id] += 1
        a = MentorAssignment(
            institution_id=inst.id,
            mentor_staff_id=m.id,
            student_program_enrollment_id=e.id,
            term_id=term.id,
            from_on=term.start_date,
            status="active",
        )
        db.add(a)
        assignments.append(a)
    await db.flush()
    ctx.count("mentor_assignments", len(assignments))

    # ---- slots + bookings ---------------------------------------------------------------------------------------------------
    mentors = list({a.mentor_staff_id for a in assignments})[:15]
    for mid in mentors:
        for d in range(1, 4):
            start = datetime.combine(today + timedelta(days=d), datetime.min.time(), tzinfo=UTC) + timedelta(hours=9)
            db.add(
                MentoringSlot(
                    institution_id=inst.id,
                    mentor_staff_id=mid,
                    starts_at=start,
                    ends_at=start + timedelta(minutes=30),
                    capacity=1,
                    location="Staff room",
                )
            )
            ctx.count("mentoring_slots")
    await db.flush()
    slots = list((await db.execute(select(MentoringSlot).where(MentoringSlot.institution_id == inst.id))).scalars())
    mentees_of: dict[uuid.UUID, list[MentorAssignment]] = defaultdict(list)
    for a in assignments:
        mentees_of[a.mentor_staff_id].append(a)
    for slot in slots[::3]:
        mine = mentees_of.get(slot.mentor_staff_id) or []
        if mine:
            db.add(
                MentoringBooking(
                    institution_id=inst.id,
                    slot_id=slot.id,
                    student_program_enrollment_id=rng.choice(mine).student_program_enrollment_id,
                    status="booked",
                )
            )
            ctx.count("mentoring_bookings")

    # ---- 300 sessions with action items -------------------------------------------------------------------------------------
    concerns = ("academic", "personal", "financial", "health", "career")
    for i in range(min(300, len(assignments) * 3)):
        a = assignments[i % len(assignments)]
        conf = i % 17 == 0
        share = (not conf) and i % 5 == 0
        db.add(
            MentoringSession(
                institution_id=inst.id,
                mentor_assignment_id=a.id,
                held_on=today - timedelta(days=rng.randint(1, 80)),
                mode=rng.choice(("in_person", "in_person", "online", "phone")),
                notes="Discussed attendance, upcoming assessments and study plan."
                if not conf
                else "Confidential personal matter discussed.",
                concerns={
                    "items": rng.sample(concerns, k=rng.randint(1, 2)),
                    "share_with_guardian": share,
                    "guardian_summary": "Progress is satisfactory; please encourage regular attendance."
                    if share
                    else None,
                },
                action_items=[
                    {
                        "text": "Submit pending assignment",
                        "owner": "student",
                        "due_on": (today + timedelta(days=rng.randint(-5, 10))).isoformat(),
                        "done": rng.random() < 0.5,
                    },
                    {"text": "Meet course teacher for doubts", "owner": "student", "due_on": None, "done": False},
                ],
                follow_up_on=today + timedelta(days=rng.randint(0, 21)) if i % 4 == 0 else None,
                is_confidential=conf,
            )
        )
        ctx.count("mentoring_sessions")
    await db.flush()

    # ---- 40 referrals -------------------------------------------------------------------------------------------------------
    for i in range(min(40, len(assignments))):
        a = assignments[(i * 7) % len(assignments)]
        db.add(
            CounsellingReferral(
                institution_id=inst.id,
                student_program_enrollment_id=a.student_program_enrollment_id,
                referred_by=next(
                    (s.user_id for s in staff if s.id == a.mentor_staff_id and s.user_id), actor_id or uuid.uuid4()
                ),
                reason="Signs of stress before examinations; student agreed to meet the counsellor.",
                status=("referred", "scheduled", "in_progress", "closed")[i % 4],
                is_confidential=True,
            )
        )
        ctx.count("counselling_referrals")

    # ---- risk flags (~12 % high) ----------------------------------------------------------------------------------------------
    for i, e in enumerate(enrols):
        r = rng.random()
        level = "high" if r < 0.12 else "medium" if r < 0.35 else "low"
        score = round(
            rng.uniform(66, 90)
            if level == "high"
            else rng.uniform(40, 64)
            if level == "medium"
            else rng.uniform(5, 39),
            2,
        )
        att = round(
            rng.uniform(55, 70)
            if level == "high"
            else rng.uniform(70, 80)
            if level == "medium"
            else rng.uniform(80, 98),
            1,
        )
        db.add(
            RiskFlag(
                institution_id=inst.id,
                student_program_enrollment_id=e.id,
                term_id=term.id,
                score=Decimal(str(score)),
                factors={
                    "attendance": {"value": round(max(0.0, (75 - att) / 25), 3), "weight": 35, "avg_pct": att},
                    "cia": {"value": round(rng.random() * (0.8 if level == "high" else 0.3), 3), "weight": 25},
                    "dues": {
                        "value": 0.7 if level == "high" and i % 2 else 0.0,
                        "weight": 10,
                        "overdue_paise": 2500000 if level == "high" and i % 2 else 0,
                    },
                    "standing": {"value": 0.6 if level == "high" else 0.0, "weight": 15},
                    "hostel": {"value": 0.0, "weight": 5},
                    "engagement": {"value": round(rng.random() * 0.5, 3), "weight": 10},
                },
                level=level,
                acknowledged_by=actor_id if level == "high" and i % 3 == 0 else None,
                acknowledged_at=now if level == "high" and i % 3 == 0 else None,
            )
        )
        ctx.count("risk_flags")
    await db.flush()

    # ---- 150 grievances (10 anonymous, 6 ICC) --------------------------------------------------------------------------------
    sla = {
        "harassment": 24,
        "ragging": 24,
        "discrimination": 48,
        "exam": 72,
        "fee": 72,
        "academic": 120,
        "hostel": 72,
        "infrastructure": 120,
        "other": 120,
    }
    route = {"harassment": "icc", "ragging": "anti_ragging", "discrimination": "sc_st_cell"}
    officer = users.get("grievance.off") or actor
    icc_left = 6
    for i in range(150):
        anon = i < 10
        if icc_left and i >= 10 and i % 7 == 3:
            cat = "harassment"
            icc_left -= 1
        else:
            cat = rng.choice(CATS[:6]) if i % 9 else rng.choice(("ragging", "discrimination"))
        e = enrols[(i * 13) % len(enrols)]
        st = STATUSES[i % len(STATUSES)]
        created = now - timedelta(days=rng.randint(0, 120), hours=rng.randint(0, 23))
        com = route.get(cat, "grievance_cell")
        ctype = {"grievance_cell": "grievance"}.get(com, com)
        g = Grievance(
            institution_id=inst.id,
            college_id=e.college_id,
            ticket_number=f"GRV/{created.year}/{i + 1:05d}",
            raised_by_user_id=None if anon else student_of[e.id].user_id,
            student_program_enrollment_id=None if anon else e.id,
            category=cat,
            is_anonymous=anon,
            description=f"Demo grievance about {cat.replace('_', ' ')} — please look into the issue at the earliest.",
            attachments={"files": [], **({"tracking": {"secret_hash": sha(f"demo-secret-{i}")}} if anon else {})},
            priority="high" if cat in ("harassment", "ragging") else rng.choice(("low", "normal", "normal", "high")),
            committee=com,
            committee_id=committees[ctype].id if ctype in committees else None,
            assigned_to=officer.id if officer and st != "open" else None,
            sla_due_at=created + timedelta(hours=sla[cat]),
            status=st,
            resolution="Issue addressed with the department; corrective action taken."
            if st in ("resolved", "closed")
            else None,
            resolved_at=created + timedelta(hours=rng.randint(4, sla[cat] + 48))
            if st in ("resolved", "closed")
            else None,
            satisfaction_rating=rng.randint(3, 5) if st == "closed" else None,
            created_at=created,
        )
        db.add(g)
        await db.flush()
        db.add(
            GrievanceUpdate(
                institution_id=inst.id,
                grievance_id=g.id,
                by_user_id=None,
                note="Grievance received",
                is_internal=False,
                at=created,
            )
        )
        if st != "open":
            db.add(
                GrievanceUpdate(
                    institution_id=inst.id,
                    grievance_id=g.id,
                    by_user_id=officer.id if officer else None,
                    note="Assigned to the committee for review (internal)",
                    is_internal=True,
                    at=created + timedelta(hours=2),
                )
            )
        ctx.count("grievances")
    await db.flush()

    # ---- 25 disciplinary cases (2 staff) -------------------------------------------------------------------------------------
    disc_com = committees.get("discipline")
    for i in range(25):
        staff_case = i < 2
        subj = rng.choice(staff).id if staff_case else enrols[(i * 17 + 3) % len(enrols)].id
        st = ("reported", "inquiry", "hearing", "decided", "appealed", "closed")[i % 6]
        sanctions = None
        if st in ("decided", "appealed", "closed"):
            sanctions = (
                [{"type": "warning", "details": "Written warning"}]
                if staff_case or i % 3
                else [
                    {"type": "fine", "amount_paise": 100000, "details": "Fine for misconduct"},
                    {"type": "community_service", "hours": 20, "details": "NSS community service"},
                ]
            )
        db.add(
            DisciplinaryCase(
                institution_id=inst.id,
                subject_type="staff" if staff_case else "student",
                subject_id=subj,
                case_number=f"DC/{today.year}/{i + 1:04d}",
                category=rng.choice(("misconduct", "hostel", "attendance_fraud", "ragging", "property_damage")),
                description="Demo disciplinary case reported for inquiry.",
                evidence={
                    "items": [{"name": "Incident report", "url": None, "note": "Filed by the warden"}],
                    "source": {"type": "hostel" if i % 4 == 0 else "manual", "id": None},
                    "timeline": [{"at": (now - timedelta(days=30 - i)).isoformat(), "by": None, "action": "reported"}],
                    "decision_text": "The committee found the charge proved." if sanctions else None,
                },
                reported_by=actor_id,
                committee_id=disc_com.id if disc_com and st != "reported" else None,
                hearing_at=now - timedelta(days=rng.randint(1, 20)) if st not in ("reported", "inquiry") else None,
                sanctions=sanctions,
                appeal_status="pending" if st == "appealed" else ("uphold" if st == "closed" and i % 2 else None),
                decided_by=actor_id if sanctions else None,
                decided_at=now - timedelta(days=rng.randint(1, 10)) if sanctions else None,
                status=st,
            )
        )
        ctx.count("disciplinary_cases")
    await db.flush()

    # ---- 8 surveys with ~60 % responses ---------------------------------------------------------------------------------------
    svc = SurveyService(db, None, institution_id=inst.id)
    secret = await svc.secret()
    regs: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for eid, oid in (
        await db.execute(
            select(CourseRegistration.student_program_enrollment_id, CourseRegistrationItem.offering_id)
            .join(CourseRegistrationItem, CourseRegistrationItem.registration_id == CourseRegistration.id)
            .where(CourseRegistration.term_id == term.id)
        )
    ).all():
        regs[eid].add(oid)
    hostel_of = dict(
        (
            await db.execute(
                select(HostelAllocation.student_program_enrollment_id, HostelAllocation.hostel_id).where(
                    HostelAllocation.institution_id == inst.id, HostelAllocation.status == "active"
                )
            )
        )
        .tuples()
        .all()
    )
    course_q = [
        dict(q, co_id=f"CO{i + 1}") if q["type"] != "text" and i < 5 else dict(q)
        for i, q in enumerate(COURSE_FEEDBACK_QUESTIONS)
    ]
    surveys = [
        ("course", "Course feedback — current term", course_q, "open"),
        ("course", "Course feedback — mid-term pulse", course_q, "closed"),
        ("faculty", "Faculty feedback", COURSE_FEEDBACK_QUESTIONS[1:6], "open"),
        ("sss", "Student Satisfaction Survey (NAAC)", SSS_QUESTIONS, "open"),
        ("hostel", "Hostel facilities survey", HOSTEL_QUESTIONS, "open"),
        ("parent", "Parent feedback", PARENT_QUESTIONS, "open"),
        ("institution", "Campus facilities survey", HOSTEL_QUESTIONS[2:], "analysed"),
        (
            "program_exit",
            "Programme exit survey",
            [
                {
                    "id": f"p{i}",
                    "text": f"PO{i} attainment",
                    "type": "likert5",
                    "scale": 5,
                    "po_id": f"PO{i}",
                    "required": True,
                }
                for i in range(1, 6)
            ],
            "draft",
        ),
    ]
    sample = enrols[: min(len(enrols), 400)]
    for stype, title, qs, status in surveys:
        s = FeedbackSurvey(
            institution_id=inst.id,
            survey_type=stype,
            term_id=term.id if stype in ("course", "faculty") else None,
            title=title,
            questions=qs,
            audience_rules={"targets": {"auto": True}, "reminder_days": [3, 1], "min_responses": 5},
            is_anonymous=True,
            opens_at=now - timedelta(days=10),
            closes_at=now + timedelta(days=10) if status == "open" else now - timedelta(days=1),
            status=status,
            created_by=actor_id,
        )
        db.add(s)
        await db.flush()
        ctx.count("feedback_surveys")
        if status == "draft":
            continue

        def answers(qs: list[dict[str, object]] = qs) -> dict[str, object]:
            out: dict[str, object] = {}
            for q in qs:
                if q["type"] == "text":
                    if rng.random() < 0.2:
                        out[q["id"]] = rng.choice(
                            ("Good teaching.", "More lab hours please.", "Clean washrooms needed.")
                        )
                else:
                    out[q["id"]] = (
                        rng.choice((2, 3, 3, 4, 4, 5)) if (q.get("scale") or 5) == 5 else rng.choice((2, 3, 3, 4))
                    )
            return out

        if stype == "parent":
            guardians = [
                g[0]
                for g in (
                    await db.execute(
                        select(StudentGuardian.user_id)
                        .where(StudentGuardian.user_id.is_not(None))
                        .distinct()
                        .limit(100)
                    )
                ).all()
            ]
            pairs = [(u, "institution", None) for u in guardians]
        else:
            pairs = []
            for e in sample:
                uid = student_of[e.id].user_id
                if uid is None:
                    continue
                if stype in ("course", "faculty"):
                    pairs += [(uid, "offering", o) for o in list(regs.get(e.id, set()))[:6]]
                elif stype == "hostel":
                    if e.id in hostel_of:
                        pairs.append((uid, "hostel", hostel_of[e.id]))
                else:
                    pairs.append((uid, "institution", None))
        for uid, ttype, tid in pairs:
            if rng.random() > 0.6:
                continue
            db.add(
                FeedbackResponse(
                    institution_id=inst.id,
                    survey_id=s.id,
                    respondent_hash=respondent_hash(secret, uid, s.id),
                    target_type=ttype,
                    target_id=tid,
                    answers=answers(),
                    submitted_at=now - timedelta(days=rng.randint(0, 9)),
                )
            )
            ctx.count("feedback_responses")
        await db.flush()

    # ---- 20 clubs with members / events ---------------------------------------------------------------------------------------
    clubs: list[Club] = []
    for name, ctype in CLUBS:
        c = (
            await db.execute(select(Club).where(Club.institution_id == inst.id, Club.name == name))
        ).scalar_one_or_none()
        if c is None:
            c = Club(
                institution_id=inst.id,
                name=name,
                club_type=ctype,
                faculty_advisor_id=rng.choice(teaching).id,
                description=f"{name} — student activities and outreach.",
                budget_paise=rng.choice((2500000, 5000000, 10000000)),
                is_active=True,
            )
            db.add(c)
            await db.flush()
            ctx.count("clubs")
        clubs.append(c)
    member_of: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for c in clubs:
        picks = rng.sample(enrols, k=min(len(enrols), rng.randint(15, 40)))
        for j, e in enumerate(picks):
            role = (
                "pending" if j >= len(picks) - 2 else ("president", "secretary", "treasurer")[j] if j < 3 else "member"
            )
            db.add(
                ClubMember(
                    institution_id=inst.id,
                    club_id=c.id,
                    student_program_enrollment_id=e.id,
                    role=role,
                    from_on=term.start_date,
                )
            )
            if role != "pending":
                member_of[c.id].append(e.id)
            ctx.count("club_members")
        for k in range(3):
            db.add(
                ClubEvent(
                    institution_id=inst.id,
                    club_id=c.id,
                    title=f"{c.name} activity {k + 1}",
                    held_on=today - timedelta(days=rng.randint(5, 90)),
                    venue="Seminar hall",
                    participants_count=rng.randint(20, 120),
                    budget_paise=rng.choice((0, 500000, 1500000)),
                    images=[],
                )
            )
            ctx.count("club_events")
    await db.flush()

    # ---- 1,200 activity hours (400 verified) --------------------------------------------------------------------------------
    verifier = users.get("nss.off") or actor
    act_of = {"nss": "nss", "ncc": "ncc", "sports": "sports"}
    club_ids = [c for c in clubs if member_of.get(c.id)]
    for i in range(1200):
        c = club_ids[i % len(club_ids)]
        eid = rng.choice(member_of[c.id])
        verified = i % 3 == 0
        db.add(
            ActivityHour(
                institution_id=inst.id,
                student_program_enrollment_id=eid,
                activity_type=act_of.get(
                    c.club_type, "community_service" if c.club_type in ("social", "extension") else "club"
                ),
                hours=Decimal(str(rng.choice((2, 3, 4, 6, 8)))),
                on_date=today - timedelta(days=rng.randint(1, 150)),
                description=f"{c.name} activity",
                evidence_url=None,
                verified_by=verifier.id if verified and verifier else None,
                verified_at=now - timedelta(days=rng.randint(0, 30)) if verified else None,
            )
        )
        ctx.count("activity_hours")
    await db.flush()

    # ---- 150 achievements -----------------------------------------------------------------------------------------------------
    for i in range(150):
        e = enrols[(i * 11) % len(enrols)]
        cat = ("sports", "cultural", "technical", "research", "hackathon", "other")[i % 6]
        verified = i % 2 == 0
        db.add(
            StudentAchievement(
                institution_id=inst.id,
                student_program_enrollment_id=e.id,
                category=cat,
                title=f"{cat.title()} achievement {i + 1}",
                level=("college", "university", "state", "national", "international")[i % 5],
                position=rng.choice(("1st", "2nd", "3rd", "participant")),
                held_on=today - timedelta(days=rng.randint(10, 300)),
                evidence_url=None,
                verified_by=verifier.id if verified and verifier else None,
                verified_at=now if verified else None,
            )
        )
        ctx.count("student_achievements")
    await db.flush()
