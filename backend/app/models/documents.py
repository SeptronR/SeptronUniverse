"""Document engine — ``document_templates`` / ``certificate_requests`` / ``issued_documents`` / ``document_serials`` of
section 25 (Prompts/26 §26.3).

``document_templates.institution_id`` NULL = platform (pack) default; institution overrides are cloned rows, every
publish adds a new ``version`` row (same ``name`` / ``template_type``) and keeps the older ones for re-render
fidelity. Draft state, change notes and the publishing user live in ``layout['_meta']``.

``issued_documents.pdf_url`` holds the storage key of the unwatermarked original (``content_hash`` = its SHA-256);
reissue links (``superseded_by``) and the downloads count live in the ``revoke_reason`` JSON note / audit log.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated

__all__ = ["CertificateRequest", "DocumentSerial", "DocumentTemplate", "IssuedDocument"]


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class DocumentTemplate(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "document_templates"
    __mapper_args__ = {"eager_defaults": True}

    institution_id: Mapped[uuid.UUID | None] = _fk("institutions.id", "CASCADE")  # NULL = platform default
    template_type: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    layout: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    html_template: Mapped[str | None] = mapped_column(Text)
    css: Mapped[str | None] = mapped_column(Text)
    page_size: Mapped[str] = mapped_column(String(20), nullable=False, default="A4")
    is_bilingual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    secondary_language: Mapped[str | None] = mapped_column(String(10))
    variables: Mapped[Any | None] = mapped_column(JSONB)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CertificateRequest(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "certificate_requests"
    __mapper_args__ = {"eager_defaults": True}

    requester_user_id: Mapped[uuid.UUID] = _fk("users.id", nullable=False)
    person_type: Mapped[str] = mapped_column(String(10), nullable=False)  # student | staff | alumni
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    template_type: Mapped[str] = mapped_column(String(40), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(200))
    copies: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    delivery: Mapped[str] = mapped_column(String(20), nullable=False, default="digital")
    fee_invoice_id: Mapped[uuid.UUID | None] = _fk("fee_invoices.id")
    workflow_instance_id: Mapped[uuid.UUID | None] = _uuid()
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    issued_document_id: Mapped[uuid.UUID | None] = _uuid()  # FK → issued_documents (ON DELETE SET NULL)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class IssuedDocument(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "issued_documents"
    __table_args__ = (UniqueConstraint("institution_id", "document_number"),)

    template_id: Mapped[uuid.UUID | None] = _fk("document_templates.id")
    template_type: Mapped[str] = mapped_column(String(40), nullable=False)
    person_type: Mapped[str | None] = mapped_column(String(10))
    person_id: Mapped[uuid.UUID | None] = _uuid()
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[uuid.UUID | None] = _uuid()
    document_number: Mapped[str] = mapped_column(String(40), nullable=False)
    serial_no: Mapped[str | None] = mapped_column(String(40))
    pdf_url: Mapped[str] = mapped_column(Text, nullable=False)
    verification_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    watermark_text: Mapped[str | None] = mapped_column(String(120))
    issued_by: Mapped[uuid.UUID | None] = _uuid()
    issued_at: Mapped[datetime] = _now()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[uuid.UUID | None] = _uuid()


class DocumentSerial(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "document_serials"
    __table_args__ = (UniqueConstraint("institution_id", "register", "serial_no"),)

    register: Mapped[str] = mapped_column(String(40), nullable=False)
    serial_no: Mapped[str] = mapped_column(String(40), nullable=False)
    issued_document_id: Mapped[uuid.UUID | None] = _fk("issued_documents.id")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="used")
    created_at: Mapped[datetime] = _now()
