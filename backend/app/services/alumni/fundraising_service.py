"""Fundraising, donations & 80G — Prompts/29 §29.6 ``fundraising_service`` {alumni.fundraising, alumni.donations_80g}.

1. **Campaigns** with goal / progress, purpose, period and the restricted-fund flag (+ optional ledger account) —
   restricted donations post to the Phase 23 restricted fund; milestone notifications at 25 / 50 / 75 / 100 % (on
   each donation and the hourly Beat). A closed campaign refuses donations (409 ``CAMPAIGN_CLOSED``).
2. **Donations**: *online* through the Phase 12 gateway — an ``intent:<id>`` side-store row, a one-item invoice
   (``payer_type`` alumni / individual / company, ``source_type='donation'``, ``source_id`` = intent) and
   ``PaymentService.initiate``; the ``fees.payment_received(source_type=donation)`` consumer turns the settled intent
   into the ``donations`` row. Minimum ``fundraising.min_online_paise`` (422), ``Idempotency-Key`` replays return the
   same order. *Offline* (bank transfer / cheque / cash / UPI) recorded by the coordinator or accountant with a
   reference. Anonymous donations hide the donor on public / campaign views. Every donation updates ``raised_paise``
   under ``FOR UPDATE``, thanks the donor and emits ``alumni.donation_received`` → Phase 23 income (general or
   restricted fund).
3. **80G** (``alumni.donations_80g``): PAN encrypted at rest (``pan_encrypted``), required above
   ``fundraising.pan_threshold_paise`` (422 ``PAN_REQUIRED``), cash above ₹2,000 never qualifies; the receipt number
   comes from the per-FY counter (``fundraising.receipt_sequence`` = ``80g:{fy}``), the Phase 26 template
   ``donation_receipt_80g`` renders it with the institution's 80G registration / signatory → ``receipt_document_id``;
   reissue (corrected name / address / PAN) supersedes the old document and keeps the number; the 80G register and
   the Form 10BD-style donor-wise statement for a financial year.
4. **Donor CRM-lite**: donor page (all donations, receipts, campaigns, CSR references) keyed ``alumni:<id>`` /
   ``email:<sha>`` / ``name:<slug>``. Refunds (rare, audited) reverse ``raised_paise`` and emit
   ``alumni.donation_refunded``; the money goes back through the Phase 12 refund desk for online payments.
"""

import hashlib
import re
import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.core.security import decrypt_secret, encrypt_secret
from app.enums.alumni import CASH_80G_LIMIT_PAISE, MILESTONES, PAN_THRESHOLD_PAISE
from app.models.alumni import AlumniProfile, Donation, FundraisingCampaign
from app.schemas.alumni import (
    CampaignIn,
    CampaignOut,
    CampaignUpdate,
    DonationCreate,
    DonationOut,
    DonationRefund,
    DonorPage,
    OnlineDonateRequest,
    OnlineDonateResponse,
    Receipt80GOut,
    Receipt80GReissue,
    Register80GRow,
)
from app.services.alumni.common import (
    AlumniBase,
    financial_year,
    forbidden,
    mask_pan,
    not_found,
    now_utc,
    rule,
    rupees,
)

ENTITY = "donation"
CAMPAIGN = "fundraising_campaign"


def donor_key(donor_type: str, ref: dict[str, Any]) -> str:
    if ref.get("alumni_id"):
        return f"alumni:{ref['alumni_id']}"
    if ref.get("email"):
        return "email:" + hashlib.sha256(str(ref["email"]).lower().encode()).hexdigest()[:16]
    slug = re.sub(r"[^a-z0-9]+", "-", str(ref.get("organisation") or ref.get("name") or "anonymous").lower()).strip("-")
    return f"{'org' if donor_type == 'corporate' else 'name'}:{slug[:40]}"


