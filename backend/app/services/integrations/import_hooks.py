"""Entity import hooks — Prompts/41 §41.6 ``import_service`` rules 1–3 (``import_hooks.validate / apply / rollback``).

Each :class:`EntityHook` declares the template columns, the permission that may import it (``integrations:import``
always may; else ``<module>:bulk_import``), a ``validate(row, ctx)`` returning ``(normalized, errors)`` and an
``apply(row, ctx)`` that goes through the owning module's service where one exists (students → Phase 07
``StudentService.create`` — registration numbers, events, audit; staff → Phase 06 ``StaffService.create``) and
returns the created entity id; ``rollback(entity_id, ctx)`` returns ``None`` when undone or the reason it cannot be
(e.g. a student who already has attendance / fee payments). Legacy results keep their Phase 16 service
(``/imports/legacy-results`` delegates).
"""

import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import text

Ctx = dict[str, Any]
Errors = list[dict[str, str]]


@dataclass
class EntityHook:
    entity: str
    label: str
    module: str
    columns: list[dict[str, Any]]
    validate: Callable[[dict[str, Any], Ctx], Awaitable[tuple[dict[str, Any], Errors]]]
    apply: Callable[[dict[str, Any], Ctx], Awaitable[uuid.UUID | None]]
    rollback: Callable[[uuid.UUID, Ctx], Awaitable[str | None]] | None = None
    notes: str | None = None
    unique: tuple[str, ...] = field(default_factory=tuple)

    @property
    def permission(self) -> str:
        return f"{self.module}:bulk_import"


HOOKS: dict[str, EntityHook] = {}


def col(
    key: str,
    label: str,
    type_: str = "str",
    required: bool = False,
    lookup: str | None = None,
    example: str | None = None,
    unique: bool = False,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "type": type_,
        "required": required,
        "lookup": lookup,
        "unique_in": "file+db" if unique else None,
        "example": example,
    }


def _err(column: str, code: str, message: str) -> dict[str, str]:
    return {"column": column, "code": code, "message": message}


def _date(v: Any) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(s)


def _phone(v: Any) -> str | None:
    if v in (None, ""):
        return None
    digits = re.sub(r"[^0-9+]", "", str(v))
    if digits.startswith("+"):
        return digits if 9 <= len(digits) <= 16 else ""
    if len(digits) == 10:
        return "+91" + digits
    return "+" + digits if 11 <= len(digits) <= 15 else ""


async def _required(row: dict[str, Any], hook: EntityHook) -> Errors:
    return [
        _err(c["key"], "REQUIRED", f"{c['label']} is required")
        for c in hook.columns
        if c["required"] and row.get(c["key"]) in (None, "")
    ]


# ---- students (Phase 07) ----------------------------------------------------------------------------------------------
async def _students_validate(row: dict[str, Any], ctx: Ctx) -> tuple[dict[str, Any], Errors]:
    db, inst = ctx["db"], ctx["inst"]
    errors = await _required(row, HOOKS["students"])
    n: dict[str, Any] = {k: (str(v).strip() if isinstance(v, str) else v) for k, v in row.items()}
    try:
        n["dob"] = _date(row.get("dob"))
    except ValueError:
        errors.append(_err("dob", "BAD_DATE", "Date of birth is not a date"))
    if row.get("phone"):
        n["phone"] = _phone(row["phone"])
        if not n["phone"]:
            errors.append(_err("phone", "BAD_PHONE", "Phone must have 10 digits (or E.164)"))
    if row.get("gender") and str(row["gender"]).lower() not in ("male", "female", "other", "m", "f", "o"):
        errors.append(_err("gender", "BAD_GENDER", "Gender must be male / female / other"))
    n["gender"] = {"m": "male", "f": "female", "o": "other"}.get(
        str(row.get("gender") or "").lower(), str(row.get("gender") or "").lower() or None
    )
    prog = (
        await db.execute(
            text(
                "SELECT id FROM programs WHERE institution_id = :i AND code = :c AND deleted_at IS NULL AND status = 'active'"
            ),
            {"i": inst, "c": str(row.get("program_code") or "").upper()},
        )
    ).first()
    if prog is None:
        errors.append(_err("program_code", "UNKNOWN_PROGRAM", f"No active programme {row.get('program_code')!r}"))
    else:
        n["program_id"] = str(prog[0])
    if row.get("category"):
        from app.core.packs.registry import get_pack

        try:
            pack = get_pack(ctx.get("pack", "IN"))
            cats = {c.upper() for c in getattr(pack, "categories", []) or []}
            if cats and str(row["category"]).upper() not in cats:
                errors.append(
                    _err("category", "BAD_CATEGORY", f"Category {row['category']!r} is not in the regulatory pack")
                )
        except Exception:  # noqa: BLE001 - pack lookup optional
            pass
    reg = str(row.get("registration_number") or "").strip()
    if reg:
        if reg in ctx.setdefault("seen_reg", set()):
            errors.append(_err("registration_number", "DUPLICATE_IN_FILE", "Registration number repeats in the file"))
        ctx["seen_reg"].add(reg)
        if (
            await db.execute(
                text(
                    "SELECT 1 FROM students WHERE institution_id = :i AND registration_number = :r AND deleted_at IS NULL"
                ),
                {"i": inst, "r": reg},
            )
        ).first():
            errors.append(_err("registration_number", "EXISTS", "A student with this registration number exists"))
    return n, errors


