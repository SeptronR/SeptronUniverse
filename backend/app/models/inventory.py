"""Inventory, procurement & bills — section 21 of Database_Schema.sql (Prompts/22 §22.3).

DDL notes the services rely on: ``stock_levels UNIQUE (store_id, item_id)`` (rows are locked ``FOR UPDATE`` for every
stock transaction), ``items UNIQUE (institution_id, item_code)``, ``assets UNIQUE (institution_id, asset_tag)``,
``vendor_bills UNIQUE (supplier_id, bill_number)``; indent / quotation / GRN lines are JSONB arrays.
``amc_contracts`` is modelled by Phase 25.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import EncryptedBytes, TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class Supplier(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("institution_id", "name"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str | None] = mapped_column(String(20))
    gstin: Mapped[str | None] = mapped_column(String(20))
    pan: Mapped[str | None] = mapped_column(String(12))
    contact: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    address: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    categories: Mapped[list[Any] | None] = mapped_column(JSONB)
    bank_details_encrypted: Mapped[str | None] = mapped_column(EncryptedBytes)  # JSON {account_no, ifsc, bank}
    rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    portal_user_id: Mapped[uuid.UUID | None] = _fk("users.id")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class Store(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "stores"
    __table_args__ = (UniqueConstraint("institution_id", "name"),)

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    department_id: Mapped[uuid.UUID | None] = _fk("departments.id")
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    store_type: Mapped[str] = mapped_column(String(20), nullable=False, default="central")
    keeper_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()


class InventoryCategory(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "inventory_categories"
    __table_args__ = (UniqueConstraint("institution_id", "name"),)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = _fk("inventory_categories.id")
    is_consumable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Item(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("institution_id", "item_code"),)

    category_id: Mapped[uuid.UUID | None] = _fk("inventory_categories.id")
    item_code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="nos")
    description: Mapped[str | None] = mapped_column(Text)
    is_consumable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_hazardous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    safety_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    min_stock_level: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    reorder_qty: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    unit_cost_paise: Mapped[int | None] = mapped_column(Integer)
    gst_rate: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = _uuid()


class StockLevel(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "stock_levels"
    __table_args__ = (UniqueConstraint("store_id", "item_id"),)

    store_id: Mapped[uuid.UUID] = _fk("stores.id", "CASCADE", nullable=False)
    item_id: Mapped[uuid.UUID] = _fk("items.id", "CASCADE", nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    updated_at: Mapped[datetime] = _updated()


class Indent(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "indents"
    __table_args__ = (UniqueConstraint("institution_id", "indent_number"),)

    indent_number: Mapped[str] = mapped_column(String(30), nullable=False)
    department_id: Mapped[uuid.UUID | None] = _fk("departments.id")
    store_id: Mapped[uuid.UUID | None] = _fk("stores.id")
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    purpose: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="normal")
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    estimated_paise: Mapped[int | None] = mapped_column(Integer)
    budget_head_id: Mapped[uuid.UUID | None] = _uuid()
    workflow_instance_id: Mapped[uuid.UUID | None] = _uuid()
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class Quotation(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "quotations"

    indent_id: Mapped[uuid.UUID] = _fk("indents.id", "CASCADE", nullable=False)
    supplier_id: Mapped[uuid.UUID] = _fk("suppliers.id", nullable=False)
    reference: Mapped[str | None] = mapped_column(String(60))
    tender_ref: Mapped[str | None] = mapped_column(String(60))
    gem_ref: Mapped[str | None] = mapped_column(String(60))
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    total_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date)
    file_url: Mapped[str | None] = mapped_column(Text)
    is_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    comparison_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class PurchaseOrder(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("institution_id", "po_number"),)

    po_number: Mapped[str] = mapped_column(String(30), nullable=False)
    supplier_id: Mapped[uuid.UUID] = _fk("suppliers.id", nullable=False)
    indent_id: Mapped[uuid.UUID | None] = _fk("indents.id")
    quotation_id: Mapped[uuid.UUID | None] = _fk("quotations.id")
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_date: Mapped[date | None] = mapped_column(Date)
    terms: Mapped[str | None] = mapped_column(Text)
    subtotal_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    approved_by: Mapped[uuid.UUID | None] = _uuid()
    workflow_instance_id: Mapped[uuid.UUID | None] = _uuid()
    created_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class PurchaseOrderItem(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "purchase_order_items"

    po_id: Mapped[uuid.UUID] = _fk("purchase_orders.id", "CASCADE", nullable=False)
    item_id: Mapped[uuid.UUID] = _fk("items.id", nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    unit_price_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    received_qty: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)


class GoodsReceipt(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "goods_receipts"
    __table_args__ = (UniqueConstraint("institution_id", "grn_number"),)

    grn_number: Mapped[str] = mapped_column(String(30), nullable=False)
    po_id: Mapped[uuid.UUID] = _fk("purchase_orders.id", nullable=False)
    store_id: Mapped[uuid.UUID] = _fk("stores.id", nullable=False)
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    received_by: Mapped[uuid.UUID | None] = _uuid()
    invoice_no: Mapped[str | None] = mapped_column(String(60))
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class StockTransaction(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "stock_transactions"

    store_id: Mapped[uuid.UUID] = _fk("stores.id", nullable=False)
    item_id: Mapped[uuid.UUID] = _fk("items.id", nullable=False)
    txn_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    unit_cost_paise: Mapped[int | None] = mapped_column(Integer)
    reference_type: Mapped[str | None] = mapped_column(String(30))
    reference_id: Mapped[uuid.UUID | None] = _uuid()
    issued_to_type: Mapped[str | None] = mapped_column(String(20))
    issued_to_id: Mapped[uuid.UUID | None] = _uuid()
    remarks: Mapped[str | None] = mapped_column(Text)
    performed_by: Mapped[uuid.UUID | None] = _uuid()
    occurred_at: Mapped[datetime] = _now()


class Asset(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("institution_id", "asset_tag"),)

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    asset_tag: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str | None] = mapped_column(String(60))
    item_id: Mapped[uuid.UUID | None] = _fk("items.id")
    serial_no: Mapped[str | None] = mapped_column(String(80))
    location_room_id: Mapped[uuid.UUID | None] = _fk("rooms.id")
    custodian_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    department_id: Mapped[uuid.UUID | None] = _fk("departments.id")
    purchase_date: Mapped[date | None] = mapped_column(Date)
    cost_paise: Mapped[int | None] = mapped_column(BigInteger)
    po_id: Mapped[uuid.UUID | None] = _fk("purchase_orders.id")
    warranty_until: Mapped[date | None] = mapped_column(Date)
    depreciation_method: Mapped[str | None] = mapped_column(String(20))
    depreciation_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    current_value_paise: Mapped[int | None] = mapped_column(BigInteger)
    qr_code_url: Mapped[str | None] = mapped_column(Text)
    is_bookable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_use")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = _uuid()


class AssetAudit(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "asset_audits"

    asset_id: Mapped[uuid.UUID] = _fk("assets.id", "CASCADE", nullable=False)
    audited_on: Mapped[date] = mapped_column(Date, nullable=False)
    audited_by: Mapped[uuid.UUID | None] = _uuid()
    found: Mapped[bool] = mapped_column(Boolean, nullable=False)
    condition: Mapped[str | None] = mapped_column(String(20))
    remarks: Mapped[str | None] = mapped_column(Text)
    scanned_qr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class VendorBill(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "vendor_bills"
    __table_args__ = (UniqueConstraint("supplier_id", "bill_number"),)

    supplier_id: Mapped[uuid.UUID] = _fk("suppliers.id", nullable=False)
    po_id: Mapped[uuid.UUID | None] = _fk("purchase_orders.id")
    grn_id: Mapped[uuid.UUID | None] = _fk("goods_receipts.id")
    bill_number: Mapped[str] = mapped_column(String(60), nullable=False)
    bill_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    subtotal_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    tax_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tds_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    file_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    workflow_instance_id: Mapped[uuid.UUID | None] = _uuid()
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_ref: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
