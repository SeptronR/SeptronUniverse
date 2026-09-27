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
