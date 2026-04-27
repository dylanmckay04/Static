"""Invite endpoints — mint and join sealed seances."""
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_seeker, get_db
from app.core.limiter import limiter
from app.models.seeker import Seeker
from app.realtime.hub import hub
from app.schemas.presence import OwnPresenceResponse
from app.schemas.seance import InviteResponse
from app.services import invite_service

router = APIRouter(tags=["invites"])


@router.post("/seances/{seance_id}/invites", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_invite(
    request: Request,
    seance_id: int,
    expires_in_seconds: int = Query(default=86400, ge=60, le=604800, description="Token lifetime in seconds (60s–7d)"),
    db: Session = Depends(get_db),
    current_seeker: Seeker = Depends(get_current_seeker),
):
    """Mint a single-use invite link for a sealed seance. Warden-only."""
    return invite_service.create_invite(seance_id, current_seeker, db, expires_in_seconds)


@router.post("/seances/join", response_model=OwnPresenceResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def join_via_invite(
    request: Request,
    token: str = Query(..., description="Single-use invite token"),
    db: Session = Depends(get_db),
    current_seeker: Seeker = Depends(get_current_seeker),
):
    """Join a sealed seance using a warden-issued invite token."""
    presence = invite_service.join_via_invite(token, current_seeker, db)
    await hub.broadcast(presence.seance_id, {"op": "enter", "sigil": presence.sigil})
    return OwnPresenceResponse(
        sigil=presence.sigil,
        role=presence.role,
        entered_at=presence.entered_at,
        seance_id=presence.seance_id,
    )
