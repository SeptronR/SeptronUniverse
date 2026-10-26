"""Frameworks & criteria trees — Prompts/32 §32.6 ``framework_service``.

Frameworks / criteria are platform rows versioned by ``version`` (``0001`` §36 + ``0032``); an institution cannot edit
them but may add custom sub-items in ``institution_settings['accreditation.custom_criteria']`` (``{framework_code:
[{code, title, parent, metric_key?}]}``) which are merged into the tree as ``custom`` nodes. Activation per institution
follows the feature flags (``accreditation.naac|nba|nirf|aishe|aicte_ugc``)."""

import uuid
from typing import Any

from sqlalchemy import func, select

from app.enums.accreditation import FRAMEWORK_FEATURES
from app.models.accreditation import AccreditationFramework, FrameworkCriterion
from app.schemas.accreditation import CriterionOut, FrameworkOut, MetricDefinitionOut
from app.services.accreditation.common import AccreditationBase, forbidden


def build_tree(rows: list[FrameworkCriterion], custom: list[dict[str, Any]] | None = None) -> list[CriterionOut]:
    nodes: dict[str, CriterionOut] = {}
    parent_of: dict[str, str | None] = {}
    by_id = {r.id: r for r in rows}
    for r in rows:
        nodes[r.code] = CriterionOut(
            id=r.id,
            code=r.code,
            title=r.title,
            metric_type=r.metric_type,
            max_score=r.max_score,
            period_type=r.period_type,
            metric_key=r.metric_key,
        )
        parent_of[r.code] = by_id[r.parent_id].code if r.parent_id and r.parent_id in by_id else None
    for c in custom or []:
        code = str(c.get("code") or "")
        if not code or code in nodes:
            continue
        nodes[code] = CriterionOut(
            id=uuid.uuid5(uuid.NAMESPACE_URL, f"custom:{code}"),
            code=code,
            title=str(c.get("title") or code),
            metric_type=str(c.get("metric_type") or "qualitative"),
            period_type="academic_year",
            metric_key=c.get("metric_key"),
            custom=True,
        )
        parent_of[code] = c.get("parent")
    roots: list[CriterionOut] = []
    for code, node in nodes.items():
        parent = parent_of.get(code)
        if parent and parent in nodes:
            nodes[parent].children.append(node)
        else:
            roots.append(node)
    return roots


class FrameworkService(AccreditationBase):
    def require_reader(self) -> None:
        if not (self.can(self.module, "view") or self.can(self.module, "view_all") or self.can(self.module, "manage")):
            raise forbidden("accreditation:view required")

    async def frameworks(self) -> list[FrameworkOut]:
        self.require_reader()
        counts: dict[uuid.UUID, int] = {
            fid: int(n)
            for fid, n in (
                await self.db.execute(
                    select(FrameworkCriterion.framework_id, func.count()).group_by(FrameworkCriterion.framework_id)
                )
            ).all()
        }
        out: list[FrameworkOut] = []
        for fw in (
            await self.db.execute(select(AccreditationFramework).order_by(AccreditationFramework.code))
        ).scalars():
            out.append(
                FrameworkOut(
                    id=fw.id,
                    code=fw.code,
                    name=fw.name,
                    version=fw.version,
                    active=await self.framework_enabled(fw),
                    feature=FRAMEWORK_FEATURES.get(fw.code),
                    criteria_count=int(counts.get(fw.id, 0)),
                )
            )
        return out

    async def tree(self, code: str) -> FrameworkOut:
        self.require_reader()
        fw = await self.framework(code)
        await self.require_framework(fw)
        rows = await self.criteria(fw.id)
        custom = await self.acc_setting("custom_criteria")
        extra = custom.get(fw.code) if isinstance(custom, dict) else None
        return FrameworkOut(
            id=fw.id,
            code=fw.code,
            name=fw.name,
            version=fw.version,
            active=True,
            feature=FRAMEWORK_FEATURES.get(fw.code),
            criteria_count=len(rows),
            criteria=build_tree(rows, extra if isinstance(extra, list) else None),
        )

    async def framework_metrics(self, code: str) -> list[MetricDefinitionOut]:
        self.require_reader()
        fw = await self.framework(code)
        await self.require_framework(fw)
        keys = {c.metric_key for c in await self.criteria(fw.id) if c.metric_key}
        from app.services.accreditation.metric_service import MetricService

        return [d for d in await MetricService(self.db, self.principal, self.request).definitions() if d.key in keys]
