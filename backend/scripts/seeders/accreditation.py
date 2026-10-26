"""``accreditation`` demo seeder (Prompts/32 §32.2) — ``seed_demo_institution.py --only accreditation``.

Enables the Phase 32 features (NAAC, NIRF, AICTE / UGC, evidence repository, IQAC cycles, audit registers; NBA when
``obe.attainment`` is on), makes sure the criteria trees / metric definitions of revision ``0032`` exist, then writes
metric values for the last 5 academic years — computed by the engine from the seeded modules, plus the event-fed
research / PhD / placement / alumni values pushed as ``*.stats_published`` would, a few manual inputs (green / energy
audit) and one pending override —, 400 evidence documents tagged across NAAC criteria (a share verified), one NAAC
cycle (criterion responses in mixed states with best practices and distinctiveness narratives, owners from the teaching
staff), one NBA SAR cycle for the B.Tech CSE programme, NIRF and AISHE submissions for the last 2 years (one submitted
with an ack ref, one generated) and 6 audit registers with findings. Uses the existing demo accounts ``iqac``,
``obe``, ``auditor.tmp`` (time-boxed peer team) — no new credentials. Idempotent: skipped when evidence exists.
"""

import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select

DOC_TYPES = ("policy", "minutes", "certificate", "report", "photo", "mou", "circular", "feedback_analysis")
PUSHED = {
    "research.publications_per_teacher": (0.6, 1.8),
    "research.grants_amount": (8_000_000_00, 40_000_000_00),
    "research.consultancy_revenue": (500_000_00, 4_000_000_00),
    "research.patents": (2, 14),
    "research.fdp_participation": (40, 85),
    "nirf.pu": (0.6, 1.8),
    "nirf.qp": (20, 140),
    "nirf.ipr": (0, 6),
    "nirf.fppp": (9_000_000_00, 44_000_000_00),
    "nirf.gphd": (2, 12),
    "faculty.phd_guides": (12, 30),
    "research.phd_awarded": (2, 12),
    "placement.placed_pct": (62, 91),
    "nirf.gms": (380_000_00, 720_000_00),
    "students.higher_studies_pct": (6, 18),
    "academics.internships_pct": (55, 96),
    "alumni.total": (1200, 5200),
    "alumni.donations_total_paise": (200_000_00, 2_500_000_00),
    "library.books_added": (900, 3200),
    "library.eresources_count": (12, 40),
}