async def _students_apply(row: dict[str, Any], ctx: Ctx) -> uuid.UUID | None:
    from app.schemas.students import StudentCreate
    from app.services.student_service import StudentService

    body = StudentCreate.model_validate(
        {
            k: v
            for k, v in {
                "first_name": row.get("first_name"),
                "last_name": row.get("last_name"),
                "dob": row.get("dob"),
                "gender": row.get("gender"),
                "program_id": row.get("program_id"),
                "admission_year": int(row["admission_year"]) if row.get("admission_year") else None,
                "category": row.get("category"),
                "phone": row.get("phone"),
                "email": row.get("email") or None,
                "registration_number": row.get("registration_number") or None,
                "section": row.get("section") or None,
            }.items()
            if v not in (None, "")
        }
    )
    res = await StudentService(ctx["db"], ctx["principal"], ctx.get("request"), ctx["inst"]).create(
        body, "import", notify=False
    )
    return uuid.UUID(str(res.student.id))


async def _students_rollback(entity_id: uuid.UUID, ctx: Ctx) -> str | None:
    db = ctx["db"]
    deps = (
        await db.execute(
            text(
                "SELECT (SELECT count(*) FROM student_class_attendance a JOIN student_program_enrollments e ON e.id = a.student_program_enrollment_id WHERE e.student_id = :s) "
                "+ (SELECT count(*) FROM fee_payments p JOIN fee_invoices i ON i.id = p.invoice_id WHERE i.payer_type = 'student' AND i.payer_id = :s)"
            ),
            {"s": entity_id},
        )
    ).scalar_one()
    if deps:
        return "the student already has attendance or fee payments"
    await db.execute(text("UPDATE students SET deleted_at = NOW(), is_active = FALSE WHERE id = :s"), {"s": entity_id})
    return None


# ---- staff (Phase 06) -------------------------------------------------------------------------------------------------
async def _staff_validate(row: dict[str, Any], ctx: Ctx) -> tuple[dict[str, Any], Errors]:
    db, inst = ctx["db"], ctx["inst"]
    errors = await _required(row, HOOKS["staff"])
    n = dict(row)
    if row.get("phone"):
        n["phone"] = _phone(row["phone"])
        if not n["phone"]:
            errors.append(_err("phone", "BAD_PHONE", "Phone must have 10 digits"))
    try:
        n["joining_date"] = _date(row.get("joining_date"))
    except ValueError:
        errors.append(_err("joining_date", "BAD_DATE", "Joining date is not a date"))
    if row.get("department_code"):
        d = (
            await db.execute(
                text(
                    "SELECT id, college_id FROM departments WHERE institution_id = :i AND code = :c AND deleted_at IS NULL"
                ),
                {"i": inst, "c": str(row["department_code"]).upper()},
            )
        ).first()
        if d is None:
            errors.append(_err("department_code", "UNKNOWN_DEPARTMENT", "Unknown department code"))
        else:
            n["department_id"], n["college_id"] = str(d[0]), str(d[1]) if d[1] else None
    if row.get("designation_code"):
        g = (
            await db.execute(
                text("SELECT id FROM designations WHERE institution_id = :i AND code = :c"),
                {"i": inst, "c": str(row["designation_code"]).upper()},
            )
        ).first()
        if g is None:
            errors.append(_err("designation_code", "UNKNOWN_DESIGNATION", "Unknown designation code"))
        else:
            n["designation_id"] = str(g[0])
    return n, errors


