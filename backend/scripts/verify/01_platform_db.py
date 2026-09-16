"""Database-side assertions for ``scripts/verify/01_platform.ps1`` (Prompts/01 §01.11 steps 4, 5, 9).

    python scripts/verify/01_platform_db.py tables             # 411 base tables (+ alembic_version), one head
    python scripts/verify/01_platform_db.py outbox [--wait 15] # test.ping dispatched + consumed; test.fail re-armed
    python scripts/verify/01_platform_db.py partitions         # runs ensure_next_month → >= 2 partitions per table
    python scripts/verify/01_platform_db.py outbox-inprocess   # relay + consumers run in-process (no worker/Beat)

Each sub-command prints ``OK …`` lines and exits 1 on the first failed assertion. ``outbox`` expects a running Celery
worker + Beat (Redis); ``outbox-inprocess`` drives ``_relay`` and the consumer bodies directly so the outbox contract
can be proven on a machine without Redis (the relay's ``send_task`` is stubbed to call the consumer inline).
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1])
)  # scripts/ holds _bootstrap (this file lives in scripts/verify/)
import _bootstrap  # noqa: E402,F401
from sqlalchemy import text


def ok(msg: str) -> None:
    print(f"OK {msg}")


def fail(msg: str) -> int:
    print(f"FAIL {msg}")
    return 1


async def cmd_tables() -> int:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from app.db.session import PlatformSessionLocal

    async with PlatformSessionLocal() as db:
        n = (
            await db.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' "
                    "AND table_type='BASE TABLE' AND table_name <> 'alembic_version'"
                )
            )
        ).scalar_one()
        current = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()
        matview = (
            await db.execute(text("SELECT count(*) FROM pg_matviews WHERE matviewname='search_documents'"))
        ).scalar_one()
        rls = (
            await db.execute(
                text(
                    "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND c.relrowsecurity AND c.relkind IN ('r','p')"
                )
            )
        ).scalar_one()
    heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
    if n != 411:
        return fail(f"expected 411 base tables (405 + 6 partition defaults), found {n}")
    ok("411 base tables present (+ alembic_version)")
    if len(heads) != 1:
        return fail(f"alembic heads = {heads}")
    ok(f"alembic single head {heads[0]}; database at {current}")
    if current != heads[0]:
        return fail("database is not at head")
    if matview != 1:
        return fail("search_documents materialized view missing")
    ok(f"search_documents matview present; RLS enabled on {rls} tables")
    return 0


async def _insert_event(event_type: str, payload: dict[str, Any]) -> str:
    from app.db.session import PlatformSessionLocal

    async with PlatformSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "INSERT INTO domain_events (event_type, payload, aggregate_type) "
                    "VALUES (:t, CAST(:p AS jsonb), 'verify') RETURNING id"
                ),
                {"t": event_type, "p": json.dumps(payload)},
            )
        ).first()
        await db.commit()
    return str(row[0])  # type: ignore[index]


async def _event_state(event_id: str) -> dict[str, Any]:
    from app.db.session import PlatformSessionLocal

    async with PlatformSessionLocal() as db:
        row = (
            (
                await db.execute(
                    text(
                        "SELECT status, attempts, next_attempt_at, last_error, "
                        "(SELECT count(*) FROM event_consumptions ec WHERE ec.event_id = de.id "
                        " AND ec.consumer = 'outbox.test_ping') AS consumptions, "
                        "(SELECT count(*) FROM event_consumptions ec WHERE ec.event_id = de.id) AS all_consumptions "
                        "FROM domain_events de WHERE id = :i"
                    ),
                    {"i": event_id},
                )
            )
            .mappings()
            .first()
        )
    return dict(row) if row else {}


async def cmd_outbox(wait: int) -> int:
    ping = await _insert_event("test.ping", {"verify": "phase01"})
    failing = await _insert_event("test.fail", {"verify": "phase01"})
    deadline = time.time() + wait
    ping_state: dict[str, Any] = {}
    fail_state: dict[str, Any] = {}
    while time.time() < deadline:
        ping_state, fail_state = await _event_state(ping), await _event_state(failing)
        if (
            ping_state.get("status") == "dispatched"
            and ping_state.get("consumptions") == 1
            and fail_state.get("attempts", 0) >= 1
        ):
            break
        await asyncio.sleep(1)
    if ping_state.get("status") != "dispatched" or ping_state.get("consumptions") != 1:
        return fail(f"test.ping not dispatched/consumed within {wait}s: {ping_state}")
    ok(
        f"test.ping dispatched and consumed once by outbox.test_ping "
        f"({ping_state['all_consumptions']} event_consumptions rows incl. the webhooks.deliver wildcard consumer)"
    )
    if fail_state.get("attempts", 0) < 1 or not fail_state.get("next_attempt_at"):
        return fail(f"test.fail was not re-armed: {fail_state}")
    ok(
        f"test.fail re-armed: attempts={fail_state['attempts']} next_attempt_at={fail_state['next_attempt_at']} status={fail_state['status']}"
    )
    return 0


async def cmd_outbox_inprocess() -> int:
    """Drive the relay and the consumers without a broker (send_task → consumer body inline)."""
    from app.tasks import outbox
    from app.tasks.celery_app import celery

    ping = await _insert_event("test.ping", {"verify": "phase01-inprocess"})
    failing = await _insert_event("test.fail", {"verify": "phase01-inprocess"})

    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_send_task(name: str, kwargs: dict[str, Any] | None = None, **_: Any) -> None:
        calls.append((name, dict(kwargs or {})))

    original = celery.send_task
    celery.send_task = fake_send_task  # type: ignore[method-assign]
    try:
        counters = await outbox._relay(500)  # noqa: SLF001
    finally:
        celery.send_task = original  # type: ignore[method-assign]
    ok(f"relay dispatched {counters['dispatched']} event(s) to {len(calls)} consumer task(s)")
    for name, event in calls:
        task = celery.tasks.get(name)
        if task is None:
            return fail(f"consumer task {name} is not registered")
        # the wrapper records event_consumptions or re-arms the event (same code path as the Celery task body)
        await outbox._consume(name, task.__consumer_fn__, event)  # noqa: SLF001
    ping_state, fail_state = await _event_state(ping), await _event_state(failing)
    if ping_state.get("status") != "dispatched" or ping_state.get("consumptions") != 1:
        return fail(f"test.ping: {ping_state}")
    ok(
        f"test.ping dispatched and consumed once by outbox.test_ping "
        f"({ping_state['all_consumptions']} event_consumptions rows incl. the webhooks.deliver wildcard consumer)"
    )
    if (
        fail_state.get("attempts") != 1
        or fail_state.get("status") != "pending"
        or not fail_state.get("next_attempt_at")
    ):
        return fail(f"test.fail: {fail_state}")
    ok(
        f"test.fail re-armed: attempts=1 next_attempt_at={fail_state['next_attempt_at']} last_error={str(fail_state['last_error'])[:60]!r}"
    )
    # idempotency: replaying the ping to its consumer does not add a second consumption
    for name, event in calls:
        if event.get("event_type") == "test.ping":
            await outbox._consume(name, celery.tasks[name].__consumer_fn__, event)  # noqa: SLF001
    if (await _event_state(ping)).get("consumptions") != 1:
        return fail("duplicate delivery produced a second consumption")
    ok("duplicate delivery skipped (consumer idempotent)")
    return 0


async def cmd_partitions() -> int:
    from app.db.session import PlatformSessionLocal
    from app.tasks.platform import PARTITIONED_TABLES, ensure_next_month

    result = await ensure_next_month()
    ok(f"ensure_next_month created={result['created']} skipped={len(result['skipped'])}")
    async with PlatformSessionLocal() as db:
        for table in PARTITIONED_TABLES:
            n = (
                await db.execute(text(f"SELECT count(*) FROM pg_inherits WHERE inhparent='{table}'::regclass"))
            ).scalar_one()
            if n < 3:  # default + current month + next month
                return fail(f"{table}: {n} partitions (expected >= 3 incl. default)")
            ok(f"{table}: {n} partitions (default + monthly)")
        # rows written earlier now live in the monthly partition, not in the default
        moved = (
            await db.execute(
                text(
                    "SELECT count(*) FROM domain_events WHERE tableoid <> 'domain_events_default'::regclass "
                    "AND created_at >= date_trunc('month', now())"
                )
            )
        ).scalar_one()
        ok(f"{moved} domain_events row(s) of this month live in the monthly partition")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["tables", "outbox", "outbox-inprocess", "partitions"])
    ap.add_argument("--wait", type=int, default=15, help="seconds to wait for the worker (outbox)")
    args = ap.parse_args()
    if args.command == "tables":
        return asyncio.run(cmd_tables())
    if args.command == "outbox":
        return asyncio.run(cmd_outbox(args.wait))
    if args.command == "outbox-inprocess":
        return asyncio.run(cmd_outbox_inprocess())
    return asyncio.run(cmd_partitions())


if __name__ == "__main__":
    sys.exit(main())
