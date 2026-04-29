"""Contact assignment.

A Contact is an Operator's anonymous identity within a Channel. Callsigns are
generated randomly and must be unique within the channel — we retry a small
number of times before giving up, which is overwhelmingly enough for the size
of the callsign namespace (~30 adjectives * 32 nouns plus the and/number variants).
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.callsigns import generate_callsign
from app.models.contact import Contact, ContactRole

_MAX_CALLSIGN_ATTEMPTS = 8


def assign_contact(operator_id: int, channel_id: int, role: ContactRole, db: Session) -> Contact:
    """Create a Contact with a fresh, unique-within-channel callsign.

    The caller must commit the surrounding transaction.
    """

    last_error: IntegrityError | None = None
    for _ in range(_MAX_CALLSIGN_ATTEMPTS):
        callsign = generate_callsign()
        contact = Contact(
            operator_id=operator_id,
            channel_id=channel_id,
            callsign=callsign,
            role=role,
        )
        db.add(contact)
        try:
            db.flush()
            return contact
        except IntegrityError as exc:
            db.rollback()
            last_error = exc
            continue

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Could not assign a callsign. Try again.",
    ) from last_error
