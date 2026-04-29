import enum

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class ContactRole(str, enum.Enum):
    controller = "controller"  # opened the channel, holds the keys
    relay      = "relay"       # can kick listeners, redact transmissions; cannot dissolve
    listener   = "listener"    # ordinary participant


class Contact(Base):
    """An Operator's anonymous identity within a single Channel.

    The callsign is the only identifier other participants see. It is generated
    fresh each time an Operator enters the channel, so leaving and returning
    yields a different callsign. The operator_id is retained for moderation and
    is never exposed in the public API.
    """

    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("channel_id", "callsign", name="uq_contact_channel_callsign"),)

    operator_id = Column(Integer, ForeignKey("operators.id", ondelete="CASCADE"), primary_key=True)
    channel_id  = Column(Integer, ForeignKey("channels.id", ondelete="CASCADE"), primary_key=True)
    callsign    = Column(String(80), nullable=False)
    role        = Column(Enum(ContactRole, name="contactrole"), default=ContactRole.listener, nullable=False)
    entered_at  = Column(DateTime(timezone=True), server_default=func.now())

    operator = relationship("Operator", back_populates="contacts")
    channel  = relationship("Channel", back_populates="contacts")
