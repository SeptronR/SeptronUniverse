"""One event loop per worker process for the Celery tasks (sync entry points that run async bodies).

``asyncio.run()`` creates and closes a fresh loop on every call, but the module-level SQLAlchemy engines and the Redis
client (``app.db.session``) keep pooled connections bound to the loop that opened them: the second task of a worker
then fails with "Future attached to a different loop" / "Event loop is closed" (found by the first live
``01_platform.ps1`` run with a real worker — the in-process harnesses never cross loops). Every task therefore runs
its coroutine on the same per-process loop; forked pool children create their own on first use.
"""

import asyncio
import os
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_pid: int | None = None


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run ``coro`` to completion on this process's persistent loop (never from inside a running loop)."""
    global _loop, _pid
    if _loop is None or _loop.is_closed() or _pid != os.getpid():
        _loop = asyncio.new_event_loop()
        _pid = os.getpid()
        asyncio.set_event_loop(_loop)
    return _loop.run_until_complete(coro)
