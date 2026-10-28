"""Self-serve registration and demo requests — Prompts/38 §38.6 ``registration_service`` (Phase 40 forms).

Business rules
1. ``POST /public/registrations`` (captcha + 5 per IP per 10 minutes): slug format / reserved words (422), slug taken
   by an institution or a live registration (409), admin e-mail already used by a user or a live registration (409),
   active plan; row ``pending`` + a verification e-mail with a signed single-use token (sha256 kept in
   ``platform_settings['reg:<id>']`` with the trial flag, history and errors).
2. ``verify`` (token) → ``verified``; a trial (or a free plan) goes straight to provisioning, otherwise the next
   step is ``pay``: a platform gateway order (``order:<id>`` maps the webhook back) → ``paid`` → provisioning.
3. Provisioning (job ``tenant.provision``): ``institution_admin_service.onboard`` with the template of the
   institution type, the chosen plan (trial when asked), the admin from the form → ``provisioned`` +
   ``saas.registration_provisioned`` (login link; the Phase 03 credential mail carries the temporary password, never
   this one) — or ``failed`` with the error (super admin ``retry``).
4. ``expire`` (hourly): ``pending`` / ``verified`` registrations older than ``registration.expiry_hours`` → ``expired``.
5. Super admin list / actions (verify, provision, expire, retry); every transition audited and evented
   (``registration.created|verified|paid|provisioned|failed|expired``).
6. Demo requests: public form (captcha) → ``new`` + an e-mail to ``sales.email``; CRM-lite statuses with notes
   (``platform_settings['demo_req:<id>']``) by the super admin.
"""

import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from app.enums.saas import RESERVED_SLUGS, TYPE_TEMPLATE
from app.models.platform import Institution, User
from app.models.saas import DemoRequest, PendingRegistration, SubscriptionPlan
from app.schemas.saas import (
    DemoRequestIn,
    DemoRequestOut,
    DemoRequestUpdate,
    JobAccepted,
    PublicRegistrationIn,
    PublicRegistrationOut,
    RegistrationAction,
    RegistrationOut,
)
from app.services.saas.common import PlatformBase, conflict, forbidden, not_found, now_utc, rule, unprocessable

LIVE = ("pending", "verified", "paid")


