"""Mandatory disclosures feed — Prompts/32 §32.6 ``disclosure_service`` (Phase 40 website blocks).

``accreditation.disclosure_items`` (sanctioned intake, faculty, FSR, fee structure, results, placement, median salary,
grievance redressal, anti-ragging, IQAC minutes, AQAR links) resolved to the latest institution-level metric values
(no PII — aggregates only) plus a verified evidence link where one is tagged with the metric; stored in
``disclosures:feed`` and refreshed after every compute. The public read serves the stored feed."""

from typing import Any

from sqlalchemy import select

from app.models.accreditation import EvidenceDocument, MetricValue
from app.schemas.accreditation import DisclosureFeedOut, DisclosureItem
from app.services.accreditation.common import AccreditationBase, now_utc


class DisclosureService(AccreditationBase):
    async def refresh(self) -> DisclosureFeedOut:
        items_cfg = await self.acc_setting("disclosure_items")
        defs = await self.definitions_by_key()
        items: list[DisclosureItem] = []
        latest_label: str | None = None
        for it in items_cfg if isinstance(items_cfg, list) else []:
            key = it.get("metric_key")
            row: MetricValue | None = None
            if key:
                row = (
                    await self.db.execute(
                        select(MetricValue)
                        .where(
                            MetricValue.institution_id == self.inst,
                            MetricValue.metric_key == key,
                            MetricValue.college_id.is_(None),
                            MetricValue.program_id.is_(None),
                            MetricValue.value.is_not(None),
                        )
                        .order_by(MetricValue.period_label.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
            ev = (
                await self.db.execute(
                    select(EvidenceDocument.file_url)
                    .where(
                        EvidenceDocument.institution_id == self.inst,
                        EvidenceDocument.verified_at.is_not(None),
                        (EvidenceDocument.metric_key == key)
                        if key
                        else EvidenceDocument.tags.contains([it.get("key")]),
                    )
                    .order_by(EvidenceDocument.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is not None and (latest_label is None or row.period_label > latest_label):
                latest_label = row.period_label
            items.append(
                DisclosureItem(
                    key=str(it.get("key")),
                    title=str(it.get("title")),
                    metric_key=key,
                    value=row.value if row else None,
                    unit=defs[key].unit if key in defs else None,
                    period_label=row.period_label if row else None,
                    evidence_url=ev,
                )
            )
        feed = DisclosureFeedOut(refreshed_at=now_utc().isoformat(), period_label=latest_label, items=items)
        await self.put_meta("disclosures", "feed", feed.model_dump(mode="json"))
        await self._emit("accreditation.disclosures_refreshed", {"items": len(items)}, "institution", self.inst)
        return feed

    async def feed(self) -> DisclosureFeedOut:
        m: dict[str, Any] = await self.meta("disclosures", "feed")
        return DisclosureFeedOut(**m) if m else DisclosureFeedOut()
