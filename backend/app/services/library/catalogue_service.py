"""Catalogue — Prompts/19 §19.6 ``catalogue_service`` (+ ``member_service``).

Books with an ``authors`` JSON array; ISBN normalised (ISBN-10 → ISBN-13, hyphens stripped); a duplicate ISBN is a
warning, not an error. ``total_copies`` / ``available_copies`` move only with copies (bulk add, status changes,
circulation). Accession numbers come from sequence ``lib:acc`` (fallback ``ACC{n:06d}``); the barcode defaults to the
accession number. CSV import (``title, authors (;-separated), isbn, publisher, year, category, copies, location``)
runs as job ``library.import_catalogue``. Books are institution-wide (``college_id`` NULL) or college-owned; college
scoped librarians see their college's books plus the shared ones.

Members: auto-provisioned from students / staff (consumers on ``student.created`` / ``staff.created``, the seeder and
``provision_all``) with the type's rules; ``valid_to`` = enrolment exit term end (expected graduation year) or none for
staff. Block reasons: ``SUSPENDED``, ``EXPIRED``, ``FINES`` (outstanding > ``library.block_fine_threshold_paise``),
``OVERDUE`` (an issue overdue > ``library.block_overdue_days``), ``HOLD`` (open library / all hold).
"""

import csv
import io
import re
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, or_, select

from app.core.errors import APIError, ErrorCode
from app.enums.library import ACTIVE_ISSUE, MANUAL_COPY_STATUS
from app.models.fees import FeeInvoice
from app.models.hr import Staff
from app.models.library import Book, BookCategory, BookIssue, LibraryCopy, LibraryMember
from app.models.platform import Department
from app.models.students import Student, StudentHold, StudentProgramEnrollment
from app.schemas.library import (
    BookCategoryIn,
    BookCategoryOut,
    BookCreate,
    BookResponse,
    BookUpdate,
    CatalogueImportReport,
    CopyBulkCreate,
    CopyResponse,
    CopyStatusChange,
    ExternalMemberCreate,
    LibraryMemberResponse,
    LibraryMemberRulesUpdate,
)
from app.services.library.common import LibraryBase, member_predicate, rule

ENTITY = "book"


def normalise_isbn(raw: str | None) -> str | None:
    if not raw:
        return None
    s = re.sub(r"[^0-9Xx]", "", raw).upper()
    if len(s) == 10:
        core = "978" + s[:9]
        total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(core))
        return core + str((10 - total % 10) % 10)
    return s or None


def college_predicate(p: Any) -> Any:
    """Books a college-scoped librarian sees: their college's + shared (``college_id`` NULL)."""
    colleges = [sid for t, sid in getattr(p, "scopes", []) if t == "college" and sid is not None]
    institution = getattr(p, "is_super_admin", False) or any(t == "institution" for t, _ in getattr(p, "scopes", []))
    if p is None or institution or not colleges:
        return None
    return or_(Book.college_id.is_(None), Book.college_id.in_(colleges))


