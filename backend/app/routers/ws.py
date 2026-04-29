"""WebSocket endpoint for real-time Channel communication.

Authentication flow
-------------------
1. Client fetches a short-lived socket token via ``POST /auth/socket-token``.
2. Client connects to ``/ws/channels/{channel_id}?token=<socket_token>``.
3. Server decodes, atomically consumes the JTI from Redis (GETDEL).
4. Server verifies Contact in the channel.
5. Connection is accepted and registered in the hub.

Rate limiting
-------------
Each operator+channel pair is governed by a Redis token bucket:
  - Capacity: 10 tokens
  - Refill:   1 token per second
  - Violation: error frame sent; message silently dropped (no disconnect).

Frame protocol (JSON)
---------------------
Client → Server:
  {"op": "transmission", "content": "<text>"}

Server → Client (broadcast):
  {"op": "transmission", "id":…, "channel_id":…, "callsign":…, "content":…, "created_at":…}
  {"op": "enter",   "callsign":…}
  {"op": "depart",  "callsign":…}
  {"op": "redact",  "transmission_id":…}

Server → Client (sender only, on error):
  {"op": "error", "detail": "…"}
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.security import decode_socket_token
from app.models.contact import Contact
from app.models.operator import Operator
from app.realtime.hub import hub
from app.schemas.transmission import TransmissionResponse
from app.services import transmission_service
from app.services.redis import redis_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

_CLOSE_UNAUTHORIZED = 4001
_CLOSE_FORBIDDEN    = 4003

# ── Token-bucket Lua script ────────────────────────────────────────────────
_BUCKET_LUA = """
local key         = KEYS[1]
local capacity    = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now         = tonumber(ARGV[3])

local data       = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens     = tonumber(data[1]) or capacity
local last_refill = tonumber(data[2]) or now

local elapsed = math.max(0, now - last_refill)
tokens = math.min(capacity, tokens + elapsed * refill_rate)

if tokens < 1 then
    redis.call('HSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 120)
    return 0
end

tokens = tokens - 1
redis.call('HSET', key, 'tokens', tokens, 'last_refill', now)
redis.call('EXPIRE', key, 120)
return 1
"""

_BUCKET_CAPACITY    = 10
_BUCKET_REFILL_RATE = 1.0  # tokens per second


async def _consume_token(channel_id: int, operator_id: int) -> bool:
    """Return True if a token was successfully consumed, False if rate-limited."""
    key = f"wsbucket:{channel_id}:{operator_id}"
    result = await redis_client.eval(
        _BUCKET_LUA,
        1,
        key,
        str(_BUCKET_CAPACITY),
        str(_BUCKET_REFILL_RATE),
        str(time.time()),
    )
    return bool(result)


@router.websocket("/ws/channels/{channel_id}")
async def channel_ws(
    websocket: WebSocket,
    channel_id: int,
    token: str = Query(...),
    db: Session = Depends(get_db),
) -> None:
    # 1. Decode socket token
    payload = decode_socket_token(token)
    if payload is None:
        await websocket.accept()
        await websocket.close(code=_CLOSE_UNAUTHORIZED, reason="Invalid or expired token")
        return

    jti = payload.get("jti")
    if not jti:
        await websocket.accept()
        await websocket.close(code=_CLOSE_UNAUTHORIZED, reason="Malformed token: missing jti")
        return

    # 2. Atomically consume JTI
    consumed = await redis_client.getdel(f"socket_jti:{jti}")
    if consumed is None:
        await websocket.accept()
        await websocket.close(code=_CLOSE_UNAUTHORIZED, reason="Token already used or expired")
        return

    # 3. Resolve Operator
    try:
        operator_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        await websocket.accept()
        await websocket.close(code=_CLOSE_UNAUTHORIZED, reason="Malformed token: bad sub")
        return

    operator = db.query(Operator).filter(Operator.id == operator_id).first()
    if operator is None:
        await websocket.accept()
        await websocket.close(code=_CLOSE_UNAUTHORIZED, reason="Operator not found")
        return

    # 4. Contact check
    contact = (
        db.query(Contact)
        .filter(Contact.channel_id == channel_id, Contact.operator_id == operator_id)
        .first()
    )
    if contact is None:
        await websocket.accept()
        await websocket.close(code=_CLOSE_FORBIDDEN, reason="You are not in this channel")
        return

    callsign = contact.callsign

    # 5. Accept and register
    await websocket.accept()
    hub.register(channel_id, websocket)
    logger.info("WS connected  channel=%d callsign=%r", channel_id, callsign)

    # 6. Message loop
    try:
        while True:
            try:
                data = await websocket.receive_json()
            except Exception:
                break

            op = data.get("op")

            if op == "transmission":
                content = (data.get("content") or "").strip()
                if not content:
                    await websocket.send_json({"op": "error", "detail": "Empty transmission"})
                    continue
                if len(content) > 4000:
                    await websocket.send_json({"op": "error", "detail": "Transmission too long (max 4000 chars)"})
                    continue

                allowed = await _consume_token(channel_id, operator_id)
                if not allowed:
                    await websocket.send_json({"op": "error", "detail": "You are speaking too quickly. Slow down."})
                    continue

                db.expire(contact)
                db.refresh(contact)

                try:
                    transmission = transmission_service.create_transmission(channel_id, operator, content, db)
                except Exception as exc:
                    logger.warning("create_transmission failed: %s", exc)
                    await websocket.send_json({"op": "error", "detail": str(exc)})
                    continue

                response = TransmissionResponse.from_orm_redacted(transmission)
                await hub.broadcast(channel_id, {"op": "transmission", **response.model_dump(mode="json")})

            else:
                await websocket.send_json({"op": "error", "detail": f"Unknown op: {op!r}"})

    except WebSocketDisconnect:
        logger.info("WS disconnected channel=%d callsign=%r", channel_id, callsign)
    except Exception:
        logger.exception("WS error        channel=%d callsign=%r", channel_id, callsign)
    finally:
        hub.unregister(channel_id, websocket)
        await hub.broadcast(channel_id, {"op": "depart", "callsign": callsign})
        logger.info("WS cleaned up   channel=%d callsign=%r", channel_id, callsign)
