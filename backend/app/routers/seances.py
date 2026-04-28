from fastapi import APIRouter, Body, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_seeker, get_db
from app.core.limiter import limiter
from app.models.presence import PresenceRole
from app.models.seeker import Seeker
from app.realtime.hub import hub
from app.schemas.presence import OwnPresenceResponse, PresenceResponse
from app.schemas.seance import SeanceCreate, SeanceDetail, SeanceResponse
from app.services import seance_service

router = APIRouter(prefix="/seances", tags=["seances"])


@router.post("", response_model=SeanceResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def open_seance(request: Request, payload: SeanceCreate,
                      db: Session = Depends(get_db),
                      current_seeker: Seeker = Depends(get_current_seeker)):
    return seance_service.create_seance(payload, current_seeker, db)


@router.get("", response_model=list[SeanceResponse])
@limiter.limit("60/minute")
async def list_seances(request: Request, db: Session = Depends(get_db),
                       current_seeker: Seeker = Depends(get_current_seeker)):
    return seance_service.list_seances(current_seeker, db)


@router.get("/{seance_id}", response_model=SeanceDetail)
@limiter.limit("60/minute")
async def get_seance(request: Request, seance_id: int,
                     db: Session = Depends(get_db),
                     current_seeker: Seeker = Depends(get_current_seeker)):
    return seance_service.get_seance(seance_id, current_seeker, db)


@router.post("/{seance_id}/enter", response_model=OwnPresenceResponse,
             status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def enter_seance(request: Request, seance_id: int,
                       db: Session = Depends(get_db),
                       current_seeker: Seeker = Depends(get_current_seeker)):
    presence = seance_service.enter_seance(seance_id, current_seeker, db)
    await hub.broadcast(seance_id, {"op": "enter", "sigil": presence.sigil})
    return OwnPresenceResponse(sigil=presence.sigil, role=presence.role,
                                entered_at=presence.entered_at, seance_id=presence.seance_id)


@router.delete("/{seance_id}/depart", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def depart_seance(request: Request, seance_id: int,
                        db: Session = Depends(get_db),
                        current_seeker: Seeker = Depends(get_current_seeker)):
    sigil = seance_service.depart_seance(seance_id, current_seeker, db)
    await hub.broadcast(seance_id, {"op": "depart", "sigil": sigil})


@router.get("/{seance_id}/presences", response_model=list[PresenceResponse])
@limiter.limit("60/minute")
async def list_presences(request: Request, seance_id: int,
                         db: Session = Depends(get_db),
                         current_seeker: Seeker = Depends(get_current_seeker)):
    return seance_service.list_presences(seance_id, current_seeker, db)


@router.get("/{seance_id}/presences/me", response_model=OwnPresenceResponse)
@limiter.limit("60/minute")
async def get_own_presence(request: Request, seance_id: int,
                           db: Session = Depends(get_db),
                           current_seeker: Seeker = Depends(get_current_seeker)):
    presence = seance_service.get_own_presence(seance_id, current_seeker, db)
    return OwnPresenceResponse(sigil=presence.sigil, role=presence.role,
                                entered_at=presence.entered_at, seance_id=presence.seance_id)


@router.delete("/{seance_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def dissolve_seance(request: Request, seance_id: int,
                          db: Session = Depends(get_db),
                          current_seeker: Seeker = Depends(get_current_seeker)):
    await hub.broadcast(seance_id, {"op": "dissolve"})
    seance_service.dissolve_seance(seance_id, current_seeker, db)


# ── Warden controls ────────────────────────────────────────────────────────

@router.delete("/{seance_id}/presences/{target_seeker_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def kick_presence(request: Request, seance_id: int, target_seeker_id: int,
                        db: Session = Depends(get_db),
                        current_seeker: Seeker = Depends(get_current_seeker)):
    """Warden/moderator: forcibly remove a Presence from the seance."""
    sigil = seance_service.kick_presence(seance_id, target_seeker_id, current_seeker, db)
    await hub.broadcast(seance_id, {"op": "depart", "sigil": sigil})


@router.post("/{seance_id}/transfer", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def transfer_wardenship(
    request: Request, seance_id: int,
    target_seeker_id: int = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_seeker: Seeker = Depends(get_current_seeker),
):
    """Warden: hand warden role to another present Seeker."""
    old_sigil, new_sigil = seance_service.transfer_wardenship(seance_id, target_seeker_id, current_seeker, db)
    await hub.broadcast(seance_id, {"op": "promote", "sigil": old_sigil, "role": "attendant"})
    await hub.broadcast(seance_id, {"op": "promote", "sigil": new_sigil, "role": "warden"})


@router.patch("/{seance_id}/presences/{target_seeker_id}/role", response_model=PresenceResponse)
@limiter.limit("20/minute")
async def set_presence_role(
    request: Request, seance_id: int, target_seeker_id: int,
    role: PresenceRole = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_seeker: Seeker = Depends(get_current_seeker),
):
    """Warden: promote an attendant to moderator, or demote a moderator back."""
    presence = seance_service.set_presence_role(seance_id, target_seeker_id, role, current_seeker, db)
    await hub.broadcast(seance_id, {"op": "promote", "sigil": presence.sigil, "role": presence.role.value})
    return presence


# ── Sigil-based warden controls (frontend-friendly — no seeker_id needed) ──

@router.delete("/{seance_id}/presences/sigil/{sigil}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def kick_by_sigil(
    request: Request, seance_id: int, sigil: str,
    db: Session = Depends(get_db),
    current_seeker: Seeker = Depends(get_current_seeker),
):
    """Warden/moderator: kick a Presence by their visible sigil."""
    evicted = seance_service.kick_by_sigil(seance_id, sigil, current_seeker, db)
    await hub.broadcast(seance_id, {"op": "depart", "sigil": evicted})


@router.post("/{seance_id}/transfer/sigil", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def transfer_wardenship_by_sigil(
    request: Request, seance_id: int,
    target_sigil: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_seeker: Seeker = Depends(get_current_seeker),
):
    """Warden: hand warden role to the Presence with the given sigil."""
    old_sigil, new_sigil = seance_service.transfer_wardenship_by_sigil(seance_id, target_sigil, current_seeker, db)
    await hub.broadcast(seance_id, {"op": "promote", "sigil": old_sigil, "role": "attendant"})
    await hub.broadcast(seance_id, {"op": "promote", "sigil": new_sigil, "role": "warden"})


@router.patch("/{seance_id}/presences/sigil/{sigil}/role", response_model=PresenceResponse)
@limiter.limit("20/minute")
async def set_role_by_sigil(
    request: Request, seance_id: int, sigil: str,
    role: PresenceRole = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_seeker: Seeker = Depends(get_current_seeker),
):
    """Warden: promote/demote a Presence identified by sigil."""
    presence = seance_service.set_role_by_sigil(seance_id, sigil, role, current_seeker, db)
    await hub.broadcast(seance_id, {"op": "promote", "sigil": presence.sigil, "role": presence.role.value})
    return presence
