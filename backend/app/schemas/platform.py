"""Platform schemas — Prompts/01 §01.4 (health, jobs, read-only mode, help centre, feedback, search, public config)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field

from app.schemas.common import ORMModel

# ---- infra -----------------------------------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: Literal["ok", "ready", "degraded"]
    environment: str | None = None
    checks: dict[str, Any] = Field(default_factory=dict)


# ---- background jobs -------------------------------------------------------------------------------------------

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class JobResponse(ORMModel):
    id: uuid.UUID
    job_type: str
    status: JobStatus
    progress_pct: int
    message: str | None = None
    result_url: str | None = None
    error: str | None = None
    requested_by: uuid.UUID | None = None
    cancel_requested: bool = False
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    expires_at: datetime | None = None


class JobListQuery(BaseModel):
    """Filters accepted by ``GET /jobs`` (on top of page/page_size/sort/scope)."""

    status: JobStatus | None = None
    job_type: str | None = Field(default=None, max_length=80)


# ---- read-only mode --------------------------------------------------------------------------------------------


class ReadOnlyModeRequest(BaseModel):
    scope: Literal["platform", "institution"] = "institution"
    enabled: bool
    reason: str | None = Field(default=None, max_length=200)
    ends_at: datetime | None = None
    institution_id: uuid.UUID | None = Field(
        default=None, description="Super admin only: target tenant (defaults to the caller's institution)"
    )


class ReadOnlyState(BaseModel):
    platform: bool
    institution: bool = False
    reason: str | None = None
    ends_at: datetime | None = None
    institution_id: uuid.UUID | None = None


# ---- help centre / feedback -------------------------------------------------------------------------------------


class HelpArticleResponse(ORMModel):
    id: uuid.UUID
    slug: str
    title: str
    body: str
    module: str | None = None
    audience: list[str] | None = None
    is_platform: bool = False
    updated_at: datetime


class HelpArticleSummary(ORMModel):
    id: uuid.UUID
    slug: str
    title: str
    module: str | None = None
    is_platform: bool = False
    updated_at: datetime


class FeedbackCreate(BaseModel):
    page: str | None = Field(default=None, max_length=200)
    category: Literal["bug", "idea", "question", "praise"] = "idea"
    rating: int | None = Field(default=None, ge=1, le=5)
    message: str = Field(min_length=3, max_length=4000)
    screenshot_url: str | None = Field(default=None, max_length=2000)
    client: Literal["web", "mobile", "pwa"] = "web"


class FeedbackResponse(ORMModel):
    id: uuid.UUID
    page: str | None = None
    category: str | None = None
    rating: int | None = None
    message: str | None = None
    client: str | None = None
    status: str
    created_at: datetime


# ---- search ----------------------------------------------------------------------------------------------------

SearchEntity = Literal["student", "staff", "course", "applicant"]


class SearchResult(BaseModel):
    entity_type: SearchEntity
    entity_id: uuid.UUID
    title: str
    subtitle: str | None = None
    route: str
    college_id: uuid.UUID | None = None


class SearchResponse(BaseModel):
    q: str
    results: list[SearchResult]
    entity_types: list[str]


# ---- public / mobile config -------------------------------------------------------------------------------------


class InstitutionSummary(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    # ``AliasChoices`` so the schema validates both from the ORM row (``institution_type``) and from its own serialised
    # form (``type``) — FastAPI re-validates every ``response_model`` against the encoded envelope (Phase 02 fix).
    type: str = Field(validation_alias=AliasChoices("institution_type", "type"), serialization_alias="type")
    logo_url: str | None = None
    timezone: str
    locale: str
    currency: str


class CollegeSummary(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    college_type: str
    is_main: bool = False
    logo_url: str | None = None


class PublicConfig(BaseModel):
    environment: str
    api_version: str
    packs: dict[str, dict[str, Any]]
    default_pack: str
    themes: list[str]
    table_styles: list[str]
    captcha: dict[str, Any]
    min_app_versions: dict[str, str]
    features_public: list[str] = Field(default_factory=list)
    institution: InstitutionSummary | None = None
    colleges: list[CollegeSummary] = Field(default_factory=list)


class MobileConfigRequest(BaseModel):
    platform: Literal["android", "ios", "web"] = "android"
    app_version: str | None = Field(default=None, max_length=20, pattern=r"^\d+(\.\d+){0,3}$")
    institution_slug: str | None = Field(default=None, max_length=60)


class MobileConfigResponse(BaseModel):
    min_versions: dict[str, str]
    force_update_below: dict[str, str]
    force_update: bool
    update_available: bool
    store_urls: dict[str, str]
    maintenance_banner: str | None = None
    read_only: bool = False
    feature_hints: dict[str, str] = Field(default_factory=dict)
    cache_ttl_seconds: int = 300
