"""``library`` demo seeder (Prompts/19 §19.2) — ``seed_demo_institution.py --only library``.

Library members for every active student / staff user, 50 categories (Dewey classes + subjects), 1,200 books with
ISBNs and 3,000 copies (accession numbers / barcodes), 20 e-resources (2 expired), 400 issues (about 60 overdue and 15
lost, with fines), 40 reservations (5 ``available`` holds), 10 ILL requests and one transcript no-dues request whose
library sign-off is evaluated automatically. Bulk rows are inserted directly (counters kept consistent); fines and
lost-book charges go through the circulation service so the Phase 12 invoices exist. Idempotent: skipped when books
exist.
"""

import random
from datetime import UTC, datetime, timedelta

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select

SUBJECTS = [
    "Algorithms",
    "Data Structures",
    "Operating Systems",
    "Computer Networks",
    "Databases",
    "Machine Learning",
    "Artificial Intelligence",
    "Compiler Design",
    "Software Engineering",
    "Digital Electronics",
    "Signals and Systems",
    "Control Systems",
    "Thermodynamics",
    "Fluid Mechanics",
    "Engineering Mathematics",
    "Linear Algebra",
    "Probability",
    "Statistics",
    "Discrete Mathematics",
    "Physics",
    "Chemistry",
    "Economics",
    "Accounting",
    "Marketing",
    "Finance",
    "Organisational Behaviour",
    "Business Law",
    "Communication Skills",
    "Environmental Science",
    "Ethics",
    "Cloud Computing",
    "Cyber Security",
    "Internet of Things",
    "Embedded Systems",
    "VLSI Design",
    "Power Systems",
    "Microprocessors",
    "Computer Graphics",
    "Human Computer Interaction",
    "Information Retrieval",
]
ADJ = [
    "Introduction to",
    "Principles of",
    "Advanced",
    "Fundamentals of",
    "Applied",
    "Modern",
    "Essentials of",
    "Handbook of",
]
AUTHORS = [
    "A. Sharma",
    "R. Iyer",
    "S. Gupta",
    "P. Nair",
    "K. Reddy",
    "M. Joshi",
    "T. Cormen",
    "A. Tanenbaum",
    "D. Knuth",
    "S. Haykin",
    "J. Kurose",
    "R. Pressman",
    "B. Grewal",
    "H. Anton",
    "S. Ross",
    "P. Kotler",
    "I. Pandey",
    "N. Rao",
]


def _isbn13(seed: int) -> str:
    core = f"978{seed:09d}"[:12]
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(core))
    return core + str((10 - total % 10) % 10)


