"""APIError + error-code catalogue — Prompts/00_PREREQUISITE_Project_Setup.md §3.7 (docs/Technical_Architecture.md §1)."""

from typing import Any

from fastapi import Request
from fastapi.responses import ORJSONResponse

from app.core.config import settings


class ErrorCode:
    VALIDATION = "VALIDATION"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    STALE_VERSION = "STALE_VERSION"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    FEATURE_DISABLED = "FEATURE_DISABLED"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    READ_ONLY = "READ_ONLY"
    RATE_LIMITED = "RATE_LIMITED"
    IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"
    HOLD_BLOCKED = "HOLD_BLOCKED"
    RECORD_LOCKED = "RECORD_LOCKED"
    RULE_VIOLATION = "RULE_VIOLATION"
    INTEGRATION_FAILED = "INTEGRATION_FAILED"
    MFA_REQUIRED = "MFA_REQUIRED"
    GONE = "GONE"  # a purged report file (Phase 36 retention)
    INTERNAL = "INTERNAL"


# HTTP codes the API is allowed to return (coding standard 3); 410 only for report files past retention (Phase 36)
ALLOWED_HTTP_CODES = {200, 201, 202, 204, 400, 401, 403, 404, 409, 410, 413, 422, 429, 503, 500}


class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def error_response(
    request: Request, status: int, code: str, message: str, details: dict[str, Any] | None = None
) -> ORJSONResponse:
    body = {
        "success": False,
        "error": {"code": code, "message": message, "details": details or {}},
        "request_id": getattr(request.state, "request_id", None),
    }
    resp = ORJSONResponse(status_code=status, content=body)
    origin = request.headers.get("origin")
    if origin and (origin in settings.ALLOWED_ORIGINS or "*" in settings.ALLOWED_ORIGINS):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Vary"] = "Origin"
    return resp
