"""Campus wellness & services — Prompts/25 §25.8: emergency / SOS {facilities.emergency_sos}, health centre
{facilities.health_centre}, counselling {facilities.counselling_appointments}, sports {facilities.sports}, canteen
wallet {facilities.canteen_wallet}. SOS raise and POS debit honour ``Idempotency-Key``. Confidentiality (health,
counselling notes) is enforced by the services.
"""

import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.features import feature_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.facilities import (
    CanteenIn,
    CanteenOut,
    CounsellingAppointmentOut,
    CounsellingBook,
    CounsellingNotes,
    CounsellingSlotCreate,
    CounsellingUtilisation,
    FacJobAccepted,
    HealthCertificateRequest,
    HealthStats,
    HealthVisitIn,
    HealthVisitOut,
    InsurancePolicyIn,
    InsurancePolicyOut,
    SosBroadcast,
    SosNotes,
    SosOut,
    SosRaise,
    SportsEventIn,
    SportsEventOut,
    SportsParticipationIn,
    SportsParticipationOut,
    SportsTeamIn,
    SportsTeamOut,
    WalletCounterTopup,
    WalletDebit,
    WalletOut,
    WalletRefund,
    WalletSettlement,
    WalletStatement,
    WalletTopupRequest,
    WalletTopupResponse,
    WalletTxnOut,
)
from app.services.facilities.counselling_service import CounsellingService
from app.services.facilities.emergency_service import EmergencyService
from app.services.facilities.health_service import HealthService
from app.services.facilities.sports_service import SportsService
from app.services.facilities.wallet_service import WalletService
from app.utils.response import ok

router = APIRouter(tags=["campus"])

F = "facilities"
SELF = any_permission_required((F, "view"), (F, "book"), (F, "view_all"), (F, "manage"))
RESPOND = any_permission_required((F, "manage"), (F, "view_all"))
MANAGE = any_permission_required((F, "manage"))
HEALTH_SELF = any_permission_required(
    ("health", "view"), ("health", "record"), ("health", "view_all"), ("health", "manage")
)
HEALTH_REC = any_permission_required(("health", "record"), ("health", "manage"))
HEALTH_STATS = any_permission_required(("health", "view_all"), ("health", "record"), ("health", "manage"))
COUNSEL = any_permission_required((F, "counsel"), (F, "manage"))
COUNSEL_SELF = any_permission_required(
    (F, "view"), (F, "book"), (F, "counsel"), (F, "manage"), (F, "view_all"), ("health", "view_all")
)
SPORTS_SELF = any_permission_required(("sports", "view"), ("sports", "view_all"), ("sports", "manage"))
SPORTS_MANAGE = any_permission_required(("sports", "manage"))
WALLET_SELF = any_permission_required((F, "view"), (F, "book"), (F, "manage"))
WALLET_LEDGER = any_permission_required((F, "manage"), (F, "view_all"), ("accounting", "view"))

SOS = [feature_required("facilities.emergency_sos")]
HEALTH = [feature_required("facilities.health_centre")]
COUNSELLING = [feature_required("facilities.counselling_appointments")]
SPORTS = [feature_required("facilities.sports")]
WALLET = [feature_required("facilities.canteen_wallet")]


# ---- emergency ---------------------------------------------------------------------------------------------------------
@router.post(
    "/emergency/sos",
    status_code=201,
    summary="Raise an SOS (mobile; Idempotency-Key)",
    response_model=Envelope[SosOut],
    dependencies=SOS,
)
async def sos_raise(
    body: SosRaise,
    request: Request,
    key: str | None = Depends(idempotency_key),
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    res = ok(await EmergencyService(db, principal, request).raise_alert(body), message="Help is being alerted")
    await store(request, res, db, 201)
    return res


@router.get("/emergency/me", summary="My alerts", response_model=Envelope[list[SosOut]], dependencies=SOS)
async def sos_me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EmergencyService(db, principal, request).mine())


@router.get(
    "/emergency/alerts",
    summary="Live alerts board (responders)",
    response_model=Envelope[list[SosOut]],
    dependencies=SOS,
)
async def sos_list(
    request: Request,
    status: str | None = None,
    principal: Principal = Depends(RESPOND),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EmergencyService(db, principal, request).list_alerts(status))


