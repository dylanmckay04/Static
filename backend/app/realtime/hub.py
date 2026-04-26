"""In-process WebSocket connection registry.

Connections are bucketed by ``seance_id``. Broadcast fans out to every
live socket in that bucket, pruning dead connections on the fly.

Single-process only - horizontal scaling would require a Redis pub/sub
layer on top (Phase 1b).
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionHub:
    """Registry of live WebSocket connections, keyed by seance_id."""

    def __init__(self) -> None:
        # defaultdict so lookup never KeyErrors; we clean up empty sets manually.
        self._rooms: dict[int, set[WebSocket]] = defaultdict(set)

    def register(self, seance_id: int, ws: WebSocket) -> None:
        """Add *ws* to the bucket for *seance_id*."""
        self._rooms[seance_id].add(ws)
        logger.debug("hub.register seance=%d total=%d", seance_id, len(self._rooms[seance_id]))

    def unregister(self, seance_id: int, ws: WebSocket) -> None:
        """Remove *ws* from the bucket; prunes the bucket if now empty."""
        self._rooms[seance_id].discard(ws)
        if not self._rooms[seance_id]:
            self._rooms.pop(seance_id, None)
        logger.debug("hub.unregister seance=%d", seance_id)

    async def broadcast(self, seance_id: int, payload: dict) -> None:
        """Send *payload* as JSON text to every socket in *seance_id*'s bucket.

        Dead sockets (send raises) are silently pruned from the registry.
        """
        message = json.dumps(payload, default=str)
        # Snapshot to avoid mutating the set while iterating.
        connections = list(self._rooms.get(seance_id, set()))
        dead: list[WebSocket] = []

        for ws in connections:
            try:
                await ws.send_text(message)
            except Exception:
                logger.warning(
                    "Stale WebSocket during broadcast (seance=%d); removing.", seance_id
                )
                dead.append(ws)

        for ws in dead:
            self.unregister(seance_id, ws)


# ---------------------------------------------------------------------------
# Module-level singleton - one hub shared by the entire process.
# ---------------------------------------------------------------------------
hub = ConnectionHub()
