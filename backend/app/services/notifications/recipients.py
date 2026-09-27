"""Recipient resolution for a notification request (Prompts/04 §04.6 ``recipients.py``)."""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.audience_repository import AudienceRepository


@dataclass
class Recipient:
    user_id: uuid.UUID | None
    email: str | None = None
    phone: str | None = None
    locale: str | None = None
    name: str | None = None
    direct: dict[str, str] = field(default_factory=dict)  # {"channel": "sms", "to": "+91…"} for account-less people


async def resolve_recipients(
    db: AsyncSession, institution_id: uuid.UUID | None, audience: dict[str, Any]
) -> list[Recipient]:
    repo = AudienceRepository(db)
    users: set[uuid.UUID] = set()
    if institution_id is not None:
        users = await repo.resolve(institution_id, audience)
    elif audience.get("user_ids"):  # platform-level notification (super admin, installer)
        users = {uuid.UUID(str(u)) for u in audience["user_ids"]}
    contacts = await repo.contacts(sorted(users, key=str))
    out = [
        Recipient(
            user_id=uid,
            email=c.get("email"),
            phone=c.get("phone"),
            locale=c.get("locale"),
            name=c.get("display_name") or c.get("username"),
        )
        for uid, c in contacts.items()
    ]
    for contact in audience.get("direct_contacts") or []:
        if contact.get("to") and contact.get("channel"):
            out.append(
                Recipient(
                    user_id=None, name=contact.get("name"), direct={"channel": contact["channel"], "to": contact["to"]}
                )
            )
    return out
