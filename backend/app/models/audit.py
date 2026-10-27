"""Audit / security / settings / retention projections — Prompts/37 §37.3 (no new tables).

``AuditLog`` (Phase 01, partitioned parent, hash chain computed by ``trigger_audit_hash_chain``) is re-exported from
``models/platform.py``. Everything else of Phase 37 is a read-only projection or lives in the ``institution_settings``
side store (category ``audit_meta``):

* ``digest:<yyyy-mm-dd>`` — the signed daily chain digest ``{date, rows, last_hash, digest, signature, key_id,
  archived_key}`` (also written to cold storage ``{institution}/audit-digests/{date}.json``);
* ``verify:<id>`` — a chain verification result (:class:`ChainVerification`);
* ``anomaly:<id>`` — an anomaly alert ``{rule, count, window, users, first_seen, acknowledged, note}``;
* ``legal_hold:<id>`` — ``{data_class, scope, reason, until, set_by, set_at}``;
* ``manifest:<id>`` — :class:`ArchiveManifest` (purge and archive runs).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.platform import AuditLog, FeatureFlagChange, LoginHistory, UserSession

__all__ = [
    "AUDIT_JOB_TYPES",
    "META",
    "ArchiveManifest",
    "AuditLog",
    "AuditTimelineEntry",
    "ChainVerification",
    "EffectiveSetting",
    "FeatureFlagChange",
    "LoginHistory",
    "RetentionPolicy",
    "SecurityEvent",
    "UserSession",
]

META = "audit_meta"
AUDIT_JOB_TYPES = (
    "audit.export",
    "audit.chain_verify",
    "audit.digest_sign",
    "exams.audit_report",
    "settings.import",
    "retention.purge",
    "retention.archive",
    "retention.restore",
)


@dataclass
class AuditTimelineEntry:
    at: datetime
    source: str  # audit | event | workflow
    action: str
    actor_id: uuid.UUID | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SecurityEvent:
    id: str
    type: str
    at: datetime
    user_id: uuid.UUID | None
    ip: str | None
    severity: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChainVerification:
    institution_id: uuid.UUID
    date_from: datetime
    date_to: datetime
    rows: int
    ok: bool
    digest: str
    verified_at: datetime
    first_broken_id: uuid.UUID | None = None


@dataclass
class EffectiveSetting:
    key: str
    value: Any
    source: str  # college | institution | platform | default
    locked_by: str = "none"


@dataclass
class RetentionPolicy:
    values: dict[str, Any]
    maximums: dict[str, int]


@dataclass
class ArchiveManifest:
    data_class: str
    period: str
    rows: int
    file_url: str | None
    sha256: str | None
    created_at: datetime
