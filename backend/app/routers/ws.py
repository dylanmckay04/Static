"""WebSocket endpoint for real-time Séance communication.

Authentication flow
-------------------
1. Client fetches a short-lived socket token via ``POST /auth/socket-token``.
2. Client connects to ``/ws/seances/{seance_id}?token=<socket_token>``.
3. Server decodes, atomically consumes the JTI from Redis (GETDEL).
4. Server verifies Presence in the seance.
5. Connection is accepted and registered in the hub.

Rate limiting
-------------
Each seeker+seance pair is governed by a Redis token bucket:
  - Capacity: 10 tokens
  - Refill:   1 token per second
  - Violation: error frame sent; message silently dropped (no disconnect).

Frame protocol (JSON)
---------------------
Client → Server:
  {"op": "whisper", "content": "<text>"}

Server → Client (broadcast):
  {"op": "whisper", "id":…, "seance_id":…, "sigil":…, "content":…, "created_at":…}
  {"op": "enter",   "sigil":…}
  {"op": "depart",  "sigil":…}
  {"op": "redact",  "whisper_id":…}

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
from app.models.presence import Presence
from app.models.seeker import Seeker
from app.realtime.hub import hub
from app.schemas.whisper import WhisperResponse
from app.services import whisper_service
from app.services.redis import redis_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

_CLOSE_UNAUTHORIZED = 4001
_CLOSE_FORBIDDEN    = 4003

# ── Token-bucket Lua script ────────────────────────────────────────────────
# KEYS[1] = bucket key
# ARGV[1] = capacity (int)
# ARGV[2] = refill_rate (tokens/second, float)
# ARGV[3] = current unix timestamp (float)
# Returns 1 if token consumed, 0 if bucket empty.

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


async def _consume_token(seance_id: int, seeker_id: int) -> bool:
    """Return True if a token was successfully consumed, False if rate-limited."""
    key = f"wsbucket:{seance_id}:{seeker_id}"
    result = await redis_client.eval(
        _BUCKET_LUA,
        1,  # numkeys
        key,
        str(_BUCKET_CAPACITY),
        str(_BUCKET_REFILL_RATE),
        str(time.time()),
    )
    return bool(result)


@router.websocket("/ws/seances/{seance_id}")
async def seance_ws(
    websocket: WebSocket,
    seance_id: int,
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

    # 3. Resolve Seeker
    try:
        seeker_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        await websocket.accept()
        await websocket.close(code=_CLOSE_UNAUTHORIZED, reason="Malformed token: bad sub")
        return

    seeker = db.query(Seeker).filter(Seeker.id == seeker_id).first()
    if seeker is None:
        await websocket.accept()
        await websocket.close(code=_CLOSE_UNAUTHORIZED, reason="Seeker not found")
        return

    # 4. Presence check
    presence = (
        db.query(Presence)
        .filter(Presence.seance_id == seance_id, Presence.seeker_id == seeker_id)
        .first()
    )
    if presence is None:
        await websocket.accept()
        await websocket.close(code=_CLOSE_FORBIDDEN, reason="You are not present in this seance")
        return

    sigil = presence.sigil

    # 5. Accept and register
    await websocket.accept()
    hub.register(seance_id, websocket)
    logger.info("WS connected  seance=%d sigil=%r", seance_id, sigil)

    # 6. Message loop
    try:
        while True:
            try:
                data = await websocket.receive_json()
            except Exception:
                break

            op = data.get("op")

            if op == "whisper":
                content = (data.get("content") or "").strip()
                if not content:
                    await websocket.send_json({"op": "error", "detail": "Empty whisper"})
                    continue
                if len(content) > 4000:
                    await websocket.send_json({"op": "error", "detail": "Whisper too long (max 4000 chars)"})
                    continue

                # Rate limiting
                allowed = await _consume_token(seance_id, seeker_id)
                if not allowed:
                    await websocket.send_json({"op": "error", "detail": "You are speaking too quickly. Slow down."})
                    continue

                db.expire(presence)
                db.refresh(presence)

                try:
                    whisper = whisper_service.create_whisper(seance_id, seeker, content, db)
                except Exception as exc:
                    logger.warning("create_whisper failed: %s", exc)
                    await websocket.send_json({"op": "error", "detail": str(exc)})
                    continue

                response = WhisperResponse.from_orm_redacted(whisper)
                await hub.broadcast(seance_id, {"op": "whisper", **response.model_dump(mode="json")})

            else:
                await websocket.send_json({"op": "error", "detail": f"Unknown op: {op!r}"})

    except WebSocketDisconnect:
        logger.info("WS disconnected seance=%d sigil=%r", seance_id, sigil)
    except Exception:
        logger.exception("WS error        seance=%d sigil=%r", seance_id, sigil)
    finally:
        hub.unregister(seance_id, websocket)
        await hub.broadcast(seance_id, {"op": "depart", "sigil": sigil})
        logger.info("WS cleaned up   seance=%d sigil=%r", seance_id, sigil)
