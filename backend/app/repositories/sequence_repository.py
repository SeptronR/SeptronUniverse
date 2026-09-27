"""Number sequences — Prompts/03 §03.5 ``sequence_repository``.

``next_value`` reserves a value with one ``UPDATE … SET next_value = next_value + 1 RETURNING`` **inside the caller's
transaction** (the row lock serialises concurrent callers; a rollback returns the value). ``render`` supports the
Phase 03 tokens ``{yy}``, ``{yyyy}``, ``{mm}``, ``{college_code}``, ``{prog_code}``, ``{term}``, ``{seq}`` and
``{seq:N}`` (zero-padded to N; ``{seq}`` uses the row's ``padding``) plus the Phase 00 upper-case aliases
(``{YYYY}``, ``{YY}``, ``{MM}``, ``{SEQ}``) used by ``app/utils/sequences.py``.
"""

import re
import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import Select, select, text, update

from app.core.errors import APIError, ErrorCode
from app.models.platform import NumberSequence
from app.repositories.base import BaseRepository

TOKEN_RE = re.compile(r"\{([A-Za-z_]+)(?::(\d{1,2}))?\}")
KNOWN_TOKENS = {"yy", "yyyy", "mm", "college_code", "prog_code", "term", "seq"}


def render(pattern: str, context: dict[str, Any], value: int, padding: int) -> str:
    """Render ``pattern`` for ``value`` — unknown tokens raise 422 (checked on create/update too)."""

    def sub(m: re.Match[str]) -> str:
        name, width = m.group(1), m.group(2)
        low = name.lower()
        if low == "seq":
            return str(value).zfill(int(width) if width else padding)
        if low not in KNOWN_TOKENS:
            raise APIError(422, ErrorCode.VALIDATION, f"Unknown token {{{name}}} in pattern", {"field": "pattern"})
        return str(context.get(low) or "")

    return TOKEN_RE.sub(sub, pattern)


def validate_pattern(pattern: str) -> None:
    tokens = [m.group(1).lower() for m in TOKEN_RE.finditer(pattern)]
    unknown = sorted({t for t in tokens if t not in KNOWN_TOKENS})
    if unknown:
        raise APIError(422, ErrorCode.VALIDATION, f"Unknown pattern tokens: {', '.join(unknown)}", {"field": "pattern"})
    if "seq" not in tokens:
        raise APIError(422, ErrorCode.VALIDATION, "The pattern must contain {seq} or {seq:N}", {"field": "pattern"})


def date_context(day: date) -> dict[str, str]:
    return {"yyyy": f"{day.year:04d}", "yy": f"{day.year % 100:02d}", "mm": f"{day.month:02d}"}


class SequenceRepository(BaseRepository[NumberSequence]):
    model = NumberSequence
    module = "settings"

    def filtered(self, college_id: uuid.UUID | None = None, q: str | None = None) -> Select[tuple[NumberSequence]]:
        stmt = self._base()
        if college_id is not None:
            stmt = stmt.where(NumberSequence.college_id == college_id)
        if q:
            stmt = stmt.where(NumberSequence.scope_key.ilike(f"%{q}%"))
        return stmt

    async def get_one(self, seq_id: uuid.UUID, *, for_update: bool = False) -> NumberSequence:
        stmt = self._base().where(NumberSequence.id == seq_id)
        if for_update:
            stmt = stmt.with_for_update()
        obj = (await self.db.execute(stmt)).scalar_one_or_none()
        if obj is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Number sequence not found")
        return obj

    async def by_scope(
        self, institution_id: uuid.UUID, scope_key: str, college_id: uuid.UUID | None
    ) -> NumberSequence | None:
        stmt = select(NumberSequence).where(
            NumberSequence.institution_id == institution_id, NumberSequence.scope_key == scope_key
        )
        stmt = stmt.where(
            NumberSequence.college_id.is_(None) if college_id is None else NumberSequence.college_id == college_id
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def next_value(
        self, institution_id: uuid.UUID, scope_key: str, college_id: uuid.UUID | None
    ) -> tuple[int, NumberSequence]:
        """Atomically reserve the next value (the college row wins over the institution-wide row)."""
        for cid in ([college_id, None] if college_id is not None else [None]):
            row = (
                await self.db.execute(
                    text(
                        "UPDATE number_sequences SET next_value = next_value + 1, updated_at = NOW() "
                        "WHERE institution_id = :i AND scope_key = :k AND college_id IS NOT DISTINCT FROM :c "
                        "RETURNING id, next_value - 1 AS value"
                    ),
                    {"i": institution_id, "k": scope_key, "c": cid},
                )
            ).first()
            if row is not None:
                seq = (
                    await self.db.execute(
                        select(NumberSequence)
                        .where(NumberSequence.id == row.id)
                        .execution_options(populate_existing=True)
                    )
                ).scalar_one()
                return int(row.value), seq
        raise APIError(404, ErrorCode.NOT_FOUND, f"Number sequence {scope_key!r} is not configured")

    async def reset(self, ids: Sequence[uuid.UUID]) -> int:
        if not ids:
            return 0
        res = await self.db.execute(update(NumberSequence).where(NumberSequence.id.in_(ids)).values(next_value=1))
        return int(res.rowcount or 0)  # type: ignore[attr-defined]

    async def with_policy(self, policy: str) -> Sequence[NumberSequence]:
        return (
            (await self.db.execute(select(NumberSequence).where(NumberSequence.reset_policy == policy))).scalars().all()
        )
