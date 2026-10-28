"""Generate a VAPID key pair for web push — Prompts/39 §39.2 (run once per deployment; never commit the output).

Prints ``VAPID_PUBLIC_KEY`` / ``VAPID_PRIVATE_KEY`` lines for ``.env`` and, with ``--store``, writes the public key
into ``platform_settings['push.vapid']`` (the private key stays in the environment / secret store only).
"""

import argparse
import asyncio
import base64
import json

import _bootstrap  # noqa: F401


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def generate() -> tuple[str, str]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64(public), b64(private)


async def store(public: str) -> None:
    from sqlalchemy import text

    from app.db.session import PlatformSessionLocal

    async with PlatformSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO platform_settings (key, value) VALUES ('push.vapid', CAST(:v AS jsonb)) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
            ),
            {"v": json.dumps({"public_key": public, "subject": "mailto:support@septron.in", "generated_at": "now"})},
        )
        await db.commit()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", action="store_true", help="write the public key to platform_settings['push.vapid']")
    args = ap.parse_args()
    public, private = generate()
    print(f"VAPID_PUBLIC_KEY={public}")  # noqa: T201
    print(f"VAPID_PRIVATE_KEY={private}")  # noqa: T201
    if args.store:
        asyncio.run(store(public))


if __name__ == "__main__":
    main()
