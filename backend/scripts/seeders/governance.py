"""``governance`` demo seeder (Prompts/33 §33.2) — ``seed_demo_institution.py --only governance``.

Enables the Phase 33 features (minutes, policies, legal, RTI, e-File; audit paras when ``accreditation.audit_registers``
is available), then writes: committees from the statutory templates of the institution type (stub-created rows of
Phases 27 / 30 are kept unchanged — templates whose type already exists are skipped) with staff / external / student
members, a BoS for CSE; 60 meetings across statuses with agendas / attendance / minutes; 240 resolutions numbered per
committee code and year (30 with action-taken reports pending, 20 linked to regulations / result runs / degrees /
policies); 15 legal cases with hearings; 40 RTI requests (3 appealed); 2 audit registers (financial statutory, AG) with
25 paras; 120 e-files with movements (10 pending beyond the SLA); 25 policies (5 requiring acknowledgement, ~60 %
acknowledged). Demo users ``sec.ac`` (committee secretary @Academic Council), ``chair.ac``, ``member.ac``,
``member.student`` (anti-ragging), ``sec.bos.cse`` (@BoS CSE) and ``pio`` — credentials go to
LOCAL_TEST_CREDENTIALS.md only. Idempotent: skipped when policies exist. ``council_resolution`` gives earlier seeders
(degrees) the resolution ``governance.minutes`` requires.
"""

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select, text


