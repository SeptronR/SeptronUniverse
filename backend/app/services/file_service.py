"""File service — Prompts/01 §01.6 (uploads on top of ``app/core/files.py`` storage).

Business rules
1. Every stored object lives under the tenant prefix ``{institution_id}/{folder}/{uuid}.{ext}`` (``core.files.build_key``);
   platform-level files (no tenant) use the ``platform`` prefix.
2. The content type is **sniffed from the bytes**, never trusted from the client: ``FILE_MIME_SNIFFER=magic`` uses
   python-magic/libmagic (Docker image); ``builtin`` (default, no native library) recognises the types the platform
   accepts (PNG/JPEG/GIF/WEBP/SVG, PDF, OOXML/ZIP, CSV/plain text) and flags executables/archives. A file whose sniffed
   type is not in ``allowed_types`` — e.g. an ``.exe`` renamed to ``.png`` — is rejected with ``422 VALIDATION``.
3. Size limit ``max_mb`` (default ``MAX_UPLOAD_MB``) → ``422 VALIDATION``; empty files are rejected.
4. Plan quota: the tenant's ``subscription_plans.storage_gb`` (via ``institution_subscriptions``) is compared with the
   usage counter ``storage:{institution_id}`` (Redis, rebuilt from the local tree when missing) → ``409 CONFLICT``
   ``storage_quota_exceeded``. Tenants without a subscription row are not limited (dev/demo).
5. Optional ClamAV: when ``CLAMAV_HOST`` is set the bytes are streamed to clamd (INSTREAM); ``FOUND`` → 422.
6. ``signed_url(key, ttl)`` → HMAC-signed ``/uploads/{key}?sig=&exp=`` (local) or an S3 presigned URL; the API route
   ``GET /uploads/{key}`` verifies signature + expiry (``main.py``).
"""

import asyncio
import contextlib
import os
import struct
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.core.files import build_key, storage
from app.repositories.platform_repository import PlatformConfigRepository

log = structlog.get_logger()

IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")
DOCUMENT_TYPES = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/csv",
    "text/plain",
)
BLOCKED_TYPES = frozenset(
    {
        "application/x-dosexec",
        "application/x-msdownload",
        "application/vnd.microsoft.portable-executable",
        "application/x-executable",
        "application/x-sharedlib",
        "application/x-mach-binary",
        "application/x-msi",
        "application/x-bat",
        "text/x-shellscript",
        "application/javascript",
        "text/javascript",
    }
)

_EXT_TO_TEXT = {
    "csv": "text/csv",
    "txt": "text/plain",
    "md": "text/plain",
    "json": "application/json",
    "svg": "image/svg+xml",
}


@dataclass(frozen=True)
class SavedFile:
    key: str
    url: str
    content_type: str
    size: int
    original_name: str | None


def sniff_mime(data: bytes, filename: str | None = None) -> str:
    """Rule 2 — detect the real content type from the first bytes (see ``_builtin_sniff``)."""
    if settings.FILE_MIME_SNIFFER == "magic":
        try:
            import magic  # python-magic (libmagic) — Linux/Docker only

            detected = str(magic.from_buffer(data[:8192], mime=True))
            if detected and detected != "application/octet-stream":
                return detected
        except Exception as exc:  # noqa: BLE001 - fall back to the builtin sniffer
            log.warning("mime_magic_unavailable", error=str(exc))
    return _builtin_sniff(data, filename)


