"""Run the API locally WITHOUT a Redis server (development aid only).

    python scripts/dev_api_fakeredis.py [--port 8000]

Redis is required by the platform (lifespan pings it and fails loudly). On a workstation without Redis this launcher
swaps every ``redis_client`` reference for an in-memory ``fakeredis`` server and starts uvicorn, so the web shell,
the WebSocket hub, idempotency, feature flags and the read-only gate can be exercised. What it cannot do: run Celery
workers/Beat — enqueued jobs stay ``queued`` and the outbox is not relayed. Never use it outside development
(``APP_ENV`` must be ``development``; the script refuses otherwise). The canonical verification runs against real Redis
(RUN_AFTER_PHASE.md §5-6).
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: E402,F401


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    from app.core.config import settings

    if settings.APP_ENV != "development":
        print("refusing: APP_ENV must be 'development' for the fakeredis launcher")
        return 1
    import fakeredis
    import fakeredis.aioredis

    server = fakeredis.FakeServer()

    import app.core.authz.dependencies as dependencies
    import app.core.features as features
    import app.core.idempotency as idempotency
    import app.core.rate_limit as rate_limit
    import app.core.ws as ws
    import app.db.session as session

    fake = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    for mod in (session, features, idempotency, rate_limit, ws, dependencies):
        mod.redis_client = fake  # type: ignore[attr-defined]
    import main as main_module

    main_module.redis_client = fake  # type: ignore[attr-defined]
    from app.tasks.celery_app import celery

    celery.conf.broker_url = "memory://"  # enqueue succeeds; nothing consumes (no worker in this mode)
    celery.conf.result_backend = "cache+memory://"
    os.environ.setdefault("PYTHONUTF8", "1")
    print(f"** DEV ONLY: API on http://{args.host}:{args.port} with an in-memory Redis stand-in (no worker/Beat) **")

    import uvicorn

    uvicorn.run(main_module.app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
