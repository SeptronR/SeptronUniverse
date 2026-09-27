"""RBAC schemas — Prompts/02 §02.4 (roles, permission catalogue, matrix, scoped assignments, users, credential sheets)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.authz.masking import MaskedEmail, MaskedPhone
from app.schemas.common import ORMModel

SLUG_PATTERN = r"^[a-z][a-z0-9_]{1,59}$"
ScopeTypeName = Literal[
    "institution", "college", "faculty", "department", "program", "offering", "self", "committee", "hostel"
]
UserTypeName = Literal["staff", "student", "guardian", "alumni", "applicant", "recruiter", "external", "platform"]


# ---- permissions -------------------------------------------------------------------------------------------
class PermissionResponse(ORMModel):
    id: uuid.UUID
    module: str
    action: str
    description: str | None = None
    is_platform: bool = False


class PermissionCatalogue(BaseModel):
    modules: list[str]
    standard_actions: list[str]
    permissions: list[PermissionResponse]


# ---- roles -------------------------------------------------------------------------------------------------
class RoleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    slug: str = Field(pattern=SLUG_PATTERN)
    description: str | None = Field(default=None, max_length=2000)
    default_scope_type: ScopeTypeName = "institution"
    portal: str | None = Field(default=None, max_length=30)
    permissions: list[str] = Field(default_factory=list, description="initial module:action grants")


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    default_scope_type: ScopeTypeName | None = None
    portal: str | None = Field(default=None, max_length=30)
    is_active: bool | None = None
    version: int | None = Field(default=None, description="optimistic lock (If-Match semantics)")


class RoleCloneRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    slug: str = Field(pattern=SLUG_PATTERN)


class RoleResponse(ORMModel):
    id: uuid.UUID
    institution_id: uuid.UUID | None = None
    name: str
    slug: str
    description: str | None = None
    is_system: bool
    default_scope_type: str
    portal: str | None = None
    is_active: bool
    version: int
    created_at: datetime
    updated_at: datetime
    permission_count: int | None = None
    assignment_count: int | None = None


class MatrixAction(BaseModel):
    action: str
    granted: bool


class MatrixModule(BaseModel):
    module: str
    actions: list[MatrixAction]


class RolePermissionMatrix(BaseModel):
    """Rows = modules, columns = actions (docs/Roles_and_Permissions.md §2). ``PUT`` may send only the changed cells."""

    role_id: uuid.UUID | None = None
    modules: list[MatrixModule]


class RolePermissionMatrixUpdate(BaseModel):
    modules: list[MatrixModule] = Field(min_length=1)
    version: int | None = None


# ---- user roles ----------------------------------------------------------------------------------------------
class UserRoleAssign(BaseModel):
    role_id: uuid.UUID
    scope_type: ScopeTypeName | None = Field(default=None, description="defaults to the role's default scope")
    scope_id: uuid.UUID | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class UserRoleResponse(BaseModel):
    id: uuid.UUID
    role_id: uuid.UUID
    role_slug: str
    role_name: str
    scope_type: str
    scope_id: uuid.UUID | None = None
    scope_label: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    assigned_at: datetime


# ---- users ---------------------------------------------------------------------------------------------------
class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9._@+-]+$")
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=20)
    display_name: str | None = Field(default=None, max_length=200)
    user_type: UserTypeName = "staff"
    password: str | None = Field(default=None, description="omit to generate a temporary password")
    must_change_password: bool = True
    locale: str | None = Field(default=None, max_length=10)
    timezone: str | None = Field(default=None, max_length=60)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    roles: list[UserRoleAssign] = Field(default_factory=list)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        digits = "".join(ch for ch in v if ch.isdigit() or ch == "+")
        if len(digits.lstrip("+")) < 8:
            raise ValueError("phone must have at least 8 digits")
        return digits


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=20)
    display_name: str | None = Field(default=None, max_length=200)
    avatar_url: str | None = Field(default=None, max_length=2000)
    user_type: UserTypeName | None = None
    locale: str | None = Field(default=None, max_length=10)
    timezone: str | None = Field(default=None, max_length=60)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    version: int | None = None


class UserResponse(ORMModel):
    id: uuid.UUID
    institution_id: uuid.UUID | None = None
    username: str
    email: MaskedEmail = None
    phone: MaskedPhone = None
    display_name: str | None = None
    avatar_url: str | None = None
    user_type: str
    is_super_admin: bool = False
    is_active: bool
    is_verified: bool = False
    must_change_password: bool = False
    mfa_enabled: bool = False
    last_login_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    version: int
    created_at: datetime
    updated_at: datetime
    role_slugs: list[str] = Field(default_factory=list)


class UserDetailResponse(UserResponse):
    roles: list[UserRoleResponse] = Field(default_factory=list)


class UserCreatedResponse(UserDetailResponse):
    temporary_password: str | None = Field(default=None, description="only when generated for the caller to hand over")


class AdminResetPasswordResponse(BaseModel):
    user_id: uuid.UUID
    temporary_password: str
    must_change_password: bool = True


class CredentialSheetRequest(BaseModel):
    audience: Literal["students", "guardians", "staff"] = "staff"
    ids: list[uuid.UUID] = Field(min_length=1, max_length=2000)
    batch_label: str | None = Field(default=None, max_length=120)


class CredentialSheetResponse(BaseModel):
    job_id: uuid.UUID
    sheet_id: uuid.UUID
    audience: str
    count: int
