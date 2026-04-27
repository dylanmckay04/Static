from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_seeker, get_db
from app.core.limiter import limiter
from app.models.seeker import Seeker
from app.realtime.hub import hub
from app.schemas.whisper import WhisperCreate, WhisperPage, WhisperResponse
from app.services import whisper_service

router = APIRouter(prefix="/seances", tags=["whispers"])


@router.post("/{seance_id}/whispers", response_model=WhisperResponse,
             status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def send_whisper(
    request: Request, seance_id: int, payload: WhisperCreate,
    db: Session = Depends(get_db),
    current_seeker: Seeker = Depends(get_current_seeker),
):
    whisper = whisper_service.create_whisper(seance_id, current_seeker, payload.content, db)
    response = WhisperResponse.from_orm_redacted(whisper)
    await hub.broadcast(seance_id, {"op": "whisper", **response.model_dump(mode="json")})
    return response


@router.get("/{seance_id}/whispers", response_model=WhisperPage)
@limiter.limit("60/minute")
async def list_whispers(
    request: Request, seance_id: int,
    before_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=50),
    db: Session = Depends(get_db),
    current_seeker: Seeker = Depends(get_current_seeker),
):
    return whisper_service.list_whispers(seance_id, current_seeker, before_id, limit, db)


@router.delete("/{seance_id}/whispers/{whisper_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def redact_whisper(
    request: Request, seance_id: int, whisper_id: int,
    db: Session = Depends(get_db),
    current_seeker: Seeker = Depends(get_current_seeker),
):
    """Warden/moderator: soft-delete a whisper. Broadcasts redact op to the room."""
    whisper = whisper_service.redact_whisper(seance_id, whisper_id, current_seeker, db)
    await hub.broadcast(seance_id, {"op": "redact", "whisper_id": whisper.id})
