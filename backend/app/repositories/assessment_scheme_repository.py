"""Assessment schemes and their components — Prompts/05 §05.5 ``assessment_scheme_repository`` (configuration only;
marks entry against the components arrives with Phase 13)."""

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, delete, func, select, update

from app.core.errors import APIError, ErrorCode
from app.models.curriculum import AssessmentComponent, AssessmentScheme
from app.repositories.base import BaseRepository


class AssessmentSchemeRepository(BaseRepository[AssessmentScheme]):
    model = AssessmentScheme
    module = "grading"

    def filtered(self, regulation_id: uuid.UUID | None = None) -> Select[tuple[AssessmentScheme]]:
        stmt = self._base()
        if regulation_id:
            stmt = stmt.where(AssessmentScheme.regulation_id == regulation_id)
        return stmt

    async def get_scheme(self, scheme_id: uuid.UUID) -> AssessmentScheme:
        obj = (await self.db.execute(self._base().where(AssessmentScheme.id == scheme_id))).scalar_one_or_none()
        if obj is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Assessment scheme not found")
        return obj

    async def by_code(self, regulation_id: uuid.UUID, code: str) -> AssessmentScheme | None:
        return (
            await self.db.execute(
                self._base().where(
                    AssessmentScheme.regulation_id == regulation_id,
                    func.upper(AssessmentScheme.code) == code.upper(),
                )
            )
        ).scalar_one_or_none()

    async def for_regulation(self, regulation_id: uuid.UUID) -> Sequence[AssessmentScheme]:
        return (
            (
                await self.db.execute(
                    self._base().where(AssessmentScheme.regulation_id == regulation_id).order_by(AssessmentScheme.code)
                )
            )
            .scalars()
            .all()
        )

    async def components(self, scheme_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[AssessmentComponent]]:
        out: dict[uuid.UUID, list[AssessmentComponent]] = {s: [] for s in scheme_ids}
        if not scheme_ids:
            return out
        rows = (
            (
                await self.db.execute(
                    select(AssessmentComponent)
                    .where(AssessmentComponent.scheme_id.in_(list(scheme_ids)))
                    .order_by(AssessmentComponent.sequence, AssessmentComponent.code)
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            out.setdefault(r.scheme_id, []).append(r)
        return out

    async def replace_components(self, scheme_id: uuid.UUID, rows: list[AssessmentComponent]) -> None:
        await self.db.execute(delete(AssessmentComponent).where(AssessmentComponent.scheme_id == scheme_id))
        for r in rows:
            self.db.add(r)
        await self.db.flush()

    async def clear_default(self, regulation_id: uuid.UUID, except_id: uuid.UUID) -> None:
        await self.db.execute(
            update(AssessmentScheme)
            .where(AssessmentScheme.regulation_id == regulation_id, AssessmentScheme.id != except_id)
            .values(is_default=False)
        )

    async def codes(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not ids:
            return {}
        rows = (
            await self.db.execute(
                select(AssessmentScheme.id, AssessmentScheme.code).where(AssessmentScheme.id.in_(list(ids)))
            )
        ).all()
        return {r[0]: r[1] for r in rows}
