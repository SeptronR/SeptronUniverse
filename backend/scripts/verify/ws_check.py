"""WebSocket handshake / channel checks for ``01_platform.ps1`` (Prompts/01 §01.11 steps 6-7).

    python scripts/verify/ws_check.py --url ws://localhost:8000/ws                 # no token / forged token -> 4401
    python scripts/verify/ws_check.py --url ... --token <jwt> --watch-job 20       # hello + jobs:{user} events for 20 s

With ``--token`` the script prints the ``hello`` channel list and, with ``--watch-job``, every ``jobs:*`` message it
receives until a terminal status (succeeded/failed/cancelled) arrives or the timeout elapses; exit 1 when no progress
event was seen. It is a plain ``websockets`` client — the same protocol the web ``lib/ws.ts`` client speaks.
"""

import argparse
import asyncio
import json
import sys
import time

import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus


async def expect_close(url: str, label: str, code: int = 4401) -> int:
    try:
        async with websockets.connect(url, open_timeout=10) as ws:
            await ws.recv()
    except ConnectionClosed as exc:
        got = exc.rcvd.code if exc.rcvd else None
        if got == code:
            print(f"OK ws {label} -> close {got}")
            return 0
        print(f"FAIL ws {label} -> close {got} (expected {code})")
        return 1
    except InvalidStatus as exc:
        print(f"FAIL ws {label} -> HTTP {exc.response.status_code} instead of a close frame")
        return 1
    print(f"FAIL ws {label} -> server accepted the connection")
    return 1


async def watch(url: str, token: str, seconds: int) -> int:
    seen: list[dict] = []
    async with websockets.connect(f"{url}?token={token}", open_timeout=10) as ws:
        hello = json.loads(await ws.recv())
        if hello.get("channel") != "system" or hello.get("data", {}).get("type") != "hello":
            print(f"FAIL unexpected first frame: {hello}")
            return 1
        print(f"OK ws hello channels={hello['data']['channels']}")
        await ws.send("ping")
        pong = json.loads(await ws.recv())
        if pong.get("data", {}).get("type") != "pong":
            print(f"FAIL ping -> {pong}")
            return 1
        print("OK ws ping -> pong")
        if seconds <= 0:
            return 0
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(0.5, deadline - time.time()))
            except TimeoutError:
                break
            msg = json.loads(raw)
            if str(msg.get("channel", "")).startswith("jobs:"):
                seen.append(msg["data"])
                d = msg["data"]
                print(
                    f"   job event: status={d.get('status')} progress={d.get('progress_pct')} message={d.get('message')}"
                )
                if d.get("status") in {"succeeded", "failed", "cancelled"}:
                    break
    statuses = {m.get("status") for m in seen}
    if not seen:
        print("FAIL no jobs:{user} events received")
        return 1
    if "succeeded" not in statuses:
        print(f"FAIL job did not report success over the tray channel: {statuses}")
        return 1
    print(f"OK {len(seen)} progress events received, terminal status succeeded")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="ws://localhost:8000/ws")
    ap.add_argument("--token")
    ap.add_argument("--watch-job", type=int, default=0, help="seconds to collect jobs:{user} events")
    args = ap.parse_args()
    if not args.token:
        rc = asyncio.run(expect_close(args.url, "without token"))
        rc |= asyncio.run(expect_close(f"{args.url}?token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.forged", "forged token"))
        return rc
    return asyncio.run(watch(args.url, args.token, args.watch_job))


if __name__ == "__main__":
    sys.exit(main())
