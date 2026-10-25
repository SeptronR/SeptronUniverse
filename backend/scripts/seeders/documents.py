"""``documents`` demo seeder (Prompts/26 §26.2) — ``seed_demo_institution.py --only documents``.

Enables the Phase 26 features, makes sure the platform default templates exist, then: institution overrides of 6
templates (branding; published), the register back-fill of earlier seeds (grade cards, transcripts, degrees, hall
tickets, event certificates), fresh ID cards (and bonafide certificates) for the students up to ~2,000 issued
documents, serial registers with reserved serials and 3 voided ones, 120 certificate requests across statuses (30 fee
pending, 20 ready for pickup, 5 rejected) and 3 finished bulk jobs. Idempotent: skipped when requests exist.
"""

import random
from datetime import UTC, datetime, timedelta

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select

TARGET_DOCUMENTS = 2000


@seeder("documents", after=["students", "hr", "fees", "results", "facilities"])
async def seed_documents(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.db.session import bind_tenant, set_tenant
    from app.enums.documents import DEFAULT_REQUEST_RULES
    from app.models.documents import CertificateRequest, DocumentTemplate, IssuedDocument
    from app.models.hr import Staff
    from app.models.platform import BackgroundJob, Institution, User
    from app.models.students import Student, StudentProgramEnrollment
    from app.services.documents.backfill_service import BackfillService
    from app.services.documents.defaults import default_template
    from app.services.documents.registers_service import RegistersService
    from app.services.documents.render_service import RenderService
    from app.services.feature_service import FeatureService
    from app.services.institution_defaults import seed_document_templates

    db = ctx.db
    rng = random.Random(26)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if (
        await db.execute(
            select(func.count()).select_from(CertificateRequest).where(CertificateRequest.institution_id == inst.id)
        )
    ).scalar_one():
        return

    features = FeatureService(db)
    effective = await features.effective(inst.id)
    for key in (
        "documents.templates",
        "documents.bulk_generation",
        "documents.certificate_requests",
        "documents.serial_registers",
        "documents.watermark_signed_links",
    ):
        if key in effective:
            continue
        try:
            await features.set_platform_flag(
                inst.id, key, enabled=True, reason="demo seed (Phase 26)", config=None, confirm_dependencies=True
            )
            ctx.count("feature_overrides")
        except (APIError, KeyError) as exc:
            print(f"   documents: {key} not enabled ({exc})")

    ctx.count("platform_templates", await (await db.connection()).run_sync(seed_document_templates))

    users = list(
        (await db.execute(select(User).where(User.institution_id == inst.id).order_by(User.username))).scalars()
    )
    by_name = {u.username: u for u in users}
    actor = by_name.get("registrar") or (users[0] if users else None)
    actor_id = actor.id if actor else None

    # ---- 6 institution overrides (branding) -------------------------------------------------------------------------------
    for t in ("bonafide", "conduct", "tc", "id_card", "experience", "course_completion"):
        d = default_template(t)
        layout = dict(d["layout"])
        layout["blocks"] = [
            {**b, "props": {**(b.get("props") or {}), "logo": True, "band": "#1f3a8a"}}
            if b.get("type") == "header"
            else b
            for b in layout["blocks"]
        ]
        row = DocumentTemplate(
            institution_id=inst.id,
            template_type=t,
            name=f"{inst.short_name or inst.name} {d['name']}"[:120],
            layout={**layout, "_meta": {"status": "published", "change_note": "Institution branding (demo)"}},
            html_template=d["html_template"],
            css=(d["css"] or "") + ".hdr h1{color:#1f3a8a}",
            page_size=d["page_size"],
            variables=d["variables"],
            is_default=True,
            version=1,
            created_by=actor_id,
        )
        db.add(row)
        await db.flush()
        row.layout = {**row.layout, "_meta": {**row.layout["_meta"], "family": str(row.id)}}
        ctx.count("template_overrides")
    await db.flush()

    # ---- back-fill + fresh documents ----------------------------------------------------------------------------------------
    report = await BackfillService(db, None, institution_id=inst.id).run()
    for k, v in report.items():
        if isinstance(v, int):
            ctx.count(f"backfilled_{k}", v)
    render = RenderService(db, None, institution_id=inst.id)
    enrols = list(
        (
            await db.execute(
                select(StudentProgramEnrollment)
                .where(
                    StudentProgramEnrollment.institution_id == inst.id, StudentProgramEnrollment.deleted_at.is_(None)
                )
                .order_by(StudentProgramEnrollment.admission_date)
            )
        ).scalars()
    )

    async def issued_count() -> int:
        return int(
            (
                await db.execute(
                    select(func.count()).select_from(IssuedDocument).where(IssuedDocument.institution_id == inst.id)
                )
            ).scalar_one()
        )

    have = await issued_count()
    for e in enrols:
        if have >= TARGET_DOCUMENTS:
            break
        try:
            async with db.begin_nested():
                await render.render("id_card", "student_program_enrollment", e.id, issued_by=actor_id)
            have += 1
            ctx.count("id_cards")
        except APIError as exc:
            print(f"   documents: id card skipped ({exc.message})")
            break
    for e in enrols:
        if have >= TARGET_DOCUMENTS:
            break
        async with db.begin_nested():
            await render.render(
                "bonafide",
                "student_program_enrollment",
                e.id,
                register="bonafide",
                variables_override={"purpose": rng.choice(["Bank loan", "Passport", "Scholarship", "Bus pass"])},
                issued_by=actor_id,
            )
        have += 1
        ctx.count("bonafide")
    staff = list((await db.execute(select(Staff).where(Staff.institution_id == inst.id).limit(20))).scalars())
    for s in staff[:10]:
        async with db.begin_nested():
            await render.render("service", "staff", s.id, issued_by=actor_id)
        ctx.count("service_letters")

    # ---- serial registers: reserve, void 3 ------------------------------------------------------------------------------
    regs = RegistersService(db, None, institution_id=inst.id)
    for reg in ("provisional", "tc", "migration"):
        rows = await regs.reserve(reg, 5)
        ctx.count("serials_reserved", len(rows))
    for reg in ("provisional", "tc", "migration"):
        rows = await regs.rows(reg, "reserved")
        if rows:
            await regs.void(reg, rows[-1].serial_no, "Misprint — spoiled form (demo)")
            ctx.count("serials_voided")

    # ---- 120 certificate requests --------------------------------------------------------------------------------------
    students = list(
        (
            await db.execute(
                select(Student).where(Student.institution_id == inst.id, Student.user_id.is_not(None)).limit(150)
            )
        ).scalars()
    )
    plan = (
        ["fee_pending"] * 30
        + ["pickup"] * 20
        + ["rejected"] * 5
        + ["requested"] * 20
        + ["approved"] * 10
        + ["generated"] * 10
        + ["issued"] * 25
    )
    now = datetime.now(UTC)
    req_svc_types = ["bonafide", "conduct", "transcript", "character", "internship_noc"]
    for n, state in enumerate(plan):
        if not students:
            break
        st = students[n % len(students)]
        t = req_svc_types[n % len(req_svc_types)]
        status = {"pickup": "generated"}.get(state, state)
        r = CertificateRequest(
            institution_id=inst.id,
            requester_user_id=st.user_id,
            person_type="student",
            person_id=st.id,
            template_type=t,
            purpose=rng.choice(["Bank loan", "Higher studies", "Visa", "Internship"]),
            copies=rng.choice([1, 1, 2]),
            delivery="pickup" if state == "pickup" else rng.choice(["digital", "digital", "post"]),
            status=status,
        )
        db.add(r)
        await db.flush()
        r.created_at = now - timedelta(days=rng.randint(0, 20))
        meta: dict[str, object] = {
            "timeline": [{"at": r.created_at.isoformat(), "action": "requested"}],
            "stage": {"pickup": "pickup_ready", "rejected": "rejected", "requested": "awaiting_approval"}.get(state),
        }
        if state == "fee_pending":
            meta["fee_paise"] = int(DEFAULT_REQUEST_RULES[t]["fee_paise"]) * r.copies
        if state == "rejected":
            meta["reject_reason"] = "Purpose not supported (demo)"
        if state == "pickup":
            meta["pickup"] = {"on": (now + timedelta(days=2)).date().isoformat()}
        if status in ("generated", "issued"):
            enrol = next((e for e in enrols if e.student_id == st.id), None)
            if enrol is not None:
                async with db.begin_nested():
                    res = await render.render(t, "certificate_request", r.id, variables_override={"purpose": r.purpose})
                r.issued_document_id = res.issued_document_id
        await render.put_meta("req", r.id, meta)
        ctx.count("certificate_requests")

    # ---- 3 bulk jobs ---------------------------------------------------------------------------------------------------
    for label, t in (
        ("ID cards — first batch", "id_card"),
        ("Bonafide — scholarship drive", "bonafide"),
        ("Service letters", "service"),
    ):
        db.add(
            BackgroundJob(
                institution_id=inst.id,
                job_type="documents.bulk_generate",
                params={"template_type": t, "label": label, "scope": {"enrollment_ids": []}},
                status="succeeded",
                progress_pct=100,
                message=label,
                result={"total": 0, "ok": 0, "failed": [], "documents": []},
                requested_by=actor_id,
            )
        )
        ctx.count("bulk_jobs")
    await db.flush()