async def council_resolution(db: Any, institution_id: uuid.UUID, subject: str) -> uuid.UUID:
    """A council resolution for seeders of earlier modules (Phase 18 degree awards) now that ``governance.minutes``
    requires one: the Academic Council (created when missing), an approved meeting and a passed resolution numbered
    ``AC/<yyyy>/D<n>`` (outside the numeric series the services issue)."""
    from app.models.governance import Committee, Meeting, Resolution

    c = (
        await db.execute(
            select(Committee)
            .where(Committee.institution_id == institution_id, Committee.committee_type == "academic_council")
            .order_by(Committee.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if c is None:
        c = Committee(
            institution_id=institution_id,
            name="Academic Council",
            committee_type="academic_council",
            quorum_rule={"type": "fraction", "value": "1/2", "code": "AC", "template_key": "academic_council"},
            is_active=True,
        )
        db.add(c)
        await db.flush()
    now = datetime.now(UTC)
    m = Meeting(
        institution_id=institution_id,
        committee_id=c.id,
        meeting_no=f"D/{now.year}",
        held_on=now - timedelta(days=2),
        venue_or_link="Senate Hall",
        agenda=[{"item": subject}],
        quorum_met=True,
        minutes_text=f"Resolved: {subject}.",
        status="minutes_approved",
    )
    db.add(m)
    await db.flush()
    n = (
        await db.execute(
            select(func.count()).where(
                Resolution.institution_id == institution_id, Resolution.number.like(f"AC/{now.year}/D%")
            )
        )
    ).scalar_one()
    r = Resolution(
        institution_id=institution_id,
        meeting_id=m.id,
        number=f"AC/{now.year}/D{int(n) + 1}",
        subject=subject[:300],
        text=f"Resolved to approve: {subject}.",
        status="passed",
    )
    db.add(r)
    await db.flush()
    return r.id


@seeder("governance", after=["hr", "students", "accreditation"])
async def seed_governance(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    from seeders.base import _password, _phone

    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.core.security import hash_password
    from app.db.session import bind_tenant, set_tenant
    from app.enums.governance import TYPE_CODES, committee_templates
    from app.models.accreditation import AuditRegister
    from app.models.governance import (
        ActionTakenReport,
        AuditPara,
        Committee,
        CommitteeMember,
        Efile,
        EfileMovement,
        LegalCase,
        Meeting,
        Policy,
        Resolution,
        RtiRequest,
    )
    from app.models.hr import Staff
    from app.models.platform import Department, Institution, InstitutionSetting, Role, User, UserRole
    from app.services.feature_service import FeatureService

    db = ctx.db
    rng = random.Random(33)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if (
        await db.execute(select(func.count()).select_from(Policy).where(Policy.institution_id == inst.id))
    ).scalar_one():
        return  # meetings may already exist (council resolutions cited by the degrees seeder)

    features = FeatureService(db)
    effective = await features.effective(inst.id)
    for key in (
        "governance.committees",
        "governance.minutes",
        "governance.policies",
        "governance.legal",
        "governance.rti",
        "governance.efile",
        "governance.audit_paras",
    ):
        if key in effective:
            continue
        try:
            await features.set_platform_flag(
                inst.id, key, enabled=True, reason="demo seed (Phase 33)", config=None, confirm_dependencies=True
            )
            ctx.count("feature_overrides")
        except (APIError, KeyError) as exc:
            print(f"   governance: {key} not enabled ({exc})")

    now = datetime.now(UTC)
    today = now.date()
    users = {u.username: u for u in (await db.execute(select(User).where(User.institution_id == inst.id))).scalars()}
    roles = {
        r.slug: r
        for r in (
            await db.execute(select(Role).where(Role.institution_id == inst.id, Role.deleted_at.is_(None)))
        ).scalars()
    }
    depts = {
        d.code: d for d in (await db.execute(select(Department).where(Department.institution_id == inst.id))).scalars()
    }
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
    if len(teaching) < 8:
        print("   governance: fewer than 8 staff — run the hr seeder first; skipped")
        return
    student_users = list(
        (
            await db.execute(
                select(User)
                .where(User.institution_id == inst.id, User.user_type == "student")
                .order_by(User.username)
                .limit(20)
            )
        ).scalars()
    )

    def meta(kind: str, rid: object, value: dict[str, Any]) -> None:
        db.add(
            InstitutionSetting(
                institution_id=inst.id,
                college_id=None,
                category="governance_meta",
                key=f"{kind}:{rid}",
                value=value,
                value_type="json",
            )
        )

    async def demo_user(
        username: str, name: str, role: str, scope: str, user_type: str, label: str, scope_id: uuid.UUID | None = None
    ) -> User:
        u = users.get(username)
        if u is None:
            pwd = _password()
            u = User(
                institution_id=inst.id,
                username=username,
                email=f"{username}@{ctx.profile['slug']}.septronuniverse.in",
                phone=_phone(username),
                display_name=name,
                user_type=user_type,
                password_hash=hash_password(pwd),
                is_verified=True,
                must_change_password=False,
                locale="en-IN",
                timezone="Asia/Kolkata",
            )
            db.add(u)
            await db.flush()
            users[username] = u
            ctx.count("users")
            ctx.credentials.append((label, username, pwd))
        if role in roles:
            has = (
                await db.execute(select(UserRole).where(UserRole.user_id == u.id, UserRole.role_id == roles[role].id))
            ).first()
            if has is None:
                db.add(
                    UserRole(
                        institution_id=inst.id,
                        user_id=u.id,
                        role_id=roles[role].id,
                        scope_type=scope,
                        scope_id=scope_id,
                    )
                )
        return u

    def free_staff(skip: set[uuid.UUID]) -> Staff:
        """An unlinked teaching staff member not yet used as an office bearer; reuse starts once all are taken."""
        pool = [x for x in teaching if x.id not in skip]
        if not pool:
            skip.clear()
            pool = list(teaching)
        pick: Staff = next((x for x in pool if x.user_id is None), pool[0])
        return pick

    # ---- committees --------------------------------------------------------------------------------------------------
    existing = list((await db.execute(select(Committee).where(Committee.institution_id == inst.id))).scalars())
    by_type: dict[str, Committee] = {}
    used: set[uuid.UUID] = set()
    for c in existing:  # stub rows (Phases 27 / 30 / 0033) keep their data; office bearers are added where missing
        by_type.setdefault(c.committee_type, c)
        if c.chair_staff_id is None:
            c.chair_staff_id = free_staff(used).id
            used.add(c.chair_staff_id)
        if c.secretary_staff_id is None:
            c.secretary_staff_id = free_staff(used).id
            used.add(c.secretary_staff_id)
        c.constituted_on = c.constituted_on or today.replace(month=1, day=1)
    constituted = (
        today.replace(month=6, day=1) if today.month >= 6 else today.replace(year=today.year - 1, month=6, day=1)
    )
    for key, name, ctype, code, quorum, per_dept in committee_templates(inst.institution_type):
        targets = [None]
        if per_dept:
            targets = [depts.get("CSE")] + [d for k, d in depts.items() if k != "CSE"][:2]
        for d in targets:
            if per_dept and d is None:
                continue
            if not per_dept and ctype in by_type:
                continue
            if per_dept and any(c.committee_type == ctype and c.department_id == d.id for c in existing):  # type: ignore[union-attr]
                if d.code == "CSE":  # type: ignore[union-attr]
                    by_type["bos_cse"] = next(
                        c for c in existing if c.committee_type == ctype and c.department_id == d.id
                    )  # type: ignore[union-attr]
                continue
            chair, sec = free_staff(used), None
            used.add(chair.id)
            sec = free_staff(used)
            used.add(sec.id)
            c = Committee(
                institution_id=inst.id,
                name=f"{name} — {d.code}" if d is not None else name,
                committee_type=ctype,
                department_id=d.id if d is not None else None,
                chair_staff_id=chair.id,
                secretary_staff_id=sec.id,
                constituted_on=constituted,
                valid_to=constituted.replace(year=constituted.year + 2) - timedelta(days=1),
                quorum_rule={**quorum, "code": code if not per_dept else f"BOS-{d.code}", "template_key": key},  # type: ignore[union-attr]
                is_active=True,
            )
            db.add(c)
            await db.flush()
            if per_dept and d is not None and d.code == "CSE":
                by_type["bos_cse"] = c
            elif not per_dept:
                by_type[ctype] = c
            ctx.count("committees")
    await db.flush()
    committees = list((await db.execute(select(Committee).where(Committee.institution_id == inst.id))).scalars())

    # members: chair / secretary rows, 6–10 staff, 2 externals on BoS / councils, students on anti-ragging / grievance / IQAC
    for c in committees:
        have = (await db.execute(select(func.count()).where(CommitteeMember.committee_id == c.id))).scalar_one()
        if have >= 4:
            continue
        start = c.constituted_on or constituted
        rows: list[CommitteeMember] = []
        for sid, role in ((c.chair_staff_id, "chair"), (c.secretary_staff_id, "secretary")):
            if sid:
                st = next((s for s in staff if s.id == sid), None)
                rows.append(
                    CommitteeMember(
                        institution_id=inst.id,
                        committee_id=c.id,
                        member_type="staff",
                        staff_id=sid,
                        user_id=st.user_id if st else None,
                        role=role,
                        from_on=start,
                        to_on=c.valid_to,
                    )
                )
        pool = [s for s in teaching if s.id not in (c.chair_staff_id, c.secretary_staff_id)]
        if c.department_id:
            pool = [s for s in pool if s.department_id == c.department_id] or pool
        for s in rng.sample(pool, min(len(pool), rng.randint(6, 10))):
            rows.append(
                CommitteeMember(
                    institution_id=inst.id,
                    committee_id=c.id,
                    member_type="staff",
                    staff_id=s.id,
                    user_id=s.user_id,
                    role="member",
                    from_on=start,
                    to_on=c.valid_to,
                )
            )
        if c.committee_type in ("bos", "academic_council", "executive_council", "iqac", "finance", "governing_body"):
            for i in range(2):
                rows.append(
                    CommitteeMember(
                        institution_id=inst.id,
                        committee_id=c.id,
                        member_type="external",
                        external={
                            "name": f"Prof. External {c.committee_type[:3].upper()}{i + 1}",
                            "org": "IIT Madras" if i == 0 else "Industry (TCS)",
                            "email": f"external{i + 1}.{c.committee_type}@example.org",
                        },
                        role="member",
                        from_on=start,
                        to_on=c.valid_to,
                    )
                )
        if c.committee_type in ("anti_ragging", "grievance", "iqac") and student_users:
            for u in student_users[:2]:
                rows.append(
                    CommitteeMember(
                        institution_id=inst.id,
                        committee_id=c.id,
                        member_type="student",
                        user_id=u.id,
                        role="member",
                        from_on=start,
                        to_on=c.valid_to,
                    )
                )
        db.add_all(rows)
        ctx.count("committee_members", len(rows))
    await db.flush()

    # ---- demo users ------------------------------------------------------------------------------------------------------
    ac = by_type.get("academic_council") or by_type.get("academic_committee") or committees[0]
    bos_cse = by_type.get("bos_cse")
    ar = by_type.get("anti_ragging")
    for uname, label, sid in (
        ("chair.ac", "committee_chair_ac", ac.chair_staff_id),
        ("sec.ac", "committee_secretary_ac", ac.secretary_staff_id),
    ):
        st = next((s for s in staff if s.id == sid), None)
        u = await demo_user(
            uname,
            f"{'Chair' if 'chair' in uname else 'Secretary'} (Academic Council)",
            "faculty",
            "self",
            "staff",
            label,
        )
        if st is not None and st.user_id is None and all(x.user_id != u.id for x in staff):
            st.user_id = u.id
    await demo_user(
        "sec.ac",
        "Secretary (Academic Council)",
        "committee_secretary",
        "committee",
        "staff",
        "committee_secretary_ac",
        ac.id,
    )
    mu = await demo_user("member.ac", "Member (Academic Council)", "faculty", "self", "staff", "committee_member_ac")
    member_staff = next((s for s in teaching if s.user_id == mu.id), None) or next(
        (s for s in teaching if s.user_id is None and s.id not in (ac.chair_staff_id, ac.secretary_staff_id)),
        None,
    )
    if member_staff is not None:
        member_staff.user_id = member_staff.user_id or mu.id
        db.add(
            CommitteeMember(
                institution_id=inst.id,
                committee_id=ac.id,
                member_type="staff",
                staff_id=member_staff.id,
                user_id=mu.id,
                role="member",
                from_on=ac.constituted_on,
                to_on=ac.valid_to,
            )
        )
    su = await demo_user(
        "member.student", "Student member (Anti-ragging)", "student", "self", "student", "committee_member_student"
    )
    if ar is not None:
        db.add(
            CommitteeMember(
                institution_id=inst.id,
                committee_id=ar.id,
                member_type="student",
                user_id=su.id,
                role="member",
                from_on=ar.constituted_on,
                to_on=ar.valid_to,
            )
        )
    if bos_cse is not None:
        await demo_user(
            "sec.bos.cse",
            "Secretary (BoS CSE)",
            "committee_secretary",
            "committee",
            "staff",
            "committee_secretary_bos_cse",
            bos_cse.id,
        )
    await demo_user("pio", "Public Information Officer", "pio", "institution", "staff", "pio")
    await db.flush()
    hod_user = users.get("hod.cse")
    hod_staff = next((s for s in staff if hod_user and s.user_id == hod_user.id), None)

    # ---- meetings, resolutions, ATRs ------------------------------------------------------------------------------------
    main = [c for c in committees if c.is_active][:12] or committees
    statuses = ["minutes_approved"] * 38 + ["minutes_draft"] * 6 + ["held"] * 4 + ["scheduled"] * 8 + ["cancelled"] * 4
    rng.shuffle(statuses)
    meetings: list[tuple[Meeting, Committee]] = []
    seq: dict[tuple[uuid.UUID, int], int] = {}
    for i, status in enumerate(statuses):
        c = main[i % len(main)]
        held = (
            now + timedelta(days=rng.randint(5, 40))
            if status == "scheduled"
            else now - timedelta(days=rng.randint(10, 540))
        )
        k = (c.id, held.year)
        seq[k] = seq.get(k, 0) + 1
        members = list(
            (await db.execute(select(CommitteeMember).where(CommitteeMember.committee_id == c.id))).scalars()
        )
        present = [str(m.id) for m in members if rng.random() < 0.8] if status not in ("scheduled", "cancelled") else []
        m = Meeting(
            institution_id=inst.id,
            committee_id=c.id,
            meeting_no=f"{seq[k]}/{held.year}",
            held_on=held,
            venue_or_link=rng.choice(["Board Room", "Senate Hall", "https://meet.example.org/gov"]),
            agenda=[
                {"item": "Confirmation of the minutes of the previous meeting", "source": "standing"},
                {"item": "Action taken report on previous minutes", "source": "atr"},
                {
                    "item": rng.choice(
                        ["Approval of revised curriculum", "Budget review", "Student welfare measures", "Policy review"]
                    )
                },
            ],
            quorum_met=(len(present) >= max(1, len(members) // 2)) if present else None,
            attendance={"present_member_ids": present, "invitees": [], "total": len(members)} if present else None,
            minutes_text="Minutes recorded. The committee deliberated on the agenda items and resolved as below."
            if status in ("minutes_approved", "minutes_draft")
            else None,
            status=status,
            created_by=users["registrar"].id if "registrar" in users else None,
        )
        db.add(m)
        meetings.append((m, c))
    await db.flush()
    ctx.count("meetings", len(meetings))
    for m, _c in meetings:
        if m.status in ("minutes_approved", "minutes_draft"):
            meta(
                "meeting",
                m.id,
                {
                    "notice_sent_at": (m.held_on - timedelta(days=rng.choice([3, 7, 10]))).isoformat(),
                    "minutes_version": 1,
                    "submitted": m.status == "minutes_draft" and rng.random() < 0.5,
                    "approval": [
                        {"action": "approved", "via": "seed", "at": (m.held_on + timedelta(days=5)).isoformat()}
                    ]
                    if m.status == "minutes_approved"
                    else [],
                },
            )

    regs = [
        r
        for (r,) in (
            await db.execute(text("SELECT id FROM regulations WHERE institution_id = :i LIMIT 5"), {"i": inst.id})
        ).all()
    ]
    runs = [
        r
        for (r,) in (
            await db.execute(
                text("SELECT id FROM result_processing_runs WHERE institution_id = :i LIMIT 5"), {"i": inst.id}
            )
        ).all()
    ]
    degs = [
        r
        for (r,) in (
            await db.execute(text("SELECT id FROM degrees_awarded WHERE institution_id = :i LIMIT 5"), {"i": inst.id})
        ).all()
    ]
    approved = [(m, c) for m, c in meetings if m.status == "minutes_approved"]
    counters: dict[str, int] = {}
    resolutions: list[Resolution] = []
    subjects = [
        "Approval of the revised scheme and syllabus",
        "Constitution of a sub-committee",
        "Adoption of the academic calendar",
        "Approval of results",
        "Ratification of appointments",
        "Approval of the annual budget",
        "Revision of examination rules",
        "Approval of a new elective",
    ]
    for n in range(240):
        m, c = approved[n % len(approved)]
        code = str((c.quorum_rule or {}).get("code") or TYPE_CODES.get(c.committee_type, "CMT"))
        key = f"{code}/{m.held_on.year}"
        counters[key] = counters.get(key, 0) + 1
        owner = rng.choice(teaching) if n % 3 == 0 else None
        if n < 6 and hod_staff is not None:
            owner = hod_staff
        r = Resolution(
            institution_id=inst.id,
            meeting_id=m.id,
            number=f"{key}/{counters[key]}",
            subject=rng.choice(subjects),
            text="Resolved to approve as placed before the committee, with the modifications recorded in the minutes.",
            action_owner_staff_id=owner.id if owner else None,
            due_on=(m.held_on + timedelta(days=30)).date() if owner else None,
            status=rng.choice(["passed"] * 6 + ["implemented"] * 3 + ["deferred", "rejected"]) if n >= 30 else "passed",
        )
        db.add(r)
        resolutions.append(r)
    await db.flush()
    ctx.count("resolutions", len(resolutions))
    owned = [r for r in resolutions if r.action_owner_staff_id and r.status == "passed"]
    for r in owned[:30]:
        db.add(
            ActionTakenReport(
                institution_id=inst.id,
                resolution_id=r.id,
                report_text="Action initiated; the department has circulated the revised scheme to the faculty.",
                submitted_by=next((s.user_id for s in staff if s.id == r.action_owner_staff_id), None),
                status="submitted",
            )
        )
    ctx.count("atr_pending", min(30, len(owned)))
    for r in [x for x in resolutions if x.status == "implemented"][:20]:
        db.add(
            ActionTakenReport(
                institution_id=inst.id,
                resolution_id=r.id,
                report_text="Implemented.",
                status="accepted",
            )
        )
    linkable = [r for r in resolutions if r.status in ("passed", "implemented") and not r.action_owner_staff_id]
    links = 0
    for r, (etype, ids, table, col) in zip(
        linkable[:15],
        [("regulation", regs, "regulations", "approval_resolution_id")] * 5
        + [("result_run", runs, "result_processing_runs", "approval_resolution_id")] * 5
        + [("degree_award", degs, "degrees_awarded", "approval_resolution_id")] * 5,
        strict=False,
    ):
        if not ids:
            continue
        eid = ids[links % len(ids)]
        r.linked_entity = {"entity_type": etype, "entity_id": str(eid)}
        await db.execute(text(f"UPDATE {table} SET {col} = :r WHERE id = :e"), {"r": r.id, "e": eid})  # noqa: S608
        links += 1
    await db.flush()

    # ---- policies --------------------------------------------------------------------------------------------------------
    cats = [
        "academic",
        "examination",
        "it",
        "posh",
        "anti_ragging",
        "research_ethics",
        "data_protection",
        "hr",
        "finance",
        "hostel",
        "conduct",
    ]
    staff_users = [s.user_id for s in staff if s.user_id]
    policy_res = linkable[15:40]
    ack_target = 0
    for i in range(25):
        cat = cats[i % len(cats)]
        status = "draft" if i >= 21 else ("superseded" if i in (3, 14) else "approved")
        p = Policy(
            institution_id=inst.id,
            title=f"{cat.replace('_', ' ').title()} Policy",
            category=cat,
            version="2.0" if i in (3, 14) else ("1.0" if i < 11 else "1.1"),
            effective_from=today - timedelta(days=rng.randint(30, 600)),
            file_url=f"/files/policies/{cat}-{i}.pdf",
            status=status,
            approved_resolution_id=policy_res[i].id if status != "draft" and i < len(policy_res) else None,
        )
        db.add(p)
        await db.flush()
        requires_ack = cat in ("conduct", "it", "posh") and status == "approved" and ack_target < 5
        if requires_ack:
            ack_target += 1
        meta(
            "policy",
            p.id,
            {
                "owner": str(users["registrar"].id) if "registrar" in users else None,
                "summary": f"Institutional {cat.replace('_', ' ')} policy.",
                "requires_ack": requires_ack,
                "website": status == "approved" and i % 2 == 0,
                "published": status == "approved",
                "stage": "submitted"
                if status == "draft" and i == 22
                else ("published" if status == "approved" else status),
            },
        )
        if requires_ack and staff_users:
            acked = rng.sample(staff_users, int(len(staff_users) * 0.6))
            meta("policy_ack", p.id, {str(u): (now - timedelta(days=rng.randint(1, 60))).isoformat() for u in acked})
        if policy_res and status != "draft" and i < len(policy_res):
            policy_res[i].linked_entity = {"entity_type": "policy", "entity_id": str(p.id), "label": p.title}
    ctx.count("policies", 25)

    # ---- legal cases -----------------------------------------------------------------------------------------------------
    legal_user = users.get("legal.off")
    legal_staff = next((s for s in staff if legal_user and s.user_id == legal_user.id), None)
    courts = [
        "High Court of Telangana",
        "District Court, Hyderabad",
        "Consumer Forum",
        "Labour Court",
        "Supreme Court of India",
    ]
    for i in range(15):
        status = ["open", "hearing", "hearing", "judgement", "appeal", "closed"][i % 6]
        lc = LegalCase(
            institution_id=inst.id,
            case_no=f"WP/{today.year - (i % 4)}/{1000 + i}",
            court=courts[i % len(courts)],
            case_type=rng.choice(["writ", "service", "consumer", "civil", "labour"]),
            parties={"petitioner": f"Petitioner {i + 1}", "respondent": inst.name},
            counsel=rng.choice(["Adv. R. Rao", "Adv. S. Menon", "Adv. K. Iyer"]),
            filed_on=today - timedelta(days=rng.randint(60, 900)),
            next_hearing=(today + timedelta(days=7 if i == 0 else rng.randint(2, 60)))
            if status in ("open", "hearing", "appeal")
            else None,
            status=status,
            documents=[{"name": "Petition copy", "url": f"/files/legal/{i}/petition.pdf"}],
            outcome="Disposed in favour of the institution." if status in ("judgement", "closed") else None,
            owner_staff_id=legal_staff.id if legal_staff else None,
        )
        db.add(lc)
        await db.flush()
        meta(
            "legal",
            lc.id,
            {
                "institution_role": "respondent",
                "hearings": [
                    {"held_on": str(today - timedelta(days=30 * k + 10)), "notes": "Adjourned.", "next_hearing": None}
                    for k in range(rng.randint(1, 4))
                ],
            },
        )
    ctx.count("legal_cases", 15)

    # ---- RTI -------------------------------------------------------------------------------------------------------------
    pio_user = users.get("pio")
    pio_staff = next((s for s in staff if pio_user and s.user_id == pio_user.id), None) or teaching[-1]
    for i in range(40):
        received = today - timedelta(days=rng.randint(0, 200))
        status = ["received", "assigned", "responded", "responded", "closed"][i % 5]
        if i < 3:
            status = "appealed"
        responded = (
            received + timedelta(days=rng.randint(10, 35)) if status in ("responded", "closed", "appealed") else None
        )
        bpl = i % 9 == 0
        rq = RtiRequest(
            institution_id=inst.id,
            request_no=f"RTI/{received.year}/{i + 1:04d}",
            applicant={"name": f"Applicant {i + 1}", "address": "Hyderabad", "phone": f"98480{i:05d}", "is_bpl": bpl},
            received_on=received,
            due_on=received + timedelta(days=30),
            subject=rng.choice(
                [
                    "Copies of admission records",
                    "Faculty appointment details",
                    "Fee collection statement",
                    "Examination results data",
                ]
            ),
            pio_staff_id=pio_staff.id if status != "received" else None,
            fee_paise=0 if bpl else 1000,
            status=status,
            responded_on=responded,
            first_appeal={
                "grounds": "Incomplete information",
                "filed_on": str(today - timedelta(days=5)),
                "status": "pending",
            }
            if i < 3
            else None,
        )
        db.add(rq)
        await db.flush()
        meta(
            "rti",
            rq.id,
            {
                "mode": "in_person",
                "fee_status": "waived" if bpl else "paid",
                "response_text": "Information furnished." if responded else None,
            },
        )
    ctx.count("rti_requests", 40)

    # ---- audit registers + paras ---------------------------------------------------------------------------------------
    regs_out: list[AuditRegister] = list(
        (
            await db.execute(
                select(AuditRegister).where(
                    AuditRegister.institution_id == inst.id, AuditRegister.audit_type.in_(("financial_statutory", "ag"))
                )
            )
        ).scalars()
    )
    for t, auditor in (
        ("financial_statutory", "M/s Rao & Co., Chartered Accountants"),
        ("ag", "Office of the Accountant General"),
    ):
        if not any(r.audit_type == t for r in regs_out):
            ar_ = AuditRegister(
                institution_id=inst.id,
                audit_type=t,
                period_label=f"FY{today.year - 1}-{str(today.year)[-2:]}",
                auditor=auditor,
                status="open",
            )
            db.add(ar_)
            regs_out.append(ar_)
    await db.flush()
    acct = users.get("accountant")
    acct_staff = next((s for s in staff if acct and s.user_id == acct.id), None)
    for i in range(25):
        reg = regs_out[i % len(regs_out)]
        owner = hod_staff if i == 1 and hod_staff else (acct_staff or teaching[0])
        para = AuditPara(
            institution_id=inst.id,
            audit_register_id=reg.id,
            para_no=f"{i // len(regs_out) + 1}.{i % 7 + 1}",
            description=rng.choice(
                [
                    "Non-recovery of hostel dues",
                    "Excess payment of honorarium",
                    "Delay in remittance of TDS",
                    "Idle equipment",
                    "Advances not adjusted",
                ]
            ),
            amount_paise=rng.randint(10_000, 900_000) * 100,
            owner_staff_id=owner.id if owner else None,
            status=["open", "open", "replied", "settled", "dropped"][i % 5],
            reply_text="Recovery initiated." if i % 5 >= 2 else None,
        )
        db.add(para)
    await db.flush()
    ctx.count("audit_paras", 25)

    # ---- e-files ---------------------------------------------------------------------------------------------------------
    movers = [
        u
        for u in (users.get(n) for n in ("faculty.1", "hod.cse", "accountant", "registrar", "principal", "dean.eng"))
        if u
    ]
    if len(movers) >= 2:
        sla = 7
        for i in range(120):
            creator = movers[i % len(movers)]
            hops = rng.randint(1, 4)
            path = [creator] + [rng.choice(movers) for _ in range(hops)]
            created = now - timedelta(days=rng.randint(20, 120))
            closed = i % 4 == 0 and i >= 10  # the first 10 stay pending beyond the SLA
            f = Efile(
                institution_id=inst.id,
                file_no=f"EF/{created.year}/{i + 1:05d}",
                subject=rng.choice(
                    [
                        "Purchase of lab equipment",
                        "Leave encashment proposal",
                        "Guest lecture honorarium",
                        "Repair of hostel block",
                        "Conference travel grant",
                    ]
                ),
                category=rng.choice(["purchase", "establishment", "academic", "finance"]),
                created_by=creator.id,
                current_holder_user_id=path[-1].id,
                priority=rng.choice(["normal", "normal", "high", "urgent"]),
                status="closed" if closed else "in_movement",
                closed_at=now - timedelta(days=1) if closed else None,
            )
            db.add(f)
            await db.flush()
            # the last movement is recent (within the SLA) except for the first 10 open files, pending beyond it
            last = now - timedelta(days=sla + 3 + i) if i < 10 else now - timedelta(days=rng.randint(0, sla - 2))
            stamps = sorted(created + (last - created) * rng.random() for _ in range(len(path) - 1)) + [last]
            for h in range(len(path)):
                stamp = stamps[h]
                db.add(
                    EfileMovement(
                        institution_id=inst.id,
                        efile_id=f.id,
                        from_user_id=path[h - 1].id if h else creator.id,
                        to_user_id=path[h].id,
                        noting="Initial noting: proposal placed for consideration."
                        if h == 0
                        else rng.choice(
                            [
                                "Forwarded for approval.",
                                "Please examine and put up.",
                                "Returned with a query.",
                                "Approved; may be processed.",
                            ]
                        ),
                        action="forward" if h == 0 or rng.random() < 0.8 else "return",
                        moved_at=stamp,
                    )
                )
        ctx.count("efiles", 120)
    await db.flush()