async def _staff_apply(row: dict[str, Any], ctx: Ctx) -> uuid.UUID | None:
    from app.schemas.hr import StaffCreate
    from app.services.staff_service import StaffService

    body = StaffCreate.model_validate(
        {
            k: v
            for k, v in {
                "first_name": row.get("first_name"),
                "last_name": row.get("last_name"),
                "phone": row.get("phone"),
                "email": row.get("email") or None,
                "department_id": row.get("department_id"),
                "designation_id": row.get("designation_id"),
                "college_id": row.get("college_id"),
                "joining_date": row.get("joining_date"),
            }.items()
            if v not in (None, "")
        }
    )
    res = await StaffService(ctx["db"], ctx["principal"], ctx.get("request"), ctx["inst"]).create(body)
    return uuid.UUID(str(res.staff.id))


async def _staff_rollback(entity_id: uuid.UUID, ctx: Ctx) -> str | None:
    db = ctx["db"]
    if (await db.execute(text("SELECT 1 FROM staff_attendance WHERE staff_id = :s LIMIT 1"), {"s": entity_id})).first():
        return "the staff member already has attendance"
    await db.execute(text("UPDATE staff SET deleted_at = NOW(), is_active = FALSE WHERE id = :s"), {"s": entity_id})
    return None


# ---- books (Phase 19) -------------------------------------------------------------------------------------------------
async def _books_validate(row: dict[str, Any], ctx: Ctx) -> tuple[dict[str, Any], Errors]:
    errors = await _required(row, HOOKS["books"])
    n = dict(row)
    try:
        n["copies"] = max(1, int(row.get("copies") or 1))
    except ValueError:
        errors.append(_err("copies", "BAD_NUMBER", "Copies must be a number"))
    acc = str(row.get("accession_prefix") or "").strip()
    if acc and acc in ctx.setdefault("seen_acc", set()):
        errors.append(_err("accession_prefix", "DUPLICATE_IN_FILE", "Accession prefix repeats"))
    ctx["seen_acc"].add(acc)
    return n, errors


async def _books_apply(row: dict[str, Any], ctx: Ctx) -> uuid.UUID | None:
    db, inst = ctx["db"], ctx["inst"]
    bid = uuid.uuid4()
    copies = int(row.get("copies") or 1)
    await db.execute(
        text(
            "INSERT INTO books (id, institution_id, title, isbn, resource_type, total_copies, available_copies, is_active, version, created_at, updated_at) "
            "VALUES (:id, :i, :t, :isbn, 'book', :n, :n, TRUE, 1, NOW(), NOW())"
        ),
        {"id": bid, "i": inst, "t": row["title"], "isbn": row.get("isbn") or None, "n": copies},
    )
    prefix = str(row.get("accession_prefix") or f"IMP{bid.hex[:6].upper()}")
    for k in range(copies):
        await db.execute(
            text(
                "INSERT INTO library_copies (id, institution_id, book_id, accession_number, status, created_at, updated_at) VALUES (:id, :i, :b, :a, 'available', NOW(), NOW())"
            ),
            {"id": uuid.uuid4(), "i": inst, "b": bid, "a": f"{prefix}-{k + 1:03d}"},
        )
    return bid


async def _books_rollback(entity_id: uuid.UUID, ctx: Ctx) -> str | None:
    db = ctx["db"]
    if (
        await db.execute(
            text(
                "SELECT 1 FROM book_issues bi JOIN library_copies c ON c.id = bi.copy_id WHERE c.book_id = :b LIMIT 1"
            ),
            {"b": entity_id},
        )
    ).first():
        return "copies of this book were issued"
    await db.execute(text("DELETE FROM library_copies WHERE book_id = :b"), {"b": entity_id})
    await db.execute(text("DELETE FROM books WHERE id = :b"), {"b": entity_id})
    return None


