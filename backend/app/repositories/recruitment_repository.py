"""Recruitment — Prompts/06 §06.5 ``recruitment_repository.py`` (``module="recruitment"``): postings, applications,
interview panels and scores. Panel members (``interview_panels.members[].user_id``) are the ownership link for the
scoring route."""

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, select

from app.core.errors import APIError, ErrorCode
from app.models.hr import InterviewPanel, InterviewScore, JobApplication, JobPosting
from app.repositories.base import BaseRepository


class PostingRepository(BaseRepository[JobPosting]):
    model = JobPosting
    module = "recruitment"

    def filtered(
        self, *, status: str | None = None, department_id: uuid.UUID | None = None, q: str | None = None
    ) -> Select[tuple[JobPosting]]:
        stmt = self._base()
        if status:
            stmt = stmt.where(JobPosting.status == status)
        if department_id:
            stmt = stmt.where(JobPosting.department_id == department_id)
        if q:
            stmt = stmt.where(JobPosting.title.ilike(f"%{q.strip()}%"))
        return stmt

    async def get_one(self, posting_id: uuid.UUID, *, for_update: bool = False) -> JobPosting:
        stmt = self._base().where(JobPosting.id == posting_id)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Job posting not found")
        return row

    async def open_postings(self) -> Sequence[JobPosting]:
        stmt = self._base().where(JobPosting.status == "open").order_by(JobPosting.closes_at.asc().nulls_last())
        return (await self.db.execute(stmt)).scalars().all()

    async def application_counts(self, posting_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
        if not posting_ids:
            return {}
        rows = (
            await self.db.execute(
                select(JobApplication.posting_id, JobApplication.status, func.count())
                .where(JobApplication.posting_id.in_(list(posting_ids)))
                .group_by(JobApplication.posting_id, JobApplication.status)
            )
        ).all()
        out: dict[uuid.UUID, dict[str, int]] = {}
        for pid, status, n in rows:
            out.setdefault(pid, {})[status] = int(n)
        return out


class ApplicationRepository(BaseRepository[JobApplication]):
    model = JobApplication
    module = "recruitment"

    async def for_posting(self, posting_id: uuid.UUID, status: str | None = None) -> Sequence[JobApplication]:
        stmt = self._base().where(JobApplication.posting_id == posting_id)
        if status:
            stmt = stmt.where(JobApplication.status == status)
        return (await self.db.execute(stmt.order_by(JobApplication.created_at))).scalars().all()

    async def get_one(self, application_id: uuid.UUID, *, for_update: bool = False) -> JobApplication:
        stmt = self._base().where(JobApplication.id == application_id)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Application not found")
        return row

    async def duplicate(self, posting_id: uuid.UUID, email: str) -> bool:
        stmt = select(JobApplication.id).where(
            JobApplication.posting_id == posting_id,
            func.lower(JobApplication.applicant["email"].astext) == email.lower(),
        )
        return (await self.db.execute(stmt.limit(1))).first() is not None

    async def joined_count(self, posting_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(JobApplication.posting_id == posting_id, JobApplication.status == "joined")
        return int((await self.db.execute(stmt)).scalar_one())


class PanelRepository(BaseRepository[InterviewPanel]):
    model = InterviewPanel
    module = "recruitment"

    async def for_posting(self, posting_id: uuid.UUID) -> Sequence[InterviewPanel]:
        stmt = self._base().where(InterviewPanel.posting_id == posting_id).order_by(InterviewPanel.scheduled_at)
        return (await self.db.execute(stmt)).scalars().all()

    async def get_one(self, panel_id: uuid.UUID) -> InterviewPanel:
        row = (await self.db.execute(self._base().where(InterviewPanel.id == panel_id))).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Interview panel not found")
        return row

    async def score(
        self, panel_id: uuid.UUID, application_id: uuid.UUID, *, for_update: bool = False
    ) -> InterviewScore | None:
        stmt = select(InterviewScore).where(
            InterviewScore.panel_id == panel_id, InterviewScore.application_id == application_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def scores_for(self, panel_ids: Sequence[uuid.UUID]) -> Sequence[InterviewScore]:
        if not panel_ids:
            return []
        stmt = select(InterviewScore).where(InterviewScore.panel_id.in_(list(panel_ids)))
        return (await self.db.execute(stmt)).scalars().all()

    async def add(self, obj: object) -> None:
        self.db.add(obj)
        await self.db.flush()


async def posting_institution(posting_id: uuid.UUID) -> uuid.UUID | None:
    """Institution of a posting, read on the platform session (the public apply route has no tenant context yet)."""
    from app.db.session import PlatformSessionLocal

    async with PlatformSessionLocal() as pdb:
        row = (await pdb.execute(select(JobPosting.institution_id).where(JobPosting.id == posting_id))).first()
    return uuid.UUID(str(row[0])) if row else None
