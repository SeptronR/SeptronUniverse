"""Phase 44 — ops console, public status page, internal ops reports (Prompts/44 §44.8).

``router``: ``/platform/ops/*``, ``/platform/maintenance``, ``/platform/releases*`` — super admin (support agents read
the GET routes). ``public_router``: ``/public/status`` (+ RSS feed, uptime history) and the internal reports
``/internal/ops/{deploy-report,backup-report,alert-events,heartbeat/{queue}}`` authenticated by ``X-Ops-Token``
(``INTERNAL_OPS_TOKEN``) — both listed in ``PUBLIC_ROUTES``.
"""

from typing import Any
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, platform_permission
from app.core.errors import APIError, ErrorCode
from app.core.rate_limit import rate_limited
from app.db.session import get_platform_db, redis_client
from app.schemas.common import Envelope
from app.services.ops.ops_service import OpsService, internal_token_ok
from app.utils.response import ok

router = APIRouter(tags=["ops"])
public_router = APIRouter(tags=["public"])

READ = platform_permission("platform", "view")
WRITE = platform_permission("platform", "manage", support=False)


class NoteIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class DrillIn(BaseModel):
    source_backup: str | None = Field(default=None, max_length=200)
    target_env: str = Field(default="scratch", max_length=40)
    rpo_observed_min: float | None = None
    rto_observed_min: float | None = None
    verified_checks: list[str] = Field(default_factory=list)
    report_url: str | None = Field(default=None, max_length=2000)


class IncidentIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    components: list[str] = Field(default_factory=list)
    state: str = Field(default="investigating", pattern="^(investigating|identified|monitoring)$")
    message: str = Field(default="", max_length=4000)


class IncidentUpdateIn(BaseModel):
    state: str = Field(default="monitoring", pattern="^(investigating|identified|monitoring|resolved)$")
    message: str = Field(default="", max_length=4000)


class ComponentIn(BaseModel):
    state: str | None = Field(default=None, pattern="^(operational|degraded|outage|maintenance)$")
    message: str | None = Field(default=None, max_length=500)


class ScriptRunIn(BaseModel):
    script: str = Field(max_length=40)
    params: dict[str, Any] = Field(default_factory=dict)


class ReleaseIn(BaseModel):
    version: str = Field(pattern=r"^v?\d+\.\d+\.\d+(-[\w.]+)?$")
    notes_md: str = Field(default="", max_length=50_000)
    sbom_url: str | None = Field(default=None, max_length=2000)
    images: dict[str, str] = Field(default_factory=dict)
    deprecations: list[str] = Field(default_factory=list)


class MaintenanceIn(BaseModel):
    reason: str = Field(min_length=3, max_length=200)
    starts_at: str
    ends_at: str
    notice_hours: int = Field(default=24, ge=0, le=720)


# ---- console ---------------------------------------------------------------------------------------------------------
@router.get("/platform/ops/overview", summary="Operations overview", response_model=Envelope[dict[str, Any]])
async def overview(
    request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await OpsService(db, principal, request).overview())


@router.get("/platform/ops/deploys", summary="Deploy history", response_model=Envelope[list[dict[str, Any]]])
async def deploys(principal: Principal = Depends(READ), db: AsyncSession = Depends(get_platform_db)) -> dict[str, Any]:
    return ok(await OpsService(db, principal).ring("ops.deploys"))


@router.post("/platform/ops/deploys/{id}/notes", summary="Annotate a deploy", response_model=Envelope[dict[str, Any]])
async def deploy_note(
    id: str,
    body: NoteIn,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await OpsService(db, principal, request).deploy_note(id, body.note))


@router.get("/platform/ops/backups", summary="Backups (summary + log)", response_model=Envelope[dict[str, Any]])
async def backups(principal: Principal = Depends(READ), db: AsyncSession = Depends(get_platform_db)) -> dict[str, Any]:
    svc = OpsService(db, principal)
    return ok(
        {"summary": await svc.platform_value("ops.backups", None) or {}, "log": await svc.ring("ops.backups_log")}
    )


@router.get("/platform/ops/restore-drills", summary="Restore drills", response_model=Envelope[list[dict[str, Any]]])
async def drills(principal: Principal = Depends(READ), db: AsyncSession = Depends(get_platform_db)) -> dict[str, Any]:
    return ok(await OpsService(db, principal).ring("ops.restore_drills"))


