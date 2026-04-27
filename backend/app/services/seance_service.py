from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.presence import Presence, PresenceRole
from app.models.seance import Seance
from app.models.seeker import Seeker
from app.schemas.seance import SeanceCreate, SeanceDetail
from app.services.presence_service import assign_presence


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_seance_or_404(seance_id: int, db: Session) -> Seance:
    seance = db.query(Seance).filter(Seance.id == seance_id).first()
    if not seance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Seance not found.",
        )
    return seance


def _get_presence(seance_id: int, seeker_id: int, db: Session) -> Presence | None:
    return (
        db.query(Presence)
        .filter(Presence.seance_id == seance_id, Presence.seeker_id == seeker_id)
        .first()
    )


def _require_visibility(seance: Seance, seeker_id: int, db: Session) -> Presence | None:
    """For sealed seances: 403 unless the Seeker has an existing Presence.

    Returns the Presence if one exists (whether or not the seance is
    sealed), or ``None`` for an open seance the Seeker hasn't entered yet.
    """
    presence = _get_presence(seance.id, seeker_id, db)
    if seance.is_sealed and presence is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This seance is sealed. You must be invited to enter.",
        )
    return presence


def _require_warden(seance: Seance, seeker_id: int, db: Session) -> Presence:
    presence = _get_presence(seance.id, seeker_id, db)
    if not presence or presence.role != PresenceRole.warden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the warden may perform this rite.",
        )
    return presence


def _build_seance_detail(seance: Seance, db: Session) -> SeanceDetail:
    presence_count = (
        db.query(Presence).filter(Presence.seance_id == seance.id).count()
    )
    return SeanceDetail(
        id=seance.id,
        name=seance.name,
        description=seance.description,
        is_sealed=seance.is_sealed,
        created_at=seance.created_at,
        presence_count=presence_count,
    )


# ---------------------------------------------------------------------------
# Public service surface
# ---------------------------------------------------------------------------

def create_seance(payload: SeanceCreate, current_seeker: Seeker, db: Session) -> Seance:
    existing = db.query(Seance).filter(Seance.name == payload.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A seance with this name already exists.",
        )

    seance = Seance(
        name=payload.name,
        description=payload.description,
        is_sealed=payload.is_sealed,
        created_by=current_seeker.id,
    )
    db.add(seance)
    db.flush()

    # The warden is just a Presence with the warden role — they get a sigil
    # too, so even the seance's creator is anonymous within the room.
    assign_presence(
        seeker_id=current_seeker.id,
        seance_id=seance.id,
        role=PresenceRole.warden,
        db=db,
    )

    db.commit()
    db.refresh(seance)
    return seance


def list_seances(current_seeker: Seeker, db: Session) -> list[Seance]:
    """All open seances, plus any sealed seances the Seeker has Presence in."""
    open_seances = db.query(Seance).filter(Seance.is_sealed == False).all()  # noqa: E712

    sealed_seances = (
        db.query(Seance)
        .join(Presence, Presence.seance_id == Seance.id)
        .filter(
            Seance.is_sealed == True,  # noqa: E712
            Presence.seeker_id == current_seeker.id,
        )
        .all()
    )

    by_id = {s.id: s for s in (open_seances + sealed_seances)}
    return sorted(by_id.values(), key=lambda s: s.created_at)


def get_seance(seance_id: int, current_seeker: Seeker, db: Session) -> SeanceDetail:
    seance = _get_seance_or_404(seance_id, db)
    _require_visibility(seance, current_seeker.id, db)
    return _build_seance_detail(seance, db)


def enter_seance(seance_id: int, current_seeker: Seeker, db: Session) -> Presence:
    """Become a Presence in the seance — a fresh sigil is minted each time."""
    seance = _get_seance_or_404(seance_id, db)

    if seance.is_sealed:
        # Sealed seances require an explicit invitation flow (not yet built).
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This seance is sealed. You must be invited to enter.",
        )

    if _get_presence(seance_id, current_seeker.id, db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already walk this seance. Depart before re-entering.",
        )

    presence = assign_presence(
        seeker_id=current_seeker.id,
        seance_id=seance_id,
        role=PresenceRole.attendant,
        db=db,
    )
    db.commit()
    db.refresh(presence)
    return presence


def depart_seance(seance_id: int, current_seeker: Seeker, db: Session) -> str:
    """Remove the Seeker's Presence and return their sigil for broadcast.

    Returns the sigil so the caller can notify connected WebSocket clients
    that this Presence has departed.
    """
    presence = _get_presence(seance_id, current_seeker.id, db)
    if not presence:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are not present in this seance.",
        )

    if presence.role == PresenceRole.warden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "The warden cannot depart. "
                "Dissolve the seance, or transfer the wardenship first."
            ),
        )

    sigil = presence.sigil
    db.delete(presence)
    db.commit()
    return sigil


def list_presences(seance_id: int, current_seeker: Seeker, db: Session) -> list[Presence]:
    """Visible to anyone with access to the seance."""
    seance = _get_seance_or_404(seance_id, db)
    _require_visibility(seance, current_seeker.id, db)
    return (
        db.query(Presence)
        .filter(Presence.seance_id == seance_id)
        .order_by(Presence.entered_at.asc())
        .all()
    )


def dissolve_seance(seance_id: int, current_seeker: Seeker, db: Session) -> None:
    """Wardens-only: tear down the seance and cascade everything inside."""
    seance = _get_seance_or_404(seance_id, db)
    _require_warden(seance, current_seeker.id, db)
    db.delete(seance)
    db.commit()
