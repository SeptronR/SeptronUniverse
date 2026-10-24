"""Vendor portal & vendor store — Prompts/22 §22.6 ``vendor_portal_service`` / ``vendor_store_service``.

Portal (``inventory.vendor_portal``): public self-registration (tenant by institution slug, rate-limited + captcha) →
``suppliers.status='registered'``; the inventory manager's ``verify`` creates the portal user (``user_type='external'``,
role ``vendor`` scoped ``self``, no usable password — the vendor sets one through *Forgot password*) and makes the
supplier ``active``. RFQ inbox = approved indents of the supplier's categories (or all approved indents without
categories); quotation submit; POs (sent onward) with acknowledgement; GRN and bill status.

Store (``inventory.vendor_store``): campus store sales — an ``issue`` to the buyer at the item's sale price
(``safety_data.sale_price_paise`` → ``unit_cost_paise`` fallback) and a fee invoice ``source_type='vendor_store_sale'``
for students; daily sales report.
"""

import secrets
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text

from app.core.errors import APIError, ErrorCode
from app.models.inventory import Indent, Item, StockTransaction, Supplier
from app.models.platform import Role, User, UserRole
from app.schemas.inventory import (
    IndentResponse,
    SupplierIn,
    SupplierOut,
    SupplierRegister,
    VendorStoreSale,
)
from app.services.inventory.common import InventoryBase, rule

D = Decimal


async def tenant_by_slug(slug: str) -> uuid.UUID:
    from app.db.session import PlatformSessionLocal

    async with PlatformSessionLocal() as db:
        iid = (
            await db.execute(text("SELECT id FROM institutions WHERE slug = :s AND deleted_at IS NULL"), {"s": slug})
        ).scalar_one_or_none()
    if iid is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Institution not found")
    return uuid.UUID(str(iid))


