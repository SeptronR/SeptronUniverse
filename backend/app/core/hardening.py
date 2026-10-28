"""Security hardening primitives — Prompts/43 §43.6 ``security_hardening_service`` items 1–3.

* :class:`SecurityHeadersMiddleware` — HSTS (https only), CSP (report-only until ``CSP_ENFORCE``; ``report-uri``
  ``/api/v1/security/csp-report``), ``X-Content-Type-Options``, ``X-Frame-Options`` / ``frame-ancestors 'none'``,
  ``Referrer-Policy``, ``Permissions-Policy`` (camera / geolocation self), ``Cross-Origin-Opener-Policy``; refuses
  bodies over ``MAX_UPLOAD_MB`` (413) and JSON nested deeper than ``MAX_JSON_DEPTH`` (400) before routing.
* :func:`assert_public_url` — SSRF guard for webhook / LTI / provider URLs (private, loopback, link-local,
  multicast and reserved ranges refused, also after DNS resolution).
* :func:`check_breached_password` — HIBP Pwned Passwords k-anonymity range query (only the first five SHA-1 hex
  characters leave the server); fails open when the service is unreachable.
* :func:`safe_next` — open-redirect guard for ``next=`` parameters.
"""

import hashlib
import ipaddress
import json
import socket
from typing import Any
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.errors import APIError, ErrorCode, error_response

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; "
    "font-src 'self' data:; connect-src 'self' wss: https:; frame-src https://www.youtube.com https://www.google.com; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'; report-uri /api/v1/security/csp-report"
)
# SSR site pages embed small inline scripts / styles (Phase 40) and may be framed by nothing either
SITE_CSP = CSP.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'")


def _depth(value: Any, limit: int, level: int = 0) -> bool:
    if level > limit:
        return False
    if isinstance(value, dict):
        return all(_depth(v, limit, level + 1) for v in value.values())
    if isinstance(value, list):
        return all(_depth(v, limit, level + 1) for v in value)
    return True


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.MAX_UPLOAD_MB * 1024 * 1024:
            return error_response(
                request,
                413,
                ErrorCode.VALIDATION,
                f"Request body exceeds {settings.MAX_UPLOAD_MB} MB",
                {"code": "PAYLOAD_TOO_LARGE"},
            )
        if request.method in {"POST", "PUT", "PATCH"} and "json" in request.headers.get("content-type", ""):
            body = await request.body()
            if body:
                try:
                    parsed = json.loads(body)
                except ValueError:
                    parsed = None
                if parsed is not None and not _depth(parsed, settings.MAX_JSON_DEPTH):
                    return error_response(
                        request, 400, ErrorCode.VALIDATION, "JSON nested too deeply", {"code": "JSON_DEPTH"}
                    )
        response = await call_next(request)
        h = response.headers
        site = request.url.path.startswith("/site/") or "x-site-host" in request.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "camera=(self), geolocation=(self), microphone=(), payment=(self)")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        csp_header = "Content-Security-Policy" if settings.CSP_ENFORCE else "Content-Security-Policy-Report-Only"
        if "Content-Security-Policy" not in h and "Content-Security-Policy-Report-Only" not in h:
            h[csp_header] = SITE_CSP if site else CSP
        if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


def _blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return any(
        (
            addr.is_private,
            addr.is_loopback,
            addr.is_link_local,
            addr.is_multicast,
            addr.is_reserved,
            addr.is_unspecified,
        )
    )


def assert_public_url(url: str, *, field: str = "url", allow_http: bool = False) -> None:
    """422 unless ``url`` is https (or http when allowed) to a public host; outside production the development
    hosts (``localhost`` / ``*.test`` / ``*.example.*``) are accepted so mock endpoints keep working."""
    parsed = urlparse(url)
    if parsed.scheme not in ({"https", "http"} if allow_http else {"https"}) or not parsed.hostname:
        raise APIError(
            422, ErrorCode.VALIDATION, "URL must be https with a host", {"field": field, "code": "URL_SCHEME"}
        )
    host = parsed.hostname
    if not settings.is_production and (
        host == "localhost" or host.endswith((".test", ".local")) or ".example." in host
    ):
        return
    try:
        ipaddress.ip_address(host)
        candidates = [host]
    except ValueError:
        try:
            candidates = sorted({str(i[4][0]) for i in socket.getaddrinfo(host, None)})
        except OSError:
            raise APIError(
                422, ErrorCode.VALIDATION, "Host does not resolve", {"field": field, "code": "URL_HOST"}
            ) from None
    if any(_blocked(ip) for ip in candidates):
        raise APIError(
            422, ErrorCode.VALIDATION, "URL points to a private network", {"field": field, "code": "SSRF_BLOCKED"}
        )


async def check_breached_password(password: str) -> None:
    """422 ``PASSWORD_BREACHED`` when the password appears in the Pwned Passwords corpus."""
    if not settings.BREACHED_PASSWORD_CHECK:
        return
    digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()  # noqa: S324 - k-anonymity protocol
    prefix, suffix = digest[:5], digest[5:]
    try:
        import httpx

        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"https://api.pwnedpasswords.com/range/{prefix}", headers={"Add-Padding": "true"})
        if r.status_code != 200:
            return
        for line in r.text.splitlines():
            h, _, count = line.partition(":")
            if h == suffix and count.strip() not in ("", "0"):
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    "This password appears in known data breaches — choose another",
                    {"field": "password", "code": "PASSWORD_BREACHED"},
                )
    except APIError:
        raise
    except Exception:  # noqa: BLE001 - fail open: availability of a third party never blocks a password change
        return


def safe_next(target: str | None, default: str = "/") -> str:
    """Only same-site relative paths survive (``/x``, never ``//evil`` or ``https://evil``)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\\\" in target:
        return default
    return target