class SystemPlatformActor:
    """Actor of unattended platform work (provisioning a self-serve registration)."""

    id = None
    institution_id = None
    impersonator_id = None
    is_super_admin = True
    roles: list[str] = []
    scopes: list[tuple[str, Any]] = [("institution", None)]

    def has(self, module: str, action: str) -> bool:
        return True


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class RegistrationService(PlatformBase):
    # ---- helpers ------------------------------------------------------------------------------------------------
    async def _row(self, reg_id: uuid.UUID, *, lock: bool = False) -> PendingRegistration:
        q = select(PendingRegistration).where(PendingRegistration.id == reg_id)
        if lock:
            q = q.with_for_update()
        r = (await self.db.execute(q)).scalar_one_or_none()
        if r is None:
            raise not_found("Registration")
        return r

    async def _meta(self, reg_id: uuid.UUID) -> dict[str, Any]:
        return dict(await self.pget(f"reg:{reg_id}", {}) or {})

    async def _history(self, r: PendingRegistration, meta: dict[str, Any], status: str, **extra: Any) -> None:
        old = r.status
        r.status = status
        meta.setdefault("history", []).append({"at": now_utc().isoformat(), "from": old, "to": status, **extra})
        await self.pput(f"reg:{r.id}", meta)
        await self.db.flush()
        await self.audit(
            f"registration_{status}",
            "pending_registration",
            r.id,
            {"slug": r.slug, "from": old, **extra},
            institution_id=r.institution_id,
        )
        await self.emit(
            f"registration.{status}",
            {"registration_id": str(r.id), "slug": r.slug},
            aggregate_type="pending_registration",
            aggregate_id=r.id,
        )

    def _next(self, r: PendingRegistration, meta: dict[str, Any]) -> str:
        return {
            "pending": "verify_email",
            "verified": "provisioning" if meta.get("trial") else "pay",
            "paid": "provisioning",
            "provisioned": "done",
            "failed": "failed",
            "expired": "expired",
        }.get(r.status, r.status)

    async def public_out(self, r: PendingRegistration) -> PublicRegistrationOut:
        from app.core.config import settings

        meta = await self._meta(r.id)
        login = None
        if r.status == "provisioned":
            base = settings.FRONTEND_URL or ""
            login = f"{base}/login?institution={r.slug}"
        return PublicRegistrationOut(id=r.id, status=r.status, next=self._next(r, meta), login_url=login)

    # ---- public (rules 1–2) ---------------------------------------------------------------------------------------
    async def create(self, body: PublicRegistrationIn, ip: str | None) -> PublicRegistrationOut:
        from app.core.rate_limit import verify_captcha

        await verify_captcha(body.captcha_token, ip)
        slug = body.slug.lower()
        if slug in RESERVED_SLUGS:
            raise unprocessable(f"{slug!r} is reserved", field="slug", code="SLUG_RESERVED")
        if (await self.db.execute(select(Institution.id).where(Institution.slug == slug))).first() or (
            await self.db.execute(
                select(PendingRegistration.id).where(
                    PendingRegistration.slug == slug, PendingRegistration.status.in_(LIVE)
                )
            )
        ).first():
            raise conflict(f"{slug!r} is taken", field="slug")
        email = str(body.admin.email).lower()
        if (
            await self.db.execute(select(User.id).where(func.lower(User.email) == email, User.deleted_at.is_(None)))
        ).first() or (
            await self.db.execute(
                select(PendingRegistration.id).where(
                    func.lower(PendingRegistration.admin_email) == email, PendingRegistration.status.in_(LIVE)
                )
            )
        ).first():
            raise conflict("This e-mail is already registered", field="admin.email")
        plan = (
            await self.db.execute(
                select(SubscriptionPlan).where(
                    SubscriptionPlan.code == body.plan_code, SubscriptionPlan.is_active.is_(True)
                )
            )
        ).scalar_one_or_none()
        if plan is None:
            raise unprocessable(f"Unknown plan {body.plan_code!r}", field="plan_code")
        r = PendingRegistration(
            institution_name=body.institution_name,
            institution_type=body.institution_type,
            slug=slug,
            admin_name=body.admin.name,
            admin_email=email,
            admin_phone=body.admin.phone,
            plan_id=plan.id,
            status="pending",
        )
        self.db.add(r)
        await self.db.flush()
        token = secrets.token_urlsafe(24)
        meta = {
            "token_sha256": _hash(token),
            "trial": body.trial or not plan.price_paise_monthly,
            "plan": plan.code,
            "ip": ip,
            "history": [],
        }
        await self.pput(f"reg:{r.id}", meta)
        await self.audit(
            "registration_create",
            "pending_registration",
            r.id,
            {"slug": slug, "type": body.institution_type, "plan": plan.code},
        )
        await self.emit(
            "registration.created",
            {"registration_id": str(r.id), "slug": slug},
            aggregate_type="pending_registration",
            aggregate_id=r.id,
        )
        await self.notify(
            "saas.registration_verify",
            None,
            {"direct_contacts": [{"channel": "email", "to": email, "name": body.admin.name}]},
            {
                "institution": body.institution_name,
                "link": f"/register/verify?id={r.id}&token={token}",
                "hours": await self.setting("registration.expiry_hours"),
            },
            ["email"],
        )
        return await self.public_out(r)

    async def status(self, reg_id: uuid.UUID) -> PublicRegistrationOut:
        return await self.public_out(await self._row(reg_id))

    async def verify(self, reg_id: uuid.UUID, token: str | None, *, manual: bool = False) -> PublicRegistrationOut:
        r = await self._row(reg_id, lock=True)
        meta = await self._meta(r.id)
        if r.status != "pending":
            raise conflict(f"The registration is {r.status}")
        if not manual and (not token or _hash(token) != meta.get("token_sha256")):
            raise forbidden("Invalid or used verification link")
        meta.pop("token_sha256", None)
        meta["verified_at"] = now_utc().isoformat()
        await self._history(r, meta, "verified", manual=manual)
        if meta.get("trial"):
            await self.queue_provision(r)
        return await self.public_out(r)

    async def pay(self, reg_id: uuid.UUID) -> dict[str, Any]:
        from app.services.saas.subscription_service import SubscriptionService

        r = await self._row(reg_id, lock=True)
        meta = await self._meta(r.id)
        if r.status != "verified":
            raise conflict("Verify the e-mail first" if r.status == "pending" else f"The registration is {r.status}")
        if meta.get("trial"):
            raise rule("Trial registrations need no payment")
        plan = (await self.db.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == r.plan_id))).scalar_one()
        billing = await self.setting("billing")
        amount = int(plan.price_paise_yearly or 0)
        total = amount + round(amount * float(billing.get("gst_pct") or 0) / 100)
        order = await SubscriptionService(self.db, None, self.request).gateway_order(
            total, f"REG-{r.slug}", {"kind": "registration", "registration_id": str(r.id)}
        )
        meta["order_id"] = order["order_id"]
        await self.pput(f"reg:{r.id}", meta)
        await self.audit(
            "registration_pay_start",
            "pending_registration",
            r.id,
            {"order_id": order["order_id"], "amount_paise": total},
        )
        return {"registration_id": str(r.id), "order": order, "amount_paise": total}

    async def paid(self, reg_id: uuid.UUID, payment_ref: str) -> dict[str, Any]:
        r = await self._row(reg_id, lock=True)
        meta = await self._meta(r.id)
        if r.status != "verified":
            return {"registration_id": str(r.id), "status": r.status}
        r.payment_ref = payment_ref
        await self._history(r, meta, "paid", payment_ref=payment_ref)
        await self.queue_provision(r)
        return {"registration_id": str(r.id), "status": r.status}

    async def queue_provision(self, r: PendingRegistration) -> JobAccepted:
        from app.core.jobs import enqueue

        job = await enqueue(
            self.db, self.principal, "tenant.provision", {"registration_id": str(r.id)}, queue="reports"
        )
        meta = await self._meta(r.id)
        meta["job_id"] = str(job.id)
        await self.pput(f"reg:{r.id}", meta)
        return JobAccepted(job_id=job.id, job_type="tenant.provision", detail={"registration_id": str(r.id)})

    # ---- provisioning (rule 3) ------------------------------------------------------------------------------------
    async def provision_now(self, reg_id: uuid.UUID) -> dict[str, Any]:
        from app.schemas.institution import OnboardingAdmin, OnboardingInstitution, OnboardingRequest
        from app.services.saas.institution_admin_service import InstitutionAdminService

        r = await self._row(reg_id, lock=True)
        meta = await self._meta(r.id)
        if r.status not in ("verified", "paid", "failed"):
            raise conflict(f"The registration is {r.status}")
        plan = (await self.db.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == r.plan_id))).scalar_one()
        username = "".join(ch for ch in r.admin_email.split("@")[0] if ch.isalnum() or ch in "._-")[:40] or "admin"
        body = OnboardingRequest(
            institution=OnboardingInstitution(
                name=r.institution_name, slug=r.slug, institution_type=r.institution_type
            ),  # type: ignore[arg-type]
            admin=OnboardingAdmin(
                username=username if len(username) >= 3 else "admin",
                email=r.admin_email,
                display_name=r.admin_name or r.institution_name,
                phone=r.admin_phone,
            ),
            plan_code=plan.code,
            template=TYPE_TEMPLATE.get(r.institution_type, "standalone"),  # type: ignore[arg-type]
            trial=bool(meta.get("trial")),
        )
        try:
            async with self.db.begin_nested():
                result = await InstitutionAdminService(self.db, SystemPlatformActor(), self.request).onboard(body)
        except Exception as exc:  # noqa: BLE001 - recorded on the registration; the super admin retries
            meta["error"] = str(getattr(exc, "message", None) or exc)[:500]
            await self._history(r, meta, "failed", error=meta["error"])
            await self.notify_platform("saas.registration_failed", {"slug": r.slug, "error": meta["error"]})
            await self.notify(
                "saas.registration_failed",
                None,
                {"direct_contacts": [{"channel": "email", "to": r.admin_email, "name": r.admin_name}]},
                {"slug": r.slug, "error": "We could not finish setting up your workspace; our team has been notified."},
                ["email"],
            )
            return {"registration_id": str(r.id), "status": "failed", "error": meta["error"]}
        r.institution_id = result.institution.id
        if r.payment_ref:
            from app.services.saas.subscription_service import SubscriptionService

            subs = SubscriptionService(self.db, None, self.request)
            for doc in await subs.invoices(r.institution_id, _checked=True):
                if doc.status != "paid":
                    await subs._mark_paid(r.institution_id, doc.number, r.payment_ref, now_utc().date())
        meta.pop("error", None)
        await self._history(r, meta, "provisioned", institution_id=str(r.institution_id))
        await self.notify(
            "saas.registration_provisioned",
            None,
            {"direct_contacts": [{"channel": "email", "to": r.admin_email, "name": r.admin_name}]},
            {
                "institution": r.institution_name,
                "login": f"/login?institution={r.slug}",
                "username": result.admin_username,
            },
            ["email"],
        )
        return {"registration_id": str(r.id), "status": "provisioned", "institution_id": str(r.institution_id)}

    # ---- Beat (rule 4) --------------------------------------------------------------------------------------------
    async def expire(self) -> int:
        hours = int(await self.setting("registration.expiry_hours") or 72)
        cutoff = now_utc() - timedelta(hours=hours)
        rows = list(
            (
                await self.db.execute(
                    select(PendingRegistration)
                    .where(
                        PendingRegistration.status.in_(("pending", "verified")), PendingRegistration.created_at < cutoff
                    )
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        for r in rows:
            meta = await self._meta(r.id)
            meta.pop("token_sha256", None)
            await self._history(r, meta, "expired", after_hours=hours)
        return len(rows)

    # ---- platform (rule 5) ------------------------------------------------------------------------------------------
    async def out(self, r: PendingRegistration, plans: dict[uuid.UUID, str]) -> RegistrationOut:
        meta = await self._meta(r.id)
        return RegistrationOut(
            id=r.id,
            institution_name=r.institution_name,
            institution_type=r.institution_type,
            slug=r.slug,
            admin_name=r.admin_name,
            admin_email=self.mask(r.admin_email, "email") or r.admin_email,
            admin_phone=self.mask(r.admin_phone, "phone"),
            plan=plans.get(r.plan_id) if r.plan_id else None,
            trial=bool(meta.get("trial")),
            status=r.status,
            payment_ref=r.payment_ref,
            institution_id=r.institution_id,
            error=meta.get("error"),
            history=list(meta.get("history") or []),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )

    async def list_registrations(self, status: str | None = None) -> list[RegistrationOut]:
        self.require_platform("platform", "view")
        q = select(PendingRegistration).order_by(PendingRegistration.created_at.desc()).limit(500)
        if status:
            q = q.where(PendingRegistration.status == status)
        rows = list((await self.db.execute(q)).scalars())
        plans = await self._plan_codes()
        return [await self.out(r, plans) for r in rows]

    async def action(self, reg_id: uuid.UUID, body: RegistrationAction) -> RegistrationOut:
        self.require_super("Registration actions")
        r = await self._row(reg_id, lock=True)
        if body.action == "verify":
            await self.verify(r.id, None, manual=True)
        elif body.action in ("provision", "retry"):
            if body.action == "retry" and r.status != "failed":
                raise conflict("Only failed registrations are retried")
            if body.action == "provision" and r.status not in ("verified", "paid"):
                raise conflict(f"The registration is {r.status}")
            await self.queue_provision(r)
            await self.audit(f"registration_{body.action}", "pending_registration", r.id, {"note": body.note})
        elif body.action == "expire":
            if r.status not in LIVE + ("failed",):
                raise conflict(f"The registration is {r.status}")
            await self._history(r, await self._meta(r.id), "expired", manual=True, note=body.note)
        plans = await self._plan_codes()
        return await self.out(r, plans)

    async def _plan_codes(self) -> dict[uuid.UUID, str]:
        rows = (await self.db.execute(select(SubscriptionPlan.id, SubscriptionPlan.code))).all()
        return {r[0]: str(r[1]) for r in rows}

    # ---- demo requests (rule 6) -------------------------------------------------------------------------------------
    async def demo_create(self, body: DemoRequestIn, ip: str | None) -> DemoRequestOut:
        from app.core.rate_limit import verify_captcha

        await verify_captcha(body.captcha_token, ip)
        d = DemoRequest(
            name=body.name,
            institution_name=body.institution_name,
            email=str(body.email).lower(),
            phone=body.phone,
            institution_type=body.institution_type,
            message=body.message,
            status="new",
        )
        self.db.add(d)
        await self.db.flush()
        await self.audit("demo_request_create", "demo_request", d.id, {"institution": body.institution_name})
        await self.emit(
            "demo_request.created", {"demo_request_id": str(d.id)}, aggregate_type="demo_request", aggregate_id=d.id
        )
        sales = await self.setting("sales.email")
        if sales:
            await self.notify(
                "saas.demo_requested",
                None,
                {"direct_contacts": [{"channel": "email", "to": sales, "name": "Sales"}]},
                {
                    "name": body.name,
                    "institution": body.institution_name or "—",
                    "email": str(body.email),
                    "phone": body.phone or "—",
                    "message": body.message or "",
                },
                ["email"],
            )
        return await self.demo_out(d)

    async def demo_out(self, d: DemoRequest) -> DemoRequestOut:
        meta = await self.pget(f"demo_req:{d.id}", {}) or {}
        return DemoRequestOut(
            id=d.id,
            name=d.name,
            institution_name=d.institution_name,
            email=self.mask(d.email, "email"),
            phone=self.mask(d.phone, "phone"),
            institution_type=d.institution_type,
            message=d.message,
            status=d.status,
            notes=list(meta.get("notes") or []),
            owner=meta.get("owner"),
            created_at=d.created_at,
        )

    async def demo_list(self, status: str | None = None) -> list[DemoRequestOut]:
        self.require_platform("platform", "view")
        q = select(DemoRequest).order_by(DemoRequest.created_at.desc()).limit(1000)
        if status:
            q = q.where(DemoRequest.status == status)
        return [await self.demo_out(d) for d in (await self.db.execute(q)).scalars()]

    async def demo_update(self, demo_id: uuid.UUID, body: DemoRequestUpdate) -> DemoRequestOut:
        self.require_super("Updating demo requests")
        d = (
            await self.db.execute(select(DemoRequest).where(DemoRequest.id == demo_id).with_for_update())
        ).scalar_one_or_none()
        if d is None:
            raise not_found("Demo request")
        old = d.status
        d.status = body.status
        meta = dict(await self.pget(f"demo_req:{d.id}", {}) or {})
        meta["owner"] = meta.get("owner") or str(self.actor_id)
        if body.notes or old != body.status:
            meta.setdefault("notes", []).append(
                {"at": now_utc().isoformat(), "by": str(self.actor_id), "status": body.status, "text": body.notes}
            )
        await self.pput(f"demo_req:{d.id}", meta)
        await self.db.flush()
        await self.audit("demo_request_update", "demo_request", d.id, {"from": old, "to": d.status})
        await self.emit(
            "demo_request.updated",
            {"demo_request_id": str(d.id), "status": d.status},
            aggregate_type="demo_request",
            aggregate_id=d.id,
        )
        return await self.demo_out(d)


__all__ = ["RegistrationService", "SystemPlatformActor"]
