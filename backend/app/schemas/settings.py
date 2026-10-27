"""Settings schemas — Prompts/03 §03.4 (typed key/value settings by category, public keys, provider tests)."""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class SettingResponse(BaseModel):
    category: str
    key: str
    value: Any = None
    value_type: str
    is_public: bool = False
    default: Any = None
    is_default: bool = True
    choices: list[str] = Field(default_factory=list)
    label: str | None = None
    feature: str | None = None
    college_id: uuid.UUID | None = None


class SettingsCategoryResponse(BaseModel):
    category: str
    items: list[SettingResponse]


class SettingItem(BaseModel):
    category: str = Field(max_length=40)
    key: str = Field(max_length=80)
    value: Any = None
    college_id: uuid.UUID | None = Field(default=None, description="college-level override (NULL = institution)")


class SettingsBulkUpdate(BaseModel):
    items: list[SettingItem] = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=500, description="required for sensitive categories")


class PublicSettingsResponse(BaseModel):
    institution_id: uuid.UUID | None = None
    theme: str
    table_style: str
    theme_tokens: dict[str, str]
    settings: dict[str, dict[str, Any]]


class ProviderTestRequest(BaseModel):
    channel: Literal["sms", "email", "whatsapp", "push"]
    to: str = Field(min_length=3, max_length=200)
    message: str | None = Field(default=None, max_length=300)


class ProviderTestResponse(BaseModel):
    channel: str
    provider: str
    status: str
    reference: str | None = None
    message_log_id: uuid.UUID


# ---- Phase 37: catalogue, effective values, history, import / export ---------------------------------------------------
class SettingDefOut(BaseModel):
    key: str
    category: str
    name: str
    type: str
    default: Any = None
    label: str
    help: str | None = None
    choices: list[str] = Field(default_factory=list)
    min: int | None = None
    max: int | None = None
    is_public: bool = False
    feature: str | None = None
    scope: str
    locked_by: str
    lock_reason: str | None = None
    requires_restart: bool = False
    depends_on: list[str] = Field(default_factory=list)
    dependency_hint: str | None = None
    sensitive: bool = False
    overridden_in_colleges: int = 0


class EffectiveSettingOut(BaseModel):
    key: str
    category: str
    value: Any = None
    source: Literal["college", "institution", "platform", "default"]
    locked_by: str = "none"
    overridden_at_college: bool = False
    updated_at: Any = None


class SettingsHistoryOut(BaseModel):
    audit_id: uuid.UUID
    at: Any
    key: str
    college_id: uuid.UUID | None = None
    old: Any = None
    new: Any = None
    actor_id: uuid.UUID | None = None
    actor_name: str | None = None
    reason: str | None = None
    request_id: str | None = None


class SettingsExportOut(BaseModel):
    institution_id: uuid.UUID
    exported_at: Any
    values: dict[str, Any]
    college_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)


class SettingsImportIn(BaseModel):
    json_: dict[str, Any] = Field(alias="json", description="an export document or {values: {key: value}}")
    reason: str | None = Field(default=None, max_length=500)

    model_config = {"populate_by_name": True}


class SettingsImportReport(BaseModel):
    dry_run: bool
    applied: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    skipped_locked: list[str] = Field(default_factory=list)
    invalid: list[dict[str, Any]] = Field(default_factory=list)
    request_id: str | None = None


class SettingsDiffOut(BaseModel):
    key: str
    before: Any = None
    after: Any = None
    changed_at: Any = None
    actor_id: uuid.UUID | None = None
