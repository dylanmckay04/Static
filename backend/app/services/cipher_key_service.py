"""Cipher key service — mint and consume single-use encrypted-channel keys."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import create_invite_token, decode_invite_token
from app.models.cipher_key import CipherKey
from app.models.contact import Contact, ContactRole
from app.models.channel import Channel
from app.models.operator import Operator
from app.schemas.channel import CipherKeyResponse
from app.services.contact_service import assign_contact

_DEFAULT_EXPIRY_SECONDS = 60 * 60 * 24  # 24 hours


def create_cipher_key(
    channel_id: int,
    current_operator: Operator,
    db: Session,
    expires_in_seconds: int = _DEFAULT_EXPIRY_SECONDS,
) -> CipherKeyResponse:
    """Mint a single-use cipher key for an encrypted channel. Controller-only."""
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found.")

    contact = (
        db.query(Contact)
        .filter(Contact.channel_id == channel_id, Contact.operator_id == current_operator.id)
        .first()
    )
    if not contact or contact.role != ContactRole.controller:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the controller may mint cipher keys.",
        )

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
    token, jti = create_invite_token(
        {"channel_id": channel_id, "created_by": current_operator.id},
        expires_in_seconds,
    )

    cipher_key = CipherKey(
        channel_id=channel_id,
        created_by=current_operator.id,
        jti=jti,
        expires_at=expires_at,
    )
    db.add(cipher_key)
    db.commit()
    db.refresh(cipher_key)

    return CipherKeyResponse(cipher_key_id=cipher_key.id, token=token, expires_at=expires_at)


def join_via_cipher_key(
    token: str,
    current_operator: Operator,
    db: Session,
) -> Contact:
    """Consume a cipher key and create a Contact in the encrypted channel."""
    payload = decode_invite_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired cipher key.",
        )

    jti = payload.get("jti")
    # Accept both old seance_id and new channel_id fields for migration safety
    channel_id = payload.get("channel_id") or payload.get("seance_id")
    if not jti or not channel_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed cipher key.",
        )

    cipher_key = db.query(CipherKey).filter(CipherKey.jti == jti).first()
    if not cipher_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cipher key not recognised.",
        )
    if cipher_key.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This cipher key has already been used.",
        )
    if cipher_key.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This cipher key has expired.",
        )

    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found.")

    existing = (
        db.query(Contact)
        .filter(Contact.channel_id == channel_id, Contact.operator_id == current_operator.id)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already in this channel.",
        )

    cipher_key.used_by = current_operator.id
    cipher_key.used_at = datetime.now(timezone.utc)

    contact = assign_contact(
        operator_id=current_operator.id,
        channel_id=channel_id,
        role=ContactRole.listener,
        db=db,
    )
    db.commit()
    db.refresh(contact)
    return contact
