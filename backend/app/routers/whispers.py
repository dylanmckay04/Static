"""REST routes for Whispers.

POST is the canonical write path - HTTP-only clients (curl, simple bots) can
send messages without holding a WebSocket open. Every successful POST is also
fanned out through the hub so connected WS clients see it instantly.

GET provides cursor-paginated history for clients catching up after a
reconnect.
"""
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_seeker, get_db
from app.core.limiter import limiter
from app.models.seeker import Seeker
from app.realtime.hub import hub
from app.schemas.whisper import WhisperCreate, WhisperPage, WhisperResponse
from app.services import whisper_service

router = APIRouter(prefix="/seances", tags=["whispers"])


@router.post("/{seance_id}/whispers", response_model=WhisperResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("60/minute")
async def send_whisper(
    request: Request,
    seance_id: int,
    payload: WhisperCreate,
    db: Session = Depends(get_db),
    current_seeker: Seeker = Depends(get_current_seeker),
):
    """Send a Whisper into a Séance via REST.

    The caller must have an active Presence in the seance. The response
    contains the persisted Whisper (including its assigned id and timestamp).
    The same payload is broadcast over the hub so live WebSocket clients
    receive it without polling.
    """
    whisper = whisper_service.create_whisper(seance_id, current_seeker, payload.content, db)
    response = WhisperResponse.model_validate(whisper)
    # Fire-and-forget broadcast; REST response is not held up by WS delivery.
    await hub.broadcast(seance_id, {"op": "whisper", **response.model_dump(mode="json")})
    return response


@router.get("/{seance_id}/whispers", response_model=WhisperPage)
@limiter.limit("60/minute")
async def get_whispers(
    request: Request,
    seance_id: int,
    before_id: int | None = Query(default=None, description="Cursor - return whispers older than this id"),
    limit: int = Query(default=50, ge=1, le=50, description="Page size, max 50"),
    db: Session = Depends(get_db),
    current_seeker: Seeker = Depends(get_current_seeker),
):
    """Fetch paginated Whisper history for a Séance.

    Results are returned newest-first. To walk backwards in time, pass the
    ``next_before_id`` from the previous response as ``before_id`` on the
    next request. A ``null`` ``next_before_id`` means you have reached the
    beginning of history.
    """
    return whisper_service.list_whispers(seance_id, current_seeker, before_id, limit, db)
