"""Whisper business logic.

A Whisper is a message sent inside a Séance. The sender's current sigil is
snapshotted onto the row at creation time so the message retains its
anonymous identity even if the Presence later dissolves.
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.presence import Presence
from app.models.seeker import Seeker
from app.models.whisper import Whisper
from app.schemas.whisper import WhisperPage, WhisperResponse


def create_whisper(seance_id: int, seeker: Seeker, content: str, db: Session) -> Whisper:
    """Persist a new Whisper, snapshotting the caller's current sigil.

    Raises 403 if the caller has no Presence in the seance — you must be
    present to be heard.
    """
    presence = (
        db.query(Presence)
        .filter(Presence.seance_id == seance_id, Presence.seeker_id == seeker.id)
        .first()
    )
    if presence is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be present in this seance to whisper.",
        )

    whisper = Whisper(
        content=content,
        sigil=presence.sigil,
        seance_id=seance_id,
        seeker_id=seeker.id,
    )
    db.add(whisper)
    db.commit()
    db.refresh(whisper)
    return whisper


def list_whispers(seance_id: int, seeker: Seeker, before_id: int | None, limit: int, db: Session) -> WhisperPage:
    """Return a page of whispers, newest-first, capped at 50.

    Cursor pagination: pass ``before_id`` to walk backwards in time.
    ``next_before_id`` in the response is the cursor for the next page, or
    ``None`` if this is the oldest page.
    """
    presence = (
        db.query(Presence)
        .filter(Presence.seance_id == seance_id, Presence.seeker_id == seeker.id)
        .first()
    )
    if presence is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be present in this seance to read its whispers.",
        )

    limit = min(max(1, limit), 50)

    query = db.query(Whisper).filter(Whisper.seance_id == seance_id)
    if before_id is not None:
        query = query.filter(Whisper.id < before_id)

    # Fetch one extra to detect whether another page exists without a COUNT().
    rows = query.order_by(Whisper.id.desc()).limit(limit + 1).all()

    has_more = len(rows) > limit
    items = rows[:limit]

    next_before_id = items[-1].id if has_more else None

    return WhisperPage(
        items=[WhisperResponse.model_validate(w) for w in items],
        next_before_id=next_before_id,
    )
