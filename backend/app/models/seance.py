from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Seance(Base):
    """A gathering around the board. The room within which whispers travel.

    Public seances may be entered by any Seeker; sealed (private) seances
    require an explicit invitation from the warden.

    whisper_ttl_seconds — when set, whispers older than this many seconds
    are periodically soft-deleted by the background pruning task.
    """

    __tablename__ = "seances"

    id                  = Column(Integer, primary_key=True, index=True)
    name                = Column(String(100), unique=True, index=True, nullable=False)
    description         = Column(String(300), nullable=True)
    is_sealed           = Column(Boolean, default=False, nullable=False)
    whisper_ttl_seconds = Column(Integer, nullable=True)
    created_by          = Column(Integer, ForeignKey("seekers.id", ondelete="SET NULL"), nullable=True)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())

    warden    = relationship("Seeker", back_populates="warded_seances", foreign_keys=[created_by])
    presences = relationship("Presence", back_populates="seance", cascade="all, delete-orphan")
    whispers  = relationship("Whisper", back_populates="seance", cascade="all, delete-orphan")
    invites   = relationship("Invite", back_populates="seance", cascade="all, delete-orphan", foreign_keys="Invite.seance_id")