class VendorService(InventoryBase):
    async def register(self, body: SupplierRegister) -> SupplierOut:
        from app.services.inventory.master_service import MasterService

        ms = MasterService(self.db, None, self.request, self.inst)
        out = await ms.create_supplier(
            SupplierIn(
                name=body.name,
                gstin=body.gstin,
                pan=body.pan,
                contact={"email": body.email, "phone": body.phone},
                categories=body.categories,
            ),
            status="registered",
        )
        await self._notify(
            "vendor.registered",
            [],
            {"supplier": body.name},
            audience={
                "roles": ["inventory_manager"],
                "direct_contacts": [{"to": body.email, "channel": "email", "name": body.name}],
            },
        )
        return out

    async def provision_user(self, s: Supplier) -> uuid.UUID | None:
        """Portal user for a verified supplier (idempotent)."""
        from app.core.security import hash_password

        if s.portal_user_id:
            return s.portal_user_id
        email = (s.contact or {}).get("email")
        if not email:
            return None
        user = (
            await self.db.execute(select(User).where(User.institution_id == self.inst, User.email == email))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                institution_id=self.inst,
                username=email.lower()[:100],
                email=email,
                phone=(s.contact or {}).get("phone"),
                display_name=s.name[:200],
                user_type="external",
                password_hash=hash_password(secrets.token_urlsafe(24)),
                is_verified=True,
                must_change_password=True,
            )
            self.db.add(user)
            await self.db.flush()
        role = (
            await self.db.execute(
                select(Role).where(Role.institution_id == self.inst, Role.slug == "vendor", Role.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if (
            role is not None
            and (
                await self.db.execute(
                    select(UserRole.id).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
                )
            ).first()
            is None
        ):
            self.db.add(
                UserRole(institution_id=self.inst, user_id=user.id, role_id=role.id, scope_type="self", scope_id=None)
            )
        s.portal_user_id = user.id
        await self.db.flush()
        return user.id

    async def me(self) -> SupplierOut:
        from app.services.inventory.master_service import MasterService

        s = await self.my_supplier()
        return MasterService(self.db, self.principal, self.request, self.inst).supplier_out(s)

    async def update_me(
        self, contact: dict[str, Any] | None, address: dict[str, Any] | None, categories: list[str] | None
    ) -> SupplierOut:
        s = await self.my_supplier()
        if contact is not None:
            s.contact = {**(s.contact or {}), **contact}
        if address is not None:
            s.address = address
        if categories is not None:
            s.categories = categories
        await self.db.flush()
        await self._audit("vendor_update", "supplier", s.id, None, {"contact": bool(contact), "address": bool(address)})
        return await self.me()

    async def rfqs(self) -> list[IndentResponse]:
        from app.services.inventory.indent_service import IndentService

        s = await self.my_supplier()
        rows = list(
            (
                await self.db.execute(
                    select(Indent)
                    .where(Indent.institution_id == self.inst, Indent.status == "approved")
                    .order_by(Indent.created_at.desc())
                    .limit(200)
                )
            ).scalars()
        )
        cats = {c.lower() for c in (s.categories or [])}
        if cats:
            from app.models.inventory import InventoryCategory

            names = {
                str(i): (n or "").lower()
                for i, n in (
                    await self.db.execute(
                        select(Item.id, InventoryCategory.name).outerjoin(
                            InventoryCategory, InventoryCategory.id == Item.category_id
                        )
                    )
                ).all()
            }
            rows = [
                r
                for r in rows
                if any(names.get(str(x.get("item_id")), "") in cats or not x.get("item_id") for x in r.items)
            ]
        outs = await IndentService(self.db, None, self.request, self.inst).outs(rows)
        for o in outs:  # vendors see lines, never estimates
            o.estimated_paise = None
            o.items = [
                {k: v for k, v in x.items() if k not in ("est_unit_cost_paise", "issued", "procured")} for x in o.items
            ]
            o.requester_name = None
        return outs

    # ---- vendor store --------------------------------------------------------------------------------------------------
    async def sale(self, body: VendorStoreSale) -> dict[str, Any]:
        from app.schemas.inventory import StockIssueRequest
        from app.services.inventory.stock_service import StockService

        self.require("issue")
        lines, total = [], 0
        for ln in body.items:
            item = (
                await self.db.execute(select(Item).where(Item.id == ln.item_id, Item.institution_id == self.inst))
            ).scalar_one_or_none()
            if item is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Item not found")
            price = int((item.safety_data or {}).get("sale_price_paise") or item.unit_cost_paise or 0)
            total += int(D(str(ln.quantity)) * D(price))
            lines.append((item, ln.quantity, price))
        ref = uuid.uuid4()
        res = await StockService(self.db, self.principal, self.request, self.inst).issue(
            StockIssueRequest(
                store_id=body.store_id,
                items=body.items,
                issued_to_type=body.buyer_type,
                issued_to_id=body.buyer_id,
                reference_type="vendor_store_sale",
                reference_id=ref,
                safety_ack=True,
            )
        )
        invoice_id = None
        if body.bill_to_fees and body.buyer_type == "student" and total > 0:
            from app.models.students import StudentProgramEnrollment
            from app.schemas.fees import InvoiceCreate, InvoiceItemIn
            from app.services.fees.invoice_service import InvoiceService

            enrol = (
                await self.db.execute(
                    select(StudentProgramEnrollment.id)
                    .where(
                        StudentProgramEnrollment.student_id == body.buyer_id,
                        StudentProgramEnrollment.status == "active",
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if enrol is None:
                raise rule("The student has no active enrolment to bill", "NO_ENROLMENT")
            inv = await InvoiceService(self.db, None, self.request, self.inst).create_invoice(
                InvoiceCreate(
                    enrollment_id=enrol,
                    source_type="vendor_store_sale",
                    source_id=ref,
                    description="Campus store purchase",
                    items=[
                        InvoiceItemIn(
                            description=f"{it.name} × {q}"[:200], amount_paise=int(D(str(q)) * D(p)), head_code="MISC"
                        )
                        for it, q, p in lines
                        if p > 0
                    ],
                    due_date=await self.today() + timedelta(days=7),
                    allow_multiple=True,
                )
            )
            invoice_id = inv.id
        await self._audit(
            "vendor_store_sale",
            "stock",
            ref,
            None,
            {"total_paise": total, "buyer": str(body.buyer_id), "invoice_id": str(invoice_id) if invoice_id else None},
        )
        return {
            "sale_id": str(ref),
            "total_paise": total,
            "invoice_id": str(invoice_id) if invoice_id else None,
            "transactions": [t.model_dump(mode="json") for t in res.transactions],
        }

    async def sales(self, on: date | None = None) -> list[dict[str, Any]]:
        self.require("issue")
        day = on or await self.today()
        start = datetime.combine(day, datetime.min.time())
        rows = (
            await self.db.execute(
                select(StockTransaction, Item.name)
                .join(Item, Item.id == StockTransaction.item_id)
                .where(
                    StockTransaction.institution_id == self.inst,
                    StockTransaction.reference_type == "vendor_store_sale",
                    StockTransaction.occurred_at >= start,
                    StockTransaction.occurred_at < start + timedelta(days=1),
                )
            )
        ).all()
        return [
            {
                "sale_id": str(t.reference_id),
                "item": n,
                "quantity": float(-t.quantity),
                "unit_cost_paise": t.unit_cost_paise,
                "buyer_type": t.issued_to_type,
                "at": t.occurred_at.isoformat(),
            }
            for t, n in rows
        ]

    async def daily_report(self, on: date | None = None) -> dict[str, Any]:
        rows = await self.sales(on)
        total = sum(int(r["quantity"] * (r["unit_cost_paise"] or 0)) for r in rows)
        sales = len({r["sale_id"] for r in rows})
        return {
            "date": (on or await self.today()).isoformat(),
            "sales": sales,
            "lines": len(rows),
            "value_paise": total,
            "rows": rows,
        }

    async def count_registered(self) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(Supplier)
                    .where(Supplier.institution_id == self.inst, Supplier.status == "registered")
                )
            ).scalar_one()
        )
