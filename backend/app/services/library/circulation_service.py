"""Circulation — Prompts/19 §19.6 ``circulation_service`` (features ``library.core`` / ``library.fines`` /
``library.rfid_barcode``).

* **issue** (``library:circulate``): member active and not blocked (409 ``MEMBER_BLOCKED`` + reasons), copy
  ``available`` (``reference_only`` → 409 ``REFERENCE_ONLY``; ``reserved`` only for the reservation holder), active
  issues < ``max_books_allowed`` (409 ``LIMIT_EXCEEDED``), no second active copy of the same title (setting
  ``library.one_copy_per_title``); a waiting / available reservation queue on the title that the member does not head
  → 409 ``RESERVED_FOR_OTHER``; due = today + loan days moved past holidays / weekly-off; copy and book counters are
  locked ``FOR UPDATE``.
* **return**: fine = ``fine_configurations(library_overdue)`` (``per_day`` × days after grace, capped; ``slab`` /
  ``flat`` supported) → Phase 12 linkage invoice (``source_type='library_fine'``, ``source_id`` = issue); a damaged
  return marks the copy ``damaged`` and may add a damage charge; the first waiting reservation becomes ``available``
  for ``library.hold_hours`` (copy ``reserved``) and is notified; otherwise the copy is ``available`` again; open
  library holds placed for this issue are released once nothing is overdue.
* **renew**: ``renewals < max_renewals`` (rules), no waiting reservation (409 ``RESERVED``), not overdue beyond the
  fine grace, member not blocked.
* **lost**: issue / copy ``lost``, replacement invoice (given cost or price × ``library.lost_replacement_pct``);
  returning a lost copy later ("found") cancels an unpaid replacement invoice when ``library.found_cancels_invoice``.
* **reservations**: only when no copy is available (unless ``library.allow_reserve_available``); one active per member
  and title; FIFO; ``available`` holds expire hourly (next in queue promoted).
* **fines**: waive (``library:manage`` — the librarian; accountants collect only) cancels the unpaid invoice; paid
  fines cannot be waived.
* **overdue Beat**: statuses → ``overdue``, reminders D-3 / D0 / D+7 / weekly, students overdue beyond
  ``library.hold_after_days`` get a ``student_holds(hold_type='library', source_type='book_issue')``.
* **no-dues hook**: the library sign-off of a no-dues request is ``cleared`` with no active issues and no unpaid
  library invoices, else ``dues_pending`` with the amount (re-evaluated on returns and payments).
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.library import ACTIVE_ISSUE
from app.models.fees import FeeInvoice, FineConfiguration, NoDuesRequest, NoDuesSignoff
from app.models.library import Book, BookIssue, LibraryCopy, LibraryMember, LibraryReservation
from app.models.students import StudentHold
from app.schemas.library import (
    BookIssueResponse,
    BookLostRequest,
    BookReturnRequest,
    BookReturnResponse,
    CirculationIssueRequest,
    LibraryFineRow,
    LibraryReservationCreate,
    LibraryReservationResponse,
)
from app.services.library.catalogue_service import MemberService
from app.services.library.common import LibraryBase, now_utc, rule, rupees, visible_member_ids

ENTITY = "book_issue"
OPEN = ("pending", "partial", "overdue")


def compute_fine(cfg: FineConfiguration | None, days_overdue: int) -> int:
    if cfg is None or days_overdue <= 0:
        return 0
    days = days_overdue - int(cfg.grace_days or 0)
    if days <= 0:
        return 0
    if cfg.calc_type == "flat":
        amount = int(cfg.amount_paise or 0)
    elif cfg.calc_type == "slab" and cfg.slabs:
        amount, left, prev = 0, days, 0
        for s in sorted(cfg.slabs, key=lambda x: int(x.get("upto_days") or 10**6)):
            upto = int(s.get("upto_days") or 10**6)
            span = min(left, upto - prev)
            if span <= 0:
                continue
            amount += span * int(s.get("per_day_paise") or 0)
            left -= span
            prev = upto
            if left <= 0:
                break
    else:
        amount = days * int(cfg.amount_paise or 0)
    if cfg.max_paise:
        amount = min(amount, int(cfg.max_paise))
    return max(amount, 0)


class CirculationService(LibraryBase):
    # ---- shared -----------------------------------------------------------------------------------------------------
    async def _fine_config(self) -> FineConfiguration | None:
        return (
            (
                await self.db.execute(
                    select(FineConfiguration).where(
                        FineConfiguration.institution_id == self.inst,
                        FineConfiguration.applies_to == "library_overdue",
                        FineConfiguration.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .first()
        )

    async def _book_locked(self, book_id: uuid.UUID) -> Book:
        return (await self.db.execute(select(Book).where(Book.id == book_id).with_for_update())).scalar_one()

    async def issue_outs(self, rows: list[BookIssue]) -> list[BookIssueResponse]:
        if not rows:
            return []
        copies = {
            c.id: c
            for c in (await self.db.execute(select(LibraryCopy).where(LibraryCopy.id.in_({r.copy_id for r in rows}))))
            .scalars()
            .all()
        }
        titles: dict[Any, Any] = dict(
            (
                await self.db.execute(
                    select(Book.id, Book.title).where(
                        Book.id.in_({c.book_id for c in copies.values()} or {uuid.uuid4()})
                    )
                )
            ).all()  # type: ignore[arg-type]
        )
        members = {
            m.id: m
            for m in (
                await self.db.execute(select(LibraryMember).where(LibraryMember.id.in_({r.member_id for r in rows})))
            )
            .scalars()
            .all()
        }
        names = await self.member_names([m.user_id for m in members.values()])
        invoices: dict[Any, Any] = dict(
            (
                await self.db.execute(
                    select(FeeInvoice.id, FeeInvoice.status).where(
                        FeeInvoice.id.in_({r.fine_invoice_id for r in rows if r.fine_invoice_id} or {uuid.uuid4()})
                    )
                )
            ).all()  # type: ignore[arg-type]
        )
        today = await self.today()
        out = []
        for r in rows:
            c = copies.get(r.copy_id)
            m = members.get(r.member_id)
            live = r.status in ACTIVE_ISSUE
            out.append(
                BookIssueResponse(
                    id=r.id,
                    copy_id=r.copy_id,
                    accession_number=c.accession_number if c else None,
                    book_id=c.book_id if c else None,
                    title=titles.get(c.book_id) if c else None,
                    member_id=r.member_id,
                    member_code=m.member_code if m else None,
                    member_name=names.get(m.user_id) if m else None,
                    issued_on=r.issued_on,
                    due_on=r.due_on,
                    returned_on=r.returned_on,
                    renewals=r.renewals,
                    status="overdue" if live and r.due_on < today else r.status,
                    days_overdue=max((today - r.due_on).days, 0)
                    if live
                    else max(((r.returned_on or today) - r.due_on).days, 0),
                    fine_paise=r.fine_paise,
                    fine_invoice_id=r.fine_invoice_id,
                    fine_status=invoices.get(r.fine_invoice_id) if r.fine_invoice_id else None,
                )
            )
        return out

    async def _invoice(self, issue: BookIssue, member: LibraryMember, amount: int, label: str) -> uuid.UUID:
        from app.schemas.fees import InvoiceCreate, InvoiceItemIn
        from app.services.fees.invoice_service import InvoiceService

        st, e = await self.student_of_user(member.user_id)
        inv = await InvoiceService(self.db, None, self.request, self.inst).create_invoice(
            InvoiceCreate(
                payer_type="student" if e is not None else ("alumni" if member.member_type == "alumni" else "staff"),
                payer_id=None if e is not None else member.user_id,
                enrollment_id=e.id if e is not None else None,
                source_type="library_fine",
                source_id=issue.id,
                description=label,
                items=[InvoiceItemIn(description=label[:200], amount_paise=amount, head_code="FINE")],
                due_date=await self.today() + timedelta(days=15),
                allow_multiple=True,
            )
        )
        await self._emit(
            "library.fine_created",
            {"issue_id": str(issue.id), "invoice_id": str(inv.id), "amount_paise": amount},
            ENTITY,
            issue.id,
        )
        await self._notify("library.fine_created", [member.user_id], {"amount": rupees(amount), "reason": label})
        return inv.id

    async def _cancel_invoice(self, invoice_id: uuid.UUID | None, reason: str) -> bool:
        if invoice_id is None:
            return False
        inv = (
            await self.db.execute(select(FeeInvoice).where(FeeInvoice.id == invoice_id).with_for_update())
        ).scalar_one_or_none()
        if inv is None or inv.status in ("cancelled", "refunded", "paid") or (inv.paid_paise or 0) > 0:
            return False
        inv.status, inv.cancelled_at, inv.cancelled_reason = "cancelled", now_utc(), reason
        await self.db.flush()
        await self._emit(
            "fees.invoice_cancelled",
            {
                "invoice_id": str(inv.id),
                "source_type": inv.source_type,
                "source_id": str(inv.source_id) if inv.source_id else None,
            },
            "fee_invoice",
            inv.id,
        )
        return True

    # ---- issue ------------------------------------------------------------------------------------------------------
    async def issue(self, body: CirculationIssueRequest) -> BookIssueResponse:
        if not self.can_circulate():
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "library:circulate required")
        m = await self.member_by(member_code=body.member_code, user_id=body.user_id, id_card_token=body.id_card_token)
        reasons, active, _ = await MemberService(self.db, self.principal, self.request, self.inst).block_reasons(m)
        if reasons:
            raise rule("The member is blocked", "MEMBER_BLOCKED", reasons=reasons)
        c = await self.copy_by(barcode=body.barcode, accession_number=body.accession_number, rfid_tag=body.rfid_tag)
        if c.status == "reference_only":
            raise rule("Reference copies cannot be issued", "REFERENCE_ONLY")
        if c.status not in ("available", "reserved"):
            raise rule(f"The copy is {c.status}", "COPY_UNAVAILABLE", copy_status=c.status)
        if active >= m.max_books_allowed:
            raise rule(f"Limit of {m.max_books_allowed} book(s) reached", "LIMIT_EXCEEDED", limit=m.max_books_allowed)
        if await self.lib_setting("one_copy_per_title", True):
            dup = (
                await self.db.execute(
                    select(BookIssue.id)
                    .join(LibraryCopy, LibraryCopy.id == BookIssue.copy_id)
                    .where(
                        BookIssue.member_id == m.id,
                        BookIssue.status.in_(ACTIVE_ISSUE),
                        LibraryCopy.book_id == c.book_id,
                    )
                )
            ).first()
            if dup:
                raise rule("The member already has a copy of this title", "TITLE_ALREADY_ISSUED")
        queue = list(
            (
                await self.db.execute(
                    select(LibraryReservation)
                    .where(
                        LibraryReservation.book_id == c.book_id, LibraryReservation.status.in_(("available", "waiting"))
                    )
                    .order_by((LibraryReservation.status == "available").desc(), LibraryReservation.reserved_at)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        mine = next((r for r in queue if r.member_id == m.id), None)
        book = await self._book_locked(c.book_id)
        if c.status == "reserved" or (
            queue and book.available_copies <= len([r for r in queue if r.status == "available"])
        ):
            holder = next((r for r in queue if r.status == "available"), None) or (queue[0] if queue else None)
            if holder is not None and holder.member_id != m.id:
                raise rule("This title is reserved for another member", "RESERVED_FOR_OTHER")
        today = await self.today()
        st, e = await self.student_of_user(m.user_id)
        due = body.due_on or await self.due_date(today, m.loan_days, "students" if st else "staff")
        issue = BookIssue(
            institution_id=self.inst,
            copy_id=c.id,
            member_id=m.id,
            issued_on=today,
            due_on=due,
            issued_by=self.actor_id,
            status="issued",
        )
        self.db.add(issue)
        if c.status == "available":
            book.available_copies = max(book.available_copies - 1, 0)
        c.status = "issued"
        if mine is not None:
            mine.status = "fulfilled"
            mine.expires_at = now_utc()
            await self._emit(
                "library.reservation_fulfilled", {"reservation_id": str(mine.id)}, "library_reservation", mine.id
            )
        await self.db.flush()
        await self.db.refresh(issue)
        await self._audit(
            "issue",
            ENTITY,
            issue.id,
            None,
            {"copy": c.accession_number, "member": m.member_code, "due_on": due.isoformat()},
        )
        await self._emit(
            "library.issued",
            {"issue_id": str(issue.id), "member_id": str(m.id), "due_on": due.isoformat()},
            ENTITY,
            issue.id,
        )
        await self._notify("library.issued", [m.user_id], {"title": book.title, "due": due.isoformat()})
        return (await self.issue_outs([issue]))[0]

    # ---- return -----------------------------------------------------------------------------------------------------
    async def return_copy(self, body: BookReturnRequest) -> BookReturnResponse:
        if not self.can_circulate():
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "library:circulate required")
        c = await self.copy_by(barcode=body.barcode, accession_number=body.accession_number, rfid_tag=body.rfid_tag)
        issue = (
            (
                await self.db.execute(
                    select(BookIssue)
                    .where(BookIssue.copy_id == c.id, BookIssue.status.in_((*ACTIVE_ISSUE, "lost")))
                    .order_by(BookIssue.issued_on.desc())
                    .with_for_update()
                )
            )
            .scalars()
            .first()
        )
        if issue is None:
            raise rule("This copy is not on loan", "NOT_ON_LOAN")
        m = (await self.db.execute(select(LibraryMember).where(LibraryMember.id == issue.member_id))).scalar_one()
        book = await self._book_locked(c.book_id)
        today = await self.today()
        was_lost = issue.status == "lost"
        fine = 0
        invoice_id = None
        if was_lost:
            # found: a lost copy comes back
            if await self.lib_setting("found_cancels_invoice", True):
                await self._cancel_invoice(issue.fine_invoice_id, "Lost book found")
                issue.fine_paise = 0
        else:
            fine = compute_fine(await self._fine_config(), (today - issue.due_on).days)
            if body.condition == "damaged" and body.damage_charge_paise:
                fine += body.damage_charge_paise
            if fine > 0:
                invoice_id = await self._invoice(issue, m, fine, f"Library fine — {book.title[:120]}")
                issue.fine_paise, issue.fine_invoice_id = fine, invoice_id
        issue.status, issue.returned_on, issue.returned_to = "returned", today, self.actor_id
        notified = False
        if body.condition == "damaged":
            c.status = "damaged"
            if was_lost:
                book.total_copies += 0
        else:
            nxt = (
                await self.db.execute(
                    select(LibraryReservation)
                    .where(LibraryReservation.book_id == book.id, LibraryReservation.status == "waiting")
                    .order_by(LibraryReservation.reserved_at)
                    .limit(1)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if nxt is not None:
                c.status = "reserved"
                nxt.status = "available"
                nxt.expires_at = now_utc() + timedelta(hours=int(await self.lib_setting("hold_hours", 48)))
                holder = (
                    await self.db.execute(select(LibraryMember).where(LibraryMember.id == nxt.member_id))
                ).scalar_one()
                await self._notify(
                    "library.reservation_available",
                    [holder.user_id],
                    {"title": book.title, "until": nxt.expires_at.isoformat()},
                )
                await self._emit(
                    "library.reservation_available", {"reservation_id": str(nxt.id)}, "library_reservation", nxt.id
                )
                notified = True
            else:
                c.status = "available"
                book.available_copies += 1
        await self.db.flush()
        await self.db.refresh(issue)
        released = await self._release_holds(m)
        await self._audit(
            "return", ENTITY, issue.id, None, {"fine_paise": fine, "condition": body.condition, "found": was_lost}
        )
        await self._emit("library.returned", {"issue_id": str(issue.id), "fine_paise": fine}, ENTITY, issue.id)
        await self.reevaluate_no_dues(m)
        return BookReturnResponse(
            issue=(await self.issue_outs([issue]))[0],
            fine_paise=fine,
            invoice_id=invoice_id,
            reservation_notified=notified,
            hold_released=released,
        )

    async def _release_holds(self, m: LibraryMember) -> bool:
        st, e = await self.student_of_user(m.user_id)
        if e is None:
            return False
        today = await self.today()
        threshold = int(await self.lib_setting("hold_after_days", 30))
        still = (
            await self.db.execute(
                select(func.count())
                .select_from(BookIssue)
                .where(
                    BookIssue.member_id == m.id,
                    BookIssue.status.in_(ACTIVE_ISSUE),
                    BookIssue.due_on < today - timedelta(days=threshold),
                )
            )
        ).scalar_one()
        if still:
            return False
        holds = (
            (
                await self.db.execute(
                    select(StudentHold).where(
                        StudentHold.student_program_enrollment_id == e.id,
                        StudentHold.hold_type == "library",
                        StudentHold.source_type == "book_issue",
                        StudentHold.released_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for h in holds:
            h.released_at, h.released_by = now_utc(), self.actor_id
            await self._emit(
                "hold.released",
                {"hold_id": str(h.id), "student_id": str(st.id) if st else None, "hold_type": "library"},
                "student_hold",
                h.id,
            )
        await self.db.flush()
        return bool(holds)

    # ---- renew / lost -----------------------------------------------------------------------------------------------
    async def _issue_row(self, issue_id: uuid.UUID) -> BookIssue:
        row = (
            await self.db.execute(
                select(BookIssue)
                .where(
                    BookIssue.id == issue_id,
                    BookIssue.institution_id == self.inst,
                    BookIssue.member_id.in_(visible_member_ids(self.principal)),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Issue not found")
        return row

    async def renew(self, issue_id: uuid.UUID, *, self_service: bool = False) -> BookIssueResponse:
        issue = await self._issue_row(issue_id)
        m = (await self.db.execute(select(LibraryMember).where(LibraryMember.id == issue.member_id))).scalar_one()
        if self_service:
            if self.principal is None or m.user_id != self.principal.id:
                raise APIError(404, ErrorCode.NOT_FOUND, "Issue not found")
        elif not self.can_circulate():
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "library:circulate required")
        if issue.status not in ACTIVE_ISSUE:
            raise rule(f"The issue is {issue.status}", "NOT_ACTIVE")
        r = await self.rules(m.member_type)
        if issue.renewals >= int(r.get("max_renewals", 1)):
            raise rule("Renewal limit reached", "RENEWAL_LIMIT", max_renewals=int(r.get("max_renewals", 1)))
        c = (await self.db.execute(select(LibraryCopy).where(LibraryCopy.id == issue.copy_id))).scalar_one()
        waiting = (
            await self.db.execute(
                select(func.count())
                .select_from(LibraryReservation)
                .where(LibraryReservation.book_id == c.book_id, LibraryReservation.status == "waiting")
            )
        ).scalar_one()
        if waiting:
            raise rule("Another member has reserved this title", "RESERVED")
        today = await self.today()
        cfg = await self._fine_config()
        if (today - issue.due_on).days > int(cfg.grace_days if cfg else 0):
            raise rule("Overdue books cannot be renewed — return it and pay the fine", "OVERDUE")
        reasons, _, _ = await MemberService(self.db, self.principal, self.request, self.inst).block_reasons(m)
        if reasons:
            raise rule("The member is blocked", "MEMBER_BLOCKED", reasons=reasons)
        st, _e = await self.student_of_user(m.user_id)
        old = issue.due_on
        issue.due_on = await self.due_date(today, m.loan_days, "students" if st else "staff")
        issue.renewals += 1
        issue.status = "issued"
        await self.db.flush()
        await self.db.refresh(issue)
        await self._audit(
            "renew",
            ENTITY,
            issue.id,
            {"due_on": old.isoformat()},
            {"due_on": issue.due_on.isoformat(), "renewals": issue.renewals},
        )
        await self._emit(
            "library.renewed", {"issue_id": str(issue.id), "due_on": issue.due_on.isoformat()}, ENTITY, issue.id
        )
        return (await self.issue_outs([issue]))[0]

    async def mark_lost(self, body: BookLostRequest) -> BookIssueResponse:
        if not self.can_circulate():
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "library:circulate required")
        issue = await self._issue_row(body.issue_id)
        if issue.status not in ACTIVE_ISSUE:
            raise rule(f"The issue is {issue.status}", "NOT_ACTIVE")
        c = (
            await self.db.execute(select(LibraryCopy).where(LibraryCopy.id == issue.copy_id).with_for_update())
        ).scalar_one()
        book = await self._book_locked(c.book_id)
        m = (await self.db.execute(select(LibraryMember).where(LibraryMember.id == issue.member_id))).scalar_one()
        cost = body.replacement_cost_paise
        if cost is None:
            price = c.price_paise or book.price_paise or 50000
            cost = int(price * int(await self.lib_setting("lost_replacement_pct", 150)) / 100)
        issue.status, c.status = "lost", "lost"
        issue.fine_paise = cost
        issue.fine_invoice_id = await self._invoice(issue, m, cost, f"Lost book — {book.title[:120]}")
        await self.db.flush()
        await self.db.refresh(issue)
        await self._audit("lost", ENTITY, issue.id, None, {"replacement_paise": cost})
        await self._emit("library.lost", {"issue_id": str(issue.id), "amount_paise": cost}, ENTITY, issue.id)
        return (await self.issue_outs([issue]))[0]

    # ---- reads ------------------------------------------------------------------------------------------------------
    async def list_issues(
        self,
        status: str | None,
        member_id: uuid.UUID | None,
        overdue: bool,
        department_id: uuid.UUID | None,
        scope: str | None = None,
    ) -> list[BookIssueResponse]:
        q = select(BookIssue).where(
            BookIssue.institution_id == self.inst, BookIssue.member_id.in_(visible_member_ids(self.principal, scope))
        )
        today = await self.today()
        if status:
            q = q.where(BookIssue.status == status)
        if overdue:
            q = q.where(BookIssue.status.in_(ACTIVE_ISSUE), BookIssue.due_on < today)
        if member_id:
            q = q.where(BookIssue.member_id == member_id)
        if department_id:
            MemberService(self.db, self.principal, self.request, self.inst).check_department(department_id)
            from app.models.hr import Staff
            from app.models.students import Student, StudentProgramEnrollment

            users = (
                select(Student.user_id)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                .where(StudentProgramEnrollment.department_id == department_id)
                .union(select(Staff.user_id).where(Staff.department_id == department_id))
            )
            q = q.where(BookIssue.member_id.in_(select(LibraryMember.id).where(LibraryMember.user_id.in_(users))))
        rows = list((await self.db.execute(q.order_by(BookIssue.due_on).limit(3000))).scalars().all())
        return await self.issue_outs(rows)

    async def get_issue(self, issue_id: uuid.UUID) -> BookIssueResponse:
        row = (
            await self.db.execute(
                select(BookIssue).where(
                    BookIssue.id == issue_id, BookIssue.member_id.in_(visible_member_ids(self.principal))
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Issue not found")
        return (await self.issue_outs([row]))[0]

    async def my_issues(self) -> list[BookIssueResponse]:
        ids = [m.id for m in await self.my_members()]
        rows = list(
            (
                await self.db.execute(
                    select(BookIssue)
                    .where(BookIssue.member_id.in_(ids or [uuid.uuid4()]))
                    .order_by(BookIssue.issued_on.desc())
                    .limit(500)
                )
            )
            .scalars()
            .all()
        )
        return await self.issue_outs(rows)

    # ---- reservations -----------------------------------------------------------------------------------------------
    async def res_outs(self, rows: list[LibraryReservation]) -> list[LibraryReservationResponse]:
        if not rows:
            return []
        titles: dict[Any, Any] = dict(
            (await self.db.execute(select(Book.id, Book.title).where(Book.id.in_({r.book_id for r in rows})))).all()  # type: ignore[arg-type]
        )
        members = {
            m.id: m
            for m in (
                await self.db.execute(select(LibraryMember).where(LibraryMember.id.in_({r.member_id for r in rows})))
            )
            .scalars()
            .all()
        }
        names = await self.member_names([m.user_id for m in members.values()])
        out = []
        for r in rows:
            pos = None
            if r.status == "waiting":
                pos = int(
                    (
                        await self.db.execute(
                            select(func.count())
                            .select_from(LibraryReservation)
                            .where(
                                LibraryReservation.book_id == r.book_id,
                                LibraryReservation.status == "waiting",
                                LibraryReservation.reserved_at <= r.reserved_at,
                            )
                        )
                    ).scalar_one()
                )
            m = members.get(r.member_id)
            out.append(
                LibraryReservationResponse(
                    id=r.id,
                    book_id=r.book_id,
                    title=titles.get(r.book_id),
                    member_id=r.member_id,
                    member_code=m.member_code if m else None,
                    member_name=names.get(m.user_id) if m else None,
                    status=r.status,
                    position=pos,
                    reserved_at=r.reserved_at,
                    expires_at=r.expires_at,
                )
            )
        return out

    async def reserve(self, body: LibraryReservationCreate) -> LibraryReservationResponse:
        if body.member_code:
            if not self.can_circulate():
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "library:circulate required")
            m = await self.member_by(member_code=body.member_code)
        else:
            mine = await self.my_members()
            if not mine:
                raise APIError(404, ErrorCode.NOT_FOUND, "You are not a library member")
            m = mine[0]
        book = (
            await self.db.execute(
                select(Book).where(Book.id == body.book_id, Book.institution_id == self.inst, Book.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if book is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Book not found")
        if book.available_copies > 0 and not await self.lib_setting("allow_reserve_available", False):
            raise rule("Copies are available — borrow one at the counter", "COPIES_AVAILABLE")
        dup = (
            await self.db.execute(
                select(LibraryReservation.id).where(
                    LibraryReservation.book_id == book.id,
                    LibraryReservation.member_id == m.id,
                    LibraryReservation.status.in_(("waiting", "available")),
                )
            )
        ).first()
        if dup:
            raise rule("You already reserved this title", "ALREADY_RESERVED")
        r = LibraryReservation(institution_id=self.inst, book_id=book.id, member_id=m.id, status="waiting")
        self.db.add(r)
        await self.db.flush()
        await self.db.refresh(r)
        await self._emit("library.reservation_created", {"reservation_id": str(r.id)}, "library_reservation", r.id)
        return (await self.res_outs([r]))[0]

    async def list_reservations(self, status: str | None, mine: bool = False) -> list[LibraryReservationResponse]:
        q = select(LibraryReservation).where(LibraryReservation.institution_id == self.inst)
        if mine or not self.can_circulate():
            q = q.where(LibraryReservation.member_id.in_([m.id for m in await self.my_members()] or [uuid.uuid4()]))
        else:
            q = q.where(LibraryReservation.member_id.in_(visible_member_ids(self.principal)))
        if status:
            q = q.where(LibraryReservation.status == status)
        rows = list((await self.db.execute(q.order_by(LibraryReservation.reserved_at).limit(2000))).scalars().all())
        return await self.res_outs(rows)

    async def _close_reservation(self, r: LibraryReservation, status: str) -> None:
        """Terminal statuses stay unique per (book, member) — an older terminal row of the same status is deleted."""
        old = (
            (
                await self.db.execute(
                    select(LibraryReservation).where(
                        LibraryReservation.book_id == r.book_id,
                        LibraryReservation.member_id == r.member_id,
                        LibraryReservation.status == status,
                        LibraryReservation.id != r.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        for o in old:
            await self.db.delete(o)
        await self.db.flush()
        r.status = status
        r.expires_at = r.expires_at or now_utc()

    async def cancel_reservation(self, rid: uuid.UUID) -> LibraryReservationResponse:
        r = (
            await self.db.execute(
                select(LibraryReservation)
                .where(LibraryReservation.id == rid, LibraryReservation.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        mine = {m.id for m in await self.my_members()}
        if r is None or (r.member_id not in mine and not self.can_circulate()):
            raise APIError(404, ErrorCode.NOT_FOUND, "Reservation not found")
        if r.status not in ("waiting", "available"):
            raise rule(f"The reservation is {r.status}", "NOT_ACTIVE")
        was_available = r.status == "available"
        await self._close_reservation(r, "cancelled")
        if was_available:
            await self._promote(r.book_id)
        await self.db.flush()
        return (await self.res_outs([r]))[0]

    async def _promote(self, book_id: uuid.UUID) -> None:
        """A reserved copy freed by an expired / cancelled hold goes to the next in queue (or back to the shelf)."""
        copy = (
            await self.db.execute(
                select(LibraryCopy)
                .where(LibraryCopy.book_id == book_id, LibraryCopy.status == "reserved")
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if copy is None:
            return
        nxt = (
            await self.db.execute(
                select(LibraryReservation)
                .where(LibraryReservation.book_id == book_id, LibraryReservation.status == "waiting")
                .order_by(LibraryReservation.reserved_at)
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        book = await self._book_locked(book_id)
        if nxt is None:
            copy.status = "available"
            book.available_copies += 1
            return
        nxt.status = "available"
        nxt.expires_at = now_utc() + timedelta(hours=int(await self.lib_setting("hold_hours", 48)))
        holder = (await self.db.execute(select(LibraryMember).where(LibraryMember.id == nxt.member_id))).scalar_one()
        await self._notify(
            "library.reservation_available",
            [holder.user_id],
            {"title": book.title, "until": nxt.expires_at.isoformat()},
        )

    async def expire_reservations(self) -> int:
        rows = (
            (
                await self.db.execute(
                    select(LibraryReservation)
                    .where(
                        LibraryReservation.institution_id == self.inst,
                        LibraryReservation.status == "available",
                        LibraryReservation.expires_at < now_utc(),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            await self._close_reservation(r, "expired")
            await self._emit("library.reservation_expired", {"reservation_id": str(r.id)}, "library_reservation", r.id)
            await self._promote(r.book_id)
        await self.db.flush()
        return len(rows)

    # ---- fines ------------------------------------------------------------------------------------------------------
    async def fines(
        self, status: str | None, member_id: uuid.UUID | None, *, mine: bool = False
    ) -> list[LibraryFineRow]:
        q = (
            select(BookIssue, FeeInvoice)
            .join(FeeInvoice, FeeInvoice.id == BookIssue.fine_invoice_id)
            .where(BookIssue.institution_id == self.inst)
        )
        if mine:
            q = q.where(BookIssue.member_id.in_([m.id for m in await self.my_members()] or [uuid.uuid4()]))
        elif not (self.can("library", "fines") or self.can_circulate() or self.can("library", "view_all")):
            q = q.where(BookIssue.member_id.in_(visible_member_ids(self.principal, "self")))
        else:
            q = q.where(
                BookIssue.member_id.in_(visible_member_ids(self.principal))
                if not self.can("library", "fines")
                else BookIssue.institution_id == self.inst
            )
        if member_id:
            q = q.where(BookIssue.member_id == member_id)
        if status == "outstanding":
            q = q.where(FeeInvoice.status.in_(OPEN))
        elif status:
            q = q.where(FeeInvoice.status == status)
        rows = (await self.db.execute(q.order_by(BookIssue.returned_on.desc().nulls_first()).limit(3000))).all()
        outs = {o.id: o for o in await self.issue_outs([r[0] for r in rows])}
        return [
            LibraryFineRow(
                issue_id=i.id,
                title=outs[i.id].title,
                member_code=outs[i.id].member_code,
                member_name=outs[i.id].member_name,
                fine_paise=i.fine_paise,
                invoice_id=inv.id,
                invoice_status=inv.status,
                balance_paise=int(inv.balance_paise or 0),
                returned_on=i.returned_on,
                status=i.status,
            )
            for i, inv in rows
        ]

    async def waive(self, issue_id: uuid.UUID, reason: str) -> LibraryFineRow:
        if not self.can("library", "manage"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the librarian may waive fines")
        issue = await self._issue_row(issue_id)
        if issue.fine_invoice_id is None:
            raise rule("No fine on this issue", "NO_FINE")
        if not await self._cancel_invoice(issue.fine_invoice_id, f"Waived: {reason}"):
            raise rule("The fine is paid or already settled", "NOT_WAIVABLE")
        old = issue.fine_paise
        issue.fine_paise = 0
        await self.db.flush()
        await self._audit("fine_waive", ENTITY, issue.id, {"fine_paise": old}, {"fine_paise": 0, "reason": reason})
        await self._emit("library.fine_waived", {"issue_id": str(issue.id), "amount_paise": old}, ENTITY, issue.id)
        m = (await self.db.execute(select(LibraryMember).where(LibraryMember.id == issue.member_id))).scalar_one()
        await self.reevaluate_no_dues(m)
        rows = await self.fines(None, issue.member_id)
        return next(
            (r for r in rows if r.issue_id == issue.id),
            rows[0] if rows else LibraryFineRow(issue_id=issue.id, fine_paise=0, status=issue.status),
        )

    # ---- overdue Beat -----------------------------------------------------------------------------------------------
    async def overdue_scan(self) -> dict[str, int]:
        today = await self.today()
        rows = (
            await self.db.execute(
                select(BookIssue, LibraryMember)
                .join(LibraryMember, LibraryMember.id == BookIssue.member_id)
                .where(BookIssue.institution_id == self.inst, BookIssue.status.in_(ACTIVE_ISSUE))
            )
        ).all()
        threshold = int(await self.lib_setting("hold_after_days", 30))
        marked = reminded = holds = 0
        titles: dict[Any, Any] = {}
        for issue, m in rows:
            days = (today - issue.due_on).days
            if days == -3 or days == 0 or days == 7 or (days > 7 and days % 7 == 0):
                if issue.copy_id not in titles:
                    titles[issue.copy_id] = (
                        await self.db.execute(
                            select(Book.title)
                            .join(LibraryCopy, LibraryCopy.book_id == Book.id)
                            .where(LibraryCopy.id == issue.copy_id)
                        )
                    ).scalar_one_or_none()
                key = "library.due_reminder" if days <= 0 else "library.overdue"
                await self._notify(
                    key,
                    [m.user_id],
                    {
                        "book": titles[issue.copy_id] or "",
                        "due_date": issue.due_on.isoformat(),
                        "days": str(max(days, 0)),
                    },
                )
                reminded += 1
            if days > 0 and issue.status != "overdue":
                issue.status = "overdue"
                marked += 1
                await self._emit("library.overdue", {"issue_id": str(issue.id), "days": days}, ENTITY, issue.id)
            if days > threshold:
                st, e = await self.student_of_user(m.user_id)
                if e is not None:
                    exists = (
                        await self.db.execute(
                            select(StudentHold.id).where(
                                StudentHold.student_program_enrollment_id == e.id,
                                StudentHold.hold_type == "library",
                                StudentHold.released_at.is_(None),
                            )
                        )
                    ).first()
                    if not exists:
                        h = StudentHold(
                            institution_id=self.inst,
                            student_program_enrollment_id=e.id,
                            hold_type="library",
                            reason=f"Library book overdue by {days} days",
                            placed_by=self.actor_id or m.user_id,
                            source_type="book_issue",
                            source_id=issue.id,
                        )
                        self.db.add(h)
                        await self.db.flush()
                        await self._emit(
                            "hold.placed",
                            {"hold_id": str(h.id), "student_id": str(st.id) if st else None, "hold_type": "library"},
                            "student_hold",
                            h.id,
                        )
                        holds += 1
        await self.db.flush()
        return {"marked": marked, "reminded": reminded, "holds": holds}

    # ---- no-dues hook -----------------------------------------------------------------------------------------------
    async def library_dues(self, m: LibraryMember) -> tuple[int, int]:
        active = (
            await self.db.execute(
                select(func.count())
                .select_from(BookIssue)
                .where(BookIssue.member_id == m.id, BookIssue.status.in_(ACTIVE_ISSUE))
            )
        ).scalar_one()
        unpaid = (
            await self.db.execute(
                select(func.coalesce(func.sum(FeeInvoice.balance_paise), 0))
                .join(BookIssue, BookIssue.fine_invoice_id == FeeInvoice.id)
                .where(BookIssue.member_id == m.id, FeeInvoice.status.in_(OPEN))
            )
        ).scalar_one()
        return int(active), int(unpaid)

    async def sign_no_dues(self, request_id: uuid.UUID) -> str | None:
        """Auto sign-off of the library step (``cleared`` / ``dues_pending``); ``None`` when the request has none."""
        from app.models.students import Student, StudentProgramEnrollment
        from app.services.fees.no_dues_service import NoDuesService

        r = (
            await self.db.execute(select(NoDuesRequest).where(NoDuesRequest.id == request_id).with_for_update())
        ).scalar_one_or_none()
        if r is None or r.status == "cleared":
            return None
        signs = list(
            (await self.db.execute(select(NoDuesSignoff).where(NoDuesSignoff.request_id == r.id).with_for_update()))
            .scalars()
            .all()
        )
        s = next((x for x in signs if x.department_key == "library"), None)
        if s is None or s.signed_by is not None and s.status == "cleared":
            return None
        st = (
            await self.db.execute(
                select(Student)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                .where(StudentProgramEnrollment.id == r.student_program_enrollment_id)
            )
        ).scalar_one()
        m = None
        if st.user_id:
            m = (
                (
                    await self.db.execute(
                        select(LibraryMember).where(
                            LibraryMember.institution_id == self.inst, LibraryMember.user_id == st.user_id
                        )
                    )
                )
                .scalars()
                .first()
            )
        active, unpaid = await self.library_dues(m) if m is not None else (0, 0)
        status = "cleared" if not active and not unpaid else "dues_pending"
        if s.status == status and s.dues_paise == unpaid:
            return status
        s.status, s.dues_paise = status, unpaid if status == "dues_pending" else 0
        s.remarks = (
            f"Auto: {active} book(s) on loan, {rupees(unpaid)} unpaid"
            if status == "dues_pending"
            else "Auto: no books or fines"
        )
        s.signed_at = now_utc()
        await self.db.flush()
        await self._emit(
            "no_dues.signoff",
            {"request_id": str(r.id), "department_key": "library", "status": status},
            "no_dues_request",
            r.id,
        )
        await NoDuesService(self.db, None, self.request, self.inst)._settle(r, signs, st)
        return status

    async def reevaluate_no_dues(self, m: LibraryMember) -> None:
        from app.models.students import Student, StudentProgramEnrollment

        reqs = (
            (
                await self.db.execute(
                    select(NoDuesRequest.id)
                    .join(
                        StudentProgramEnrollment,
                        StudentProgramEnrollment.id == NoDuesRequest.student_program_enrollment_id,
                    )
                    .join(Student, Student.id == StudentProgramEnrollment.student_id)
                    .where(
                        Student.user_id == m.user_id, NoDuesRequest.status.in_(("requested", "in_progress", "blocked"))
                    )
                )
            )
            .scalars()
            .all()
        )
        for rid in reqs:
            await self.sign_no_dues(rid)

    async def member_fine_paid(self, issue_id: uuid.UUID) -> None:
        m = (
            await self.db.execute(
                select(LibraryMember)
                .join(BookIssue, BookIssue.member_id == LibraryMember.id)
                .where(BookIssue.id == issue_id)
            )
        ).scalar_one_or_none()
        if m is not None:
            await self.reevaluate_no_dues(m)

    async def today_counts(self) -> tuple[int, int]:
        today = await self.today()
        issued = (
            await self.db.execute(
                select(func.count())
                .select_from(BookIssue)
                .where(BookIssue.institution_id == self.inst, BookIssue.issued_on == today)
            )
        ).scalar_one()
        returned = (
            await self.db.execute(
                select(func.count())
                .select_from(BookIssue)
                .where(BookIssue.institution_id == self.inst, BookIssue.returned_on == today)
            )
        ).scalar_one()
        return int(issued), int(returned)
