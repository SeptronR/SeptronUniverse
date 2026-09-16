"""Storage abstraction (local / S3) with per-tenant prefixes and signed URLs — Prompts/00 §2 tree, Technical_Architecture §2.

Keys are ``{institution_id}/{folder}/{uuid}.{ext}``. Local backend serves ``/uploads/{key}?sig=…&exp=…`` (HMAC);
S3 backend presigns. Phase 01's ``file_service`` adds MIME sniffing, quota checks and optional ClamAV on top.
"""

import hashlib
import hmac
import os
import time
import uuid
from pathlib import Path
from typing import Any, Protocol

import aiofiles

from app.core.config import settings
from app.core.errors import APIError, ErrorCode


class Storage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str | None = None) -> str: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    def signed_url(self, key: str, ttl: int | None = None) -> str: ...


def build_key(institution_id: uuid.UUID | str, folder: str, filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".") or "bin"
    return f"{institution_id}/{folder.strip('/')}/{uuid.uuid4().hex}.{ext}"


def _sign(key: str, exp: int) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"{key}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def verify_signed_url(key: str, sig: str, exp: int) -> bool:
    return exp >= int(time.time()) and hmac.compare_digest(sig, _sign(key, exp))


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise APIError(400, ErrorCode.VALIDATION, "Invalid storage key")
        return p

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> str:
        p = self._path(key)
        os.makedirs(p.parent, exist_ok=True)
        async with aiofiles.open(p, "wb") as f:
            await f.write(data)
        return key

    async def get(self, key: str) -> bytes:
        p = self._path(key)
        if not p.exists():
            raise APIError(404, ErrorCode.NOT_FOUND, "File not found")
        async with aiofiles.open(p, "rb") as f:
            return bytes(await f.read())

    async def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()

    async def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def signed_url(self, key: str, ttl: int | None = None) -> str:
        exp = int(time.time()) + (ttl or settings.SIGNED_URL_TTL_SECONDS)
        return f"/uploads/{key}?sig={_sign(key, exp)}&exp={exp}"


class S3Storage:
    def __init__(self) -> None:
        import boto3

        self.bucket = settings.S3_BUCKET
        self.client: Any = boto3.client(
            "s3",
            region_name=settings.S3_REGION,
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> str:
        extra = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
        return key

    async def get(self, key: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()  # type: ignore[no-any-return]
        except self.client.exceptions.NoSuchKey:
            raise APIError(404, ErrorCode.NOT_FOUND, "File not found") from None

    async def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    async def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:  # noqa: BLE001
            return False

    def signed_url(self, key: str, ttl: int | None = None) -> str:
        return self.client.generate_presigned_url(  # type: ignore[no-any-return]
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=ttl or settings.SIGNED_URL_TTL_SECONDS,
        )


def get_storage() -> Storage:
    if settings.STORAGE_BACKEND == "s3":
        return S3Storage()
    return LocalStorage(settings.UPLOAD_DIR)


storage: Storage = get_storage()