def _builtin_sniff(data: bytes, filename: str | None) -> str:  # noqa: C901 - a flat table of signatures
    head = data[:4096]
    ext = Path(filename or "").suffix.lower().lstrip(".")
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"MZ"):
        return "application/x-dosexec"
    if head.startswith(b"\x7fELF"):
        return "application/x-executable"
    if head[:4] in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):
        return "application/x-mach-binary"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "application/x-msi" if ext == "msi" else "application/vnd.ms-office"
    if head.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "application/x-7z-compressed"
    if head.startswith(b"Rar!\x1a\x07"):
        return "application/vnd.rar"
    if head.startswith(b"\x1f\x8b"):
        return "application/gzip"
    if head.startswith(b"PK\x03\x04"):
        return _sniff_zip(data)
    # text-like: UTF-8 without NUL bytes
    if b"\x00" not in head:
        try:
            text = head.decode("utf-8")
        except UnicodeDecodeError:
            return "application/octet-stream"
        stripped = text.lstrip("\ufeff \t\r\n").lower()
        if (stripped.startswith("<?xml") and "<svg" in stripped) or stripped.startswith("<svg"):
            return "image/svg+xml"
        if stripped.startswith(("#!", "@echo", "powershell", "cmd /c")):
            return "text/x-shellscript"
        if ext in _EXT_TO_TEXT and _EXT_TO_TEXT[ext] != "image/svg+xml":
            return _EXT_TO_TEXT[ext]
        return "text/plain"
    return "application/octet-stream"