@router.get(
    "/emergency/register", summary="Safety register", response_model=Envelope[list[dict[str, Any]]], dependencies=SOS
)
async def sos_register(
    request: Request, principal: Principal = Depends(RESPOND), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EmergencyService(db, principal, request).register())


@router.get("/emergency/alerts/{id}", summary="Alert", response_model=Envelope[SosOut], dependencies=SOS)
async def sos_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EmergencyService(db, principal, request).get(id))


@router.post(
    "/emergency/alerts/{id}/acknowledge",
    summary="Acknowledge (responder)",
    response_model=Envelope[SosOut],
    dependencies=SOS,
)
async def sos_ack(
    id: uuid.UUID,
    body: SosNotes,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EmergencyService(db, principal, request).acknowledge(id, body))


@router.post(
    "/emergency/alerts/{id}/resolve", summary="Resolve with notes", response_model=Envelope[SosOut], dependencies=SOS
)
async def sos_resolve(
    id: uuid.UUID,
    body: SosNotes,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EmergencyService(db, principal, request).resolve(id, body))


@router.post(
    "/emergency/alerts/{id}/false-alarm",
    summary="Mark as a false alarm",
    response_model=Envelope[SosOut],
    dependencies=SOS,
)
async def sos_false(
    id: uuid.UUID,
    body: SosNotes,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EmergencyService(db, principal, request).resolve(id, body, false_alarm=True))


@router.post(
    "/emergency/alerts/{id}/escalate-broadcast",
    summary="Escalate to the emergency broadcast",
    response_model=Envelope[dict[str, Any]],
    dependencies=SOS,
)
async def sos_broadcast(
    id: uuid.UUID,
    body: SosBroadcast,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EmergencyService(db, principal, request).escalate_broadcast(id, body))


