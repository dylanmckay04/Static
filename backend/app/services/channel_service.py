from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.contact import Contact, ContactRole
from app.models.channel import Channel
from app.models.operator import Operator
from app.schemas.channel import ChannelCreate, ChannelDetail
from app.services.contact_service import assign_contact


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_channel_or_404(channel_id: int, db: Session) -> Channel:
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found.")
    return channel


def _get_contact(channel_id: int, operator_id: int, db: Session) -> Contact | None:
    return (
        db.query(Contact)
        .filter(Contact.channel_id == channel_id, Contact.operator_id == operator_id)
        .first()
    )


def _require_visibility(channel: Channel, operator_id: int, db: Session) -> Contact | None:
    contact = _get_contact(channel.id, operator_id, db)
    if channel.is_encrypted and contact is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This channel is encrypted. A cipher key is required.",
        )
    return contact


def _require_controller(channel: Channel, operator_id: int, db: Session) -> Contact:
    contact = _get_contact(channel.id, operator_id, db)
    if not contact or contact.role != ContactRole.controller:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the controller may perform this action.",
        )
    return contact


def _require_controller_or_relay(channel_id: int, operator_id: int, db: Session) -> Contact:
    contact = _get_contact(channel_id, operator_id, db)
    if not contact or contact.role == ContactRole.listener:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a controller or relay may perform this action.",
        )
    return contact


def _build_channel_detail(channel: Channel, db: Session) -> ChannelDetail:
    contact_count = db.query(Contact).filter(Contact.channel_id == channel.id).count()
    return ChannelDetail(
        id=channel.id,
        name=channel.name,
        description=channel.description,
        is_encrypted=channel.is_encrypted,
        transmission_ttl_seconds=channel.transmission_ttl_seconds,
        created_at=channel.created_at,
        contact_count=contact_count,
    )


# ---------------------------------------------------------------------------
# Public service surface
# ---------------------------------------------------------------------------

def create_channel(payload: ChannelCreate, current_operator: Operator, db: Session) -> Channel:
    existing = db.query(Channel).filter(Channel.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="A channel with this name already exists.")

    channel = Channel(
        name=payload.name,
        description=payload.description,
        is_encrypted=payload.is_encrypted,
        transmission_ttl_seconds=payload.transmission_ttl_seconds,
        created_by=current_operator.id,
    )
    db.add(channel)
    db.flush()

    assign_contact(operator_id=current_operator.id, channel_id=channel.id,
                   role=ContactRole.controller, db=db)
    db.commit()
    db.refresh(channel)
    return channel


def list_channels(current_operator: Operator, db: Session) -> list[Channel]:
    open_channels = db.query(Channel).filter(Channel.is_encrypted == False).all()  # noqa: E712
    encrypted_channels = (
        db.query(Channel)
        .join(Contact, Contact.channel_id == Channel.id)
        .filter(Channel.is_encrypted == True, Contact.operator_id == current_operator.id)  # noqa: E712
        .all()
    )
    by_id = {c.id: c for c in (open_channels + encrypted_channels)}
    return sorted(by_id.values(), key=lambda c: c.created_at)


def get_channel(channel_id: int, current_operator: Operator, db: Session) -> ChannelDetail:
    channel = _get_channel_or_404(channel_id, db)
    _require_visibility(channel, current_operator.id, db)
    return _build_channel_detail(channel, db)


def enter_channel(channel_id: int, current_operator: Operator, db: Session) -> Contact:
    channel = _get_channel_or_404(channel_id, db)

    if _get_contact(channel_id, current_operator.id, db):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="You are already in this channel. Depart before re-entering.")
    if channel.is_encrypted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This channel is encrypted. A cipher key is required.",
        )

    contact = assign_contact(operator_id=current_operator.id, channel_id=channel_id,
                              role=ContactRole.listener, db=db)
    db.commit()
    db.refresh(contact)
    return contact


def depart_channel(channel_id: int, current_operator: Operator, db: Session) -> str:
    contact = _get_contact(channel_id, current_operator.id, db)
    if not contact:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="You are not in this channel.")
    if contact.role == ContactRole.controller:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The controller cannot depart. Dissolve the channel or transfer controllership first.",
        )
    callsign = contact.callsign
    db.delete(contact)
    db.commit()
    return callsign


def list_contacts(channel_id: int, current_operator: Operator, db: Session) -> list[Contact]:
    channel = _get_channel_or_404(channel_id, db)
    _require_visibility(channel, current_operator.id, db)
    return (
        db.query(Contact)
        .filter(Contact.channel_id == channel_id)
        .order_by(Contact.entered_at.asc())
        .all()
    )


def dissolve_channel(channel_id: int, current_operator: Operator, db: Session) -> None:
    channel = _get_channel_or_404(channel_id, db)
    _require_controller(channel, current_operator.id, db)
    db.delete(channel)
    db.commit()