class CatalogueService(LibraryBase):
    # ---- categories -------------------------------------------------------------------------------------------------
    async def categories(self) -> list[BookCategoryOut]:
        counts: dict[Any, Any] = dict(
            (
                await self.db.execute(
                    select(Book.category_id, func.count())
                    .where(Book.institution_id == self.inst, Book.deleted_at.is_(None))
                    .group_by(Book.category_id)
                )
            ).all()  # type: ignore[arg-type]
        )
        rows = (
            (
                await self.db.execute(
                    select(BookCategory)
                    .where(BookCategory.institution_id == self.inst)
                    .order_by(BookCategory.ddc_code, BookCategory.name)
                )
            )
            .scalars()
            .all()
        )
        return [
            BookCategoryOut(
                id=c.id,
                name=c.name,
                parent_id=c.parent_id,
                ddc_code=c.ddc_code,
                is_active=c.is_active,
                books=int(counts.get(c.id, 0)),
            )
            for c in rows
        ]

    async def save_category(self, body: BookCategoryIn, cid: uuid.UUID | None = None) -> BookCategoryOut:
        self.require("manage")
        c: BookCategory | None
        if cid is None:
            c = BookCategory(institution_id=self.inst, **body.model_dump())
            self.db.add(c)
        else:
            c = (
                await self.db.execute(
                    select(BookCategory).where(BookCategory.id == cid, BookCategory.institution_id == self.inst)
                )
            ).scalar_one_or_none()
            if c is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Category not found")
            for k, v in body.model_dump().items():
                setattr(c, k, v)
        await self.db.flush()
        await self._audit("category_save", "book_category", c.id, None, body.model_dump(mode="json"))
        return BookCategoryOut(id=c.id, name=c.name, parent_id=c.parent_id, ddc_code=c.ddc_code, is_active=c.is_active)

    async def delete_category(self, cid: uuid.UUID) -> None:
        self.require("manage")
        c = (
            await self.db.execute(
                select(BookCategory).where(BookCategory.id == cid, BookCategory.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if c is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Category not found")
        used = (
            await self.db.execute(
                select(func.count()).select_from(Book).where(Book.category_id == cid, Book.deleted_at.is_(None))
            )
        ).scalar_one()
        if used:
            c.is_active = False
        else:
            await self.db.delete(c)
        await self.db.flush()

    # ---- books ------------------------------------------------------------------------------------------------------
    async def _book(self, bid: uuid.UUID, *, for_update: bool = False) -> Book:
        q = select(Book).where(Book.id == bid, Book.institution_id == self.inst, Book.deleted_at.is_(None))
        pred = college_predicate(self.principal)
        if pred is not None:
            q = q.where(pred)
        if for_update:
            q = q.with_for_update()
        b = (await self.db.execute(q)).scalar_one_or_none()
        if b is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Book not found")
        return b

    async def outs(self, books: list[Book], warnings: dict[uuid.UUID, list[str]] | None = None) -> list[BookResponse]:
        ids = [b.id for b in books]
        stat: dict[uuid.UUID, dict[str, int]] = {}
        locs: dict[uuid.UUID, set[str]] = {}
        if ids:
            for bid, status, loc, n in (
                await self.db.execute(
                    select(LibraryCopy.book_id, LibraryCopy.status, LibraryCopy.location, func.count())
                    .where(LibraryCopy.book_id.in_(ids))
                    .group_by(LibraryCopy.book_id, LibraryCopy.status, LibraryCopy.location)
                )
            ).all():
                stat.setdefault(bid, {})[status] = stat.setdefault(bid, {}).get(status, 0) + int(n)
                if loc:
                    locs.setdefault(bid, set()).add(loc)
        cats: dict[Any, Any] = dict(
            (
                await self.db.execute(
                    select(BookCategory.id, BookCategory.name).where(
                        BookCategory.id.in_({b.category_id for b in books if b.category_id} or {uuid.uuid4()})
                    )
                )
            ).all()  # type: ignore[arg-type]
        )
        return [
            BookResponse(
                id=b.id,
                title=b.title,
                authors=list(b.authors or []),
                publisher=b.publisher,
                edition=b.edition,
                year=b.year,
                isbn=b.isbn,
                language=b.language,
                subject=b.subject,
                call_number=b.call_number,
                resource_type=b.resource_type,
                category_id=b.category_id,
                category=cats.get(b.category_id),
                college_id=b.college_id,
                price_paise=b.price_paise,
                cover_url=b.cover_url,
                description=b.description,
                total_copies=b.total_copies,
                available_copies=b.available_copies,
                copies_by_status=stat.get(b.id, {}),
                locations=sorted(locs.get(b.id, set())),
                is_active=b.is_active,
                warnings=(warnings or {}).get(b.id, []),
                created_at=b.created_at,
            )
            for b in books
        ]

    async def list_books(
        self, q: str | None, category_id: uuid.UUID | None, resource_type: str | None, limit: int = 50, offset: int = 0
    ) -> tuple[list[BookResponse], int]:
        stmt = select(Book).where(Book.institution_id == self.inst, Book.deleted_at.is_(None))
        pred = college_predicate(self.principal)
        if pred is not None:
            stmt = stmt.where(pred)
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    Book.title.ilike(like),
                    Book.isbn.ilike(like),
                    Book.subject.ilike(like),
                    func.cast(Book.authors, type_=Book.title.type).ilike(like),
                )
            )
        if category_id:
            stmt = stmt.where(Book.category_id == category_id)
        if resource_type:
            stmt = stmt.where(Book.resource_type == resource_type)
        total = (await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = list((await self.db.execute(stmt.order_by(Book.title).limit(limit).offset(offset))).scalars().all())
        return await self.outs(rows), int(total)

    async def get_book(self, bid: uuid.UUID) -> BookResponse:
        return (await self.outs([await self._book(bid)]))[0]

    async def create_book(self, body: BookCreate) -> BookResponse:
        self.require("manage")
        data = body.model_dump()
        data["isbn"] = normalise_isbn(body.isbn)
        warnings: list[str] = []
        if data["isbn"]:
            dup = (
                await self.db.execute(
                    select(Book.id).where(
                        Book.institution_id == self.inst, Book.isbn == data["isbn"], Book.deleted_at.is_(None)
                    )
                )
            ).first()
            if dup:
                warnings.append(f"DUPLICATE_ISBN:{dup[0]}")
        b = Book(institution_id=self.inst, created_by=self.actor_id, total_copies=0, available_copies=0, **data)
        self.db.add(b)
        await self.db.flush()
        await self.db.refresh(b)
        await self._audit("create", ENTITY, b.id, None, {"title": b.title, "isbn": b.isbn})
        return (await self.outs([b], {b.id: warnings}))[0]

    async def update_book(self, bid: uuid.UUID, body: BookUpdate) -> BookResponse:
        self.require("manage")
        b = await self._book(bid, for_update=True)
        data = body.model_dump(exclude_unset=True)
        if "isbn" in data:
            data["isbn"] = normalise_isbn(data["isbn"])
        for k, v in data.items():
            setattr(b, k, v)
        b.version += 1
        await self.db.flush()
        await self.db.refresh(b)
        await self._audit("update", ENTITY, b.id, None, body.model_dump(mode="json", exclude_unset=True))
        return (await self.outs([b]))[0]

    async def delete_book(self, bid: uuid.UUID) -> None:
        self.require("manage")
        b = await self._book(bid, for_update=True)
        active = (
            await self.db.execute(
                select(func.count())
                .select_from(BookIssue)
                .join(LibraryCopy, LibraryCopy.id == BookIssue.copy_id)
                .where(LibraryCopy.book_id == b.id, BookIssue.status.in_(ACTIVE_ISSUE))
            )
        ).scalar_one()
        if active:
            raise rule("Copies of this book are on loan", "COPIES_ON_LOAN")
        from app.services.library.common import now_utc

        b.deleted_at, b.deleted_by, b.is_active = now_utc(), self.actor_id, False
        await self.db.flush()
        await self._audit("delete", ENTITY, b.id, None, None)

    # ---- copies -----------------------------------------------------------------------------------------------------
    async def _accession(self) -> str:
        from app.services.sequence_service import SequenceService

        try:
            return (await SequenceService(self.db, self.principal, self.request, self.inst).next("lib:acc")).rendered[
                :30
            ]
        except APIError:
            n = (
                await self.db.execute(
                    select(func.count()).select_from(LibraryCopy).where(LibraryCopy.institution_id == self.inst)
                )
            ).scalar_one()
            for k in range(int(n) + 1, int(n) + 10000):
                code = f"ACC{k:06d}"
                if not (
                    await self.db.execute(
                        select(LibraryCopy.id).where(
                            LibraryCopy.institution_id == self.inst, LibraryCopy.accession_number == code
                        )
                    )
                ).first():
                    return code
            raise

    async def bulk_copies(self, bid: uuid.UUID, body: CopyBulkCreate) -> list[CopyResponse]:
        self.require("manage")
        b = await self._book(bid, for_update=True)
        made: list[LibraryCopy] = []
        status = "reference_only" if b.resource_type == "reference" else "available"
        for _ in range(body.count):
            acc = await self._accession()
            c = LibraryCopy(
                institution_id=self.inst,
                book_id=b.id,
                accession_number=acc,
                barcode=f"{body.barcode_prefix}{acc}" if body.barcode_prefix else acc,
                location=body.location,
                status=status,
                acquired_on=body.acquired_on or await self.today(),
                price_paise=body.price_paise if body.price_paise is not None else b.price_paise,
            )
            self.db.add(c)
            made.append(c)
        b.total_copies += body.count
        if status == "available":
            b.available_copies += body.count
        await self.db.flush()
        await self._audit("copies_add", ENTITY, b.id, None, {"count": body.count, "first": made[0].accession_number})
        return [self.copy_out(c, b.title) for c in made]

    @staticmethod
    def copy_out(c: LibraryCopy, title: str | None = None, issue_id: uuid.UUID | None = None) -> CopyResponse:
        return CopyResponse(
            id=c.id,
            book_id=c.book_id,
            title=title,
            accession_number=c.accession_number,
            barcode=c.barcode,
            rfid_tag=c.rfid_tag,
            location=c.location,
            status=c.status,
            acquired_on=c.acquired_on,
            price_paise=c.price_paise,
            current_issue_id=issue_id,
        )

    async def copies(self, bid: uuid.UUID) -> list[CopyResponse]:
        b = await self._book(bid)
        rows = (
            (
                await self.db.execute(
                    select(LibraryCopy).where(LibraryCopy.book_id == b.id).order_by(LibraryCopy.accession_number)
                )
            )
            .scalars()
            .all()
        )
        issues: dict[Any, Any] = dict(
            (
                await self.db.execute(
                    select(BookIssue.copy_id, BookIssue.id).where(
                        BookIssue.copy_id.in_([c.id for c in rows] or [uuid.uuid4()]),
                        BookIssue.status.in_(ACTIVE_ISSUE),
                    )
                )
            ).all()  # type: ignore[arg-type]
        )
        return [self.copy_out(c, b.title, issues.get(c.id)) for c in rows]

    async def resolve(self, barcode: str | None, accession: str | None, rfid: str | None) -> CopyResponse:
        if not self.can_circulate():
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "library:circulate required")
        c = await self.copy_by(barcode=barcode, accession_number=accession, rfid_tag=rfid, for_update=False)
        b = (await self.db.execute(select(Book.title).where(Book.id == c.book_id))).scalar_one_or_none()
        issue = (
            await self.db.execute(
                select(BookIssue.id).where(BookIssue.copy_id == c.id, BookIssue.status.in_(ACTIVE_ISSUE))
            )
        ).scalar_one_or_none()
        return self.copy_out(c, b, issue)

    async def change_copy_status(self, copy_id: uuid.UUID, body: CopyStatusChange) -> CopyResponse:
        self.require("manage")
        c = (
            await self.db.execute(
                select(LibraryCopy)
                .where(LibraryCopy.id == copy_id, LibraryCopy.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if c is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Copy not found")
        if c.status in ("issued", "reserved"):
            raise rule(f"The copy is {c.status} — return / release it first", "COPY_IN_CIRCULATION")
        if body.status not in MANUAL_COPY_STATUS:
            raise APIError(422, ErrorCode.VALIDATION, "Unsupported status")
        b = (await self.db.execute(select(Book).where(Book.id == c.book_id).with_for_update())).scalar_one()
        was_available = c.status == "available"
        old = c.status
        c.status = body.status
        if body.rfid_tag:
            c.rfid_tag = body.rfid_tag
        if was_available and body.status != "available":
            b.available_copies = max(b.available_copies - 1, 0)
        elif not was_available and body.status == "available":
            b.available_copies += 1
        if body.status == "withdrawn" and old != "withdrawn":
            b.total_copies = max(b.total_copies - 1, 0)
        elif old == "withdrawn" and body.status != "withdrawn":
            b.total_copies += 1
        await self.db.flush()
        await self._audit(
            "copy_status", "library_copy", c.id, {"status": old}, {"status": c.status, "remarks": body.remarks}
        )
        return self.copy_out(c, b.title)

    # ---- import -----------------------------------------------------------------------------------------------------
    async def import_csv(
        self, text: str, mapping: dict[str, str] | None, copies_column: str | None
    ) -> CatalogueImportReport:
        reader = csv.DictReader(io.StringIO(text))
        m = {
            "title": "title",
            "authors": "authors",
            "isbn": "isbn",
            "publisher": "publisher",
            "year": "year",
            "category": "category",
            "location": "location",
            **(mapping or {}),
        }
        cats = {
            c.name.lower(): c.id
            for c in (await self.db.execute(select(BookCategory).where(BookCategory.institution_id == self.inst)))
            .scalars()
            .all()
        }
        report = CatalogueImportReport(rows=0, created=0, updated=0, copies=0)
        for i, row in enumerate(reader, start=2):
            report.rows += 1
            title = (row.get(m["title"]) or "").strip()
            if not title:
                report.errors.append({"row": i, "error": "title missing"})
                continue
            isbn = normalise_isbn(row.get(m["isbn"]))
            existing = None
            if isbn:
                existing = (
                    (
                        await self.db.execute(
                            select(Book).where(
                                Book.institution_id == self.inst, Book.isbn == isbn, Book.deleted_at.is_(None)
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
            year_raw = (row.get(m["year"]) or "").strip()
            data: dict[str, Any] = {
                "title": title[:255],
                "authors": [a.strip() for a in (row.get(m["authors"]) or "").split(";") if a.strip()],
                "publisher": (row.get(m["publisher"]) or None),
                "year": int(year_raw) if year_raw.isdigit() else None,
                "isbn": isbn,
                "category_id": cats.get((row.get(m["category"]) or "").strip().lower()),
            }
            if existing is None:
                existing = Book(
                    institution_id=self.inst, created_by=self.actor_id, total_copies=0, available_copies=0, **data
                )
                self.db.add(existing)
                report.created += 1
            else:
                for k, v in data.items():
                    if v not in (None, [], ""):
                        setattr(existing, k, v)
                report.updated += 1
            await self.db.flush()
            n_raw = (row.get(copies_column or "copies") or "").strip()
            n = int(n_raw) if n_raw.isdigit() else 0
            if n:
                await self.bulk_copies(
                    existing.id, CopyBulkCreate(count=min(n, 500), location=(row.get(m["location"]) or None))
                )
                report.copies += n
        await self._audit("import", ENTITY, None, None, report.model_dump())
        return report


class MemberService(LibraryBase):
    async def code(self, member_type: str) -> str:
        from app.services.sequence_service import SequenceService

        try:
            return (
                await SequenceService(self.db, self.principal, self.request, self.inst).next("lib:member")
            ).rendered[:30]
        except APIError:
            n = (
                await self.db.execute(
                    select(func.count()).select_from(LibraryMember).where(LibraryMember.institution_id == self.inst)
                )
            ).scalar_one()
            yy = (await self.today()).year % 100
            for k in range(int(n) + 1, int(n) + 10000):
                code = f"LM{yy:02d}{k:05d}"
                if not (
                    await self.db.execute(
                        select(LibraryMember.id).where(
                            LibraryMember.institution_id == self.inst, LibraryMember.member_code == code
                        )
                    )
                ).first():
                    return code
            raise

    async def provision(self, user_id: uuid.UUID, member_type: str, valid_to: date | None = None) -> LibraryMember:
        row = (
            (
                await self.db.execute(
                    select(LibraryMember).where(
                        LibraryMember.institution_id == self.inst, LibraryMember.user_id == user_id
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is not None:
            return row
        r = await self.rules(member_type)
        row = LibraryMember(
            institution_id=self.inst,
            user_id=user_id,
            member_type=member_type,
            member_code=await self.code(member_type),
            max_books_allowed=int(r.get("max_books", 3)),
            loan_days=int(r.get("loan_days", 14)),
            valid_to=valid_to,
            is_active=True,
        )
        self.db.add(row)
        await self.db.flush()
        await self._emit(
            "library.member_created", {"member_id": str(row.id), "type": member_type}, "library_member", row.id
        )
        return row

    async def provision_all(self) -> int:
        n = 0
        students = (
            await self.db.execute(
                select(Student.user_id, func.max(StudentProgramEnrollment.admission_date))
                .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                .where(
                    Student.institution_id == self.inst,
                    Student.user_id.is_not(None),
                    Student.deleted_at.is_(None),
                    StudentProgramEnrollment.status == "active",
                )
                .group_by(Student.user_id)
            )
        ).all()
        have = set(
            (await self.db.execute(select(LibraryMember.user_id).where(LibraryMember.institution_id == self.inst)))
            .scalars()
            .all()
        )
        for uid, admitted in students:
            if uid in have:
                continue
            await self.provision(uid, "student", (admitted + timedelta(days=365 * 5)) if admitted else None)
            n += 1
        staff = (
            await self.db.execute(
                select(Staff.user_id, Staff.staff_category).where(
                    Staff.institution_id == self.inst, Staff.user_id.is_not(None), Staff.deleted_at.is_(None)
                )
            )
        ).all()
        for uid, kind in staff:
            if uid in have:
                continue
            await self.provision(uid, "faculty" if (kind or "").lower() in ("teaching", "faculty") else "staff")
            n += 1
        return n

    async def outstanding(self, member_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not member_ids:
            return {}
        rows = (
            await self.db.execute(
                select(BookIssue.member_id, func.coalesce(func.sum(FeeInvoice.balance_paise), 0))
                .join(FeeInvoice, FeeInvoice.id == BookIssue.fine_invoice_id)
                .where(BookIssue.member_id.in_(member_ids), FeeInvoice.status.in_(("pending", "partial", "overdue")))
                .group_by(BookIssue.member_id)
            )
        ).all()
        return {r[0]: int(r[1]) for r in rows}

    async def block_reasons(self, m: LibraryMember, outstanding: int | None = None) -> tuple[list[str], int, int]:
        reasons: list[str] = []
        today = await self.today()
        if not m.is_active:
            reasons.append("SUSPENDED")
        if m.valid_to and m.valid_to < today:
            reasons.append("EXPIRED")
        out = outstanding if outstanding is not None else (await self.outstanding([m.id])).get(m.id, 0)
        threshold = int(await self.lib_setting("block_fine_threshold_paise", 50000))
        if out > threshold:
            reasons.append("FINES")
        active, overdue_days = 0, 0
        for due, _status in (
            await self.db.execute(
                select(BookIssue.due_on, BookIssue.status).where(
                    BookIssue.member_id == m.id, BookIssue.status.in_(ACTIVE_ISSUE)
                )
            )
        ).all():
            active += 1
            overdue_days = max(overdue_days, (today - due).days)
        if overdue_days > int(await self.lib_setting("block_overdue_days", 30)):
            reasons.append("OVERDUE")
        st, e = await self.student_of_user(m.user_id)
        if e is not None:
            held = (
                await self.db.execute(
                    select(func.count())
                    .select_from(StudentHold)
                    .where(
                        StudentHold.student_program_enrollment_id == e.id,
                        StudentHold.released_at.is_(None),
                        StudentHold.hold_type.in_(("library", "all")),
                    )
                )
            ).scalar_one()
            if held:
                reasons.append("HOLD")
        return reasons, active, out

    async def out(self, m: LibraryMember) -> LibraryMemberResponse:
        reasons, active, outstanding = await self.block_reasons(m)
        today = await self.today()
        overdue = (
            await self.db.execute(
                select(func.count())
                .select_from(BookIssue)
                .where(BookIssue.member_id == m.id, BookIssue.status.in_(ACTIVE_ISSUE), BookIssue.due_on < today)
            )
        ).scalar_one()
        names = await self.member_names([m.user_id])
        dept = None
        st, e = await self.student_of_user(m.user_id)
        if e is not None:
            dept = (
                await self.db.execute(select(Department.name).where(Department.id == e.department_id))
            ).scalar_one_or_none()
        r = await self.rules(m.member_type)
        return LibraryMemberResponse(
            id=m.id,
            user_id=m.user_id,
            name=names.get(m.user_id),
            member_code=m.member_code,
            member_type=m.member_type,
            max_books_allowed=m.max_books_allowed,
            loan_days=m.loan_days,
            max_renewals=int(r.get("max_renewals", 1)),
            valid_to=m.valid_to,
            is_active=m.is_active,
            active_issues=active,
            overdue_issues=int(overdue),
            outstanding_fine_paise=outstanding,
            is_blocked=bool(reasons),
            block_reasons=reasons,
            department=dept,
        )

    async def list_members(
        self, member_type: str | None, status: str | None, department_id: uuid.UUID | None, scope: str | None
    ) -> list[LibraryMemberResponse]:
        if not (self.can("library", "view_all") or self.can("library", "manage") or self.can("library", "circulate")):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "library:view_all required")
        q = select(LibraryMember).where(
            LibraryMember.institution_id == self.inst, member_predicate(self.principal, scope)
        )
        if member_type:
            q = q.where(LibraryMember.member_type == member_type)
        if status == "active":
            q = q.where(LibraryMember.is_active.is_(True))
        elif status == "suspended":
            q = q.where(LibraryMember.is_active.is_(False))
        if department_id:
            self.check_department(department_id)
            q = q.where(
                LibraryMember.user_id.in_(
                    select(Student.user_id)
                    .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                    .where(StudentProgramEnrollment.department_id == department_id)
                    .union(select(Staff.user_id).where(Staff.department_id == department_id))
                )
            )
        rows = list((await self.db.execute(q.order_by(LibraryMember.member_code).limit(2000))).scalars().all())
        return [await self.out(m) for m in rows]

    def check_department(self, department_id: uuid.UUID) -> None:
        """A department filter must sit inside the caller's scope (HOD → own department)."""
        p = self.principal
        if (
            p is None
            or getattr(p, "is_super_admin", False)
            or any(t in ("institution", "college", "faculty") for t, _ in getattr(p, "scopes", []))
        ):
            return
        depts = [sid for t, sid in getattr(p, "scopes", []) if t == "department"]
        if department_id not in depts:
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "That department is outside your scope")

    async def get(self, member_id: uuid.UUID) -> LibraryMemberResponse:
        return await self.out(await self.member(member_id))

    async def me(self) -> LibraryMemberResponse:
        mine = await self.my_members()
        if not mine:
            st, e = await self.student_of_user(self.principal.id) if self.principal else (None, None)
            if st is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "You are not a library member")
            return await self.out(await self.provision(self.principal.id, "student"))
        return await self.out(mine[0])

    async def wards(self) -> list[LibraryMemberResponse]:
        from app.repositories.fee_scope import wards_predicate

        users = (
            (
                await self.db.execute(
                    select(Student.user_id).where(wards_predicate(self.principal), Student.user_id.is_not(None))
                )
            )
            .scalars()
            .all()
        )
        rows = (
            (
                await self.db.execute(
                    select(LibraryMember).where(
                        LibraryMember.institution_id == self.inst,
                        LibraryMember.user_id.in_(list(users) or [uuid.uuid4()]),
                    )
                )
            )
            .scalars()
            .all()
        )
        return [await self.out(m) for m in rows]

    async def create_external(self, body: ExternalMemberCreate) -> LibraryMemberResponse:
        self.require("manage")
        m = await self.provision(body.user_id, body.member_type, body.valid_to)
        deposit = (
            body.deposit_paise
            if body.deposit_paise is not None
            else int((await self.rules(body.member_type)).get("deposit_paise", 0))
        )
        if deposit > 0:
            from app.schemas.fees import InvoiceCreate, InvoiceItemIn
            from app.services.fees.invoice_service import InvoiceService

            await InvoiceService(self.db, None, self.request, self.inst).create_invoice(
                InvoiceCreate(
                    payer_type="alumni"
                    if body.member_type == "alumni"
                    else "staff",  # DDL payer types have no "external"
                    payer_id=body.user_id,
                    source_type="library_deposit",
                    source_id=m.id,
                    description="Library membership deposit",
                    items=[
                        InvoiceItemIn(
                            description="Library deposit (refundable)", amount_paise=deposit, head_code="CAUTION"
                        )
                    ],
                )
            )
        await self._audit("member_create", "library_member", m.id, None, body.model_dump(mode="json"))
        return await self.out(m)

    async def update_rules(self, member_id: uuid.UUID, body: LibraryMemberRulesUpdate) -> LibraryMemberResponse:
        self.require("manage")
        m = await self.member(member_id, for_update=True)
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(m, k, v)
        await self.db.flush()
        await self._audit(
            "member_rules", "library_member", m.id, None, body.model_dump(mode="json", exclude_unset=True)
        )
        return await self.out(m)

    async def set_active(self, member_id: uuid.UUID, active: bool) -> LibraryMemberResponse:
        self.require("manage")
        m = await self.member(member_id, for_update=True)
        m.is_active = active
        await self.db.flush()
        await self._audit(
            "member_activate" if active else "member_suspend", "library_member", m.id, None, {"is_active": active}
        )
        await self._emit(
            "library.member_unblocked" if active else "library.member_blocked",
            {"member_id": str(m.id)},
            "library_member",
            m.id,
        )
        return await self.out(m)

    async def membership_expiry(self) -> int:
        today = await self.today()
        rows = (
            (
                await self.db.execute(
                    select(LibraryMember).where(
                        LibraryMember.institution_id == self.inst,
                        LibraryMember.is_active.is_(True),
                        LibraryMember.valid_to.is_not(None),
                        LibraryMember.valid_to < today,
                    )
                )
            )
            .scalars()
            .all()
        )
        for m in rows:
            await self._emit(
                "library.member_blocked", {"member_id": str(m.id), "reason": "EXPIRED"}, "library_member", m.id
            )
        return len(rows)