# ---- health ------------------------------------------------------------------------------------------------------------
@router.get(
    "/health/visits",
    summary="Health visits (medical officer)",
    response_model=Envelope[list[HealthVisitOut]],
    dependencies=HEALTH,
)
async def hv_list(
    request: Request,
    person_id: uuid.UUID | None = None,
    principal: Principal = Depends(HEALTH_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await HealthService(db, principal, request).list_visits(person_id))


@router.post(
    "/health/visits",
    status_code=201,
    summary="Record a visit (confidential)",
    response_model=Envelope[HealthVisitOut],
    dependencies=HEALTH,
)
async def hv_create(
    body: HealthVisitIn,
    request: Request,
    principal: Principal = Depends(HEALTH_REC),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await HealthService(db, principal, request).record(body), message="Recorded")


@router.get(
    "/health/visits/me", summary="My health visits", response_model=Envelope[list[HealthVisitOut]], dependencies=HEALTH
)
async def hv_me(
    request: Request, principal: Principal = Depends(HEALTH_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await HealthService(db, principal, request).mine())


@router.get("/health/stats", summary="Health centre counts", response_model=Envelope[HealthStats], dependencies=HEALTH)
async def hv_stats(
    request: Request, principal: Principal = Depends(HEALTH_STATS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await HealthService(db, principal, request).stats())


@router.get(
    "/health/insurance",
    summary="Insurance policies",
    response_model=Envelope[list[InsurancePolicyOut]],
    dependencies=HEALTH,
)
async def ins_list(
    request: Request, principal: Principal = Depends(HEALTH_REC), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await HealthService(db, principal, request).policies())


@router.post(
    "/health/insurance",
    status_code=201,
    summary="Add an insurance policy",
    response_model=Envelope[InsurancePolicyOut],
    dependencies=HEALTH,
)
async def ins_create(
    body: InsurancePolicyIn,
    request: Request,
    principal: Principal = Depends(HEALTH_REC),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await HealthService(db, principal, request).add_policy(body), message="Saved")


@router.get(
    "/health/insurance/me",
    summary="My insurance",
    response_model=Envelope[list[InsurancePolicyOut]],
    dependencies=HEALTH,
)
async def ins_me(
    request: Request, principal: Principal = Depends(HEALTH_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await HealthService(db, principal, request).my_policies())


@router.get("/health/visits/{id}", summary="Health visit", response_model=Envelope[HealthVisitOut], dependencies=HEALTH)
async def hv_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(HEALTH_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await HealthService(db, principal, request).get(id))


@router.post(
    "/health/visits/{id}/certificate",
    status_code=201,
    summary="Medical certificate",
    response_model=Envelope[dict[str, Any]],
    dependencies=HEALTH,
)
async def hv_certificate(
    id: uuid.UUID,
    body: HealthCertificateRequest,
    request: Request,
    principal: Principal = Depends(HEALTH_REC),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await HealthService(db, principal, request).certificate(id, body), message="Issued")


# ---- counselling ----------------------------------------------------------------------------------------------------------
@router.get(
    "/counselling/slots",
    summary="My published slots (counsellor)",
    response_model=Envelope[list[CounsellingAppointmentOut]],
    dependencies=COUNSELLING,
)
async def cs_mine(
    request: Request, principal: Principal = Depends(COUNSEL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CounsellingService(db, principal, request).my_slots())


@router.post(
    "/counselling/slots",
    status_code=201,
    summary="Publish slots",
    response_model=Envelope[list[CounsellingAppointmentOut]],
    dependencies=COUNSELLING,
)
async def cs_publish(
    body: CounsellingSlotCreate,
    request: Request,
    principal: Principal = Depends(COUNSEL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CounsellingService(db, principal, request).publish(body), message="Published")


@router.get(
    "/counselling/slots/available",
    summary="Open slots",
    response_model=Envelope[list[CounsellingAppointmentOut]],
    dependencies=COUNSELLING,
)
async def cs_available(
    request: Request,
    counsellor_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    principal: Principal = Depends(COUNSEL_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CounsellingService(db, principal, request).available(counsellor_id, date_from, date_to))


@router.post(
    "/counselling/slots/{id}/book",
    summary="Book a slot (one active booking)",
    response_model=Envelope[CounsellingAppointmentOut],
    dependencies=COUNSELLING,
)
async def cs_book(
    id: uuid.UUID,
    body: CounsellingBook,
    request: Request,
    principal: Principal = Depends(COUNSEL_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CounsellingService(db, principal, request).book(id, body), message="Booked")


@router.get(
    "/counselling/appointments/me",
    summary="My appointments",
    response_model=Envelope[list[CounsellingAppointmentOut]],
    dependencies=COUNSELLING,
)
async def ca_me(
    request: Request, principal: Principal = Depends(COUNSEL_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CounsellingService(db, principal, request).mine())


@router.get(
    "/counselling/utilisation",
    summary="Utilisation counts (anonymised)",
    response_model=Envelope[CounsellingUtilisation],
    dependencies=COUNSELLING,
)
async def ca_util(
    request: Request, principal: Principal = Depends(COUNSEL_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CounsellingService(db, principal, request).utilisation())


@router.get(
    "/counselling/appointments/{id}",
    summary="Appointment (counsellor / person)",
    response_model=Envelope[CounsellingAppointmentOut],
    dependencies=COUNSELLING,
)
async def ca_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(COUNSEL_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CounsellingService(db, principal, request).get(id))


@router.post(
    "/counselling/appointments/{id}/cancel",
    summary="Cancel",
    response_model=Envelope[CounsellingAppointmentOut],
    dependencies=COUNSELLING,
)
async def ca_cancel(
    id: uuid.UUID, request: Request, principal: Principal = Depends(COUNSEL_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CounsellingService(db, principal, request).cancel(id))


@router.post(
    "/counselling/appointments/{id}/complete",
    summary="Complete (counsellor)",
    response_model=Envelope[CounsellingAppointmentOut],
    dependencies=COUNSELLING,
)
async def ca_complete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(COUNSEL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CounsellingService(db, principal, request).counsellor_action(id, "completed"))


@router.post(
    "/counselling/appointments/{id}/no-show",
    summary="No-show (counsellor)",
    response_model=Envelope[CounsellingAppointmentOut],
    dependencies=COUNSELLING,
)
async def ca_no_show(
    id: uuid.UUID, request: Request, principal: Principal = Depends(COUNSEL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CounsellingService(db, principal, request).counsellor_action(id, "no_show"))


@router.put(
    "/counselling/appointments/{id}/notes",
    summary="Encrypted notes (counsellor only)",
    response_model=Envelope[CounsellingAppointmentOut],
    dependencies=COUNSELLING,
)
async def ca_notes(
    id: uuid.UUID,
    body: CounsellingNotes,
    request: Request,
    principal: Principal = Depends(COUNSEL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CounsellingService(db, principal, request).notes(id, body.notes))


# ---- sports ------------------------------------------------------------------------------------------------------------
@router.get("/sports/teams", summary="Teams", response_model=Envelope[list[SportsTeamOut]], dependencies=SPORTS)
async def st_list(
    request: Request, principal: Principal = Depends(SPORTS_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SportsService(db, principal, request).teams())


@router.post(
    "/sports/teams",
    status_code=201,
    summary="Create a team",
    response_model=Envelope[SportsTeamOut],
    dependencies=SPORTS,
)
async def st_create(
    body: SportsTeamIn,
    request: Request,
    principal: Principal = Depends(SPORTS_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SportsService(db, principal, request).save_team(body), message="Created")


@router.put(
    "/sports/teams/{id}",
    summary="Edit a team (manager / coach)",
    response_model=Envelope[SportsTeamOut],
    dependencies=SPORTS,
)
async def st_update(
    id: uuid.UUID,
    body: SportsTeamIn,
    request: Request,
    principal: Principal = Depends(SPORTS_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SportsService(db, principal, request).save_team(body, id))


@router.get(
    "/sports/events", summary="Sports events", response_model=Envelope[list[SportsEventOut]], dependencies=SPORTS
)
async def se_list(
    request: Request, principal: Principal = Depends(SPORTS_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SportsService(db, principal, request).events())


@router.post(
    "/sports/events",
    status_code=201,
    summary="Create a sports event",
    response_model=Envelope[SportsEventOut],
    dependencies=SPORTS,
)
async def se_create(
    body: SportsEventIn,
    request: Request,
    principal: Principal = Depends(SPORTS_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SportsService(db, principal, request).create_event(body), message="Created")


@router.get(
    "/sports/participation",
    summary="Participation (manager / coach)",
    response_model=Envelope[list[SportsParticipationOut]],
    dependencies=SPORTS,
)
async def sp_list(
    request: Request,
    event_id: uuid.UUID | None = None,
    principal: Principal = Depends(SPORTS_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SportsService(db, principal, request).participation(event_id))


@router.post(
    "/sports/participation",
    status_code=201,
    summary="Record participation",
    response_model=Envelope[list[SportsParticipationOut]],
    dependencies=SPORTS,
)
async def sp_create(
    body: SportsParticipationIn,
    request: Request,
    principal: Principal = Depends(SPORTS_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SportsService(db, principal, request).add_participation(body), message="Recorded")


@router.post(
    "/sports/participation/{id}/verify",
    summary="Verify (→ achievements)",
    response_model=Envelope[SportsParticipationOut],
    dependencies=SPORTS,
)
async def sp_verify(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SPORTS_MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SportsService(db, principal, request).verify(id))


@router.get(
    "/sports/me", summary="My participation / teams", response_model=Envelope[dict[str, Any]], dependencies=SPORTS
)
async def sp_me(
    request: Request, principal: Principal = Depends(SPORTS_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SportsService(db, principal, request).mine())


# ---- canteens & wallet ----------------------------------------------------------------------------------------------------
@router.get("/canteens", summary="Canteens", response_model=Envelope[list[CanteenOut]], dependencies=WALLET)
async def cn_list(
    request: Request, principal: Principal = Depends(WALLET_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await WalletService(db, principal, request).canteens())


@router.post(
    "/canteens", status_code=201, summary="Add a canteen", response_model=Envelope[CanteenOut], dependencies=WALLET
)
async def cn_create(
    body: CanteenIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await WalletService(db, principal, request).save_canteen(body), message="Saved")


@router.put("/canteens/{id}", summary="Edit a canteen / menu", response_model=Envelope[CanteenOut], dependencies=WALLET)
async def cn_update(
    id: uuid.UUID,
    body: CanteenIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WalletService(db, principal, request).save_canteen(body, id))


@router.get("/wallet/me", summary="My wallet", response_model=Envelope[WalletOut], dependencies=WALLET)
async def w_me(
    request: Request, principal: Principal = Depends(WALLET_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await WalletService(db, principal, request).me())


@router.get(
    "/wallet/wards", summary="My wards' wallets (parent)", response_model=Envelope[list[WalletOut]], dependencies=WALLET
)
async def w_wards(
    request: Request, principal: Principal = Depends(WALLET_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await WalletService(db, principal, request).wards())


@router.post(
    "/wallet/topup", summary="Top up online", response_model=Envelope[WalletTopupResponse], dependencies=WALLET
)
async def w_topup(
    body: WalletTopupRequest,
    request: Request,
    principal: Principal = Depends(WALLET_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WalletService(db, principal, request).topup(body))


@router.post(
    "/wallet/topup/verify",
    summary="Confirm an online top-up (gateway callback)",
    response_model=Envelope[WalletTopupResponse],
    dependencies=WALLET,
)
async def w_topup_verify(
    body: dict[str, str],
    request: Request,
    principal: Principal = Depends(WALLET_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await WalletService(db, principal, request).verify_topup(
            body.get("order_id", ""), body.get("payment_id", ""), body.get("signature", "")
        )
    )


@router.post(
    "/wallet/topup/counter", summary="Counter top-up (cash)", response_model=Envelope[WalletOut], dependencies=WALLET
)
async def w_counter(
    body: WalletCounterTopup,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WalletService(db, principal, request).counter_topup(body))


@router.post(
    "/wallet/debit", summary="POS debit (Idempotency-Key)", response_model=Envelope[WalletTxnOut], dependencies=WALLET
)
async def w_debit(
    body: WalletDebit,
    request: Request,
    key: str | None = Depends(idempotency_key),
    principal: Principal = Depends(WALLET_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    res = ok(await WalletService(db, principal, request).debit(body))
    await store(request, res, db)
    return res


@router.post("/wallet/refund", summary="Refund a debit", response_model=Envelope[WalletTxnOut], dependencies=WALLET)
async def w_refund(
    body: WalletRefund,
    request: Request,
    principal: Principal = Depends(WALLET_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WalletService(db, principal, request).refund(body))


@router.get(
    "/wallet/statement", summary="Wallet statement", response_model=Envelope[WalletStatement], dependencies=WALLET
)
async def w_statement(
    request: Request,
    account_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    principal: Principal = Depends(WALLET_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WalletService(db, principal, request).statement(account_id, date_from, date_to))


@router.get(
    "/wallet/settlement",
    summary="Daily settlement per canteen",
    response_model=Envelope[WalletSettlement],
    dependencies=WALLET,
)
async def w_settlement(
    request: Request,
    canteen_id: uuid.UUID | None = None,
    on: date | None = None,
    principal: Principal = Depends(WALLET_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = WalletService(db, principal, request)
    return ok(await svc.settlement(canteen_id, on or await svc.today()))


@router.get(
    "/wallet/ledger",
    summary="Wallet ledger (accounts)",
    response_model=Envelope[list[WalletTxnOut]],
    dependencies=WALLET,
)
async def w_ledger(
    request: Request, principal: Principal = Depends(WALLET_LEDGER), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await WalletService(db, principal, request).ledger())


@router.post(
    "/wallet/settlement/report",
    status_code=202,
    summary="Settlement report (job)",
    response_model=Envelope[FacJobAccepted],
    dependencies=WALLET,
)
async def w_settlement_job(
    request: Request,
    on: date | None = None,
    principal: Principal = Depends(WALLET_LEDGER),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.jobs import enqueue

    j = await enqueue(db, principal, "wallet.settlement_report", {"on": on.isoformat() if on else None})
    return JSONResponse(
        status_code=202, content=ok(FacJobAccepted(job_id=j.id).model_dump(mode="json"), message="Queued")
    )