def get_own_contact(channel_id: int, current_operator: Operator, db: Session) -> Contact:
    _get_channel_or_404(channel_id, db)
    contact = _get_contact(channel_id, current_operator.id, db)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="You are not in this channel.")
    return contact


# ---------------------------------------------------------------------------
# Controller controls
# ---------------------------------------------------------------------------

def kick_contact(
    channel_id: int,
    target_operator_id: int,
    current_operator: Operator,
    db: Session,
) -> str:
    """Remove another operator's contact. Returns the evicted callsign for broadcast."""
    _get_channel_or_404(channel_id, db)
    actor_contact = _require_controller_or_relay(channel_id, current_operator.id, db)

    target_contact = _get_contact(channel_id, target_operator_id, db)
    if not target_contact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="That operator is not in this channel.")
    if target_operator_id == current_operator.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="You cannot kick yourself.")
    if target_contact.role == ContactRole.controller:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="The controller cannot be kicked.")
    if (target_contact.role == ContactRole.relay
            and actor_contact.role != ContactRole.controller):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only the controller can remove a relay.")

    callsign = target_contact.callsign
    db.delete(target_contact)
    db.commit()
    return callsign


def transfer_controllership(
    channel_id: int,
    target_operator_id: int,
    current_operator: Operator,
    db: Session,
) -> tuple[str, str]:
    """Hand controller role to another contact. Returns (old_callsign, new_callsign)."""
    channel = _get_channel_or_404(channel_id, db)
    controller_contact = _require_controller(channel, current_operator.id, db)

    target_contact = _get_contact(channel_id, target_operator_id, db)
    if not target_contact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Target operator is not in this channel.")
    if target_operator_id == current_operator.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="You are already the controller.")

    controller_contact.role = ContactRole.listener
    target_contact.role = ContactRole.controller
    channel.created_by = target_operator_id
    db.commit()
    return controller_contact.callsign, target_contact.callsign


def set_contact_role(
    channel_id: int,
    target_operator_id: int,
    new_role: ContactRole,
    current_operator: Operator,
    db: Session,
) -> Contact:
    """Controller-only: set a contact's role to listener or relay."""
    channel = _get_channel_or_404(channel_id, db)
    _require_controller(channel, current_operator.id, db)

    if new_role == ContactRole.controller:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use POST /transfer to hand off controllership.",
        )

    target = _get_contact(channel_id, target_operator_id, db)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Target operator is not in this channel.")
    if target.role == ContactRole.controller:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Cannot demote the controller directly. Use /transfer first.")

    target.role = new_role
    db.commit()
    db.refresh(target)
    return target


def kick_by_callsign(
    channel_id: int,
    callsign: str,
    current_operator: Operator,
    db: Session,
) -> str:
    """Kick a contact identified by callsign. Returns the callsign for broadcast."""
    _get_channel_or_404(channel_id, db)
    actor = _require_controller_or_relay(channel_id, current_operator.id, db)

    target = (
        db.query(Contact)
        .filter(Contact.channel_id == channel_id, Contact.callsign == callsign)
        .first()
    )
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No contact with that callsign.")
    if target.operator_id == current_operator.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="You cannot kick yourself.")
    if target.role == ContactRole.controller:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="The controller cannot be kicked.")
    if target.role == ContactRole.relay and actor.role != ContactRole.controller:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only the controller can remove a relay.")

    db.delete(target)
    db.commit()
    return callsign


def transfer_controllership_by_callsign(
    channel_id: int,
    target_callsign: str,
    current_operator: Operator,
    db: Session,
) -> tuple[str, str]:
    """Transfer controllership to the contact with the given callsign."""
    channel = _get_channel_or_404(channel_id, db)
    controller_contact = _require_controller(channel, current_operator.id, db)

    target = (
        db.query(Contact)
        .filter(Contact.channel_id == channel_id, Contact.callsign == target_callsign)
        .first()
    )
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No contact with that callsign.")
    if target.operator_id == current_operator.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="You are already the controller.")

    controller_contact.role = ContactRole.listener
    target.role = ContactRole.controller
    channel.created_by = target.operator_id
    db.commit()
    return controller_contact.callsign, target.callsign


def set_role_by_callsign(
    channel_id: int,
    target_callsign: str,
    new_role: ContactRole,
    current_operator: Operator,
    db: Session,
) -> Contact:
    """Controller: promote/demote a contact identified by callsign."""
    channel = _get_channel_or_404(channel_id, db)
    _require_controller(channel, current_operator.id, db)

    if new_role == ContactRole.controller:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Use /transfer to hand off controllership.")

    target = (
        db.query(Contact)
        .filter(Contact.channel_id == channel_id, Contact.callsign == target_callsign)
        .first()
    )
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No contact with that callsign.")
    if target.role == ContactRole.controller:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Cannot demote the controller directly. Use /transfer first.")

    target.role = new_role
    db.commit()
    db.refresh(target)
    return target