@seeder("library", after=["students", "hr", "fees"])
async def seed_library(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.core.tenancy import today_for
    from app.db.session import bind_tenant, set_tenant
    from app.models.library import (
        Book,
        BookCategory,
        BookIssue,
        LibraryCopy,
        LibraryEresource,
        LibraryIllRequest,
        LibraryMember,
        LibraryReservation,
    )
    from app.models.platform import Institution, User
    from app.models.students import Student, StudentProgramEnrollment
    from app.schemas.library import BookLostRequest, BookReturnRequest
    from app.schemas.no_dues import NoDuesCreate
    from app.services.auth_service import load_principal
    from app.services.fees.no_dues_service import NoDuesService
    from app.services.library.catalogue_service import MemberService
    from app.services.library.circulation_service import CirculationService

    db = ctx.db
    rng = random.Random(19)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if (await db.execute(select(func.count()).select_from(Book).where(Book.institution_id == inst.id))).scalar_one():
        return

    async def principal(name: str) -> object | None:
        u = (
            await db.execute(select(User).where(User.institution_id == inst.id, User.username == name))
        ).scalar_one_or_none()
        return await load_principal(db, u.id) if u else None

    librarian = await principal("librarian") or await principal("inst.admin")
    today = today_for(inst)

    members = MemberService(db, librarian, institution_id=inst.id)
    ctx.count("library_members", await members.provision_all())

    # ---- categories ----
    cats = list((await db.execute(select(BookCategory).where(BookCategory.institution_id == inst.id))).scalars().all())
    top = {c.ddc_code: c for c in cats if c.ddc_code}
    for i, subject in enumerate(SUBJECTS):
        if len(cats) >= 50:
            break
        parent = top.get("000" if i < 10 or i >= 30 else ("600" if i < 20 else "300"))
        c = BookCategory(institution_id=inst.id, name=subject, parent_id=parent.id if parent else None, ddc_code=None)
        db.add(c)
        cats.append(c)
    await db.flush()
    subject_cats = [c for c in cats if c.name in SUBJECTS] or cats
    ctx.count("book_categories", len(cats))

    # ---- books + copies ----
    books: list[Book] = []
    acc = 0
    locations = [f"Stack {chr(65 + k)}" for k in range(8)] + ["Reference hall"]
    for n in range(1200):
        cat = subject_cats[n % len(subject_cats)]
        rtype = "reference" if n % 60 == 0 else ("journal" if n % 45 == 0 else ("thesis" if n % 70 == 0 else "book"))
        b = Book(
            institution_id=inst.id,
            category_id=cat.id,
            title=f"{ADJ[n % len(ADJ)]} {cat.name}" + (f" — Volume {n // 300 + 1}" if n >= 300 else ""),
            authors=rng.sample(AUTHORS, k=1 + n % 3),
            publisher=rng.choice(
                ["Pearson", "McGraw-Hill", "Wiley", "Springer", "PHI Learning", "Oxford University Press"]
            ),
            edition=f"{1 + n % 5}e",
            year=2005 + n % 20,
            isbn=_isbn13(100000 + n),
            language="English" if n % 15 else "Hindi",
            subject=cat.name,
            call_number=f"{(n % 9) * 100 + n % 99:03d}.{n % 97:02d}",
            resource_type=rtype,
            price_paise=rng.choice([45000, 65000, 89900, 125000, 199900]),
            total_copies=0,
            available_copies=0,
            created_by=getattr(librarian, "id", None),
        )
        db.add(b)
        books.append(b)
    await db.flush()
    copies: list[LibraryCopy] = []
    for n, b in enumerate(books):
        k = 2 + (1 if n % 2 else 0) + (1 if n % 5 == 0 else 0) if len(copies) < 3000 else 0
        k = min(k, 3000 - len(copies))
        for _ in range(k):
            acc += 1
            code = f"ACC{acc:06d}"
            c = LibraryCopy(
                institution_id=inst.id,
                book_id=b.id,
                accession_number=code,
                barcode=code,
                location="Reference hall" if b.resource_type == "reference" else locations[n % 8],
                status="reference_only" if b.resource_type == "reference" else "available",
                acquired_on=today - timedelta(days=rng.randint(10, 3000)),
                price_paise=b.price_paise,
            )
            db.add(c)
            copies.append(c)
        b.total_copies = k
        b.available_copies = 0 if b.resource_type == "reference" else k
    await db.flush()
    # keep the sequence ahead of the demo accession numbers
    from sqlalchemy import text

    await db.execute(
        text(
            "UPDATE number_sequences SET next_value = GREATEST(next_value, :v) WHERE institution_id = :i AND scope_key = 'lib:acc' AND college_id IS NULL"
        ),
        {"v": acc + 1, "i": inst.id},
    )
    ctx.count("books", len(books))
    ctx.count("library_copies", len(copies))

    # ---- e-resources ----
    for n in range(20):
        expired = n < 2
        db.add(
            LibraryEresource(
                institution_id=inst.id,
                title=[
                    "IEEE Xplore",
                    "ACM Digital Library",
                    "Springer Link",
                    "ScienceDirect",
                    "JSTOR",
                    "EBSCO",
                    "ProQuest",
                    "NPTEL",
                    "Shodhganga",
                    "DELNET",
                ][n % 10]
                + (f" — package {n // 10 + 1}" if n >= 10 else ""),
                provider="Consortium (demo)",
                resource_type=["ejournal", "ebook_db", "database", "repository"][n % 4],
                url=f"https://example.org/eresource/{n}",
                access_type=["ip", "remote", "open"][n % 3],
                subscription_from=today - timedelta(days=400 if expired else 200),
                subscription_to=today - timedelta(days=30)
                if expired
                else today + timedelta(days=20 if n == 2 else 165),
                cost_paise=rng.choice([25000000, 50000000, 120000000]),
            )
        )
    ctx.count("library_eresources", 20)

    # ---- issues ----
    student_members = list(
        (
            await db.execute(
                select(LibraryMember)
                .where(LibraryMember.institution_id == inst.id, LibraryMember.member_type == "student")
                .order_by(LibraryMember.member_code)
            )
        )
        .scalars()
        .all()
    )
    staff_members = list(
        (
            await db.execute(
                select(LibraryMember)
                .where(LibraryMember.institution_id == inst.id, LibraryMember.member_type != "student")
                .order_by(LibraryMember.member_code)
            )
        )
        .scalars()
        .all()
    )
    pool = [c for c in copies if c.status == "available"]
    rng.shuffle(pool)
    book_of = {b.id: b for b in books}
    everyone = student_members + staff_members
    load: dict[object, int] = {}
    issues: list[tuple[BookIssue, LibraryCopy]] = []
    overdue_target, lost_target = 60, 15
    for n in range(min(400, len(pool))):
        if not everyone:
            break
        m = everyone[n % len(everyone)]
        if load.get(m.id, 0) >= m.max_books_allowed:
            continue
        c = pool[n]
        if n < overdue_target + lost_target:
            issued_on = today - timedelta(days=m.loan_days + rng.randint(5, 50))
        else:
            issued_on = today - timedelta(days=rng.randint(0, max(m.loan_days - 1, 0)))
        issue = BookIssue(
            institution_id=inst.id,
            copy_id=c.id,
            member_id=m.id,
            issued_on=issued_on,
            due_on=issued_on + timedelta(days=m.loan_days),
            status="overdue" if issued_on + timedelta(days=m.loan_days) < today else "issued",
            issued_by=getattr(librarian, "id", None),
        )
        db.add(issue)
        c.status = "issued"
        book_of[c.book_id].available_copies -= 1
        load[m.id] = load.get(m.id, 0) + 1
        issues.append((issue, c))
    await db.flush()
    ctx.count("book_issues", len(issues))

    circ = CirculationService(db, librarian, institution_id=inst.id)
    # lost books (replacement invoices)
    for issue, _c in issues[overdue_target : overdue_target + lost_target]:
        try:
            await circ.mark_lost(BookLostRequest(issue_id=issue.id))
            ctx.count("library_lost")
        except APIError as exc:
            print(f"   library: lost skipped ({exc.message})")
    # a handful of overdue returns create fines; a few returned on time
    for _issue, c in issues[:12] + issues[100:112]:
        try:
            await circ.return_copy(BookReturnRequest(barcode=c.barcode))
            ctx.count("library_returns")
        except APIError as exc:
            print(f"   library: return skipped ({exc.message})")

    # ---- reservations ----
    zero = [b for b in books if b.available_copies == 0 and b.total_copies > 0 and b.resource_type != "reference"]
    if len(zero) < 40:
        for b in books:
            if len(zero) >= 40:
                break
            if b.available_copies > 0 and b.resource_type != "reference" and b not in zero:
                zero.append(b)
    made = 0
    for n, b in enumerate(zero[:40]):
        m = student_members[(n * 7) % len(student_members)] if student_members else None
        if m is None:
            break
        status = "available" if n < 5 else "waiting"
        r = LibraryReservation(
            institution_id=inst.id,
            book_id=b.id,
            member_id=m.id,
            status=status,
        )
        if status == "available":
            r.expires_at = datetime.now(UTC) + timedelta(hours=24 + n)
            held = next((c for c in copies if c.book_id == b.id and c.status == "available"), None)
            if held is not None:
                held.status = "reserved"
                b.available_copies = max(b.available_copies - 1, 0)
        db.add(r)
        made += 1
    await db.flush()
    ctx.count("library_reservations", made)

    # ---- ILL ----
    for n, m in enumerate(staff_members[:10] or student_members[:10]):
        db.add(
            LibraryIllRequest(
                institution_id=inst.id,
                member_id=m.id,
                title=f"{ADJ[n % len(ADJ)]} {SUBJECTS[(n * 3) % len(SUBJECTS)]} (ILL)",
                source_library=rng.choice(["IIT Madras Central Library", "DELNET", "IISc Library"]),
                status=["requested", "approved", "received", "returned", "requested"][n % 5],
                cost_paise=[None, 15000, 20000, 0, None][n % 5],
            )
        )
    ctx.count("library_ill_requests", min(10, len(staff_members or student_members)))
    await db.flush()

    # ---- one no-dues request with an evaluated library sign-off ----
    stu_user = (
        await db.execute(select(User).where(User.institution_id == inst.id, User.username == "student.1"))
    ).scalar_one_or_none()
    if stu_user is not None:
        enrol = (
            await db.execute(
                select(StudentProgramEnrollment.id)
                .join(Student, Student.id == StudentProgramEnrollment.student_id)
                .where(Student.user_id == stu_user.id, StudentProgramEnrollment.status == "active")
                .limit(1)
            )
        ).scalar_one_or_none()
        if enrol is not None:
            try:
                nd = await NoDuesService(db, librarian, institution_id=inst.id).create(
                    NoDuesCreate(purpose="transcript", enrollment_id=enrol), system=True
                )
                await circ.sign_no_dues(nd.id)
                ctx.count("no_dues_requests")
            except APIError as exc:
                print(f"   library: no-dues skipped ({exc.message})")
    await db.flush()
