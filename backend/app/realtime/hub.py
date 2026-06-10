"""WebSocket connection registry with Redis pub/sub fanout.

Architecture
------------
Local registry (this module)
  dict[channel_id, set[WebSocket]] -- sockets connected to *this* worker.

Publish path (hub.broadcast)
  Serialize payload -> redis.publish("channel:{id}", json)
  Redis delivers the message to every worker that has subscribed.

Subscribe path (start_subscriber -- one task per worker)
  psubscribe("channel:*") -> on each pmessage, extract channel_id from the
  channel name and call hub._fan_out_local to push the raw string to every
  local WebSocket in that channel.

This means N uvicorn workers behave identically to 1: a Whisper created on
worker A is received by worker B's subscriber and delivered to B's clients
without any direct worker-to-worker communication.

Scaling note
  Each worker holds one persistent Redis connection for subscribing.
  The publish uses the shared redis_client pool (no extra connection needed).
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict

from fastapi import WebSocket

from app.services.redis import redis_client
from app.core.metrics import BROADCAST_DURATION_SECONDS, WS_CONNECTIONS_ACTIVE

logger = logging.getLogger(__name__)

_CHANNEL_PREFIX = "channel:"


class ConnectionHub:
    """Local registry of WebSocket connections for this worker process."""

    def __init__(self) -> None:
        self._rooms: dict[int, set[WebSocket]] = defaultdict(set)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, channel_id: int, ws: WebSocket) -> None:
        """Track *ws* as a live connection inside *channel_id*."""
        self._rooms[channel_id].add(ws)
        WS_CONNECTIONS_ACTIVE.inc()
        logger.debug("hub.register  channel=%d  local_total=%d", channel_id, len(self._rooms[channel_id]))

    def unregister(self, channel_id: int, ws: WebSocket) -> None:
        """Remove *ws*; prunes the bucket when it becomes empty."""
        if ws in self._rooms.get(channel_id, set()):
            WS_CONNECTIONS_ACTIVE.dec()
        self._rooms[channel_id].discard(ws)
        if not self._rooms[channel_id]:
            self._rooms.pop(channel_id, None)
        logger.debug("hub.unregister channel=%d", channel_id)

    # ------------------------------------------------------------------
    # Broadcast (publish to Redis -> all workers -> local fan-out)
    # ------------------------------------------------------------------

    async def broadcast(self, channel_id: int, payload: dict) -> None:
        """Publish *payload* to every worker connected to *channel_id*.

        Serialises to JSON and publishes on ``channel:{channel_id}``. The
        subscriber loop running in *every* worker (including this one) will
        receive the message and call ``_fan_out_local``.
        """
        with BROADCAST_DURATION_SECONDS.time():
            message = json.dumps(payload, default=str)
            await redis_client.publish(f"{_CHANNEL_PREFIX}{channel_id}", message)

    # ------------------------------------------------------------------
    # Local delivery (called by the subscriber loop)
    # ------------------------------------------------------------------

    async def _fan_out_local(self, channel_id: int, message: str) -> None:
        """Send an already-serialised message to every local socket in *channel_id*.

        Dead sockets are pruned on the fly.
        """
        connections = list(self._rooms.get(channel_id, set()))
        if not connections:
            return

        dead: list[WebSocket] = []
        for ws in connections:
            try:
                await ws.send_text(message)
            except Exception:
                logger.warning(
                    "Stale WebSocket during fan-out (channel=%d); removing.", channel_id
                )
                dead.append(ws)

        for ws in dead:
            self.unregister(channel_id, ws)


# ---------------------------------------------------------------------------
# Module-level singleton -- one hub per worker process.
# ---------------------------------------------------------------------------
hub = ConnectionHub()


# ---------------------------------------------------------------------------
# Background subscriber task -- one per worker process.
# ---------------------------------------------------------------------------

async def start_subscriber() -> None:
    """Subscribe to all channels and fan out messages to local sockets.

    Runs as a long-lived asyncio task started in the app lifespan. Reconnects
    automatically after any Redis error; cancellation (on shutdown) propagates
    cleanly.
    """
    while True:
        pubsub = redis_client.pubsub()
        try:
            await pubsub.psubscribe(f"{_CHANNEL_PREFIX}*")
            logger.info(
                "Redis pub/sub subscriber started (pattern=%s*)", _CHANNEL_PREFIX
            )

            async for message in pubsub.listen():
                # pubsub.listen() yields control-flow messages (subscribe
                # confirmations etc.) in addition to real data -- filter them.
                if message["type"] != "pmessage":
                    continue

                channel: str = message["channel"]
                try:
                    channel_id = int(channel[len(_CHANNEL_PREFIX):])
                except (ValueError, IndexError):
                    logger.warning(
                        "Subscriber: unexpected channel %r -- skipping", channel
                    )
                    continue

                await hub._fan_out_local(channel_id, message["data"])

        except asyncio.CancelledError:
            logger.info("Redis subscriber task cancelled -- shutting down")
            await pubsub.punsubscribe()
            raise  # let the lifespan handler finish cleanly

        except Exception:
            logger.exception("Redis subscriber crashed; reconnecting in 1 s")
            await asyncio.sleep(1)
            # Loop back to re-create pubsub and re-subscribe.
