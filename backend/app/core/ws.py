"""WebSocket hub on Redis pub/sub — Prompts/00 §2 tree; docs/Technical_Architecture.md §9.

``/ws?token=<access JWT>``; channels ``notifications:{user}``, ``jobs:{user}``, ``fleet:{institution}``,
``exam-board:{session}``. Every connection gets a per-principal channel allow-list; heartbeat 30 s. Redis pub/sub
makes fan-out multi-worker safe. Phase 01 completes the hub (principal-derived channels beyond self, reconnect
semantics); the skeleton authenticates, subscribes to the self channels and relays messages.
"""

import asyncio
import contextlib
import json
from typing import Any

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.errors import APIError
from app.core.security import decode_token
from app.db.session import redis_client

log = structlog.get_logger()
ws_router = APIRouter()

WS_CLOSE_UNAUTHENTICATED = 4401
HEARTBEAT_SECONDS = 30


class WebSocketHub:
    """Relays Redis pub/sub channels to connected sockets."""

    def __init__(self) -> None:
        self.connections: dict[WebSocket, set[str]] = {}

    def channels_for(self, claims: dict[str, Any]) -> set[str]:
        channels = {f"notifications:{claims['sub']}", f"jobs:{claims['sub']}"}
        if claims.get("inst"):
            channels.add(f"fleet:{claims['inst']}")
        return channels

    async def serve(self, websocket: WebSocket, channels: set[str]) -> None:
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(*channels)
        self.connections[websocket] = channels

        async def reader() -> None:
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg.get("type") == "message":
                    await websocket.send_text(json.dumps({"channel": msg["channel"], "data": _decode(msg["data"])}))
                await asyncio.sleep(0.01)

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(HEARTBEAT_SECONDS)
                await websocket.send_text(json.dumps({"channel": "system", "data": {"type": "ping"}}))

        async def inbound() -> None:
            while True:
                text = await websocket.receive_text()  # client pings / channel requests are accepted and ignored here
                if text == "ping":
                    await websocket.send_text(json.dumps({"channel": "system", "data": {"type": "pong"}}))

        tasks = [asyncio.create_task(reader()), asyncio.create_task(heartbeat()), asyncio.create_task(inbound())]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            for t in done:
                with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                    t.result()
        finally:
            for t in tasks:
                t.cancel()
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(*channels)
                await pubsub.aclose()
            self.connections.pop(websocket, None)


def _decode(raw: Any) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


hub = WebSocketHub()


async def publish(channel: str, payload: dict[str, Any]) -> None:
    await redis_client.publish(channel, json.dumps(payload, default=str))


@ws_router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str | None = Query(default=None)) -> None:
    if not token:
        await websocket.close(code=WS_CLOSE_UNAUTHENTICATED)
        return
    try:
        claims = decode_token(token, expected_type="access")
        if await redis_client.exists(f"blacklist:jti:{claims['jti']}"):
            raise APIError(401, "UNAUTHENTICATED", "Token revoked")
    except APIError:
        await websocket.close(code=WS_CLOSE_UNAUTHENTICATED)
        return
    await websocket.accept()
    try:
        await hub.serve(websocket, hub.channels_for(claims))
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        log.warning("ws_error", error=str(exc))
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)