def _sniff_zip(data: bytes) -> str:
    """OOXML documents are ZIPs whose first entries name their part folder; anything else is a plain archive."""
    names: list[bytes] = []
    pos = 0
    for _ in range(8):  # first few local headers are enough to see [Content_Types].xml + the part folder
        if data[pos : pos + 4] != b"PK\x03\x04" or len(data) < pos + 30:
            break
        (comp_size, name_len, extra_len) = struct.unpack("<IHH", data[pos + 18 : pos + 22] + data[pos + 26 : pos + 30])
        names.append(data[pos + 30 : pos + 30 + name_len])
        pos += 30 + name_len + extra_len + comp_size
    joined = b"\n".join(names)
    if b"word/" in joined:
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if b"xl/" in joined:
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if b"ppt/" in joined:
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if b"[Content_Types].xml" in joined:
        # OOXML with the part folder deeper in the archive: search the whole buffer once
        for marker, mime in (
            (b"word/", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            (b"xl/", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            (b"ppt/", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
        ):
            if marker in data:
                return mime
    return "application/zip"


class FileService:
    def __init__(self, db: AsyncSession | None = None):
        self.db = db

    async def save(
        self,
        upload: UploadFile | bytes,
        folder: str,
        allowed_types: tuple[str, ...] | list[str] = IMAGE_TYPES + DOCUMENT_TYPES,
        max_mb: int | None = None,
        institution_id: uuid.UUID | str | None = None,
        filename: str | None = None,
    ) -> SavedFile:
        """Rules 1–5. Returns the stored key, a signed URL and the sniffed content type."""
        if isinstance(upload, UploadFile):
            filename = filename or upload.filename
            data = await upload.read()
        else:
            data = bytes(upload)
        limit_mb = max_mb or settings.MAX_UPLOAD_MB
        if not data:
            raise APIError(422, ErrorCode.VALIDATION, "Empty file", {"field": "file"})
        if len(data) > limit_mb * 1024 * 1024:
            raise APIError(
                422, ErrorCode.VALIDATION, f"File exceeds {limit_mb} MB", {"field": "file", "max_mb": limit_mb}
            )
        content_type = sniff_mime(data, filename)
        if content_type in BLOCKED_TYPES or content_type not in set(allowed_types):
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "File type not allowed",
                {"field": "file", "detected": content_type, "allowed": list(allowed_types)},
            )
        await self._check_quota(institution_id, len(data))
        await self._scan(data)
        key = build_key(institution_id or "platform", folder, filename or f"upload.{_ext_for(content_type)}")
        await storage.put(key, data, content_type)
        await self._bump_usage(institution_id, len(data))
        log.info("file_saved", key=key, content_type=content_type, size=len(data))
        return SavedFile(
            key=key, url=storage.signed_url(key), content_type=content_type, size=len(data), original_name=filename
        )

    async def delete(self, key: str, institution_id: uuid.UUID | str | None = None) -> None:
        size = 0
        if settings.STORAGE_BACKEND != "s3":
            p = Path(settings.UPLOAD_DIR) / key
            size = p.stat().st_size if p.exists() else 0
        await storage.delete(key)
        if size:
            await self._bump_usage(institution_id, -size)

    def signed_url(self, key: str, ttl: int | None = None) -> str:
        """Rule 6."""
        return storage.signed_url(key, ttl)

    # ---- rule 4: quota -------------------------------------------------------------------------------------------
    async def _check_quota(self, institution_id: uuid.UUID | str | None, incoming: int) -> None:
        if not institution_id or self.db is None:
            return
        try:
            quota_gb = await PlatformConfigRepository(self.db).plan_storage_gb(uuid.UUID(str(institution_id)))
        except Exception as exc:  # noqa: BLE001 - quota lookup must never block an upload on a broken subscription row
            log.warning("storage_quota_lookup_failed", error=str(exc))
            return
        if quota_gb is None:
            return
        used = await self.usage_bytes(institution_id)
        if used + incoming > quota_gb * 1024**3:
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                "Storage quota exceeded for this institution's plan",
                {"reason": "storage_quota_exceeded", "quota_gb": quota_gb, "used_bytes": used},
            )

    async def usage_bytes(self, institution_id: uuid.UUID | str) -> int:
        from app.db.session import redis_client

        key = f"storage:{institution_id}"
        with contextlib.suppress(Exception):
            cached = await redis_client.get(key)
            if cached is not None:
                return int(cached)
        total = await asyncio.to_thread(_local_tree_size, Path(settings.UPLOAD_DIR) / str(institution_id))
        with contextlib.suppress(Exception):
            await redis_client.set(key, total, ex=6 * 3600)
        return total

    async def _bump_usage(self, institution_id: uuid.UUID | str | None, delta: int) -> None:
        if not institution_id:
            return
        from app.db.session import redis_client

        with contextlib.suppress(Exception):
            if await redis_client.exists(f"storage:{institution_id}"):
                await redis_client.incrby(f"storage:{institution_id}", delta)

    # ---- rule 5: ClamAV ------------------------------------------------------------------------------------------
    async def _scan(self, data: bytes) -> None:
        if not settings.CLAMAV_HOST:
            return
        try:
            verdict = await asyncio.wait_for(_clamd_instream(settings.CLAMAV_HOST, settings.CLAMAV_PORT, data), 30)
        except Exception as exc:  # noqa: BLE001
            # an unreachable scanner is an operational fault, not a user error
            raise APIError(
                503, ErrorCode.INTEGRATION_FAILED, "Virus scanner unavailable", {"error": str(exc)}
            ) from None
        if "FOUND" in verdict:
            raise APIError(
                422, ErrorCode.VALIDATION, "File rejected by the virus scanner", {"field": "file", "verdict": verdict}
            )


async def _clamd_instream(host: str, port: int, data: bytes) -> str:
    reader, writer = await asyncio.open_connection(host, port)
    try:
        writer.write(b"zINSTREAM\0")
        for i in range(0, len(data), 65536):
            chunk = data[i : i + 65536]
            writer.write(struct.pack("!I", len(chunk)) + chunk)
        writer.write(struct.pack("!I", 0))
        await writer.drain()
        return (await reader.read(4096)).decode(errors="replace").strip()
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


def _local_tree_size(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            with contextlib.suppress(OSError):
                total += os.path.getsize(os.path.join(dirpath, f))
    return total


def _ext_for(content_type: str) -> str:
    return {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/gif": "gif",
        "image/webp": "webp",
        "image/svg+xml": "svg",
        "application/pdf": "pdf",
        "text/csv": "csv",
        "text/plain": "txt",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    }.get(content_type, "bin")


def describe() -> dict[str, Any]:
    """Diagnostics for ``/ready`` and the verification script."""
    return {
        "backend": settings.STORAGE_BACKEND,
        "sniffer": settings.FILE_MIME_SNIFFER,
        "clamav": bool(settings.CLAMAV_HOST),
    }
