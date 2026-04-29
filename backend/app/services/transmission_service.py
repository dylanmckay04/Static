"""Transmission business logic."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.contact import Contact, ContactRole
from app.models.operator import Operator
from app.models.transmission import Transmission
from app.schemas.transmission import TransmissionPage, TransmissionResponse


def create_transmission(channel_id: int, operator: Operator, content: str, db: Session) -> Transmission:
    """Persist a new Transmission, snapshotting the caller's current callsign."""
    contact = (
        db.query(Contact)
        .filter(Contact.channel_id == channel_id, Contact.operator_id == operator.id)
        .first()
    )
    if contact is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You must be in this channel to transmit.")

    transmission = Transmission(
        content=content,
        callsign=contact.callsign,
        channel_id=channel_id,
        operator_id=operator.id,
    )
    db.add(transmission)
    db.commit()
    db.refresh(transmission)
    return transmission


def list_transmissions(
    channel_id: int, operator: Operator, before_id: int | None, limit: int, db: Session
) -> TransmissionPage:
    """Return a page of transmissions, newest-first, capped at 50."""
    contact = (
        db.query(Contact)
        .filter(Contact.channel_id == channel_id, Contact.operator_id == operator.id)
        .first()
    )
    if contact is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You must be in this channel to read its transmissions.")

    limit = min(max(1, limit), 50)

    query = db.query(Transmission).filter(Transmission.channel_id == channel_id)
    if before_id is not None:
        query = query.filter(Transmission.id < before_id)

    rows = query.order_by(Transmission.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    items = rows[:limit]

    return TransmissionPage(
        items=[TransmissionResponse.from_orm_redacted(t) for t in items],
        next_before_id=items[-1].id if has_more else None,
    )


def redact_transmission(
    channel_id: int, transmission_id: int, operator: Operator, db: Session
) -> Transmission:
    """Soft-delete a transmission. Controller or relay only."""
    contact = (
        db.query(Contact)
        .filter(Contact.channel_id == channel_id, Contact.operator_id == operator.id)
        .first()
    )
    if not contact or contact.role == ContactRole.listener:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only a controller or relay may redact transmissions.")

    transmission = (
        db.query(Transmission)
        .filter(Transmission.id == transmission_id, Transmission.channel_id == channel_id)
        .first()
    )
    if not transmission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transmission not found.")
    if transmission.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Transmission has already been redacted.")

    transmission.deleted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(transmission)
    return transmission
