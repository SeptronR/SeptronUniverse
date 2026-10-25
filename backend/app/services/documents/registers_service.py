"""Statutory serial registers — Prompts/26 §26.6 ``registers_service`` ({documents.serial_registers}).

Registers ``degree | provisional | transcript | tc | migration | bonafide``; serials come from the never-resetting
sequence ``serial:{register}`` and live in ``document_serials`` (``reserved → used``, ``void`` with a reason in
``documents_meta`` ``serial:<id>``). ``take()`` (called by the renderer) locks the register's rows ``FOR UPDATE`` and
consumes the lowest reserved serial before minting a new one. Physical book mapping (book no. / first page / serials
per page) is ``documents_meta`` ``book:<register>``. Reconciliation compares issued documents of the type against
used / reserved / void serials and lists numbering gaps.
"""

import re
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.documents import REGISTERS
from app.models.documents import DocumentSerial, IssuedDocument
from app.schemas.documents import DocReconcileOut, DocSerialRegisterOut, DocSerialRow
from app.services.documents.common import DocumentsBase, forbidden, not_found, rule

REGISTER_PREFIX = {
    "degree": "DSR",
    "provisional": "PSR",
    "transcript": "TSR",
    "tc": "TCS",
    "migration": "MSR",
    "bonafide": "BSR",
}


def _num(serial: str) -> int:
    m = re.search(r"(\d+)$", serial)
    return int(m.group(1)) if m else 0