@seeder("accreditation", after=["hr", "students", "research", "phd", "placement"])
async def seed_accreditation(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.db.session import bind_tenant, set_tenant
    from app.models.academic import Program
    from app.models.accreditation import (
        AccreditationCycle,
        AccreditationFramework,
        AuditRegister,
        ComplianceSubmission,
        CriterionResponse,
        EvidenceDocument,
        FrameworkCriterion,
        MetricDefinition,
        MetricValue,
    )
    from app.models.hr import Staff
    from app.models.platform import Institution, InstitutionSetting, User
    from app.schemas.accreditation import MetricComputeRequest
    from app.services.accreditation.disclosure_service import DisclosureService
    from app.services.accreditation.metric_service import MetricService, label_for_year
    from app.services.feature_service import FeatureService

    db = ctx.db
    rng = random.Random(32)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if (
        await db.execute(
            select(func.count()).select_from(EvidenceDocument).where(EvidenceDocument.institution_id == inst.id)
        )
    ).scalar_one():
        return

    # ---- catalogue (revision 0032 data; re-asserted so a database migrated before 0032 still seeds) --------------------
    if not (
        await db.execute(select(func.count()).select_from(FrameworkCriterion).where(FrameworkCriterion.code == "2.3.1"))
    ).scalar_one():
        from app.services.accreditation.catalogue import seed_accreditation_catalogue

        conn = await db.connection()
        await conn.run_sync(seed_accreditation_catalogue)
        ctx.count("framework_catalogue")

    features = FeatureService(db)
    effective = await features.effective(inst.id)
    for key in (
        "accreditation.naac",
        "accreditation.nirf",
        "accreditation.aicte_ugc",
        "accreditation.evidence_repo",
        "accreditation.iqac_cycles",
        "accreditation.audit_registers",
        "accreditation.nba",
    ):
        if key in effective:
            continue
        try:
            await features.set_platform_flag(
                inst.id, key, enabled=True, reason="demo seed (Phase 32)", config=None, confirm_dependencies=True
            )
            ctx.count("feature_overrides")
        except (APIError, KeyError) as exc:
            print(f"   accreditation: {key} not enabled ({exc})")

    now = datetime.now(UTC)
    today = now.date()
    start_year = today.year if today.month >= 6 else today.year - 1
    years = [start_year - i for i in range(5)][::-1]
    labels = [label_for_year(y) for y in years]
    users = {u.username: u for u in (await db.execute(select(User).where(User.institution_id == inst.id))).scalars()}
    iqac_user = users.get("iqac")
    defs = {d.key: d for d in (await db.execute(select(MetricDefinition))).scalars()}
    teaching = list(
        (
            await db.execute(
                select(Staff)
                .where(Staff.institution_id == inst.id, Staff.staff_category == "teaching", Staff.deleted_at.is_(None))
                .order_by(Staff.employee_id)
            )
        ).scalars()
    )

    # ---- metric values: computed, pushed, manual, override ---------------------------------------------------------------
    svc = MetricService(db, None, institution_id=inst.id)
    for label in labels:
        try:
            out = await svc.compute(MetricComputeRequest(period_label=label))
            ctx.count("metric_values_computed", out.computed)
            for f in out.failed:
                print(f"   accreditation: {label} {f.key} failed: {f.error[:160]}")
        except APIError as exc:
            print(f"   accreditation: compute {label} failed ({exc})")
        for i, (key, (lo, hi)) in enumerate(PUSHED.items()):
            if key not in defs:
                continue
            growth = 1 + 0.06 * labels.index(label)
            v = (lo + (hi - lo) * rng.random()) * growth
            v = round(v, 2) if isinstance(lo, float) else int(v)
            if defs[key].unit == "pct":
                v = min(v, 99)
            await svc.consume_published(
                "research.stats_published"
                if key.startswith(("research.", "nirf.p", "nirf.q", "nirf.i", "nirf.f"))
                else "metrics.publish",
                {"period_label": label, "metrics": {key: v}},
            )
            if i == 0:
                ctx.count("metric_values_pushed_periods")
    for label in labels[-2:]:
        for key, val in (("values.green_audit_score", 8.2), ("values.energy_audit_score", 7.6), ("nirf.pcs", 16)):
            if key in defs:
                db.add(
                    MetricValue(
                        institution_id=inst.id,
                        metric_key=key,
                        period_label=label,
                        value=Decimal(str(val)),
                        breakdown={"note": "demo manual input"},
                        computed_at=now,
                        source="manual",
                        overridden_by=iqac_user.id if iqac_user else None,
                    )
                )
                ctx.count("metric_values_manual")
    await db.flush()
    # one pending override proposal (HOD) and one applied + verified override
    cur = labels[-1]
    pend = await svc.value_row("research.publications_per_teacher", cur)
    if pend is not None:
        db.add(
            InstitutionSetting(
                institution_id=inst.id,
                college_id=None,
                category="accreditation_meta",
                key=f"override:{pend.id}",
                value={
                    "pending": {
                        "value": "1.42",
                        "numerator": None,
                        "denominator": None,
                        "reason": "Two Scopus papers of the CSE department were missed by the bibliographic import",
                        "evidence_ids": [],
                        "proposed_by": None,
                        "proposed_at": now.isoformat(),
                        "scope": "department",
                    }
                },
                value_type="json",
            )
        )
        ctx.count("override_proposals")
    ver = await svc.value_row("faculty.fsr", labels[-2])
    if ver is not None and ver.value is not None:
        stale = {"value": str(ver.value), "computed_at": now.isoformat()}
        ver.value, ver.source, ver.override_reason = (
            Decimal("18.5"),
            "override",
            "Visiting faculty counted per AICTE norms",
        )
        ver.verified_by, ver.verified_at = iqac_user.id if iqac_user else None, now
        db.add(
            InstitutionSetting(
                institution_id=inst.id,
                college_id=None,
                category="accreditation_meta",
                key=f"override:{ver.id}",
                value={"stale_auto": stale, "trail": [{"at": now.isoformat(), "action": "verify"}]},
                value_type="json",
            )
        )
    await db.flush()
    await DisclosureService(db, None, institution_id=inst.id).refresh()

    # ---- evidence (400 documents across NAAC criteria) ----------------------------------------------------------------------
    naac = (
        await db.execute(select(AccreditationFramework).where(AccreditationFramework.code == "NAAC_2024"))
    ).scalar_one_or_none()
    if naac is None:
        print("   accreditation: NAAC framework missing — skipped")
        return
    crits = list(
        (await db.execute(select(FrameworkCriterion).where(FrameworkCriterion.framework_id == naac.id))).scalars()
    )
    leaves = [c for c in crits if c.code.count(".") == 2]
    uploaders = [s.user_id for s in teaching if s.user_id][:30] or ([iqac_user.id] if iqac_user else [None])
    evidence: list[EvidenceDocument] = []
    for i in range(400):
        c = leaves[i % len(leaves)]
        label = labels[i % len(labels)]
        e = EvidenceDocument(
            institution_id=inst.id,
            framework_criterion_id=c.id,
            metric_key=c.metric_key,
            period_label=label,
            title=f"{c.code} — {rng.choice(DOC_TYPES).replace('_', ' ').title()} {label} #{i + 1}",
            doc_type=rng.choice(DOC_TYPES),
            file_url=f"https://files.demo.septronuniverse.in/evidence/{c.code}/{label}/{i + 1}.pdf",
            uploaded_by=rng.choice(uploaders),
            verified_by=iqac_user.id if iqac_user and i % 3 else None,
            verified_at=now - timedelta(days=rng.randint(1, 300)) if i % 3 else None,
            tags=[f"criterion-{c.code.split('.')[0]}", label],
        )
        db.add(e)
        evidence.append(e)
    await db.flush()
    ctx.count("evidence_documents", len(evidence))
    for n, (module, title, code) in enumerate(
        (
            ("events", "Event report: National seminar on IPR", "3.2.2"),
            ("research", "MoU signed with an industry partner", "3.5.1"),
            ("placement", "Placement statistics published", "5.2.1"),
        )
    ):
        db.add(
            InstitutionSetting(
                institution_id=inst.id,
                college_id=None,
                category="accreditation_meta",
                key=f"suggestion:{module}-demo-{n}",
                value={
                    "module": module,
                    "entity": module,
                    "entity_id": None,
                    "title": title,
                    "criterion_code": code,
                    "period_label": cur,
                    "file_url": None,
                    "status": "pending",
                    "created_at": now.isoformat(),
                },  # fmt: skip
                value_type="json",
            )
        )

    # ---- NAAC cycle -------------------------------------------------------------------------------------------------------
    coord = teaching[0] if teaching else None
    cycle = AccreditationCycle(
        institution_id=inst.id,
        framework_id=naac.id,
        name=f"NAAC Cycle 3 ({years[0]}–{str(years[-1] + 1)[-2:]})",
        period_from=date(years[0], 6, 1),
        period_to=date(years[-1] + 1, 5, 31),
        submission_due_on=today + timedelta(days=75),
        coordinator_staff_id=coord.id if coord else None,
        status="drafting",
    )
    db.add(cycle)
    await db.flush()
    window = f"{years[0]}-{str(years[-1] + 1)[-2:]}"
    states = ("approved", "in_review", "draft", "draft", "approved", "final", "draft")
    for k, c in enumerate(leaves):
        owner = teaching[k % len(teaching)] if teaching else None
        status = states[k % len(states)] if c.code not in ("7.2.1", "7.3.1") else "in_review"
        status = "approved" if status == "final" else status
        mv = (
            (
                await db.execute(
                    select(MetricValue.id).where(
                        MetricValue.institution_id == inst.id,
                        MetricValue.metric_key == c.metric_key,
                        MetricValue.period_label.in_([*labels, window]),
                    )
                )
            )
            .scalars()
            .all()
            if c.metric_key
            else []
        )
        narrative = (
            f"<p>The institution addresses {c.title.lower()} through a documented process reviewed by the IQAC every "
            f"semester. Data for {window} is drawn from the ERP and verified by the department.</p>"
        )
        if c.code == "7.2.1":
            narrative = (
                "<h3>Best practice 1: Outcome-based mentoring</h3><h4>Objectives</h4><p>Close attainment gaps early.</p>"
                "<h4>The practice</h4><p>Mentors review CO attainment with mentees after each CIA.</p>"
                "<h3>Best practice 2: Green campus audit cycle</h3><h4>The practice</h4><p>Annual green and energy "
                "audits with student auditors and published action-taken reports.</p>"
            )
        elif c.code == "7.3.1":
            narrative = (
                "<h3>Industry-integrated curriculum</h3><p>Every programme runs a semester-long industry studio.</p>"
            )
        r = CriterionResponse(
            institution_id=inst.id,
            cycle_id=cycle.id,
            framework_criterion_id=c.id,
            narrative=narrative if status != "draft" or k % 2 else None,
            metric_value_ids=[str(x) for x in mv],
            evidence_ids=[str(e.id) for e in evidence if e.framework_criterion_id == c.id][:3],
            owner_staff_id=owner.id if owner else None,
            status=status,
            reviewed_by=iqac_user.id if status == "approved" and iqac_user else None,
        )
        db.add(r)
        await db.flush()
        db.add(
            InstitutionSetting(
                institution_id=inst.id,
                college_id=None,
                category="accreditation_meta",
                key=f"response:{r.id}",
                value={"due_on": (today + timedelta(days=10 + k % 30)).isoformat(), "versions": [], "review_trail": []},
                value_type="json",
            )
        )
        ctx.count("criterion_responses")
    ctx.count("accreditation_cycles")

    # ---- NBA SAR cycle (B.Tech CSE) ------------------------------------------------------------------------------------------
    nba = (
        await db.execute(select(AccreditationFramework).where(AccreditationFramework.code == "NBA_UG_ENGG"))
    ).scalar_one_or_none()
    cse = (
        await db.execute(
            select(Program)
            .where(Program.institution_id == inst.id, Program.code.ilike("%CSE%"), Program.level == "ug")
            .limit(1)
        )
    ).scalar_one_or_none()
    if nba is not None and cse is not None:
        sar = AccreditationCycle(
            institution_id=inst.id,
            framework_id=nba.id,
            program_id=cse.id,
            college_id=cse.college_id,
            name=f"NBA SAR — {cse.name}",
            period_from=date(years[-1], 6, 1),
            period_to=date(years[-1] + 1, 5, 31),
            submission_due_on=today + timedelta(days=120),
            status="data_collection",
        )
        db.add(sar)
        await db.flush()
        for c in (
            await db.execute(select(FrameworkCriterion).where(FrameworkCriterion.framework_id == nba.id))
        ).scalars():
            if c.code.split(".")[0] in ("3", "4") and "." in c.code:
                mv = (
                    (
                        await db.execute(
                            select(MetricValue.id).where(
                                MetricValue.institution_id == inst.id,
                                MetricValue.metric_key == c.metric_key,
                                MetricValue.period_label == labels[-1],
                            )
                        )
                    )
                    .scalars()
                    .all()
                    if c.metric_key
                    else []
                )
                db.add(
                    CriterionResponse(
                        institution_id=inst.id,
                        cycle_id=sar.id,
                        framework_criterion_id=c.id,
                        metric_value_ids=[str(x) for x in mv],
                        evidence_ids=[],
                        status="draft",
                    )
                )
        ctx.count("accreditation_cycles")

    # ---- submissions (NIRF / AISHE, last 2 years) ---------------------------------------------------------------------------------
    from app.services.accreditation.submission_service import SubmissionService

    ssvc = SubmissionService(db, None, institution_id=inst.id)
    for stype, fw_code in (("nirf_data", "NIRF"), ("aishe", "AISHE")):
        fw = (
            await db.execute(select(AccreditationFramework).where(AccreditationFramework.code == fw_code))
        ).scalar_one_or_none()
        if fw is None:
            continue
        for j, label in enumerate(labels[-2:]):
            s = ComplianceSubmission(
                institution_id=inst.id, framework_id=fw.id, period_label=label, submission_type=stype
            )
            db.add(s)
            await db.flush()
            s.payload = await ssvc.build_payload(s)
            if j == 0:
                s.status, s.submitted_on, s.ack_ref = (
                    "acknowledged",
                    date(int(label[:4]) + 1, 1, 20),
                    f"{fw_code}-ACK-{label}-{rng.randint(1000, 9999)}",
                )
            else:
                s.status = "generated"
            ctx.count("compliance_submissions")

    # ---- audit registers (6 with findings) -------------------------------------------------------------------------------------
    hods = teaching[:6]
    for k, (atype, auditor) in enumerate(
        (
            ("academic", "Academic & Administrative Audit Committee"),
            ("administrative", "External AAA team"),
            ("green", "GreenCert Auditors LLP"),
            ("energy", "Bureau-accredited energy auditor"),
            ("gender", "Gender Audit Cell"),
            ("financial_statutory", "M/s Rao & Associates, Chartered Accountants"),
        )
    ):
        findings = []
        for n in range(3):
            owner = hods[(k + n) % len(hods)] if hods else None
            closed = (k + n) % 3 == 0
            findings.append(
                {
                    "no": n + 1,
                    "text": f"{atype.replace('_', ' ').title()} finding {n + 1}: document the action-taken report",
                    "owner_staff_id": str(owner.id) if owner else None,
                    "due_on": (today + timedelta(days=30 * (n - 1))).isoformat(),
                    "status": "closed" if closed else ("in_progress" if n == 1 else "open"),
                    "action_taken": "Completed and filed" if closed else None,
                }
            )
        db.add(
            AuditRegister(
                institution_id=inst.id,
                audit_type=atype,
                period_label=labels[-2] if k % 2 else labels[-1],
                auditor=auditor,
                report_url=f"https://files.demo.septronuniverse.in/audits/{atype}-{labels[-1]}.pdf",
                findings=findings,
                status="in_progress",
            )
        )
        ctx.count("audit_registers")
    await db.flush()
