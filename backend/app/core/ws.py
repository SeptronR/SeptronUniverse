"""WebSocket hub on Redis pub/sub — Prompts/01 §01.6; docs/Technical_Architecture.md §9.

``/ws?token=<access JWT>``. Close codes: ``4401`` unauthenticated (missing / invalid / revoked token), ``1011`` server
error. On connect the hub loads the principal, subscribes the socket to its channel allow-list and sends
``{"channel":"system","data":{"type":"hello","channels":[…]}}``; every Redis message on those channels is relayed as
``{"channel": <name>, "data": <json>}``. Heartbeat ``ping`` every 30 s (clients may also send ``"ping"`` → ``pong``).

Channels (allow-list derived from the principal, never from the client alone):
* ``notifications:{user}``, ``jobs:{user}`` — always;
* ``fleet:{institution}`` — ``transport:view_all|manage|driver`` (passengers poll the scoped ``/transport/live``); ``dashboard:{institution}`` — ``dashboard:view``;
* ``exam-board:{session}`` — on request (``{"subscribe": "exam-board:<uuid>"}``) when the principal has ``exams:view``;
  requests for channels outside the allow-list are answered with ``{"type":"denied"}`` and ignored.
Redis pub/sub makes fan-out multi-worker safe; the tray/notification stores fall back to polling when disconnected.
"""

import asyncio
import contextlib
import json
import re
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.errors import APIError
from app.core.security import decode_token
from app.db.session import SessionLocal, redis_client, set_tenant

log = structlog.get_logger()
ws_router = APIRouter()

WS_CLOSE_UNAUTHENTICATED = 4401
HEARTBEAT_SECONDS = 30
_EXAM_BOARD = re.compile(r"^exam-board:[0-9a-fA-F-]{36}$")


class WebSocketHub:
    """Relays Redis pub/sub channels to connected sockets."""

    def __init__(self) -> None:
        self.connections: dict[WebSocket, set[str]] = {}

    @staticmethod
    def channels_for(claims: dict[str, Any], principal: Any | None = None) -> set[str]:
        channels = {f"notifications:{claims['sub']}", f"jobs:{claims['sub']}"}
        inst = claims.get("inst") or (str(principal.institution_id) if principal and principal.institution_id else None)
        if inst and principal is not None:
            if any(principal.has("transport", a) for a in ("view_all", "manage", "driver")):
                channels.add(f"fleet:{inst}")
            if principal.has("dashboard", "view"):
                channels.add(f"dashboard:{inst}")
        return channels

    @staticmethod
    def may_subscribe(channel: str, principal: Any | None) -> bool:
        """Dynamic channels a client may request after connecting."""
        if principal is None:
            return False
        return bool(_EXAM_BOARD.match(channel)) and principal.has("exams", "view")

    async def serve(self, websocket: WebSocket, channels: set[str], principal: Any | None = None) -> None:
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(*channels)
        self.connections[websocket] = channels
        await websocket.send_text(
            json.dumps({"channel": "system", "data": {"type": "hello", "channels": sorted(channels)}})
        )

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
                raw = await websocket.receive_text()
                if raw == "ping":
                    await websocket.send_text(json.dumps({"channel": "system", "data": {"type": "pong"}}))
                    continue
                try:
                    req = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(req, dict):
                    continue
                if req.get("type") == "ping":
                    await websocket.send_text(json.dumps({"channel": "system", "data": {"type": "pong"}}))
                elif channel := req.get("subscribe"):
                    if isinstance(channel, str) and (channel in channels or self.may_subscribe(channel, principal)):
                        if channel not in channels:
                            channels.add(channel)
                            await pubsub.subscribe(channel)
                        await websocket.send_text(
                            json.dumps({"channel": "system", "data": {"type": "subscribed", "channel": channel}})
                        )
                    else:
                        await websocket.send_text(
                            json.dumps({"channel": "system", "data": {"type": "denied", "channel": channel}})
                        )
                elif (
                    (channel := req.get("unsubscribe"))
                    and isinstance(channel, str)
                    and channel in channels
                    and _EXAM_BOARD.match(channel)
                ):
                    channels.discard(channel)  # only dynamic channels can be dropped; self channels stay
                    await pubsub.unsubscribe(channel)

        tasks = [asyncio.create_task(reader()), asyncio.create_task(heartbeat()), asyncio.create_task(inbound())]
        try:
            done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
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


async def _load_principal(claims: dict[str, Any]) -> Any | None:
    """Resolve permissions for the channel allow-list; a DB hiccup degrades to the self channels only."""
    from app.services.auth_service import load_principal

    try:
        async with SessionLocal() as db:
            if claims.get("inst"):
                await set_tenant(db, claims["inst"])
            return await load_principal(db, uuid.UUID(claims["sub"]))
    except APIError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("ws_principal_unavailable", error=str(exc))
        return None


@ws_router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str | None = Query(default=None)) -> None:
    # A close before accept() is turned into an HTTP 403 handshake rejection by uvicorn (ASGI spec), so clients
    # would never see 4401: accept first, then close with the application code (found by the live 01_platform.ps1).
    if not token:
        await websocket.accept()
        await websocket.close(code=WS_CLOSE_UNAUTHENTICATED)
        return
    try:
        claims = decode_token(token, expected_type="access")
        if await redis_client.exists(f"blacklist:jti:{claims['jti']}"):
            raise APIError(401, "UNAUTHENTICATED", "Token revoked")
        principal = await _load_principal(claims)
    except APIError:
        await websocket.accept()
        await websocket.close(code=WS_CLOSE_UNAUTHENTICATED)
        return
    await websocket.accept()
    try:
        await hub.serve(websocket, hub.channels_for(claims, principal), principal)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        log.warning("ws_error", error=str(exc))
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)
