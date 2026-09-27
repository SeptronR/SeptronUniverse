"""In-process API verification for Phase 01 — the Redis-less counterpart of ``01_platform.ps1``.

    python scripts/verify/01_platform_inprocess.py

Drives the ASGI app through ``httpx.ASGITransport`` (no uvicorn, no lifespan) against the local PostgreSQL, with
``fakeredis`` standing in for Redis and Celery's broker switched to ``memory://``. It proves the Phase 01 contracts
that do not need a live worker: envelopes, public config, read-only gate (env + tenant window + revert), help centre,
feedback + Idempotency-Key replay, global search, WebSocket 4401 handshakes, the dev sleep job running through the
``@job`` wrapper (row queued → running → succeeded, progress events on ``jobs:{user}``, ``job.finished`` event), the
signed upload route and ``/ready``. The live-stack script (``01_platform.ps1``) remains the canonical verification —
run it on a machine with Redis (worker + Beat) before ticking PROGRESS.md.
"""

import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/ holds _bootstrap
import _bootstrap  # noqa: E402,F401

CHECKS = 0


def check(cond: Any, msg: str) -> None:
    global CHECKS
    if not cond:
        raise SystemExit(f"ASSERT FAILED: {msg}")
    CHECKS += 1
    print(f"  ok: {msg}")


FAKE_SERVER: Any = None


def install_fake_redis() -> Any:
    """Point every imported ``redis_client`` reference at a FakeRedis client (one shared in-memory server)."""
    global FAKE_SERVER
    import fakeredis
    import fakeredis.aioredis

    FAKE_SERVER = FAKE_SERVER or fakeredis.FakeServer()
    fake = fakeredis.aioredis.FakeRedis(server=FAKE_SERVER, decode_responses=True)
    import app.core.authz.dependencies as dependencies
    import app.core.features as features
    import app.core.idempotency as idempotency
    import app.core.rate_limit as rate_limit
    import app.core.ws as ws
    import app.db.session as session

    for mod in (session, features, idempotency, rate_limit, ws, dependencies):
        mod.redis_client = fake  # type: ignore[attr-defined]
    import main as main_module

    main_module.redis_client = fake  # type: ignore[attr-defined]
    return fake