def amount_words(paise: int) -> str:
    """Indian-system words for a rupee amount (receipts)."""
    ones = [
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
    ]
    tens = ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

    def two(n: int) -> str:
        return ones[n] if n < 20 else tens[n // 10] + (f"-{ones[n % 10]}" if n % 10 else "")

    def three(n: int) -> str:
        h, r = divmod(n, 100)
        return (f"{ones[h]} hundred" + (f" {two(r)}" if r else "")) if h else two(r)

    rupee = paise // 100
    if rupee == 0:
        return "Zero rupees only"
    parts: list[str] = []
    for div, label in ((10**7, "crore"), (10**5, "lakh"), (1000, "thousand")):
        q, rupee = divmod(rupee, div)
        if q:
            parts.append(f"{three(q) if q < 1000 else str(q)} {label}")
    if rupee:
        parts.append(three(rupee))
    return (" ".join(parts) + " rupees only").capitalize()


class FundraisingService(AlumniBase):
    audit_module = "fundraising"
    module = "fundraising"

    # ---- roles ----------------------------------------------------------------------------------------------------------
    def manager(self) -> bool:
        return (
            self.principal is None
            or self.can("fundraising", "manage")
            or self.can("alumni", "campaign")
            or self.can("alumni", "manage")
        )

    def reader(self, module: str | None = None) -> bool:  # noqa: ARG002 - FacilitiesBase signature
        return (
            self.manager()
            or any(self.can("fundraising", a) for a in ("view_all", "receipt"))
            or self.can("accounting", "view")
        )

    def require_manager(self) -> None:
        self.require_writer()
        if not self.manager():
            raise forbidden("alumni:campaign|fundraising:manage required")

    def require_receipt(self) -> None:
        self.require_writer()
        if not (self.can("fundraising", "receipt") or self.can("fundraising", "manage")):
            raise forbidden("fundraising:receipt required")

    # ---- campaigns --------------------------------------------------------------------------------------------------------------
    async def campaign_outs(self, rows: list[FundraisingCampaign]) -> list[CampaignOut]:
        ids = [c.id for c in rows]
        metas = await self.metas("campaign", [str(i) for i in ids])
        donors: dict[uuid.UUID, int] = {}
        mix: dict[uuid.UUID, dict[str, int]] = {}
        if ids:
            for cid, dtype, n in (
                await self.db.execute(
                    select(Donation.campaign_id, Donation.donor_type, func.count())
                    .where(Donation.campaign_id.in_(ids))
                    .group_by(Donation.campaign_id, Donation.donor_type)
                )
            ).all():
                donors[cid] = donors.get(cid, 0) + int(n)
                mix.setdefault(cid, {})[dtype] = int(n)
        out: list[CampaignOut] = []
        for c in rows:
            m = metas.get(str(c.id), {})
            out.append(
                CampaignOut(
                    id=c.id,
                    title=c.title,
                    purpose=c.purpose,
                    goal_paise=c.goal_paise,
                    raised_paise=c.raised_paise,
                    donors_count=donors.get(c.id, 0),
                    progress_pct=min(100, int(100 * c.raised_paise / c.goal_paise)) if c.goal_paise else 0,
                    from_on=c.from_on,
                    to_on=c.to_on,
                    status=c.status,
                    is_restricted_fund=bool(m.get("is_restricted_fund")),
                    ledger_account_id=uuid.UUID(m["ledger_account_id"]) if m.get("ledger_account_id") else None,
                    is_public=m.get("is_public", True) is not False,
                    milestones_reached=list(m.get("milestones") or []),
                    donor_mix=mix.get(c.id, {}),
                    created_at=c.created_at,
                )
            )
        return out

    async def campaign(self, cid: uuid.UUID, *, lock: bool = False) -> FundraisingCampaign:
        stmt = select(FundraisingCampaign).where(
            FundraisingCampaign.id == cid, FundraisingCampaign.institution_id == self.inst
        )
        if lock:
            stmt = stmt.with_for_update()
        c = (await self.db.execute(stmt)).scalar_one_or_none()
        if c is None:
            raise not_found("Campaign")
        return c

    async def list_campaigns(self, status: str | None = None) -> list[CampaignOut]:
        stmt = select(FundraisingCampaign).where(FundraisingCampaign.institution_id == self.inst)
        if not self.reader():
            stmt = stmt.where(FundraisingCampaign.status.in_(("active", "closed")))
        if status:
            stmt = stmt.where(FundraisingCampaign.status == status)
        return await self.campaign_outs(
            list((await self.db.execute(stmt.order_by(FundraisingCampaign.created_at.desc()))).scalars())
        )

    async def public_campaigns(self) -> list[CampaignOut]:
        rows = list(
            (
                await self.db.execute(
                    select(FundraisingCampaign).where(
                        FundraisingCampaign.institution_id == self.inst, FundraisingCampaign.status == "active"
                    )
                )
            ).scalars()
        )
        outs = await self.campaign_outs(rows)
        return [o.model_copy(update={"ledger_account_id": None, "donor_mix": {}}) for o in outs if o.is_public]

    async def get_campaign(self, cid: uuid.UUID) -> CampaignOut:
        c = await self.campaign(cid)
        if c.status in ("draft", "archived") and not self.reader():
            raise not_found("Campaign")
        return (await self.campaign_outs([c]))[0]

    async def create_campaign(self, body: CampaignIn) -> CampaignOut:
        self.require_manager()
        c = FundraisingCampaign(
            institution_id=self.inst,
            title=body.title,
            purpose=body.purpose,
            goal_paise=body.goal_paise,
            from_on=body.from_on,
            to_on=body.to_on,
            status=body.status,
        )
        self.db.add(c)
        await self.db.flush()
        await self.put_meta(
            "campaign",
            c.id,
            {
                "is_restricted_fund": body.is_restricted_fund,
                "ledger_account_id": str(body.ledger_account_id) if body.ledger_account_id else None,
                "is_public": body.is_public,
                "milestones": [],
            },
        )
        await self._audit("create", CAMPAIGN, c.id, None, body.model_dump(mode="json"))
        await self._emit(
            "campaign.created",
            {"campaign_id": str(c.id), "restricted": body.is_restricted_fund, "goal_paise": c.goal_paise},
            CAMPAIGN,
            c.id,
        )
        return (await self.campaign_outs([c]))[0]

    async def update_campaign(self, cid: uuid.UUID, body: CampaignUpdate) -> CampaignOut:
        self.require_manager()
        c = await self.campaign(cid, lock=True)
        if c.status == "closed" and body.status != "archived":
            raise rule("A closed campaign is only archived", "CAMPAIGN_CLOSED")
        data = body.model_dump(exclude_unset=True)
        m = await self.meta("campaign", c.id)
        for k in ("is_restricted_fund", "is_public"):
            if k in data:
                m[k] = data.pop(k)
        if "ledger_account_id" in data:
            v = data.pop("ledger_account_id")
            m["ledger_account_id"] = str(v) if v else None
        for k, v in data.items():
            setattr(c, k, v)
        await self.put_meta("campaign", c.id, m)
        await self._audit("update", CAMPAIGN, c.id, None, body.model_dump(mode="json", exclude_unset=True))
        return (await self.campaign_outs([c]))[0]

    async def close_campaign(self, cid: uuid.UUID) -> CampaignOut:
        self.require_manager()
        c = await self.campaign(cid, lock=True)
        if c.status == "closed":
            raise rule("The campaign is already closed", "CAMPAIGN_CLOSED")
        c.status = "closed"
        c.to_on = c.to_on or await self.today()
        m = await self.meta("campaign", c.id)
        m["closed_at"] = now_utc().isoformat()
        await self.put_meta("campaign", c.id, m)
        await self._audit("close", CAMPAIGN, c.id, None, {"raised_paise": c.raised_paise})
        await self._emit("campaign.closed", {"campaign_id": str(c.id), "raised_paise": c.raised_paise}, CAMPAIGN, c.id)
        return (await self.campaign_outs([c]))[0]

    async def milestones(self, c: FundraisingCampaign) -> list[int]:
        if not c.goal_paise:
            return []
        m = await self.meta("campaign", c.id)
        reached = set(m.get("milestones") or [])
        pct = 100 * c.raised_paise / c.goal_paise
        new = [x for x in MILESTONES if pct >= x and x not in reached]
        if not new:
            return []
        m["milestones"] = sorted(reached | set(new))
        await self.put_meta("campaign", c.id, m)
        staff = await self.role_users("alumni_coordinator")
        for x in new:
            await self._emit("campaign.milestone", {"campaign_id": str(c.id), "pct": x}, CAMPAIGN, c.id)
            await self._notify(
                "campaign.milestone", staff, {"campaign": c.title, "pct": x, "raised": rupees(c.raised_paise)}
            )
        return new

    async def milestone_check(self) -> int:
        n = 0
        for c in (
            await self.db.execute(
                select(FundraisingCampaign).where(
                    FundraisingCampaign.institution_id == self.inst, FundraisingCampaign.status == "active"
                )
            )
        ).scalars():
            n += len(await self.milestones(c))
            if c.to_on and c.to_on < await self.today():
                c.status = "closed"
                await self._emit("campaign.closed", {"campaign_id": str(c.id), "auto": True}, CAMPAIGN, c.id)
        return n

    # ---- donation outputs / visibility --------------------------------------------------------------------------------------------
    async def outs(self, rows: list[Donation], *, full: bool = True) -> list[DonationOut]:
        cids = list({d.campaign_id for d in rows if d.campaign_id})
        titles: dict[uuid.UUID, str] = (
            dict(
                (
                    await self.db.execute(
                        select(FundraisingCampaign.id, FundraisingCampaign.title).where(
                            FundraisingCampaign.id.in_(cids)
                        )
                    )
                )
                .tuples()
                .all()
            )
            if cids
            else {}
        )
        metas = await self.metas("donation", [str(d.id) for d in rows])
        out: list[DonationOut] = []
        for d in rows:
            ref, m = dict(d.donor_ref or {}), metas.get(str(d.id), {})
            anonymous = bool(ref.get("anonymous"))
            pan = None
            if d.pan_encrypted:
                try:
                    pan = decrypt_secret(d.pan_encrypted)
                except Exception:  # noqa: BLE001 - key rotation / corrupt blob → show nothing
                    pan = None
            out.append(
                DonationOut(
                    id=d.id,
                    donor_type=d.donor_type,
                    donor_name=("Anonymous" if anonymous and not full else ref.get("organisation") or ref.get("name"))
                    or "Donor",
                    donor_key=donor_key(d.donor_type, ref),
                    anonymous=anonymous,
                    alumni_id=uuid.UUID(ref["alumni_id"]) if ref.get("alumni_id") else None,
                    campaign_id=d.campaign_id,
                    campaign=titles.get(d.campaign_id) if d.campaign_id else "General fund",
                    amount_paise=d.amount_paise,
                    on_date=d.on_date,
                    mode=d.mode,
                    reference=m.get("reference") if full else None,
                    is_80g=d.is_80g,
                    wants_80g=bool(m.get("wants_80g")),
                    pan_masked=mask_pan(pan),
                    receipt_no=d.receipt_no,
                    receipt_document_id=d.receipt_document_id,
                    receipt_url=f"/documents/issued/{d.receipt_document_id}/pdf" if d.receipt_document_id else None,
                    refunded=bool(m.get("refund")),
                    refund=m.get("refund") if full else None,
                    created_at=d.created_at,
                )
            )
        return out

    async def _mine_predicate(self) -> Any:
        me = await self.my_profile()
        parts = []
        if me is not None:
            parts.append(Donation.donor_ref["alumni_id"].astext == str(me.id))
        if self.actor_id is not None:
            parts.append(Donation.donor_ref["user_id"].astext == str(self.actor_id))
        if not parts:
            return None
        from sqlalchemy import or_

        return or_(*parts)

    async def donation(self, did: uuid.UUID, *, lock: bool = False) -> Donation:
        stmt = select(Donation).where(Donation.id == did, Donation.institution_id == self.inst)
        if not self.reader():
            pred = await self._mine_predicate()
            if pred is None:
                raise not_found("Donation")
            stmt = stmt.where(pred)
        if lock:
            stmt = stmt.with_for_update()
        d = (await self.db.execute(stmt)).scalar_one_or_none()
        if d is None:
            raise not_found("Donation")
        return d

    async def list_donations(
        self,
        *,
        campaign_id: uuid.UUID | None = None,
        donor_type: str | None = None,
        mode: str | None = None,
        fy: str | None = None,
        limit: int = 500,
    ) -> list[DonationOut]:
        if not self.reader():
            raise forbidden("fundraising:manage|receipt|accounting:view required")
        stmt = select(Donation).where(Donation.institution_id == self.inst)
        if campaign_id:
            stmt = stmt.where(Donation.campaign_id == campaign_id)
        if donor_type:
            stmt = stmt.where(Donation.donor_type == donor_type)
        if mode:
            stmt = stmt.where(Donation.mode == mode)
        if fy:
            start, end = self.fy_bounds(fy)
            stmt = stmt.where(Donation.on_date >= start, Donation.on_date <= end)
        rows = list((await self.db.execute(stmt.order_by(Donation.on_date.desc()).limit(limit))).scalars())
        return await self.outs(rows)

    async def get_donation(self, did: uuid.UUID) -> DonationOut:
        return (await self.outs([await self.donation(did)], full=self.reader()))[0]

    async def mine(self) -> list[DonationOut]:
        pred = await self._mine_predicate()
        if pred is None:
            raise forbidden("No donor identity for the caller")
        rows = list(
            (
                await self.db.execute(
                    select(Donation).where(Donation.institution_id == self.inst, pred).order_by(Donation.on_date.desc())
                )
            ).scalars()
        )
        return await self.outs(rows)

    async def donor_page(self, key: str) -> DonorPage:
        if not self.reader():
            raise forbidden("fundraising:manage|receipt required")
        rows = [
            d
            for d in (await self.db.execute(select(Donation).where(Donation.institution_id == self.inst))).scalars()
            if donor_key(d.donor_type, d.donor_ref or {}) == key
        ]
        if not rows:
            raise not_found("Donor")
        outs = await self.outs(sorted(rows, key=lambda d: d.on_date, reverse=True))
        ref = dict(rows[0].donor_ref or {})
        return DonorPage(
            donor_key=key,
            donor_type=rows[0].donor_type,
            name=ref.get("organisation") or ref.get("name") or "Donor",
            email=ref.get("email"),
            organisation=ref.get("organisation"),
            csr_references=sorted(
                {str(d.donor_ref.get("csr_reference")) for d in rows if d.donor_ref.get("csr_reference")}
            ),
            total_paise=sum(d.amount_paise for d in rows if not o_refunded(outs, d.id)),
            donations=outs,
            campaigns=sorted({o.campaign or "General fund" for o in outs}),
        )

    # ---- recording ---------------------------------------------------------------------------------------------------------------------
    async def _donor_ref(self, donor_type: str, ref: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in ref.items() if k != "pan" and v not in (None, "")}
        if donor_type == "alumni" and ref.get("alumni_id"):
            a = (
                await self.db.execute(
                    select(AlumniProfile).where(
                        AlumniProfile.id == uuid.UUID(str(ref["alumni_id"])),
                        AlumniProfile.institution_id == self.inst,
                    )
                )
            ).scalar_one_or_none()
            if a is None:
                raise not_found("Alumni profile")
            card = (await self.cards([a])).get(a.id, {})
            out.setdefault("name", card.get("name"))
            out.setdefault("email", a.email)
            out.setdefault("phone", a.phone)
            out["alumni_id"] = str(a.id)
            if a.user_id:
                out["user_id"] = str(a.user_id)
        return out

    async def _check_80g(self, wants: bool, pan: str | None, amount: int, mode: str) -> None:
        if not wants:
            return
        if not await self.feature("alumni.donations_80g"):
            raise APIError(
                403, ErrorCode.FEATURE_DISABLED, "80G receipts are not enabled", {"feature": "alumni.donations_80g"}
            )
        if mode == "cash" and amount > CASH_80G_LIMIT_PAISE:
            raise rule("Cash donations above Rs. 2,000 do not qualify for 80G", "CASH_80G_LIMIT", 422)
        threshold = await self.int_setting("fundraising", "pan_threshold_paise", PAN_THRESHOLD_PAISE)
        if not pan and amount > threshold:
            raise rule("PAN is required for an 80G receipt above the threshold", "PAN_REQUIRED", 422)

    async def record(
        self,
        *,
        donor_type: str,
        donor_ref: dict[str, Any],
        campaign_id: uuid.UUID | None,
        amount: int,
        mode: str,
        on: date,
        pan: str | None,
        wants_80g: bool,
        reference: str | None,
        extra: dict[str, Any] | None = None,
    ) -> Donation:
        """The single write path (offline desk and the online consumer)."""
        c = None
        if campaign_id is not None:
            c = await self.campaign(campaign_id, lock=True)  # FOR UPDATE on raised_paise
            if c.status != "active":
                raise rule("The campaign is not accepting donations", "CAMPAIGN_CLOSED")
        d = Donation(
            institution_id=self.inst,
            donor_type=donor_type,
            donor_ref=donor_ref,
            campaign_id=campaign_id,
            amount_paise=amount,
            on_date=on,
            mode=mode,
            is_80g=False,
            pan_encrypted=encrypt_secret(pan) if pan else None,
        )
        self.db.add(d)
        await self.db.flush()
        if c is not None:
            c.raised_paise = int(c.raised_paise or 0) + amount
        await self.put_meta(
            "donation",
            d.id,
            {
                "reference": reference,
                "wants_80g": wants_80g,
                "recorded_by": str(self.actor_id) if self.actor_id else None,
                **(extra or {}),
            },
        )
        restricted = False
        ledger = None
        if c is not None:
            cm = await self.meta("campaign", c.id)
            restricted, ledger = bool(cm.get("is_restricted_fund")), cm.get("ledger_account_id")
        await self._audit(
            "record", ENTITY, d.id, None, {"amount_paise": amount, "mode": mode, "campaign": str(campaign_id)}
        )
        await self._emit(
            "alumni.donation_received",
            {
                "donation_id": str(d.id),
                "amount_paise": amount,
                "received_on": on.isoformat(),
                "restricted": restricted,
                "ledger_account_id": ledger,
                "campaign_id": str(campaign_id) if campaign_id else None,
                "donor_type": donor_type,
                "alumni_id": donor_ref.get("alumni_id"),
            },
            ENTITY,
            d.id,
        )
        uid = donor_ref.get("user_id")
        audience = (
            {"user_ids": [uid]} if uid else ({"emails": [donor_ref["email"]]} if donor_ref.get("email") else None)
        )
        if audience:
            await self._notify(
                "donation.thank_you",
                [],
                {"amount": rupees(amount), "campaign": c.title if c else "the general fund"},
                audience=audience,
            )
        if c is not None:
            await self.milestones(c)
        if wants_80g and await self.feature("alumni.donations_80g"):
            await self.issue_receipt(d.id, system=True)
        return d

    async def record_offline(self, body: DonationCreate) -> DonationOut:
        self.require_writer()
        if not (self.manager() or self.can("fundraising", "receipt")):
            raise forbidden("fundraising:manage|receipt required")
        if body.mode != "cash" and not body.reference:
            raise APIError(
                422, ErrorCode.VALIDATION, "A reference (UTR / cheque no.) is required", {"field": "reference"}
            )
        pan = body.donor_ref.pan
        await self._check_80g(body.wants_80g, pan, body.amount_paise, body.mode)
        ref = await self._donor_ref(body.donor_type, body.donor_ref.model_dump(mode="json"))
        d = await self.record(
            donor_type=body.donor_type,
            donor_ref=ref,
            campaign_id=body.campaign_id,
            amount=body.amount_paise,
            mode=body.mode,
            on=body.on_date,
            pan=pan,
            wants_80g=body.wants_80g,
            reference=body.reference,
        )
        return (await self.outs([d]))[0]

    # ---- online ----------------------------------------------------------------------------------------------------------------------------
    async def donate_online(self, body: OnlineDonateRequest, idem: str | None) -> OnlineDonateResponse:
        from app.schemas.fees import InvoiceCreate, InvoiceItemIn, OnlineInitiateRequest
        from app.services.fees.invoice_service import InvoiceService
        from app.services.fees.payment_service import PaymentService

        if idem:
            prior = await self.meta("idem", hashlib.sha256(idem.encode()).hexdigest()[:32])
            if prior.get("intent_id"):
                intent = await self.meta("intent", prior["intent_id"])
                return OnlineDonateResponse(
                    intent_id=uuid.UUID(prior["intent_id"]),
                    order=intent.get("order") or {},
                    checkout=intent.get("checkout") or {},
                    replayed=True,
                )
        minimum = await self.int_setting("fundraising", "min_online_paise", 10000)
        if body.amount_paise < minimum:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"The minimum online donation is Rs. {rupees(minimum)}",
                {"code": "BELOW_MINIMUM", "min_paise": minimum},
            )
        if body.campaign_id:
            c = await self.campaign(body.campaign_id)
            if c.status != "active":
                raise rule("The campaign is not accepting donations", "CAMPAIGN_CLOSED")
        me = await self.my_profile()
        donor_type = body.donor_type or ("alumni" if me else "individual")
        await self._check_80g(body.wants_80g, body.donor.pan, body.amount_paise, "online")
        raw = body.donor.model_dump(mode="json")
        if me is not None:
            raw["alumni_id"] = str(me.id)
            donor_type = "alumni" if donor_type == "individual" else donor_type
        elif self.actor_id is not None:
            raw["user_id"] = str(self.actor_id)
        if not me and not raw.get("name"):
            raise APIError(422, ErrorCode.VALIDATION, "donor.name is required", {"field": "donor.name"})
        ref = await self._donor_ref(donor_type, raw) if me else {k: v for k, v in raw.items() if k != "pan" and v}
        intent_id = uuid.uuid4()
        payer_type = {"alumni": "alumni", "corporate": "company"}.get(donor_type, "individual")
        inv = await InvoiceService(self.db, None, None, self.inst).create_invoice(
            InvoiceCreate(
                payer_type=payer_type,
                payer_id=me.id if me else intent_id,
                source_type="donation",
                source_id=intent_id,
                description="Donation",
                items=[InvoiceItemIn(description="Donation", amount_paise=body.amount_paise)],
                due_date=await self.today(),
            ),
            notify=False,
        )
        init = await PaymentService(self.db, None, None, self.inst).initiate(
            OnlineInitiateRequest(invoice_ids=[inv.id])
        )
        order = {"order_id": init.order_id, "gateway": init.gateway, "key": init.key, "amount": init.amount}
        await self.put_meta(
            "intent",
            intent_id,
            {
                "status": "initiated",
                "donor_type": donor_type,
                "donor_ref": ref,
                "pan": encrypt_secret(body.donor.pan).hex() if body.donor.pan else None,
                "campaign_id": str(body.campaign_id) if body.campaign_id else None,
                "amount_paise": body.amount_paise,
                "wants_80g": body.wants_80g,
                "invoice_id": str(inv.id),
                "order": order,
                "checkout": init.checkout,
            },
        )
        if idem:
            await self.put_meta("idem", hashlib.sha256(idem.encode()).hexdigest()[:32], {"intent_id": str(intent_id)})
        await self._audit(
            "online_initiate", ENTITY, None, None, {"intent_id": str(intent_id), "order_id": init.order_id}
        )
        return OnlineDonateResponse(intent_id=intent_id, order=order, checkout=init.checkout)

    async def on_payment(self, payload: dict[str, Any]) -> Donation | None:
        """``fees.payment_received(source_type=donation)`` → the donations row (idempotent on the intent)."""
        sid = payload.get("source_id")
        if not sid:
            return None
        row = await self._meta_row("intent", sid)
        intent = dict(row.value) if row is not None and isinstance(row.value, dict) else {}
        if not intent or intent.get("status") == "settled":
            return None
        pan = decrypt_secret(bytes.fromhex(intent["pan"])) if intent.get("pan") else None
        intent["status"] = "settled"
        await self.put_meta("intent", sid, intent)
        try:
            d = await self.record(
                donor_type=intent.get("donor_type") or "individual",
                donor_ref=dict(intent.get("donor_ref") or {}),
                campaign_id=uuid.UUID(intent["campaign_id"]) if intent.get("campaign_id") else None,
                amount=int(payload.get("amount_paise") or intent.get("amount_paise") or 0),
                mode="online",
                on=await self.today(),
                pan=pan,
                wants_80g=bool(intent.get("wants_80g")),
                reference=payload.get("receipt_no"),
                extra={
                    "intent_id": str(sid),
                    "payment_id": payload.get("payment_id"),
                    "invoice_id": payload.get("invoice_id"),
                },
            )
        except APIError:
            # campaign closed between initiation and settlement: book to the general fund
            d = await self.record(
                donor_type=intent.get("donor_type") or "individual",
                donor_ref=dict(intent.get("donor_ref") or {}),
                campaign_id=None,
                amount=int(payload.get("amount_paise") or intent.get("amount_paise") or 0),
                mode="online",
                on=await self.today(),
                pan=pan,
                wants_80g=bool(intent.get("wants_80g")),
                reference=payload.get("receipt_no"),
                extra={"intent_id": str(sid), "payment_id": payload.get("payment_id"), "rebooked": True},
            )
        intent["donation_id"] = str(d.id)
        await self.put_meta("intent", sid, intent)
        return d

    # ---- refunds ---------------------------------------------------------------------------------------------------------------------------
    async def refund(self, did: uuid.UUID, body: DonationRefund) -> DonationOut:
        self.require_manager()
        d = await self.donation(did, lock=True)
        m = await self.meta("donation", d.id)
        if m.get("refund"):
            raise rule("The donation is already refunded", "ALREADY_REFUNDED")
        amount = body.amount_paise or d.amount_paise
        if amount > d.amount_paise:
            raise APIError(422, ErrorCode.VALIDATION, "Refund exceeds the donation")
        if d.campaign_id:
            c = await self.campaign(d.campaign_id, lock=True)
            c.raised_paise = max(0, int(c.raised_paise or 0) - amount)
        m["refund"] = {
            "amount_paise": amount,
            "reason": body.reason,
            "at": now_utc().isoformat(),
            "by": str(self.actor_id) if self.actor_id else None,
            "payment_id": m.get("payment_id"),
        }
        await self.put_meta("donation", d.id, m)
        if d.receipt_document_id:
            from app.models.documents import IssuedDocument

            doc = (
                await self.db.execute(select(IssuedDocument).where(IssuedDocument.id == d.receipt_document_id))
            ).scalar_one_or_none()
            if doc is not None and doc.revoked_at is None:
                doc.revoked_at, doc.revoke_reason = now_utc(), f"Donation refunded: {body.reason}"[:200]
        await self._audit("refund", ENTITY, d.id, None, m["refund"])
        await self._emit(
            "alumni.donation_refunded",
            {"donation_id": str(d.id), "amount_paise": amount, "payment_id": m.get("payment_id")},
            ENTITY,
            d.id,
        )
        return (await self.outs([d]))[0]

    # ---- 80G ---------------------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def fy_bounds(fy: str) -> tuple[date, date]:
        try:
            start = int(fy.split("-")[0])
        except (ValueError, IndexError):
            raise APIError(422, ErrorCode.VALIDATION, "fy must look like 2026-27", {"field": "fy"}) from None
        return date(start, 4, 1), date(start + 1, 3, 31)

    async def next_receipt_no(self, on: date) -> str:
        fy = financial_year(on)
        key_tpl = str(await self.setting("fundraising", "receipt_sequence") or "80g:{fy}")
        rid = key_tpl.replace("{fy}", fy).split(":", 1)[-1]
        from app.models.platform import InstitutionSetting

        row = await self._meta_row("seq80g", rid)
        if row is not None:  # serialise receipt numbering on the counter row
            row = (
                await self.db.execute(
                    select(InstitutionSetting).where(InstitutionSetting.id == row.id).with_for_update()
                )
            ).scalar_one()
        n = int((row.value or {}).get("next", 1)) if row is not None and isinstance(row.value, dict) else 1
        await self.put_meta("seq80g", rid, {"next": n + 1})
        return f"80G/{fy}/{n:05d}"

    async def issue_receipt(self, did: uuid.UUID, *, system: bool = False) -> Receipt80GOut:
        if not system:
            self.require_receipt()
        await self.require_feature("alumni.donations_80g")
        d = await self.donation(did, lock=True)
        m = await self.meta("donation", d.id)
        if m.get("refund"):
            raise rule("A refunded donation gets no receipt", "REFUNDED")
        pan = decrypt_secret(d.pan_encrypted) if d.pan_encrypted else None
        await self._check_80g(True, pan, d.amount_paise, d.mode or "online")
        if d.receipt_no and d.receipt_document_id:
            return Receipt80GOut(donation_id=d.id, receipt_no=d.receipt_no, receipt_document_id=d.receipt_document_id)
        d.receipt_no = d.receipt_no or await self.next_receipt_no(d.on_date)
        d.is_80g = True
        doc_id = await self._render(d)
        await self._audit("receipt_80g", ENTITY, d.id, None, {"receipt_no": d.receipt_no})
        await self._emit(
            "donation.receipt_issued", {"donation_id": str(d.id), "receipt_no": d.receipt_no}, ENTITY, d.id
        )
        ref = d.donor_ref or {}
        audience = (
            {"user_ids": [ref["user_id"]]}
            if ref.get("user_id")
            else ({"emails": [ref["email"]]} if ref.get("email") else None)
        )
        if audience:
            await self._notify(
                "donation.receipt_ready",
                [],
                {"receipt_no": d.receipt_no, "amount": rupees(d.amount_paise)},
                audience=audience,
            )
        return Receipt80GOut(donation_id=d.id, receipt_no=d.receipt_no, receipt_document_id=doc_id)

    async def _render(self, d: Donation, *, supersedes: Any = None) -> uuid.UUID | None:
        from app.services.documents.render_service import RenderService

        try:
            res = await RenderService(self.db, None, self.request, self.inst).render(
                "donation_receipt_80g",
                "donation",
                d.id,
                document_number=d.receipt_no,
                supersedes=supersedes,
                issued_by=self.actor_id,
            )
        except APIError as exc:
            m = await self.meta("donation", d.id)
            m["receipt_error"] = getattr(exc, "message", str(exc))[:300]
            await self.put_meta("donation", d.id, m)
            return None
        d.receipt_document_id = res.issued_document_id
        await self.db.flush()
        return res.issued_document_id

    async def reissue(self, did: uuid.UUID, body: Receipt80GReissue) -> Receipt80GOut:
        self.require_receipt()
        await self.require_feature("alumni.donations_80g")
        d = await self.donation(did, lock=True)
        if not d.receipt_no or not d.receipt_document_id:
            raise rule("Issue the receipt first", "NO_RECEIPT")
        from app.models.documents import IssuedDocument

        old = (
            await self.db.execute(select(IssuedDocument).where(IssuedDocument.id == d.receipt_document_id))
        ).scalar_one()
        ref = dict(d.donor_ref or {})
        before = {k: ref.get(k) for k in ("name", "address")}
        if body.donor_name:
            ref["name"] = body.donor_name
        if body.address:
            ref["address"] = body.address
        d.donor_ref = ref
        if body.pan:
            d.pan_encrypted = encrypt_secret(body.pan)
        m = await self.meta("donation", d.id)
        m.setdefault("receipts", []).append(
            {"document_id": str(old.id), "superseded_at": now_utc().isoformat(), "reason": body.reason}
        )
        await self.put_meta("donation", d.id, m)
        await self.db.flush()
        new_id = await self._render(d, supersedes=old)
        await self._audit(
            "receipt_80g_reissue", ENTITY, d.id, before, {**body.model_dump(exclude={"pan"}), "pan": bool(body.pan)}
        )
        return Receipt80GOut(
            donation_id=d.id, receipt_no=d.receipt_no, receipt_document_id=new_id, superseded_document_id=old.id
        )

    async def register(self, fy: str) -> list[Register80GRow]:
        if not (self.can("fundraising", "receipt") or self.reader()):
            raise forbidden("fundraising:receipt required")
        start, end = self.fy_bounds(fy)
        rows = list(
            (
                await self.db.execute(
                    select(Donation)
                    .where(
                        Donation.institution_id == self.inst,
                        Donation.is_80g.is_(True),
                        Donation.on_date >= start,
                        Donation.on_date <= end,
                    )
                    .order_by(Donation.receipt_no)
                )
            ).scalars()
        )
        outs = {o.id: o for o in await self.outs(rows)}
        return [
            Register80GRow(
                donation_id=d.id,
                receipt_no=d.receipt_no,
                on_date=d.on_date,
                donor_name=outs[d.id].donor_name,
                donor_type=d.donor_type,
                pan_masked=outs[d.id].pan_masked,
                address=(d.donor_ref or {}).get("address"),
                mode=d.mode,
                amount_paise=d.amount_paise,
                campaign=outs[d.id].campaign,
            )
            for d in rows
            if not outs[d.id].refunded
        ]

    async def statement_10bd(self, fy: str) -> bytes:
        """Form 10BD-style donor-wise statement (PAN, name, address, donation type, mode, amount) as xlsx."""
        from openpyxl import Workbook

        self.require_receipt()
        start, end = self.fy_bounds(fy)
        rows = list(
            (
                await self.db.execute(
                    select(Donation).where(
                        Donation.institution_id == self.inst,
                        Donation.is_80g.is_(True),
                        Donation.on_date >= start,
                        Donation.on_date <= end,
                    )
                )
            ).scalars()
        )
        metas = await self.metas("donation", [str(d.id) for d in rows])
        agg: dict[tuple[str, str], dict[str, Any]] = {}
        for d in rows:
            if (metas.get(str(d.id)) or {}).get("refund"):
                continue
            pan = decrypt_secret(d.pan_encrypted) if d.pan_encrypted else ""
            ref = d.donor_ref or {}
            mode = "Cash" if d.mode == "cash" else "Electronic modes including account payee cheque/draft"
            key = (pan or donor_key(d.donor_type, ref), mode)
            a = agg.setdefault(
                key,
                {
                    "pan": pan,
                    "name": ref.get("organisation") or ref.get("name") or "",
                    "address": ref.get("address") or "",
                    "type": "Specific grant" if d.campaign_id else "Others",
                    "mode": mode,
                    "amount": 0,
                    "receipts": [],
                },
            )
            a["amount"] += d.amount_paise
            if d.receipt_no:
                a["receipts"].append(d.receipt_no)
        wb = Workbook()
        ws = wb.active
        ws.title = f"10BD {fy}"
        ws.append(
            [
                "Sl",
                "PAN / ID",
                "Name of donor",
                "Address",
                "Donation type",
                "Mode of receipt",
                "Amount (Rs.)",
                "Receipts",
            ]
        )
        for i, a in enumerate(agg.values(), start=1):
            ws.append(
                [
                    i,
                    a["pan"],
                    a["name"],
                    a["address"],
                    a["type"],
                    a["mode"],
                    a["amount"] / 100,
                    ", ".join(a["receipts"]),
                ]
            )
        import io

        buf = io.BytesIO()
        wb.save(buf)
        await self._audit("10bd_export", ENTITY, None, None, {"fy": fy, "donors": len(agg)})
        return buf.getvalue()

    async def pledge_reminders(self) -> int:
        if await self.setting("fundraising", "pledges") is not True:
            return 0
        n = 0
        for key, m in (await self.metas("pledge")).items():
            if m.get("status") != "open":
                continue
            uid = m.get("user_id")
            if uid:
                await self._notify(
                    "alumni.pledge_reminder",
                    [uuid.UUID(uid)],
                    {"amount": rupees(int(m.get("amount_paise") or 0)), "campaign": m.get("campaign") or ""},
                )
                n += 1
            _ = key
        return n


