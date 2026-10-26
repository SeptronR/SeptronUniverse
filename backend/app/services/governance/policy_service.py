"""Policy repository — Prompts/33 §33.6 ``policy_service`` ({governance.policies}).

Institutional policies by category (academic, examination, IT, POSH, anti-ragging, research ethics, data protection,
HR, finance, hostel, conduct) with versions and effective dates. Drafts belong to their owner (``policy:<id>.owner``)
and policy managers (``governance:policies`` / ``manage``); **submit** starts ``governance.policy_approval`` (owner →
registrar → principal) — the final approval cites a council resolution when ``governance.minutes`` is on (422
``RESOLUTION_REQUIRED``), written to ``policies.approved_resolution_id`` and the resolution's ``linked_entity``.
**Publish** makes an approved policy visible to every authenticated user, raises a Phase 24 announcement (with
acknowledgement for ``policies.ack_required_categories`` or ``requires_ack``) and notifies; acknowledgements are kept per
user (``policy_ack:<id>``) with stats; **supersede** closes the previous version (chain kept both ways); the website
flag feeds the public list (Phase 40). Weekly acknowledgement reminders.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.models.governance import Policy, Resolution
from app.models.platform import WorkflowInstance
from app.schemas.governance import PolicyAckOut, PolicyApprove, PolicyIn, PolicyOut, PolicyUpdate
from app.services.governance.common import GovernanceBase, forbidden, is_auditor, not_found, now_utc, rule

ENTITY = "policy"
WF_KEY = "governance.policy_approval"
AUDIENCE_ROLES = ("faculty", "hod", "dean", "registrar", "accountant", "librarian", "student", "guest_faculty")


class PolicyService(GovernanceBase):
    def manager(self) -> bool:
        p = self.principal
        return self.system() or (not is_auditor(p) and (p.has("governance", "policies") or self.admin()))

    def approver(self) -> bool:
        p = self.principal
        return self.system() or (not is_auditor(p) and (p.has("governance", "approve") or self.admin()))

    async def _row(self, pid: uuid.UUID, *, lock: bool = False) -> Policy:
        stmt = select(Policy).where(Policy.id == pid, Policy.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        r = (await self.db.execute(stmt)).scalar_one_or_none()
        if r is None:
            raise not_found("Policy")
        if r.status == "draft" and not (self.manager() or self.reader_all() or self.approver()):
            m = await self.meta("policy", r.id)
            if m.get("owner") != str(self.actor_id):
                raise not_found("Policy")
        return r

    async def ack_map(self, pid: uuid.UUID) -> dict[str, str]:
        return {k: str(v) for k, v in (await self.meta("policy_ack", pid)).items()}

    async def audience_size(self) -> int:
        from app.models.platform import Role, UserRole

        return int(
            (
                await self.db.execute(
                    select(func.count(func.distinct(UserRole.user_id)))
                    .join(Role, Role.id == UserRole.role_id)
                    .where(UserRole.institution_id == self.inst, Role.slug.in_(AUDIENCE_ROLES))
                )
            ).scalar_one()
        )

    async def outs(self, rows: list[Policy], *, stats: bool = False) -> list[PolicyOut]:
        metas = await self.metas("policy", [str(r.id) for r in rows])
        acks = await self.metas("policy_ack", [str(r.id) for r in rows])
        res = {
            r.id: r.number
            for r in (
                await self.db.execute(
                    select(Resolution).where(
                        Resolution.id.in_(
                            [x.approved_resolution_id for x in rows if x.approved_resolution_id] or [uuid.uuid4()]
                        )
                    )
                )
            ).scalars()
        }
        required = await self.gov_setting("policies.ack_required_categories") or []
        size = await self.audience_size() if stats else 0
        me = str(self.actor_id) if self.actor_id else None
        out = []
        for r in rows:
            m = metas.get(str(r.id), {})
            a = acks.get(str(r.id), {})
            req = bool(m.get("requires_ack")) or (r.category in required)
            out.append(
                PolicyOut(
                    id=r.id,
                    title=r.title,
                    category=r.category,
                    version=r.version,
                    status=r.status,
                    stage=str(m.get("stage") or ("published" if m.get("published") else r.status)),
                    effective_from=r.effective_from,
                    file_url=r.file_url,
                    summary=m.get("summary"),
                    requires_ack=req,
                    website=bool(m.get("website")),
                    published=bool(m.get("published")),
                    approved_resolution_id=r.approved_resolution_id,
                    resolution_number=res.get(r.approved_resolution_id) if r.approved_resolution_id else None,
                    owner_user_id=uuid.UUID(m["owner"]) if m.get("owner") else None,
                    supersedes_policy_id=uuid.UUID(m["supersedes"]) if m.get("supersedes") else None,
                    superseded_by_policy_id=uuid.UUID(m["superseded_by"]) if m.get("superseded_by") else None,
                    acknowledged=bool(me and me in a),
                    ack_count=len(a),
                    ack_pct=round(100 * len(a) / size, 1) if stats and size else None,
                    workflow_instance_id=uuid.UUID(m["workflow_instance_id"])
                    if m.get("workflow_instance_id")
                    else None,
                    created_at=r.created_at,
                )
            )
        return out

    async def list_policies(
        self, category: str | None = None, status: str | None = None, q: str | None = None
    ) -> list[PolicyOut]:
        stmt = select(Policy).where(Policy.institution_id == self.inst)
        if category:
            stmt = stmt.where(Policy.category == category)
        if status:
            stmt = stmt.where(Policy.status == status)
        if q:
            stmt = stmt.where(Policy.title.ilike(f"%{q}%"))
        rows = list((await self.db.execute(stmt.order_by(Policy.category, Policy.title, Policy.version))).scalars())
        if not (self.manager() or self.reader_all() or self.approver()):
            metas = await self.metas("policy", [str(r.id) for r in rows])
            rows = [
                r
                for r in rows
                if (r.status != "draft" and metas.get(str(r.id), {}).get("published"))
                or metas.get(str(r.id), {}).get("owner") == str(self.actor_id)
            ]
        return await self.outs(rows, stats=self.manager())

    async def get(self, pid: uuid.UUID) -> PolicyOut:
        return (await self.outs([await self._row(pid)], stats=True))[0]

    async def create(self, body: PolicyIn) -> PolicyOut:
        self.require_writer()
        if not (self.manager() or self.has_any("governance", "view")):
            raise forbidden("governance:policies required")
        r = Policy(
            institution_id=self.inst,
            title=body.title,
            category=body.category,
            version=body.version,
            effective_from=body.effective_from,
            file_url=body.file_url,
            status="draft",
        )
        self.db.add(r)
        await self.db.flush()
        m: dict[str, Any] = {
            "owner": str(self.actor_id) if self.actor_id else None,
            "summary": body.summary,
            "requires_ack": body.requires_ack,
            "website": body.website,
            "stage": "draft",
        }
        if body.supersedes_policy_id:
            await self._row(body.supersedes_policy_id)
            m["supersedes"] = str(body.supersedes_policy_id)
        await self.put_meta("policy", r.id, m)
        await self._audit("create", ENTITY, r.id, None, {"title": r.title, "version": r.version})
        return (await self.outs([r]))[0]

    async def _owner_or_manager(self, r: Policy) -> None:
        self.require_writer()
        m = await self.meta("policy", r.id)
        if not (self.manager() or m.get("owner") == str(self.actor_id)):
            raise forbidden("Only the policy owner or a policy manager may do this")

    async def update(self, pid: uuid.UUID, body: PolicyUpdate) -> PolicyOut:
        r = await self._row(pid, lock=True)
        await self._owner_or_manager(r)
        m = await self.meta("policy", r.id)
        if r.status != "draft" or m.get("stage") == "submitted":
            raise rule("Only drafts can be edited — create a new version", "NOT_DRAFT")
        data = body.model_dump(exclude_unset=True)
        for k in ("summary", "requires_ack", "website"):
            if k in data:
                m[k] = data.pop(k)
        for k, v in data.items():
            setattr(r, k, v)
        await self.put_meta("policy", r.id, m)
        await self.db.flush()
        return (await self.outs([r]))[0]

    async def submit(self, pid: uuid.UUID) -> PolicyOut:
        r = await self._row(pid, lock=True)
        await self._owner_or_manager(r)
        m = await self.meta("policy", r.id)
        if r.status != "draft" or m.get("stage") == "submitted":
            raise rule("The policy is not a draft", "NOT_DRAFT")
        wf = await self.start_workflow(
            WF_KEY, ENTITY, r.id, f"Policy · {r.title} v{r.version}", {"category": r.category}
        )
        m.update(
            {
                "stage": "submitted",
                "workflow_instance_id": str(wf) if wf else None,
                "submitted_at": now_utc().isoformat(),
            }
        )
        await self.put_meta("policy", r.id, m)
        await self._emit("policy.submitted", {"policy_id": str(r.id)}, ENTITY, r.id)
        return (await self.outs([r]))[0]

    async def _final_step(self, wf_id: str | None) -> bool:
        if not wf_id:
            return True
        wf = (
            await self.db.execute(select(WorkflowInstance).where(WorkflowInstance.id == uuid.UUID(wf_id)))
        ).scalar_one_or_none()
        return wf is None or wf.status not in ("pending", "escalated") or int(wf.current_step or 1) >= 2

    async def approve(self, pid: uuid.UUID, body: PolicyApprove) -> PolicyOut:
        self.require_writer()
        r = await self._row(pid, lock=True)
        m = await self.meta("policy", r.id)
        if m.get("stage") != "submitted":
            raise rule("Submit the policy first", "NOT_SUBMITTED")
        final = await self._final_step(m.get("workflow_instance_id"))
        if body.approve and final and body.resolution_id is None and await self.feature("governance.minutes"):
            raise rule("A council resolution is required to approve a policy", "RESOLUTION_REQUIRED", 422)
        if body.resolution_id:
            res = (
                await self.db.execute(
                    select(Resolution).where(
                        Resolution.id == body.resolution_id, Resolution.institution_id == self.inst
                    )
                )
            ).scalar_one_or_none()
            if res is None:
                raise rule("Unknown resolution", "UNKNOWN_RESOLUTION", 422)
            m["resolution_id"] = str(body.resolution_id)
            await self.put_meta("policy", r.id, m)
        if await self.acted_on_workflow(m.get("workflow_instance_id"), body.approve, body.comment):
            return (await self.outs([r]))[0]
        if not self.approver():
            raise forbidden("governance:approve required")
        if body.approve:
            await self.finalise(r)
        else:
            await self.returned(r, body.comment)
        return (await self.outs([r]))[0]

    async def finalise(self, r: Policy) -> None:
        m = await self.meta("policy", r.id)
        r.status = "approved"
        if m.get("resolution_id"):
            r.approved_resolution_id = uuid.UUID(m["resolution_id"])
            res = (
                await self.db.execute(select(Resolution).where(Resolution.id == r.approved_resolution_id))
            ).scalar_one_or_none()
            if res is not None and not res.linked_entity:
                res.linked_entity = {"entity_type": "policy", "entity_id": str(r.id), "label": r.title}
        m.update({"stage": "approved", "approved_at": now_utc().isoformat()})
        await self.put_meta("policy", r.id, m)
        await self.db.flush()
        await self._audit("approve", ENTITY, r.id, None, {"resolution_id": m.get("resolution_id")})
        await self._emit("policy.approved", {"policy_id": str(r.id)}, ENTITY, r.id)

    async def returned(self, r: Policy, comment: str | None) -> None:
        m = await self.meta("policy", r.id)
        m.update({"stage": "draft", "workflow_instance_id": None, "returned_comment": comment})
        await self.put_meta("policy", r.id, m)

    async def publish(self, pid: uuid.UUID) -> PolicyOut:
        self.require_writer()
        if not (self.manager() or self.approver()):
            raise forbidden("governance:policies required")
        r = await self._row(pid, lock=True)
        if r.status != "approved":
            raise rule("Only approved policies are published", "NOT_APPROVED")
        m = await self.meta("policy", r.id)
        if m.get("published"):
            raise rule("Already published", "ALREADY_PUBLISHED")
        out = (await self.outs([r]))[0]
        m.update({"published": True, "published_at": now_utc().isoformat(), "stage": "published"})
        ann = await self._announce(r, out.requires_ack)
        m["announcement_id"] = str(ann) if ann else None
        await self.put_meta("policy", r.id, m)
        if m.get("supersedes"):
            await self._supersede(uuid.UUID(m["supersedes"]), r.id)
        ctx = {"title": r.title, "version": r.version, "effective_from": str(r.effective_from or "")}
        aud = {"roles": list(AUDIENCE_ROLES)}
        await self._notify("policy.ack_required" if out.requires_ack else "policy.published", [], ctx, audience=aud)
        await self._emit(
            "policy.published",
            {"policy_id": str(r.id), "category": r.category, "website": bool(m.get("website"))},
            ENTITY,
            r.id,
        )
        return (await self.outs([r], stats=True))[0]

    async def _announce(self, r: Policy, requires_ack: bool) -> uuid.UUID | None:
        try:
            from app.models.communication import Announcement

            async with self.db.begin_nested():
                a = Announcement(
                    institution_id=self.inst,
                    title=f"Policy: {r.title} (v{r.version})"[:200],
                    body=(await self.meta("policy", r.id)).get("summary") or f"{r.title} is published.",
                    category="policy",
                    audience_rules={},
                    attachments=[{"url": r.file_url, "name": r.title}] if r.file_url else None,
                    publish_at=now_utc(),
                    requires_ack=requires_ack,
                    created_by=self.actor_id,
                )
                self.db.add(a)
                await self.db.flush()
            return a.id
        except Exception:  # noqa: BLE001 - the announcement is a convenience; acknowledgements live on the policy
            return None

    async def _supersede(self, old_id: uuid.UUID, by: uuid.UUID | None) -> None:
        old = (await self.db.execute(select(Policy).where(Policy.id == old_id).with_for_update())).scalar_one_or_none()
        if old is None or old.status == "superseded":
            return
        old.status = "superseded"
        m = await self.meta("policy", old.id)
        m.update(
            {"superseded_by": str(by) if by else None, "stage": "superseded", "superseded_at": now_utc().isoformat()}
        )
        await self.put_meta("policy", old.id, m)
        await self.db.flush()
        await self._emit("policy.superseded", {"policy_id": str(old.id), "by": str(by) if by else None}, ENTITY, old.id)

    async def supersede(self, pid: uuid.UUID, by_policy_id: uuid.UUID | None = None) -> PolicyOut:
        self.require_writer()
        if not self.manager():
            raise forbidden("governance:policies required")
        r = await self._row(pid, lock=True)
        if r.status != "approved":
            raise rule("Only approved policies are superseded", "NOT_APPROVED")
        await self._supersede(r.id, by_policy_id)
        await self.db.refresh(r)
        return (await self.outs([r]))[0]

    async def acknowledge(self, pid: uuid.UUID) -> PolicyOut:
        if self.actor_id is None:
            raise forbidden("A signed-in user acknowledges")
        r = await self._row(pid)
        m = await self.meta("policy", r.id)
        if not m.get("published") or r.status != "approved":
            raise rule("The policy is not published", "NOT_PUBLISHED")
        acks = await self.meta("policy_ack", r.id)
        if str(self.actor_id) not in acks:
            acks[str(self.actor_id)] = now_utc().isoformat()
            await self.put_meta("policy_ack", r.id, acks)
            await self._emit(
                "policy.acknowledged", {"policy_id": str(r.id), "user_id": str(self.actor_id)}, ENTITY, r.id
            )
        return (await self.outs([r]))[0]

    async def acknowledgements(self, pid: uuid.UUID) -> list[PolicyAckOut]:
        if not (self.manager() or self.reader_all()):
            raise forbidden("governance:policies required")
        r = await self._row(pid)
        acks = await self.meta("policy_ack", r.id)
        names = await self.user_names([uuid.UUID(k) for k in acks])
        return [
            PolicyAckOut(
                user_id=uuid.UUID(k), name=names.get(uuid.UUID(k)), acknowledged_at=datetime.fromisoformat(str(v))
            )
            for k, v in sorted(acks.items(), key=lambda kv: str(kv[1]))
        ]

    async def published_rows(self) -> list[Policy]:
        rows = list(
            (
                await self.db.execute(
                    select(Policy).where(Policy.institution_id == self.inst, Policy.status == "approved")
                )
            ).scalars()
        )
        metas = await self.metas("policy", [str(r.id) for r in rows])
        return [r for r in rows if metas.get(str(r.id), {}).get("published")]

    async def pending_ack(self) -> list[PolicyOut]:
        outs = await self.outs(await self.published_rows())
        return [p for p in outs if p.requires_ack and not p.acknowledged]

    async def public(self) -> list[PolicyOut]:
        outs = await self.outs(await self.published_rows())
        return [p.model_copy(update={"owner_user_id": None, "workflow_instance_id": None}) for p in outs if p.website]

    async def submitted(self) -> list[PolicyOut]:
        rows = list(
            (
                await self.db.execute(
                    select(Policy).where(Policy.institution_id == self.inst, Policy.status == "draft")
                )
            ).scalars()
        )
        metas = await self.metas("policy", [str(r.id) for r in rows])
        return await self.outs([r for r in rows if metas.get(str(r.id), {}).get("stage") == "submitted"])

    async def ack_reminders(self) -> int:
        n = 0
        for p in await self.outs(await self.published_rows()):
            if not p.requires_ack:
                continue
            await self._notify(
                "policy.ack_required",
                [],
                {"title": p.title, "version": p.version},
                audience={"roles": list(AUDIENCE_ROLES)},
            )
            n += 1
        return n


# ---- workflow hooks ------------------------------------------------------------------------------------------------------
def _hook_service(db: Any, instance: Any, actor: Any) -> PolicyService:
    from app.services.governance.meeting_service import _Actor

    return PolicyService(db, _Actor(instance.institution_id, getattr(actor, "id", None)), None, instance.institution_id)


def _register_hooks() -> None:
    from app.core.workflow import engine as workflow_engine

    @workflow_engine.on(WF_KEY, "approved")
    async def _approved(db: Any, instance: Any, actor: Any) -> None:
        if instance.entity_type != ENTITY:
            return
        svc = _hook_service(db, instance, actor)
        r = (await db.execute(select(Policy).where(Policy.id == instance.entity_id).with_for_update())).scalar_one()
        if r.status == "draft":
            await svc.finalise(r)

    @workflow_engine.on(WF_KEY, "rejected")
    async def _rejected(db: Any, instance: Any, actor: Any) -> None:
        if instance.entity_type != ENTITY:
            return
        svc = _hook_service(db, instance, actor)
        r = (await db.execute(select(Policy).where(Policy.id == instance.entity_id))).scalar_one()
        if r.status == "draft":
            await svc.returned(r, "returned in approval")


_register_hooks()
