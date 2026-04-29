from fastapi import APIRouter, Body, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_operator, get_db
from app.core.limiter import limiter
from app.models.contact import ContactRole
from app.models.operator import Operator
from app.realtime.hub import hub
from app.schemas.contact import ContactResponse, OwnContactResponse
from app.schemas.channel import ChannelCreate, ChannelDetail, ChannelResponse
from app.services import channel_service

router = APIRouter(prefix="/channels", tags=["channels"])


@router.post("", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def open_channel(request: Request, payload: ChannelCreate,
                       db: Session = Depends(get_db),
                       current_operator: Operator = Depends(get_current_operator)):
    return channel_service.create_channel(payload, current_operator, db)


@router.get("", response_model=list[ChannelResponse])
@limiter.limit("60/minute")
async def list_channels(request: Request, db: Session = Depends(get_db),
                        current_operator: Operator = Depends(get_current_operator)):
    return channel_service.list_channels(current_operator, db)


@router.get("/{channel_id}", response_model=ChannelDetail)
@limiter.limit("60/minute")
async def get_channel(request: Request, channel_id: int,
                      db: Session = Depends(get_db),
                      current_operator: Operator = Depends(get_current_operator)):
    return channel_service.get_channel(channel_id, current_operator, db)


@router.post("/{channel_id}/enter", response_model=OwnContactResponse,
             status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def enter_channel(request: Request, channel_id: int,
                        db: Session = Depends(get_db),
                        current_operator: Operator = Depends(get_current_operator)):
    contact = channel_service.enter_channel(channel_id, current_operator, db)
    await hub.broadcast(channel_id, {"op": "enter", "callsign": contact.callsign})
    return OwnContactResponse(callsign=contact.callsign, role=contact.role,
                               entered_at=contact.entered_at, channel_id=contact.channel_id)


@router.delete("/{channel_id}/depart", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def depart_channel(request: Request, channel_id: int,
                         db: Session = Depends(get_db),
                         current_operator: Operator = Depends(get_current_operator)):
    callsign = channel_service.depart_channel(channel_id, current_operator, db)
    await hub.broadcast(channel_id, {"op": "depart", "callsign": callsign})


@router.get("/{channel_id}/contacts", response_model=list[ContactResponse])
@limiter.limit("60/minute")
async def list_contacts(request: Request, channel_id: int,
                        db: Session = Depends(get_db),
                        current_operator: Operator = Depends(get_current_operator)):
    return channel_service.list_contacts(channel_id, current_operator, db)


@router.get("/{channel_id}/contacts/me", response_model=OwnContactResponse)
@limiter.limit("60/minute")
async def get_own_contact(request: Request, channel_id: int,
                          db: Session = Depends(get_db),
                          current_operator: Operator = Depends(get_current_operator)):
    contact = channel_service.get_own_contact(channel_id, current_operator, db)
    return OwnContactResponse(callsign=contact.callsign, role=contact.role,
                               entered_at=contact.entered_at, channel_id=contact.channel_id)


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def dissolve_channel(request: Request, channel_id: int,
                           db: Session = Depends(get_db),
                           current_operator: Operator = Depends(get_current_operator)):
    await hub.broadcast(channel_id, {"op": "dissolve"})
    channel_service.dissolve_channel(channel_id, current_operator, db)


# ── Controller controls ────────────────────────────────────────────────────

@router.delete("/{channel_id}/contacts/{target_operator_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def kick_contact(request: Request, channel_id: int, target_operator_id: int,
                       db: Session = Depends(get_db),
                       current_operator: Operator = Depends(get_current_operator)):
    """Controller/relay: forcibly remove a Contact from the channel."""
    callsign = channel_service.kick_contact(channel_id, target_operator_id, current_operator, db)
    await hub.broadcast(channel_id, {"op": "depart", "callsign": callsign})


@router.post("/{channel_id}/transfer", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def transfer_controllership(
    request: Request, channel_id: int,
    target_operator_id: int = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_operator: Operator = Depends(get_current_operator),
):
    """Controller: hand controller role to another present Operator."""
    old_callsign, new_callsign = channel_service.transfer_controllership(channel_id, target_operator_id, current_operator, db)
    await hub.broadcast(channel_id, {"op": "promote", "callsign": old_callsign, "role": "listener"})
    await hub.broadcast(channel_id, {"op": "promote", "callsign": new_callsign, "role": "controller"})


@router.patch("/{channel_id}/contacts/{target_operator_id}/role", response_model=ContactResponse)
@limiter.limit("20/minute")
async def set_contact_role(
    request: Request, channel_id: int, target_operator_id: int,
    role: ContactRole = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_operator: Operator = Depends(get_current_operator),
):
    """Controller: promote a listener to relay, or demote a relay back."""
    contact = channel_service.set_contact_role(channel_id, target_operator_id, role, current_operator, db)
    await hub.broadcast(channel_id, {"op": "promote", "callsign": contact.callsign, "role": contact.role.value})
    return contact


# ── Callsign-based controller controls (frontend-friendly — no operator_id needed) ──

@router.delete("/{channel_id}/contacts/callsign/{callsign}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def kick_by_callsign(
    request: Request, channel_id: int, callsign: str,
    db: Session = Depends(get_db),
    current_operator: Operator = Depends(get_current_operator),
):
    """Controller/relay: kick a Contact by their visible callsign."""
    evicted = channel_service.kick_by_callsign(channel_id, callsign, current_operator, db)
    await hub.broadcast(channel_id, {"op": "depart", "callsign": evicted})


@router.post("/{channel_id}/transfer/callsign", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def transfer_controllership_by_callsign(
    request: Request, channel_id: int,
    target_callsign: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_operator: Operator = Depends(get_current_operator),
):
    """Controller: hand controller role to the Contact with the given callsign."""
    old_callsign, new_callsign = channel_service.transfer_controllership_by_callsign(channel_id, target_callsign, current_operator, db)
    await hub.broadcast(channel_id, {"op": "promote", "callsign": old_callsign, "role": "listener"})
    await hub.broadcast(channel_id, {"op": "promote", "callsign": new_callsign, "role": "controller"})


@router.patch("/{channel_id}/contacts/callsign/{callsign}/role", response_model=ContactResponse)
@limiter.limit("20/minute")
async def set_role_by_callsign(
    request: Request, channel_id: int, callsign: str,
    role: ContactRole = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_operator: Operator = Depends(get_current_operator),
):
    """Controller: promote/demote a Contact identified by callsign."""
    contact = channel_service.set_role_by_callsign(channel_id, callsign, role, current_operator, db)
    await hub.broadcast(channel_id, {"op": "promote", "callsign": contact.callsign, "role": contact.role.value})
    return contact