def o_refunded(outs: list[DonationOut], did: uuid.UUID) -> bool:
    return any(o.id == did and o.refunded for o in outs)


# ---- Phase 26 resolver ---------------------------------------------------------------------------------------------------------------
def _register() -> None:
    from app.services.documents.render_service import RenderService, register_resolver

    @register_resolver("donation")
    async def _donation_ctx(svc: RenderService, did: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
        d = (await svc.db.execute(select(Donation).where(Donation.id == did))).scalar_one()
        ref = d.donor_ref or {}
        camp = None
        if d.campaign_id:
            camp = (
                await svc.db.execute(select(FundraisingCampaign.title).where(FundraisingCampaign.id == d.campaign_id))
            ).scalar_one_or_none()
        from app.services.settings_service import SettingsService

        g80 = await SettingsService(svc.db).value(svc.inst, "fundraising", "80g") or {}
        pan = decrypt_secret(d.pan_encrypted) if d.pan_encrypted else ""
        from app.models.platform import InstitutionSetting

        meta = (
            await svc.db.execute(
                select(InstitutionSetting.value).where(
                    InstitutionSetting.institution_id == d.institution_id,
                    InstitutionSetting.category == "alumni_meta",
                    InstitutionSetting.key == f"donation:{d.id}",
                )
            )
        ).scalar_one_or_none()
        meta = meta if isinstance(meta, dict) else {}
        ctx = {
            "donor": {
                "name": ref.get("organisation") or ref.get("name") or "Donor",
                "address": ref.get("address") or "",
                "pan": pan,
                "type": d.donor_type,
            },
            "donation": {
                "amount": rupees(d.amount_paise),
                "amount_words": amount_words(d.amount_paise),
                "mode": (d.mode or "online").replace("_", " "),
                "reference": meta.get("reference") or "",
                "on_date": d.on_date.strftime("%d-%m-%Y"),
                "receipt_no": d.receipt_no or "",
                "campaign": camp or "the general fund",
                "financial_year": financial_year(d.on_date),
            },
            "g80": {k: (v or "") for k, v in (g80 if isinstance(g80, dict) else {}).items()},
        }
        person = None
        if ref.get("alumni_id"):
            person = (
                await svc.db.execute(
                    select(AlumniProfile.student_id).where(AlumniProfile.id == uuid.UUID(str(ref["alumni_id"])))
                )
            ).scalar_one_or_none()
        return ctx, ("alumni" if person else None), person


_register()
