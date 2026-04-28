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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seance not found.")
    return seance


def _get_presence(seance_id: int, seeker_id: int, db: Session) -> Presence | None:
    return (
        db.query(Presence)
        .filter(Presence.seance_id == seance_id, Presence.seeker_id == seeker_id)
        .first()
    )


def _require_visibility(seance: Seance, seeker_id: int, db: Session) -> Presence | None:
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


def _require_warden_or_mod(seance_id: int, seeker_id: int, db: Session) -> Presence:
    presence = _get_presence(seance_id, seeker_id, db)
    if not presence or presence.role == PresenceRole.attendant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a warden or moderator may perform this action.",
        )
    return presence


def _build_seance_detail(seance: Seance, db: Session) -> SeanceDetail:
    presence_count = db.query(Presence).filter(Presence.seance_id == seance.id).count()
    return SeanceDetail(
        id=seance.id,
        name=seance.name,
        description=seance.description,
        is_sealed=seance.is_sealed,
        whisper_ttl_seconds=seance.whisper_ttl_seconds,
        created_at=seance.created_at,
        presence_count=presence_count,
    )


# ---------------------------------------------------------------------------
# Public service surface
# ---------------------------------------------------------------------------

def create_seance(payload: SeanceCreate, current_seeker: Seeker, db: Session) -> Seance:
    existing = db.query(Seance).filter(Seance.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="A seance with this name already exists.")

    seance = Seance(
        name=payload.name,
        description=payload.description,
        is_sealed=payload.is_sealed,
        whisper_ttl_seconds=payload.whisper_ttl_seconds,
        created_by=current_seeker.id,
    )
    db.add(seance)
    db.flush()

    assign_presence(seeker_id=current_seeker.id, seance_id=seance.id,
                    role=PresenceRole.warden, db=db)
    db.commit()
    db.refresh(seance)
    return seance


def list_seances(current_seeker: Seeker, db: Session) -> list[Seance]:
    open_seances = db.query(Seance).filter(Seance.is_sealed == False).all()  # noqa: E712
    sealed_seances = (
        db.query(Seance)
        .join(Presence, Presence.seance_id == Seance.id)
        .filter(Seance.is_sealed == True, Presence.seeker_id == current_seeker.id)  # noqa: E712
        .all()
    )
    by_id = {s.id: s for s in (open_seances + sealed_seances)}
    return sorted(by_id.values(), key=lambda s: s.created_at)


def get_seance(seance_id: int, current_seeker: Seeker, db: Session) -> SeanceDetail:
    seance = _get_seance_or_404(seance_id, db)
    _require_visibility(seance, current_seeker.id, db)
    return _build_seance_detail(seance, db)


def enter_seance(seance_id: int, current_seeker: Seeker, db: Session) -> Presence:
    seance = _get_seance_or_404(seance_id, db)

    if _get_presence(seance_id, current_seeker.id, db):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="You already walk this seance. Depart before re-entering.")
    if seance.is_sealed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This seance is sealed. You must be invited to enter.",
        )

    presence = assign_presence(seeker_id=current_seeker.id, seance_id=seance_id,
                               role=PresenceRole.attendant, db=db)
    db.commit()
    db.refresh(presence)
    return presence


def depart_seance(seance_id: int, current_seeker: Seeker, db: Session) -> str:
    presence = _get_presence(seance_id, current_seeker.id, db)
    if not presence:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="You are not present in this seance.")
    if presence.role == PresenceRole.warden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The warden cannot depart. Dissolve the seance, or transfer wardenship first.",
        )
    sigil = presence.sigil
    db.delete(presence)
    db.commit()
    return sigil


def list_presences(seance_id: int, current_seeker: Seeker, db: Session) -> list[Presence]:
    seance = _get_seance_or_404(seance_id, db)
    _require_visibility(seance, current_seeker.id, db)
    return (
        db.query(Presence)
        .filter(Presence.seance_id == seance_id)
        .order_by(Presence.entered_at.asc())
        .all()
    )


def dissolve_seance(seance_id: int, current_seeker: Seeker, db: Session) -> None:
    seance = _get_seance_or_404(seance_id, db)
    _require_warden(seance, current_seeker.id, db)
    db.delete(seance)
    db.commit()


def get_own_presence(seance_id: int, current_seeker: Seeker, db: Session) -> Presence:
    _get_seance_or_404(seance_id, db)
    presence = _get_presence(seance_id, current_seeker.id, db)
    if presence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="You are not present in this seance.")
    return presence


# ---------------------------------------------------------------------------
# Warden controls
# ---------------------------------------------------------------------------

