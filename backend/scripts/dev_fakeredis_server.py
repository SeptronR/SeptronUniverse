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


def _pubsub_handler():  # noqa: ANN202 - built lazily: fakeredis is a dev-only import
    """fakeredis' TCP handler is strictly request / response, so PUBLISH reached a subscriber's queue but was never
    written to its socket (WebSocket ``jobs:*`` / ``notifications:*`` events never arrived). Once a connection sends
    (P)SUBSCRIBE this handler switches it to push mode: a fakeredis PubSub feeds a pump thread that writes
    ``message`` / ``pmessage`` frames while the request loop keeps serving (P)UNSUBSCRIBE / PING."""
    import threading

    from fakeredis import FakeRedis
    from fakeredis._tcp_server import TCPFakeRequestHandler

    class Handler(TCPFakeRequestHandler):
        def handle(self) -> None:
            lock = threading.Lock()
            ps = None
            stop = threading.Event()

            def write(value: object) -> None:
                with lock:
                    self.writer.dump(value)
                    self.wfile.flush()

            def pump() -> None:
                while not stop.is_set():
                    try:
                        m = ps.get_message(timeout=0.2)
                    except Exception:  # noqa: BLE001 - connection closing
                        return
                    if m and m["type"] in ("message", "pmessage"):
                        frame = [m["type"]] + ([m["pattern"]] if m["type"] == "pmessage" else []) + [m["channel"], m["data"]]
                        write(frame)

            try:
                while True:
                    data = self.reader.load()
                    if not data:
                        break
                    cmd = data[0].upper() if isinstance(data[0], bytes) else data[0]
                    if cmd in (b"SUBSCRIBE", b"PSUBSCRIBE", b"UNSUBSCRIBE", b"PUNSUBSCRIBE"):
                        if ps is None:
                            ps = FakeRedis(server=self.server.fake_server).pubsub()
                            threading.Thread(target=pump, daemon=True).start()
                        names = [n.decode() if isinstance(n, bytes) else n for n in data[1:]]
                        getattr(ps, cmd.decode().lower())(*names)
                        for n in names or [None]:
                            write([cmd.decode().lower(), n, len(ps.channels) + len(ps.patterns)])
                        continue
                    if ps is not None and cmd == b"PING":
                        write(["pong", data[1] if len(data) > 1 else b""])
                        continue
                    res = self.current_client.connection.execute_command(*data)
                    write(res)
            except Exception as e:  # noqa: BLE001
                with contextlib.suppress(Exception):
                    write(e)
            finally:
                stop.set()
                if ps is not None:
                    with contextlib.suppress(Exception):
                        ps.close()

    return Handler


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
    server.RequestHandlerClass = _pubsub_handler()
    print(f"fakeredis TCP server on {args.host}:{args.port} (in-memory, development only)", flush=True)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
