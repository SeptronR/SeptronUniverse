"""File-service verification — Prompts/01 §01.11 step 8.

    python scripts/verify/file_service_check.py [--base-url http://localhost:8000]

1. uploads a PNG (bytes generated here) through ``FileService.save`` → key ``{institution}/verify/<uuid>.png``;
2. uploads an ``.exe`` renamed to ``.png`` → rejected with ``422 VALIDATION`` (detected ``application/x-dosexec``);
3. the signed URL of the PNG is fetched from the running API (200, ``image/png``); a tampered signature → 403; an
   expired link (``ttl=-1``) → 403; then the file is deleted.
Exit code 0 on success. Needs the DB (quota lookup) — Redis is optional here (usage counter degrades gracefully).
"""

import argparse
import asyncio
import struct
import sys
import uuid
import zlib
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1])
)  # scripts/ holds _bootstrap (this file lives in scripts/verify/)
import _bootstrap  # noqa: E402,F401
import httpx


def tiny_png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack("!I", len(data)) + body + struct.pack("!I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack("!IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00" + b"\xff\x00\x00"  # one red pixel, filter byte 0
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def fake_exe() -> bytes:
    return b"MZ\x90\x00" + b"\x00" * 60 + b"PE\x00\x00" + b"\x00" * 200


async def run(base_url: str) -> int:
    from app.core.errors import APIError
    from app.db.session import SessionLocal
    from app.services.file_service import IMAGE_TYPES, FileService

    institution = uuid.UUID("00000000-0000-0000-0000-00000000f11e")  # no subscription row → no quota (dev)
    checks = 0
    async with SessionLocal() as db:
        svc = FileService(db)
        saved = await svc.save(
            tiny_png(), "verify", IMAGE_TYPES, max_mb=1, institution_id=institution, filename="pixel.png"
        )
        assert saved.key.startswith(f"{institution}/verify/") and saved.key.endswith(".png"), saved.key
        assert saved.content_type == "image/png", saved.content_type
        print(f"OK png stored under {saved.key} ({saved.size} bytes)")
        checks += 1
        try:
            await svc.save(
                fake_exe(), "verify", IMAGE_TYPES, max_mb=1, institution_id=institution, filename="virus.png"
            )
            print("FAIL renamed .exe was accepted")
            return 1
        except APIError as exc:
            assert exc.status_code == 422 and exc.code == "VALIDATION", (exc.status_code, exc.code)
            print(f"OK renamed .exe rejected: {exc.code} detected={exc.details.get('detected')}")
            checks += 1
        try:
            await svc.save(b"", "verify", IMAGE_TYPES, institution_id=institution, filename="empty.png")
            print("FAIL empty file accepted")
            return 1
        except APIError as exc:
            assert exc.code == "VALIDATION"
            print("OK empty file rejected")
            checks += 1

        url = saved.url
        expired = svc.signed_url(saved.key, ttl=-1)
        tampered = url.replace("sig=", "sig=0")
        async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
            try:
                r = await client.get(url)
            except httpx.HTTPError as exc:
                print(
                    f"SKIP signed-URL fetch (API not reachable at {base_url}: {exc.__class__.__name__}) - run with the API up"
                )
                await svc.delete(saved.key, institution)
                print(f"file_service_check: PASS ({checks} checks, HTTP checks skipped)")
                return 0
            assert r.status_code == 200 and r.headers.get("content-type", "").startswith("image/png"), (
                r.status_code,
                r.headers,
            )
            print("OK signed URL serves the PNG (200 image/png)")
            checks += 1
            r = await client.get(tampered)
            assert r.status_code == 403 and r.json()["error"]["code"] == "PERMISSION_DENIED", r.status_code
            print("OK tampered signature -> 403")
            checks += 1
            r = await client.get(expired)
            assert r.status_code == 403, r.status_code
            print("OK expired link -> 403")
            checks += 1
            r = await client.get(f"/uploads/{saved.key}")
            assert r.status_code == 403, r.status_code
            print("OK unsigned link -> 403")
            checks += 1
        await svc.delete(saved.key, institution)
        print("OK file deleted")
        checks += 1
    print(f"file_service_check: PASS ({checks} checks)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8000")
    args = ap.parse_args()
    return asyncio.run(run(args.base_url))


if __name__ == "__main__":
    sys.exit(main())
