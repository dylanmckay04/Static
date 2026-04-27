"""Whisper business logic."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.presence import Presence, PresenceRole
from app.models.seeker import Seeker
from app.models.whisper import Whisper
from app.schemas.whisper import WhisperPage, WhisperResponse


def create_whisper(seance_id: int, seeker: Seeker, content: str, db: Session) -> Whisper:
    """Persist a new Whisper, snapshotting the caller's current sigil."""
    presence = (
        db.query(Presence)
        .filter(Presence.seance_id == seance_id, Presence.seeker_id == seeker.id)
        .first()
    )
    if presence is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You must be present in this seance to whisper.")

    whisper = Whisper(content=content, sigil=presence.sigil,
                      seance_id=seance_id, seeker_id=seeker.id)
    db.add(whisper)
    db.commit()
    db.refresh(whisper)
    return whisper


def list_whispers(
    seance_id: int, seeker: Seeker, before_id: int | None, limit: int, db: Session
) -> WhisperPage:
    """Return a page of whispers, newest-first, capped at 50.

    Soft-deleted whispers are included but their content is replaced with
    the redacted sentinel so clients can render a placeholder.
    """
    presence = (
        db.query(Presence)
        .filter(Presence.seance_id == seance_id, Presence.seeker_id == seeker.id)
        .first()
    )
    if presence is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You must be present in this seance to read its whispers.")

    limit = min(max(1, limit), 50)

    query = db.query(Whisper).filter(Whisper.seance_id == seance_id)
    if before_id is not None:
        query = query.filter(Whisper.id < before_id)

    rows = query.order_by(Whisper.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    items = rows[:limit]

    return WhisperPage(
        items=[WhisperResponse.from_orm_redacted(w) for w in items],
        next_before_id=items[-1].id if has_more else None,
    )


def redact_whisper(
    seance_id: int, whisper_id: int, seeker: Seeker, db: Session
) -> Whisper:
    """Soft-delete a whisper. Warden or moderator only.

    The row is kept; content is masked in API responses. A ``redact`` WS
    frame is broadcast by the caller so live clients can update immediately.
    """
    presence = (
        db.query(Presence)
        .filter(Presence.seance_id == seance_id, Presence.seeker_id == seeker.id)
        .first()
    )
    if not presence or presence.role == PresenceRole.attendant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only a warden or moderator may redact whispers.")

    whisper = (
        db.query(Whisper)
        .filter(Whisper.id == whisper_id, Whisper.seance_id == seance_id)
        .first()
    )
    if not whisper:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Whisper not found.")
    if whisper.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Whisper has already been redacted.")

    whisper.deleted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(whisper)
    return whisper
