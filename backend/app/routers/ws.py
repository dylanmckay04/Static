"""WebSocket endpoint for real-time Séance communication.

Authentication flow
-------------------
1. Client fetches a short-lived socket token via ``POST /auth/socket-token``
   (requires a valid access token).
2. Client connects to ``/ws/seances/{seance_id}?token=<socket_token>``.
3. Server decodes the token, then atomically consumes the JTI from Redis
   (``GETDEL``) — this makes each token single-use and prevents replay.
4. Server verifies the caller has an active Presence in the seance.
5. Connection is accepted and registered in the hub.

Frame protocol (JSON)
---------------------
Client → Server:
  {"op": "whisper", "content": "<text>"}

Server → Client (broadcast to all in seance):
  {"op": "whisper", "id": …, "seance_id": …, "sigil": …,
   "content": …, "created_at": …}

  {"op": "enter", "sigil": …}          — someone joined via REST
  {"op": "depart", "sigil": …}         — someone disconnected from WS

Server → Client (only the sender, on error):
  {"op": "error", "detail": "…"}
"""
from __future__ import annotations

import logging

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

# Custom close codes (4000–4999 are reserved for application use in RFC 6455).
_CLOSE_UNAUTHORIZED = 4001
_CLOSE_FORBIDDEN = 4003


@router.websocket("/ws/seances/{seance_id}")
async def seance_ws(
    websocket: WebSocket,
    seance_id: int,
    token: str = Query(..., description="Single-use socket token from POST /auth/socket-token"),
    db: Session = Depends(get_db),
) -> None:
    """WebSocket gate for a Séance.

    The connection is refused (pre-accept close) for any auth or presence
    failure. After a successful handshake the client may send whisper frames;
    all frames are broadcasted to every other connected client in the same
    seance.
    """

    # ------------------------------------------------------------------
    # 1. Decode the socket token (signature + type check)
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 2. Atomically consume the JTI - prevents replay attacks
    # ------------------------------------------------------------------
    consumed = await redis_client.getdel(f"socket_jti:{jti}")
    if consumed is None:
        await websocket.accept()
        await websocket.close(code=_CLOSE_UNAUTHORIZED, reason="Token already used or expired")
        return

    # ------------------------------------------------------------------
    # 3. Resolve the Seeker
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 4. Presence check - must already be in the seance
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 5. Accept and register
    # ------------------------------------------------------------------
    await websocket.accept()
    hub.register(seance_id, websocket)
    logger.info("WS connected  seance=%d sigil=%r", seance_id, sigil)

    # ------------------------------------------------------------------
    # 6. Message loop
    # ------------------------------------------------------------------
    try:
        while True:
            try:
                data = await websocket.receive_json()
            except Exception:
                # Client sent non-JSON or closed mid-frame; treat as disconnect.
                break

            op = data.get("op")

            if op == "whisper":
                content = (data.get("content") or "").strip()
                if not content:
                    await websocket.send_json({"op": "error", "detail": "Empty whisper"})
                    continue
                if len(content) > 4000:
                    await websocket.send_json(
                        {"op": "error", "detail": "Whisper too long (max 4000 chars)"}
                    )
                    continue

                # Expire the cached presence so we always read the current sigil.
                db.expire(presence)
                db.refresh(presence)

                try:
                    whisper = whisper_service.create_whisper(
                        seance_id, seeker, content, db
                    )
                except Exception as exc:
                    logger.warning("create_whisper failed: %s", exc)
                    await websocket.send_json({"op": "error", "detail": str(exc)})
                    continue

                response = WhisperResponse.model_validate(whisper)
                await hub.broadcast(
                    seance_id, {"op": "whisper", **response.model_dump(mode="json")}
                )

            else:
                await websocket.send_json(
                    {"op": "error", "detail": f"Unknown op: {op!r}"}
                )

    except WebSocketDisconnect:
        logger.info("WS disconnected seance=%d sigil=%r", seance_id, sigil)
    except Exception:
        logger.exception("WS error        seance=%d sigil=%r", seance_id, sigil)
    finally:
        # ------------------------------------------------------------------
        # 7. Clean up — unregister and notify remaining clients
        # ------------------------------------------------------------------
        hub.unregister(seance_id, websocket)
        await hub.broadcast(seance_id, {"op": "depart", "sigil": sigil})
        logger.info("WS cleaned up   seance=%d sigil=%r", seance_id, sigil)