# ---- fee opening dues (Phase 12) ------------------------------------------------------------------------------------
async def _dues_validate(row: dict[str, Any], ctx: Ctx) -> tuple[dict[str, Any], Errors]:
    db, inst = ctx["db"], ctx["inst"]
    errors = await _required(row, HOOKS["fee_opening_dues"])
    n = dict(row)
    s = (
        await db.execute(
            text(
                "SELECT id, college_id FROM students WHERE institution_id = :i AND registration_number = :r AND deleted_at IS NULL"
            ),
            {"i": inst, "r": str(row.get("registration_number") or "")},
        )
    ).first()
    if s is None:
        errors.append(_err("registration_number", "UNKNOWN_STUDENT", "No student with this registration number"))
    else:
        n["student_id"], n["college_id"] = str(s[0]), str(s[1]) if s[1] else None
    try:
        n["amount_paise"] = int(round(float(str(row.get("amount_rupees") or 0)) * 100))
        if n["amount_paise"] <= 0:
            raise ValueError
    except ValueError:
        errors.append(_err("amount_rupees", "BAD_AMOUNT", "Amount must be a positive number"))
    return n, errors


async def _dues_apply(row: dict[str, Any], ctx: Ctx) -> uuid.UUID | None:
    from app.services.sequence_service import SequenceService

    db, inst = ctx["db"], ctx["inst"]
    try:
        number = (await SequenceService(db, ctx["principal"], None, inst).next("fee_invoice")).rendered
    except Exception:  # noqa: BLE001 - sequences optional for opening balances
        number = f"OB/{uuid.uuid4().hex[:8].upper()}"
    iid = uuid.uuid4()
    amt = int(row["amount_paise"])
    await db.execute(
        text(
            "INSERT INTO fee_invoices (id, institution_id, college_id, payer_type, payer_id, invoice_number, source_type, description, total_paise, "
            "discount_paise, tax_paise, fine_paise, paid_paise, balance_paise, status, version, created_at, updated_at) VALUES (:id, :i, :c, 'student', :p, :n, "
            "'opening_balance', :d, :a, 0, 0, 0, 0, :a, 'open', 1, NOW(), NOW())"
        ),
        {
            "id": iid,
            "i": inst,
            "c": row.get("college_id"),
            "p": row["student_id"],
            "n": str(number),
            "d": row.get("description") or "Opening balance (migrated)",
            "a": amt,
        },
    )
    return iid


async def _dues_rollback(entity_id: uuid.UUID, ctx: Ctx) -> str | None:
    db = ctx["db"]
    if (await db.execute(text("SELECT 1 FROM fee_payments WHERE invoice_id = :i LIMIT 1"), {"i": entity_id})).first():
        return "payments were received against this invoice"
    await db.execute(
        text(
            "UPDATE fee_invoices SET status = 'cancelled', cancelled_at = NOW(), cancelled_reason = 'import rolled back' WHERE id = :i"
        ),
        {"i": entity_id},
    )
    return None


# ---- publications (Phase 30) ------------------------------------------------------------------------------------------
async def _pubs_validate(row: dict[str, Any], ctx: Ctx) -> tuple[dict[str, Any], Errors]:
    db, inst = ctx["db"], ctx["inst"]
    errors = await _required(row, HOOKS["publications"])
    n = dict(row)
    doi = str(row.get("doi") or "").strip().lower()
    if (
        doi
        and (
            await db.execute(
                text("SELECT 1 FROM publications WHERE institution_id = :i AND lower(doi) = :d"), {"i": inst, "d": doi}
            )
        ).first()
    ):
        errors.append(_err("doi", "EXISTS", "A publication with this DOI exists"))
    if row.get("employee_id"):
        s = (
            await db.execute(
                text("SELECT id FROM staff WHERE institution_id = :i AND employee_id = :e"),
                {"i": inst, "e": str(row["employee_id"])},
            )
        ).first()
        if s is None:
            errors.append(_err("employee_id", "UNKNOWN_STAFF", "Unknown employee id"))
        else:
            n["staff_id"] = str(s[0])
    return n, errors


async def _pubs_apply(row: dict[str, Any], ctx: Ctx) -> uuid.UUID | None:
    pid = uuid.uuid4()
    await ctx["db"].execute(
        text(
            "INSERT INTO publications (id, institution_id, staff_id, pub_type, title, venue, year, doi, is_verified, created_at, updated_at) VALUES (:id, :i, :s, :t, :ti, :v, :y, :d, FALSE, NOW(), NOW())"
        ),
        {
            "id": pid,
            "i": ctx["inst"],
            "s": row.get("staff_id"),
            "t": row.get("pub_type") or "journal",
            "ti": row["title"],
            "v": row.get("venue"),
            "y": int(row["year"]) if row.get("year") else None,
            "d": row.get("doi") or None,
        },
    )
    return pid