@router.post("/platform/ops/restore-drills", summary="Record a restore drill", response_model=Envelope[dict[str, Any]])
async def drill_record(
    body: DrillIn, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    svc = OpsService(db, principal, request)
    rec = await svc.record_drill(body.model_dump())
    await svc._audit("restore_drill_record", {"status": rec["status"]})  # noqa: SLF001
    return ok(rec)


@router.get("/platform/ops/alerts", summary="Alert events", response_model=Envelope[list[dict[str, Any]]])
async def alerts(
    active: bool | None = None, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await OpsService(db, principal).alerts(active))


@router.get(
    "/platform/ops/alerts/rules",
    summary="Alert rule catalogue (ops/alerts/*.yml)",
    response_model=Envelope[list[dict[str, Any]]],
)
async def alert_rules(
    principal: Principal = Depends(READ), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(OpsService(db, principal).rules())


@router.post("/platform/ops/alerts/test", summary="Test-fire an alert rule", response_model=Envelope[dict[str, Any]])
async def alert_test(
    request: Request,
    rule: str = Query(max_length=80),
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await OpsService(db, principal, request).test_alert(rule))


@router.get("/platform/ops/incidents", summary="Incidents", response_model=Envelope[list[dict[str, Any]]])
async def incidents(
    principal: Principal = Depends(READ), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await OpsService(db, principal).incidents())


@router.post(
    "/platform/ops/incidents", status_code=201, summary="Open an incident", response_model=Envelope[dict[str, Any]]
)
async def incident_open(
    body: IncidentIn,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await OpsService(db, principal, request).incident_open(body.model_dump()))


@router.post(
    "/platform/ops/incidents/{id}/update", summary="Post an incident update", response_model=Envelope[dict[str, Any]]
)
async def incident_update(
    id: str,
    body: IncidentUpdateIn,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(
        await OpsService(db, principal, request).incident_update(
            id, body.state, body.message, resolve=body.state == "resolved"
        )
    )


@router.post(
    "/platform/ops/incidents/{id}/resolve", summary="Resolve an incident", response_model=Envelope[dict[str, Any]]
)
async def incident_resolve(
    id: str,
    body: IncidentUpdateIn,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await OpsService(db, principal, request).incident_update(id, "resolved", body.message, resolve=True))


@router.put(
    "/platform/ops/status/components/{key}",
    summary="Override a status component (null state = automatic)",
    response_model=Envelope[dict[str, Any]],
)
async def component(
    key: str,
    body: ComponentIn,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await OpsService(db, principal, request).set_component(key, body.state, body.message))


@router.get(
    "/platform/ops/capacity",
    summary="Capacity snapshots, projections, recommendations",
    response_model=Envelope[dict[str, Any]],
)
async def capacity(principal: Principal = Depends(READ), db: AsyncSession = Depends(get_platform_db)) -> dict[str, Any]:
    return ok(await OpsService(db, principal).capacity())


@router.post(
    "/platform/ops/capacity/snapshot", summary="Take a capacity snapshot", response_model=Envelope[dict[str, Any]]
)
async def capacity_snapshot(
    request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    svc = OpsService(db, principal, request)
    snap = await svc.capacity_snapshot()
    await svc._audit("capacity_snapshot", {"date": snap["date"]})  # noqa: SLF001
    return ok(snap)


@router.get("/platform/ops/partitions", summary="Partition status", response_model=Envelope[list[dict[str, Any]]])
async def partitions(
    principal: Principal = Depends(READ), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await OpsService(db, principal).partitions())


@router.post(
    "/platform/ops/partitions/ensure",
    summary="Create next month's partitions (job)",
    response_model=Envelope[dict[str, Any]],
)
async def partitions_ensure(
    request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await OpsService(db, principal, request).request_script("partitions", {}))


@router.post("/platform/ops/cache-warm", summary="Warm caches (job)", response_model=Envelope[dict[str, Any]])
async def cache_warm(
    request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await OpsService(db, principal, request).request_script("cache_warm", {}))


@router.post(
    "/platform/ops/scripts/run",
    summary="Run an ops script (job; four-eyes for destructive ones)",
    response_model=Envelope[dict[str, Any]],
)
async def script_run(
    body: ScriptRunIn,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await OpsService(db, principal, request).request_script(body.script, body.params))


@router.post(
    "/platform/ops/scripts/runs/{id}/approve",
    summary="Approve a four-eyes script run",
    response_model=Envelope[dict[str, Any]],
)
async def script_approve(
    id: str, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await OpsService(db, principal, request).approve_script(id))


@router.get("/platform/ops/scripts/runs", summary="Script runs", response_model=Envelope[list[dict[str, Any]]])
async def script_runs(
    principal: Principal = Depends(READ), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await OpsService(db, principal).script_runs())


@router.get("/platform/ops/config", summary="Non-secret configuration", response_model=Envelope[dict[str, Any]])
async def config(principal: Principal = Depends(READ), db: AsyncSession = Depends(get_platform_db)) -> dict[str, Any]:
    return ok(await OpsService(db, principal).config())


@router.post(
    "/platform/maintenance",
    summary="Schedule a platform maintenance window (read-only + announcement)",
    response_model=Envelope[dict[str, Any]],
)
async def maintenance(
    body: MaintenanceIn,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    from datetime import datetime

    from app.schemas.saas import ReadOnlyScheduleIn
    from app.services.saas.read_only_schedule_service import ReadOnlyScheduleService

    out = await ReadOnlyScheduleService(db, principal, request).schedule(
        ReadOnlyScheduleIn(
            scope="platform",
            reason=body.reason,
            starts_at=datetime.fromisoformat(body.starts_at),
            ends_at=datetime.fromisoformat(body.ends_at),
            notice_hours=body.notice_hours,
        )
    )
    return ok(out.model_dump(mode="json"), message="Maintenance scheduled")


@router.get("/platform/releases", summary="Releases", response_model=Envelope[list[dict[str, Any]]])
async def releases(principal: Principal = Depends(READ), db: AsyncSession = Depends(get_platform_db)) -> dict[str, Any]:
    return ok(await OpsService(db, principal).releases())


@router.post("/platform/releases", status_code=201, summary="Record a release", response_model=Envelope[dict[str, Any]])
async def release_add(
    body: ReleaseIn,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await OpsService(db, principal, request).add_release(body.model_dump()))


@router.post(
    "/platform/releases/{version}/announce",
    summary="Announce a release to institution admins",
    response_model=Envelope[dict[str, Any]],
)
async def release_announce(
    version: str, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await OpsService(db, principal, request).announce_release(version))


# ---- public status -----------------------------------------------------------------------------------------------------
@public_router.get(
    "/public/status",
    summary="Public status (components, incidents, maintenance)",
    response_model=Envelope[dict[str, Any]],
    dependencies=[rate_limited("status", limit=120, window=60)],
)
async def public_status(db: AsyncSession = Depends(get_platform_db)) -> dict[str, Any]:
    return ok(await OpsService(db, None).public_status())


@public_router.get(
    "/public/status/history", summary="Daily uptime per component", response_model=Envelope[list[dict[str, Any]]]
)
async def public_history(
    component: str = Query(max_length=20),
    days: int = Query(default=90, ge=1, le=90),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await OpsService(db, None).history(component, days))


@public_router.get("/public/status/feed.rss", summary="Status incidents RSS")
async def public_feed(db: AsyncSession = Depends(get_platform_db)) -> Response:
    items = await OpsService(db, None).incidents()
    entries = "".join(
        f"<item><title>{escape(i['title'])} — {escape(i.get('state', ''))}</title><guid>{escape(i['id'])}</guid>"
        f"<pubDate>{escape(i.get('started_at') or '')}</pubDate>"
        f"<description>{escape((i.get('updates') or [{}])[-1].get('message', ''))}</description></item>"
        for i in items[:50]
    )
    xml = (
        f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>SeptronUniverse status</title>'
        f"<link>/status</link><description>Incidents and maintenance</description>{entries}</channel></rss>"
    )
    return Response(xml, media_type="application/rss+xml")


# ---- internal (X-Ops-Token) ----------------------------------------------------------------------------------------------
def _token(request: Request) -> None:
    # X-Ops-Token (scripts, CI) or Authorization: Bearer (Alertmanager can only send the standard header)
    given = (
        request.headers.get("x-ops-token") or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    )
    if not internal_token_ok(given):
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid ops token")


@public_router.post("/internal/ops/deploy-report", summary="Deploy record from the dispatch receiver", status_code=204)
async def deploy_report(request: Request, db: AsyncSession = Depends(get_platform_db)) -> None:
    _token(request)
    await OpsService(db, None).deploy_report(await request.json())
    await db.commit()


@public_router.post("/internal/ops/backup-report", summary="Backup record from the backup sidecar", status_code=204)
async def backup_report(request: Request, db: AsyncSession = Depends(get_platform_db)) -> None:
    _token(request)
    await OpsService(db, None).backup_report(await request.json())
    await db.commit()


@public_router.post(
    "/internal/ops/restore-drill", summary="Restore-drill record from restore_drill.sh", status_code=204
)
async def drill_report(request: Request, db: AsyncSession = Depends(get_platform_db)) -> None:
    _token(request)
    await OpsService(db, None).record_drill(await request.json())
    await db.commit()


@public_router.post("/internal/ops/alert-events", summary="Alertmanager webhook", status_code=204)
async def alert_events(request: Request, db: AsyncSession = Depends(get_platform_db)) -> None:
    _token(request)
    await OpsService(db, None).alert_events(await request.json())
    await db.commit()


@public_router.post(
    "/internal/ops/release", summary="Tagged release from release.yml (records + announces)", status_code=204
)
async def release_report(request: Request, db: AsyncSession = Depends(get_platform_db)) -> None:
    _token(request)
    await OpsService(db, None).release_from_ci(await request.json())
    await db.commit()


@public_router.post("/internal/ops/heartbeat/{queue}", summary="Worker heartbeat", status_code=204)
async def heartbeat(queue: str, request: Request) -> None:
    _token(request)
    from datetime import UTC, datetime

    await redis_client.set(f"worker:{queue}:heartbeat", datetime.now(UTC).isoformat(), ex=120)
