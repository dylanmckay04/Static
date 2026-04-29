"""Cipher key endpoints — mint and join encrypted channels."""
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_operator, get_db
from app.core.limiter import limiter
from app.models.operator import Operator
from app.realtime.hub import hub
from app.schemas.contact import OwnContactResponse
from app.schemas.channel import CipherKeyResponse
from app.services import cipher_key_service

router = APIRouter(tags=["cipher_keys"])


@router.post("/channels/{channel_id}/cipher-keys", response_model=CipherKeyResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_cipher_key(
    request: Request,
    channel_id: int,
    expires_in_seconds: int = Query(default=86400, ge=60, le=604800, description="Token lifetime in seconds (60s–7d)"),
    db: Session = Depends(get_db),
    current_operator: Operator = Depends(get_current_operator),
):
    """Mint a single-use cipher key for an encrypted channel. Controller-only."""
    return cipher_key_service.create_cipher_key(channel_id, current_operator, db, expires_in_seconds)


@router.post("/channels/join", response_model=OwnContactResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def join_via_cipher_key(
    request: Request,
    token: str = Query(..., description="Single-use cipher key token"),
    db: Session = Depends(get_db),
    current_operator: Operator = Depends(get_current_operator),
):
    """Join an encrypted channel using a controller-issued cipher key."""
    contact = cipher_key_service.join_via_cipher_key(token, current_operator, db)
    await hub.broadcast(contact.channel_id, {"op": "enter", "callsign": contact.callsign})
    return OwnContactResponse(
        callsign=contact.callsign,
        role=contact.role,
        entered_at=contact.entered_at,
        channel_id=contact.channel_id,
    )
