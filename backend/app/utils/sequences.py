"""Atomic number sequences over ``number_sequences`` (docs/Technical_Architecture.md §5).

``UPDATE ... SET next_value = next_value + 1 RETURNING`` renders the pattern, e.g. ``ADM-{YYYY}-{SEQ}``.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode


def render_pattern(pattern: str, value: int, padding: int, when: datetime | None = None) -> str:
    now = when or datetime.now(UTC)
    return (
        pattern.replace("{YYYY}", f"{now.year:04d}")
        .replace("{YY}", f"{now.year % 100:02d}")
        .replace("{MM}", f"{now.month:02d}")
        .replace("{SEQ}", str(value).zfill(padding))
    )


async def next_number(
    db: AsyncSession, institution_id: uuid.UUID, scope_key: str, college_id: uuid.UUID | None = None
) -> str:
    """Reserve the next value of a sequence atomically and return the rendered number."""
    row = (
        await db.execute(
            text(
                "UPDATE number_sequences SET next_value = next_value + 1, updated_at = NOW() "
                "WHERE institution_id = :i AND scope_key = :k AND college_id IS NOT DISTINCT FROM :c "
                "RETURNING next_value - 1 AS value, pattern, padding"
            ),
            {"i": str(institution_id), "k": scope_key, "c": str(college_id) if college_id else None},
        )
    ).first()
    if row is None:
        raise APIError(404, ErrorCode.NOT_FOUND, f"Number sequence {scope_key!r} is not configured")
    return render_pattern(row.pattern, row.value, row.padding)
