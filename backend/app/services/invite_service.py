"""Invite service — mint and consume single-use sealed-seance invitations."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import create_invite_token, decode_invite_token
from app.models.invite import Invite
from app.models.presence import Presence, PresenceRole
from app.models.seance import Seance
from app.models.seeker import Seeker
from app.schemas.seance import InviteResponse
from app.services.presence_service import assign_presence

_DEFAULT_EXPIRY_SECONDS = 60 * 60 * 24  # 24 hours


def create_invite(
    seance_id: int,
    current_seeker: Seeker,
    db: Session,
    expires_in_seconds: int = _DEFAULT_EXPIRY_SECONDS,
) -> InviteResponse:
    """Mint a single-use invite for a sealed seance. Warden-only."""
    seance = db.query(Seance).filter(Seance.id == seance_id).first()
    if not seance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seance not found.")

    presence = (
        db.query(Presence)
        .filter(Presence.seance_id == seance_id, Presence.seeker_id == current_seeker.id)
        .first()
    )
    if not presence or presence.role != PresenceRole.warden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the warden may mint invitations.",
        )

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
    token, jti = create_invite_token(
        {"seance_id": seance_id, "created_by": current_seeker.id},
        expires_in_seconds,
    )

    invite = Invite(
        seance_id=seance_id,
        created_by=current_seeker.id,
        jti=jti,
        expires_at=expires_at,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    return InviteResponse(invite_id=invite.id, token=token, expires_at=expires_at)


def join_via_invite(
    token: str,
    current_seeker: Seeker,
    db: Session,
) -> Presence:
    """Consume an invite token and create a Presence in the sealed seance."""
    payload = decode_invite_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invitation token.",
        )

    jti = payload.get("jti")
    seance_id = payload.get("seance_id")
    if not jti or not seance_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed invitation token.",
        )

    invite = db.query(Invite).filter(Invite.jti == jti).first()
    if not invite:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation not recognised.",
        )
    if invite.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This invitation has already been used.",
        )
    if invite.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation has expired.",
        )

    seance = db.query(Seance).filter(Seance.id == seance_id).first()
    if not seance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seance not found.")

    existing = (
        db.query(Presence)
        .filter(Presence.seance_id == seance_id, Presence.seeker_id == current_seeker.id)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already walk this seance.",
        )

    # Consume the invite
    invite.used_by = current_seeker.id
    invite.used_at = datetime.now(timezone.utc)

    presence = assign_presence(
        seeker_id=current_seeker.id,
        seance_id=seance_id,
        role=PresenceRole.attendant,
        db=db,
    )
    db.commit()
    db.refresh(presence)
    return presence
