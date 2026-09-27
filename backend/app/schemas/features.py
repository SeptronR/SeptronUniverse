"""Feature-flag schemas — Prompts/02 §02.4 (definitions, per-institution effective flags, toggles, change log, matrix)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FeatureDefResponse(BaseModel):
    key: str
    group: str
    name: str
    description: str | None = None
    default_enabled: bool
    min_plan_tier: str
    depends_on: list[str] = Field(default_factory=list)
    is_core: bool = False
    registered: bool = Field(default=False, description="the code registry gates this key (module shipped)")


class InstitutionFeatureFlagResponse(BaseModel):
    key: str
    group: str
    name: str
    description: str | None = None
    min_plan_tier: str
    depends_on: list[str] = Field(default_factory=list)
    is_core: bool = False
    platform_enabled: bool
    institution_enabled: bool
    effective: bool
    source: str = Field(description="plan | override | default")
    config: dict[str, Any] | None = None
    plan_allows: bool = Field(default=True, description="key at or below the plan tier")
    set_at: datetime | None = None


class FeatureToggleRequest(BaseModel):
    enabled: bool
    reason: str | None = Field(default=None, max_length=500)
    config: dict[str, Any] | None = None
    confirm_dependencies: bool = Field(
        default=False, description="enable: also switch on missing depends_on keys instead of answering 409"
    )


class InstitutionToggleRequest(BaseModel):
    enabled: bool
    reason: str | None = Field(default=None, max_length=500)


class FeatureFlagChangeResponse(BaseModel):
    id: uuid.UUID
    feature_key: str
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    changed_by: uuid.UUID | None = None
    changed_at: datetime
    reason: str | None = None


class InstitutionFeaturesResponse(BaseModel):
    institution_id: uuid.UUID
    plan_code: str | None = None
    flags: list[InstitutionFeatureFlagResponse]
    changes: list[FeatureFlagChangeResponse] = Field(default_factory=list)


class ApplyPlanDefaultsResponse(BaseModel):
    institution_id: uuid.UUID
    plan_code: str | None = None
    applied: int
    effective: list[str]


class MatrixInstitution(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan_code: str | None = None
    effective: list[str] = Field(default_factory=list)


class FeatureMatrixResponse(BaseModel):
    features: list[FeatureDefResponse]
    institutions: list[MatrixInstitution]