def kick_presence(
    seance_id: int,
    target_seeker_id: int,
    current_seeker: Seeker,
    db: Session,
) -> str:
    """Remove another Seeker's Presence. Returns the evicted sigil for broadcast.

    - Warden can kick any attendant or moderator.
    - Moderator can kick attendants only.
    - Nobody can kick the warden.
    """
    _get_seance_or_404(seance_id, db)
    actor_presence = _require_warden_or_mod(seance_id, current_seeker.id, db)

    target_presence = _get_presence(seance_id, target_seeker_id, db)
    if not target_presence:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="That seeker is not present in this seance.")
    if target_seeker_id == current_seeker.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="You cannot kick yourself.")
    if target_presence.role == PresenceRole.warden:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="The warden cannot be kicked.")
    if (target_presence.role == PresenceRole.moderator
            and actor_presence.role != PresenceRole.warden):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only the warden can remove a moderator.")

    sigil = target_presence.sigil
    db.delete(target_presence)
    db.commit()
    return sigil


def transfer_wardenship(
    seance_id: int,
    target_seeker_id: int,
    current_seeker: Seeker,
    db: Session,
) -> tuple[str, str]:
    """Hand warden role to another Presence. Returns (old_warden_sigil, new_warden_sigil)."""
    seance = _get_seance_or_404(seance_id, db)
    warden_presence = _require_warden(seance, current_seeker.id, db)

    target_presence = _get_presence(seance_id, target_seeker_id, db)
    if not target_presence:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Target seeker is not present in this seance.")
    if target_seeker_id == current_seeker.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="You are already the warden.")

    warden_presence.role = PresenceRole.attendant
    target_presence.role = PresenceRole.warden
    # Update the seance's created_by so subsequent warden checks still work.
    seance.created_by = target_seeker_id
    db.commit()
    return warden_presence.sigil, target_presence.sigil


def set_presence_role(
    seance_id: int,
    target_seeker_id: int,
    new_role: PresenceRole,
    current_seeker: Seeker,
    db: Session,
) -> Presence:
    """Warden-only: set a Presence's role to attendant or moderator."""
    seance = _get_seance_or_404(seance_id, db)
    _require_warden(seance, current_seeker.id, db)

    if new_role == PresenceRole.warden:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use POST /transfer to hand off the wardenship.",
        )

    target = _get_presence(seance_id, target_seeker_id, db)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Target seeker is not present.")
    if target.role == PresenceRole.warden:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Cannot demote the warden directly. Use /transfer first.")

    target.role = new_role
    db.commit()
    db.refresh(target)
    return target


def kick_by_sigil(
    seance_id: int,
    sigil: str,
    current_seeker: Seeker,
    db: Session,
) -> str:
    """Kick a Presence identified by sigil. Returns the sigil for broadcast."""
    _get_seance_or_404(seance_id, db)
    actor = _require_warden_or_mod(seance_id, current_seeker.id, db)

    target = (
        db.query(Presence)
        .filter(Presence.seance_id == seance_id, Presence.sigil == sigil)
        .first()
    )
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No presence with that sigil.")
    if target.seeker_id == current_seeker.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="You cannot kick yourself.")
    if target.role == PresenceRole.warden:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="The warden cannot be kicked.")
    if target.role == PresenceRole.moderator and actor.role != PresenceRole.warden:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only the warden can remove a moderator.")

    db.delete(target)
    db.commit()
    return sigil


def transfer_wardenship_by_sigil(
    seance_id: int,
    target_sigil: str,
    current_seeker: Seeker,
    db: Session,
) -> tuple[str, str]:
    """Transfer wardenship to the Presence with the given sigil. Returns (old_warden_sigil, new_warden_sigil)."""
    seance = _get_seance_or_404(seance_id, db)
    warden_presence = _require_warden(seance, current_seeker.id, db)

    target = (
        db.query(Presence)
        .filter(Presence.seance_id == seance_id, Presence.sigil == target_sigil)
        .first()
    )
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No presence with that sigil.")
    if target.seeker_id == current_seeker.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="You are already the warden.")

    warden_presence.role = PresenceRole.attendant
    target.role = PresenceRole.warden
    seance.created_by = target.seeker_id
    db.commit()
    return warden_presence.sigil, target.sigil


def set_role_by_sigil(
    seance_id: int,
    target_sigil: str,
    new_role: PresenceRole,
    current_seeker: Seeker,
    db: Session,
) -> Presence:
    """Warden: promote/demote a Presence identified by sigil."""
    seance = _get_seance_or_404(seance_id, db)
    _require_warden(seance, current_seeker.id, db)

    if new_role == PresenceRole.warden:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Use /transfer to hand off wardenship.")

    target = (
        db.query(Presence)
        .filter(Presence.seance_id == seance_id, Presence.sigil == target_sigil)
        .first()
    )
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No presence with that sigil.")
    if target.role == PresenceRole.warden:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Cannot demote the warden directly. Use /transfer first.")

    target.role = new_role
    db.commit()
    db.refresh(target)
    return target
