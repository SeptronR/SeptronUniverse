"""Run an in-memory Redis **TCP server** (fakeredis) for a workstation without Redis (development aid only).

    python scripts/dev_fakeredis_server.py [--port 6380]

Unlike ``dev_api_fakeredis.py`` (which patches the API process only), this serves the Redis protocol on a TCP port,
so the API, a Celery worker and Celery Beat can share it: start this first, then run each process with
``REDIS_URL=redis://localhost:6380/0``, ``CELERY_BROKER_URL=redis://localhost:6380/1`` and
``CELERY_RESULT_BACKEND=redis://localhost:6380/2`` in the environment of each process (a shell ``export`` / PowerShell
``$env:`` — ``.env`` keeps pointing at the real Redis). Launcher: ``fakeredis-server``. Everything is lost when it
stops. Never use it outside development — the canonical verification runs against real
Redis (RUN_AFTER_PHASE.md §5-6).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contextlib

import _bootstrap  # noqa: E402,F401


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=6380)
    args = ap.parse_args()

    from app.core.config import settings

    if settings.APP_ENV != "development":
        print("refusing: APP_ENV must be 'development' for the fakeredis server")
        return 1
    from fakeredis import TcpFakeServer

    server = TcpFakeServer((args.host, args.port), server_type="redis")
    print(f"fakeredis TCP server on {args.host}:{args.port} (in-memory, development only)", flush=True)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
