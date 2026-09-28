"""Communication and workflow enums — Prompts/04 §04.3 (values copied from Database_Schema.sql §6, §23)."""

from enum import StrEnum


class Channel(StrEnum):
    IN_APP = "in_app"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    PUSH = "push"


class MessageStatus(StrEnum):
    QUEUED = "queued"
    DEFERRED = "deferred"  # quiet hours / digest: delivered later by notifications.digest / retry_failed
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    BOUNCED = "bounced"
    READ = "read"
    SUPPRESSED = "suppressed"  # preference switched the channel off


class Digest(StrEnum):
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    ESCALATED = "escalated"


class StepStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"
    ESCALATED = "escalated"
    DELEGATED = "delegated"


class StepDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    DELEGATE = "delegate"


class ApproverType(StrEnum):
    ROLE = "role"
    SCOPE_RULE = "scope_rule"
    USER = "user"


class WhatsappTemplateStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
