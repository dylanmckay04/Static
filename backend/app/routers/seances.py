from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_seeker, get_db
from app.core.limiter import limiter
from app.models.seeker import Seeker
from app.realtime.hub import hub
from app.schemas.presence import OwnPresenceResponse, PresenceResponse
from app.schemas.seance import SeanceCreate, SeanceDetail, SeanceResponse
from app.services import seance_service

router = APIRouter(prefix="/seances", tags=["seances"])


@router.post("", response_model=SeanceResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def open_seance(
    request: Request,
    payload: SeanceCreate,
    db: Session = Depends(get_db),
    current_seeker: Seeker = Depends(get_current_seeker),
):
    return seance_service.create_seance(payload, current_seeker, db)


@router.get("", response_model=list[SeanceResponse])
@limiter.limit("60/minute")
async def list_seances(
    request: Request,
    db: Session = Depends(get_db),
    current_seeker: Seeker = Depends(get_current_seeker),
):
    return seance_service.list_seances(current_seeker, db)


@router.get("/{seance_id}", response_model=SeanceDetail)
@limiter.limit("60/minute")
async def get_seance(
    request: Request,
    seance_id: int,
    db: Session = Depends(get_db),
    current_seeker: Seeker = Depends(get_current_seeker),
):
    return seance_service.get_seance(seance_id, current_seeker, db)


@router.post(
    "/{seance_id}/enter",
    response_model=OwnPresenceResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def enter_seance(
    request: Request,
    seance_id: int,
    db: Session = Depends(get_db),
    current_seeker: Seeker = Depends(get_current_seeker),
):
    presence = seance_service.enter_seance(seance_id, current_seeker, db)
    # Notify connected WebSocket clients that a new Presence has arrived.
    await hub.broadcast(seance_id, {"op": "enter", "sigil": presence.sigil})
    return OwnPresenceResponse(
        sigil=presence.sigil,
        role=presence.role,
        entered_at=presence.entered_at,
        seance_id=presence.seance_id,
    )


@router.delete("/{seance_id}/depart", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def depart_seance(
    request: Request,
    seance_id: int,
    db: Session = Depends(get_db),
    current_seeker: Seeker = Depends(get_current_seeker),
):
    seance_service.depart_seance(seance_id, current_seeker, db)


@router.get("/{seance_id}/presences", response_model=list[PresenceResponse])
@limiter.limit("60/minute")
async def list_presences(
    request: Request,
    seance_id: int,
    db: Session = Depends(get_db),
    current_seeker: Seeker = Depends(get_current_seeker),
):
    return seance_service.list_presences(seance_id, current_seeker, db)


@router.delete("/{seance_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def dissolve_seance(
    request: Request,
    seance_id: int,
    db: Session = Depends(get_db),
    current_seeker: Seeker = Depends(get_current_seeker),
):
    seance_service.dissolve_seance(seance_id, current_seeker, db)
