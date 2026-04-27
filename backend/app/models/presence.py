import enum

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class PresenceRole(str, enum.Enum):
    warden    = "warden"      # opened the seance, holds the keys
    moderator = "moderator"   # can kick attendants, redact whispers; cannot dissolve
    attendant = "attendant"   # ordinary participant


class Presence(Base):
    """A Seeker's manifestation within a single Seance.

    The sigil is the only identifier other participants see. It is generated
    fresh each time a Seeker enters the seance, so leaving and returning
    yields a different name. The seeker_id is retained for moderation and
    is never exposed in the public API.
    """

    __tablename__ = "presences"
    __table_args__ = (UniqueConstraint("seance_id", "sigil", name="uq_presence_seance_sigil"),)

    seeker_id = Column(Integer, ForeignKey("seekers.id", ondelete="CASCADE"), primary_key=True)
    seance_id = Column(Integer, ForeignKey("seances.id", ondelete="CASCADE"), primary_key=True)
    sigil     = Column(String(80), nullable=False)
    role      = Column(Enum(PresenceRole, name="presencerole"), default=PresenceRole.attendant, nullable=False)
    entered_at = Column(DateTime(timezone=True), server_default=func.now())

    seeker = relationship("Seeker", back_populates="presences")
    seance = relationship("Seance", back_populates="presences")