async def _pubs_rollback(entity_id: uuid.UUID, ctx: Ctx) -> str | None:
    await ctx["db"].execute(text("DELETE FROM publications WHERE id = :p AND NOT is_verified"), {"p": entity_id})
    return None


def _register() -> None:
    HOOKS["students"] = EntityHook(
        "students",
        "Students",
        "students",
        [
            col("first_name", "First name", required=True, example="Asha"),
            col("last_name", "Last name", example="Rao"),
            col("dob", "Date of birth", "date", True, example="2006-05-14"),
            col("gender", "Gender", required=True, example="female"),
            col("program_code", "Programme code", required=True, lookup="programs.code", example="BTECH_CSE"),
            col("admission_year", "Admission year", "int", example="2026"),
            col("category", "Category", example="GEN"),
            col("phone", "Phone", example="9876543210"),
            col("email", "E-mail", example="asha@example.com"),
            col("registration_number", "Registration number", unique=True),
            col("section", "Section", example="A"),
        ],
        _students_validate,
        _students_apply,
        _students_rollback,
        "Registration numbers are generated when blank (Phase 07 sequence).",
        ("registration_number",),
    )
    HOOKS["staff"] = EntityHook(
        "staff",
        "Staff",
        "hr",
        [
            col("first_name", "First name", required=True),
            col("last_name", "Last name"),
            col("phone", "Phone"),
            col("email", "E-mail"),
            col("department_code", "Department code", lookup="departments.code"),
            col("designation_code", "Designation code", lookup="designations.code"),
            col("joining_date", "Joining date", "date"),
        ],
        _staff_validate,
        _staff_apply,
        _staff_rollback,
    )
    HOOKS["books"] = EntityHook(
        "books",
        "Library books & copies",
        "library",
        [
            col("title", "Title", required=True),
            col("isbn", "ISBN"),
            col("copies", "Copies", "int", example="2"),
            col("accession_prefix", "Accession prefix", unique=True, example="ACC2026"),
        ],
        _books_validate,
        _books_apply,
        _books_rollback,
    )
    HOOKS["fee_opening_dues"] = EntityHook(
        "fee_opening_dues",
        "Fee opening dues",
        "fees",
        [
            col("registration_number", "Registration number", required=True, lookup="students.registration_number"),
            col("amount_rupees", "Amount (₹)", "number", True, example="12500"),
            col("description", "Description"),
        ],
        _dues_validate,
        _dues_apply,
        _dues_rollback,
        "Creates Phase 12 invoices with source_type='opening_balance'.",
    )
    HOOKS["publications"] = EntityHook(
        "publications",
        "Publications",
        "research",
        [
            col("title", "Title", required=True),
            col("pub_type", "Type", example="journal"),
            col("venue", "Venue"),
            col("year", "Year", "int"),
            col("doi", "DOI", unique=True),
            col("employee_id", "Employee id", lookup="staff.employee_id"),
        ],
        _pubs_validate,
        _pubs_apply,
        _pubs_rollback,
        "Deduplicated by DOI.",
    )


_register()

# cut-over order (migration workbook) — entities without an apply hook are tracked manually
WORKBOOK_STEPS: tuple[tuple[int, str, str, tuple[int, ...]], ...] = (
    (1, "institution_structure", "Institution structure (colleges, departments)", ()),
    (2, "programmes", "Programmes, regulations & curriculum", (1,)),
    (3, "batches", "Batches & sections", (2,)),
    (4, "staff", "Staff", (1,)),
    (5, "students", "Students & guardians", (3,)),
    (6, "fee_opening_dues", "Fee structures & opening dues", (5,)),
    (7, "hostel", "Hostel rooms & allocations", (5,)),
    (8, "books", "Library books, copies & members", (1,)),
    (9, "legacy_results", "Legacy results by term", (5,)),
    (10, "attendance_opening", "Attendance opening balances", (5,)),
    (11, "alumni", "Alumni", (5,)),
    (12, "publications", "Publications", (4,)),
)
