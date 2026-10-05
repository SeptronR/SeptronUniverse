"""Model mixins — Prompts/00_PREREQUISITE_Project_Setup.md §3.6.

Column names mirror Database_Schema.sql conventions: UUID PKs, ``institution_id`` on every tenant table (RLS),
``college_id`` where scoped, soft delete (``is_active``, ``deleted_at``, ``deleted_by``), optimistic lock ``version``.
"""

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column
from sqlalchemy.types import TypeDecorator


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    # ``eager_defaults`` fetches server-generated values (``updated_at``, the ``version`` bump trigger) with RETURNING
    # in the same statement. Without it SQLAlchemy expires those attributes after a flush and reloads them lazily,
    # which raises ``MissingGreenlet`` as soon as a service serialises the row it just updated (Phase 02).
    __mapper_args__: ClassVar[dict[str, Any]] = {"eager_defaults": True}


class SoftDeleteMixin:
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class OptimisticLockMixin:
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # version is bumped by the DB trigger (trigger_bump_version); services compare on update (If-Match → 409 STALE_VERSION)
    __mapper_args__: ClassVar[dict[str, Any]] = {"version_id_col": None, "eager_defaults": True}


class TenantMixin:
    @declared_attr
    def institution_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
        )


class CollegeScopedMixin:
    @declared_attr
    def college_id(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("colleges.id", ondelete="CASCADE"), index=True)


class CreatedByMixin:
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class EncryptedBytes(TypeDecorator[str]):
    """A ``BYTEA`` column holding AES-GCM ciphertext of a string (``core.security.encrypt_secret``) — Prompts/06 §06.3
    ``pan_encrypted``, ``aadhaar_encrypted``, ``bank_details_encrypted``. Python sees the plain string; the database
    only ever stores ciphertext. Masking for readers without ``hr:view_pii`` happens in the schema layer."""

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> bytes | None:
        if value is None or value == "":
            return None
        from app.core.security import encrypt_secret

        return encrypt_secret(str(value))

    def process_result_value(self, value: bytes | None, dialect: Any) -> str | None:
        if value is None:
            return None
        from app.core.security import decrypt_secret

        try:
            return decrypt_secret(bytes(value))
        except Exception:  # noqa: BLE001 - a key rotation must not break reads; the value shows as unreadable
            return None


# Standard base for editable tenant masters
class TenantModelMixin(
    UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, OptimisticLockMixin, CreatedByMixin
):
    pass