async def run() -> int:
    fake = install_fake_redis()
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from starlette.testclient import TestClient

    from app.core import jobs as jobs_core
    from app.core.config import settings
    from app.db.session import PlatformSessionLocal
    from app.tasks.celery_app import celery
    from main import app

    # send_task works without a broker; nothing consumes the queue here (the job body is driven directly below)
    celery.conf.broker_url = "memory://"
    celery.conf.result_backend = "cache+memory://"
    token = await _mint_token()
    auth = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        print("1. health / ready")
        r = await c.get("/health")
        check(r.status_code == 200 and r.json()["status"] == "ok", "GET /health -> ok")
        r = await c.get("/ready")
        body = r.json()
        check(r.status_code == 200 and body["status"] == "ready", f"GET /ready -> ready ({sorted(body['checks'])})")
        check(
            body["checks"]["migrations"]["ok"]
            and body["checks"]["migrations"]["current"] == body["checks"]["migrations"]["head"],
            f"database at the Alembic head ({body['checks']['migrations']['current']})",
        )
        check(body["checks"]["storage"]["ok"], "storage writable")

        print("2. public config")
        r = await c.get("/api/v1/public/config")
        cfg = r.json()
        check(r.status_code == 200 and cfg["success"] is True, "GET /public/config -> envelope")
        check("IN" in cfg["data"]["packs"] and cfg["data"]["packs"]["IN"]["categories"], "packs.IN.categories present")
        check(len(cfg["data"]["themes"]) == 5, "5 themes")
        check(set(cfg["data"]["min_app_versions"]) == {"android", "ios"}, "min_app_versions present")
        r = await c.post("/api/v1/mobile/config", json={"platform": "android", "app_version": "0.0.1"})
        mc = r.json()["data"]
        check(
            r.status_code == 200 and mc["update_available"] is True and mc["force_update"] is False,
            "POST /mobile/config -> versions compared",
        )
        r = await c.get("/api/v1/mobile/config?platform=ios&app_version=9.9.9")
        check(
            r.status_code == 200 and r.json()["data"]["update_available"] is False,
            "GET /mobile/config -> current version",
        )

        print("3. read-only gate")
        r = await c.get("/api/v1/platform/read-only")
        check(
            r.status_code == 200 and r.json()["data"]["platform"] is False, "GET /platform/read-only -> platform:false"
        )
        tenant = "00000000-0000-0000-0000-00000000f11e"
        r = await c.get("/api/v1/platform/read-only", headers={"X-Institution-Id": tenant})
        check(
            r.status_code == 200 and r.json()["data"]["institution_id"] == tenant,
            "tenant context (X-Institution-Id) pins app.institution_id for the request",
        )
        settings.READ_ONLY_MODE = True
        r = await c.post("/api/v1/feedback", json={"message": "blocked?"}, headers=auth)
        check(
            r.status_code == 503 and r.json()["error"]["code"] == "READ_ONLY",
            "READ_ONLY_MODE=true -> POST /feedback 503 READ_ONLY",
        )
        settings.READ_ONLY_MODE = False
        r = await c.post(
            "/api/v1/platform/read-only", json={"scope": "platform", "enabled": True, "reason": "verify"}, headers=auth
        )
        check(r.status_code == 200 and r.json()["data"]["platform"] is True, "super admin opens a platform window")
        check(await fake.get("ro:platform"), "ro:platform cached in Redis")
        r = await c.post("/api/v1/feedback", json={"message": "blocked by window"}, headers=auth)
        check(
            r.status_code == 503 and r.json()["error"]["code"] == "READ_ONLY", "tenant/platform window -> 503 READ_ONLY"
        )
        r = await c.post("/api/v1/platform/read-only", json={"scope": "platform", "enabled": False}, headers=auth)
        check(r.status_code == 200 and r.json()["data"]["platform"] is False, "window closed through the exempt route")
        check(not await fake.get("ro:platform"), "ro:platform cleared")

        print("4. protected routes need a token")
        r = await c.get("/api/v1/jobs")
        check(r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED", "GET /jobs without token -> 401")

        print("5. help centre")
        r = await c.get("/api/v1/help/articles", headers=auth)
        arts = r.json()["data"]
        check(r.status_code == 200 and len(arts) >= 5, f"GET /help/articles -> {len(arts)} platform articles")
        r = await c.get("/api/v1/help/articles?module=jobs", headers=auth)
        check(r.status_code == 200 and all(a["module"] == "jobs" for a in r.json()["data"]), "module filter")
        r = await c.get("/api/v1/help/articles/getting-started", headers=auth)
        check(r.status_code == 200 and r.json()["data"]["is_platform"] is True, "article detail")
        r = await c.get("/api/v1/help/articles/nope", headers=auth)
        check(r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND", "unknown slug -> 404")

        print("6. feedback + idempotency")
        idem = {"Idempotency-Key": uuid.uuid4().hex, **auth}
        r = await c.post(
            "/api/v1/feedback",
            json={"message": "phase01 verify", "category": "praise", "rating": 5, "page": "/help"},
            headers=idem,
        )
        check(r.status_code == 201 and r.json()["data"]["status"] == "new", "POST /feedback -> 201")
        first_id = r.json()["data"]["id"]
        r = await c.post(
            "/api/v1/feedback",
            json={"message": "phase01 verify", "category": "praise", "rating": 5, "page": "/help"},
            headers=idem,
        )
        check(
            r.status_code == 200
            and r.json()["meta"].get("idempotent_replay") is True
            and r.json()["data"]["id"] == first_id,
            "same Idempotency-Key -> replayed response (Idempotent-Replayed)",
        )
        check(r.headers.get("idempotent-replayed") == "true", "Idempotent-Replayed header")
        r = await c.post("/api/v1/feedback", json={"message": "different payload"}, headers=idem)
        check(
            r.status_code == 409 and r.json()["error"]["code"] == "CONFLICT",
            "same key, different payload -> 409 CONFLICT",
        )
        r = await c.post("/api/v1/feedback", json={"message": "x"}, headers=auth)
        check(r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION", "short message -> 422 VALIDATION")

        print("7. global search")
        r = await c.get("/api/v1/search?q=nobody", headers=auth)
        check(r.status_code == 200 and r.json()["data"]["results"] == [], "GET /search -> empty results gracefully")
        r = await c.get("/api/v1/search?q=nobody&types=student,bogus", headers=auth)
        check(r.status_code == 200 and r.json()["data"]["entity_types"] == ["student"], "unknown types dropped")

        print("8. jobs list + dev sleep job through the @job wrapper")
        r = await c.get("/api/v1/jobs", headers=auth)
        check(r.status_code == 200 and r.json()["meta"]["visibility"]["self"] is True, "GET /jobs -> meta.visibility")
        r = await c.post("/api/v1/_dev/jobs/sleep?seconds=2", headers=auth)
        check(r.status_code == 202 and r.json()["data"]["status"] == "queued", "POST /_dev/jobs/sleep -> 202 queued")
        job_id = r.json()["data"]["id"]
        user_id = r.json()["data"]["requested_by"]
        pubsub = fake.pubsub()
        await pubsub.subscribe(f"jobs:{user_id}")
        from app.tasks.platform import sleep_job

        body_fn = celery.tasks["jobs.sleep"].run.__wrapped__  # the async job body behind @job
        await jobs_core._run(body_fn, uuid.UUID(job_id))  # noqa: SLF001
        r = await c.get(f"/api/v1/jobs/{job_id}", headers=auth)
        row = r.json()["data"]
        check(row["status"] == "succeeded" and row["progress_pct"] == 100, "job queued -> running -> succeeded, 100 %")
        seen: list[dict[str, Any]] = []
        for _ in range(10):
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
            if msg and msg.get("type") == "message":
                seen.append(json.loads(msg["data"]))
        statuses = {m.get("status") for m in seen}
        check(
            "running" in statuses and "succeeded" in statuses,
            f"progress events on jobs:{{user}} ({len(seen)} messages)",
        )
        r = await c.post(f"/api/v1/jobs/{job_id}/cancel", headers=auth)
        check(r.status_code == 409 and r.json()["error"]["code"] == "CONFLICT", "cancel of a finished job -> 409")
        async with PlatformSessionLocal() as db:
            n = (
                await db.execute(
                    text("SELECT count(*) FROM domain_events WHERE event_type='job.finished' AND aggregate_id = :j"),
                    {"j": job_id},
                )
            ).scalar_one()
        check(n == 1, "job.finished domain event written to the outbox")
        r = await c.post("/api/v1/_dev/jobs/sleep?seconds=60", headers=auth)
        queued_id = r.json()["data"]["id"]
        r = await c.post(f"/api/v1/jobs/{queued_id}/cancel", headers=auth)
        check(
            r.status_code == 200 and r.json()["data"]["status"] == "cancelled",
            "cancel of a queued job closes it immediately",
        )
        check(sleep_job is not None, "jobs.sleep registered")

        print("9. signed uploads route")
        from file_service_check import tiny_png

        from app.services.file_service import IMAGE_TYPES, FileService

        async with PlatformSessionLocal() as db:
            saved = await FileService(db).save(
                tiny_png(),
                "verify",
                IMAGE_TYPES,
                institution_id="00000000-0000-0000-0000-00000000f11e",
                filename="p.png",
            )
        r = await c.get(saved.url)
        check(r.status_code == 200 and r.headers["content-type"].startswith("image/png"), "signed URL serves the file")
        r = await c.get(saved.url.replace("sig=", "sig=0"))
        check(r.status_code == 403, "tampered signature -> 403")
        r = await c.get(f"/uploads/{saved.key}")
        check(r.status_code == 403, "unsigned link -> 403")
        async with PlatformSessionLocal() as db:
            await FileService(db).delete(saved.key, "00000000-0000-0000-0000-00000000f11e")

    print("10. WebSocket handshakes")
    # TestClient drives the app on its own event loop (thread): drop the pooled asyncpg connections of this loop and
    # give it a FakeRedis client of its own so nothing crosses loops
    from app.db.session import engine, platform_engine

    await engine.dispose()
    await platform_engine.dispose()
    install_fake_redis()
    with TestClient(app) as tc:
        for label, url in (
            ("without token", "/ws"),
            ("forged token", "/ws?token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.bad"),
        ):
            code = None
            try:
                with tc.websocket_connect(url) as ws_conn:
                    ws_conn.receive_text()
            except Exception as exc:  # noqa: BLE001 - WebSocketDisconnect carries the close code
                code = getattr(exc, "code", None)
            check(code == 4401, f"WS {label} -> close 4401")
        with tc.websocket_connect(f"/ws?token={token}") as ws_conn:
            hello = json.loads(ws_conn.receive_text())
            check(
                hello["channel"] == "system" and hello["data"]["type"] == "hello",
                f"WS hello with channels {hello['data']['channels']}",
            )
            ws_conn.send_text("ping")
            pong = json.loads(ws_conn.receive_text())
            check(pong["data"]["type"] == "pong", "WS ping -> pong")
    print(f"\nPHASE 01 in-process: PASS ({CHECKS} checks)")
    return 0


async def _mint_token() -> str:
    from dev_token import mint

    return await mint(None, 30)


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