class RegistersService(DocumentsBase):
    def _check(self, register: str) -> None:
        if register not in REGISTERS:
            raise APIError(422, ErrorCode.VALIDATION, f"Unknown register {register}")

    def _manage(self) -> None:
        if not (self.office() or self.can("templates", "manage")):
            raise forbidden("certificates:issue required")
        self.require_writer()

    async def mint(self, register: str) -> str:
        return await self.sequence(f"serial:{register}", REGISTER_PREFIX.get(register, "SR"))

    async def take(self, register: str) -> DocumentSerial:
        """Lowest reserved serial (``FOR UPDATE SKIP LOCKED``), else a freshly minted one — status ``used``."""
        rows = (
            (
                await self.db.execute(
                    select(DocumentSerial)
                    .where(
                        DocumentSerial.institution_id == self.inst,
                        DocumentSerial.register == register,
                        DocumentSerial.status == "reserved",
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        if rows:
            s = min(rows, key=lambda r: (_num(r.serial_no), r.serial_no))
            s.status = "used"
            await self.db.flush()
            return s
        s = DocumentSerial(
            institution_id=self.inst, register=register, serial_no=await self.mint(register), status="used"
        )
        self.db.add(s)
        await self.db.flush()
        return s

    async def registers(self) -> list[DocSerialRegisterOut]:
        await self.require_feature("documents.serial_registers")
        if not (self.office() or self.can("certificates", "view_all") or self.can("templates", "manage")):
            raise forbidden()
        counts: dict[tuple[str, str], int] = {
            (r, s): n
            for r, s, n in (
                await self.db.execute(
                    select(DocumentSerial.register, DocumentSerial.status, func.count())
                    .where(DocumentSerial.institution_id == self.inst)
                    .group_by(DocumentSerial.register, DocumentSerial.status)
                )
            ).all()
        }
        books = await self.metas("book")
        out = []
        for reg in REGISTERS:
            nxt = (
                await self.db.execute(
                    select(DocumentSerial.serial_no)
                    .where(
                        DocumentSerial.institution_id == self.inst,
                        DocumentSerial.register == reg,
                        DocumentSerial.status == "reserved",
                    )
                    .order_by(DocumentSerial.serial_no)
                    .limit(1)
                )
            ).scalar_one_or_none()
            out.append(
                DocSerialRegisterOut(
                    register=reg,
                    next=nxt,
                    reserved=counts.get((reg, "reserved"), 0),
                    used=counts.get((reg, "used"), 0),
                    void=counts.get((reg, "void"), 0),
                    book=books.get(reg) or None,
                )
            )
        return out

    async def rows(self, register: str, status: str | None = None) -> list[DocSerialRow]:
        await self.require_feature("documents.serial_registers")
        self._check(register)
        if not (self.office() or self.can("certificates", "view_all") or self.can("templates", "manage")):
            raise forbidden()
        stmt = (
            select(DocumentSerial, IssuedDocument.document_number)
            .outerjoin(IssuedDocument, IssuedDocument.id == DocumentSerial.issued_document_id)
            .where(DocumentSerial.institution_id == self.inst, DocumentSerial.register == register)
            .order_by(DocumentSerial.serial_no)
        )
        if status:
            stmt = stmt.where(DocumentSerial.status == status)
        res = (await self.db.execute(stmt)).all()
        reasons = await self.metas("serial", [s.id for s, _ in res if s.status == "void"])
        return [
            DocSerialRow(
                id=s.id,
                register=s.register,
                serial_no=s.serial_no,
                status=s.status,
                issued_document_id=s.issued_document_id,
                document_number=num,
                reason=(reasons.get(str(s.id)) or {}).get("reason"),
                created_at=s.created_at,
            )
            for s, num in res
        ]

    async def reserve(self, register: str, count: int) -> list[DocSerialRow]:
        await self.require_feature("documents.serial_registers")
        self._check(register)
        self._manage()
        made = []
        for _ in range(count):
            s = DocumentSerial(
                institution_id=self.inst, register=register, serial_no=await self.mint(register), status="reserved"
            )
            self.db.add(s)
            made.append(s)
        await self.db.flush()
        await self._audit("reserve", "document_serial", None, None, {"register": register, "count": count})
        return [
            DocSerialRow(id=s.id, register=register, serial_no=s.serial_no, status=s.status, created_at=s.created_at)
            for s in made
        ]

    async def void(self, register: str, serial_no: str, reason: str) -> DocSerialRow:
        await self.require_feature("documents.serial_registers")
        self._check(register)
        self._manage()
        s = (
            await self.db.execute(
                select(DocumentSerial)
                .where(
                    DocumentSerial.institution_id == self.inst,
                    DocumentSerial.register == register,
                    DocumentSerial.serial_no == serial_no,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if s is None:
            raise not_found("Serial")
        if s.status == "void":
            raise rule("The serial is already void", "ALREADY_VOID")
        if s.issued_document_id is not None:
            d = (
                await self.db.execute(select(IssuedDocument).where(IssuedDocument.id == s.issued_document_id))
            ).scalar_one()
            if d.revoked_at is None:
                raise rule("Revoke the document before voiding its serial", "DOCUMENT_LIVE")
        s.status = "void"
        await self.put_meta("serial", s.id, {"reason": reason, "by": str(self.actor_id) if self.actor_id else None})
        await self._audit(
            "void", "document_serial", s.id, None, {"register": register, "serial": serial_no, "reason": reason}
        )
        await self._emit(
            "documents.serial_voided",
            {"register": register, "serial_no": serial_no, "reason": reason},
            "document_serial",
            s.id,
        )
        return DocSerialRow(
            id=s.id,
            register=register,
            serial_no=s.serial_no,
            status="void",
            issued_document_id=s.issued_document_id,
            reason=reason,
            created_at=s.created_at,
        )

    async def set_book(self, register: str, book: dict[str, Any]) -> dict[str, Any]:
        self._check(register)
        self._manage()
        await self.put_meta("book", register, book)
        return book

    async def reconcile(self, register: str) -> DocReconcileOut:
        rows = await self.rows(register)
        issued = (
            (
                await self.db.execute(
                    select(IssuedDocument).where(
                        IssuedDocument.institution_id == self.inst, IssuedDocument.template_type == register
                    )
                )
            )
            .scalars()
            .all()
        )
        nums = sorted(_num(r.serial_no) for r in rows)
        gaps = [str(n) for a, b in zip(nums, nums[1:], strict=False) for n in range(a + 1, b)][:200]
        return DocReconcileOut(
            register=register,
            issued=len(issued),
            used=sum(1 for r in rows if r.status == "used"),
            reserved=sum(1 for r in rows if r.status == "reserved"),
            void=sum(1 for r in rows if r.status == "void"),
            issued_without_serial=[d.document_number for d in issued if not d.serial_no][:200],
            used_without_document=[r.serial_no for r in rows if r.status == "used" and not r.issued_document_id][:200],
            gaps=gaps,
        )

    async def export_csv(self, register: str) -> str:
        import csv
        import io

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["serial_no", "status", "document_number", "reason", "created_at"])
        for r in await self.rows(register):
            w.writerow([r.serial_no, r.status, r.document_number or "", r.reason or "", r.created_at.isoformat()])
        return buf.getvalue()
