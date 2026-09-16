"""Authentication placeholder — Phase 02 replaces this module with login/OTP/refresh/logout/me.

Until then ``POST /auth/login`` answers ``401 UNAUTHENTICATED`` so ``scripts/verify/_common.ps1`` has a real
endpoint to talk to (Prompts/00_PREREQUISITE_Project_Setup.md §9).
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.errors import APIError, ErrorCode

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=200, description="username | email | phone")
    password: str = Field(min_length=1, max_length=200)
    institution_slug: str | None = None


@router.post("/login", summary="Login (placeholder until Phase 02)")
async def login(body: LoginRequest) -> dict[str, Any]:
    raise APIError(401, ErrorCode.UNAUTHENTICATED, "Authentication is not available yet (Phase 02)")
