from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Whisper(Base):
    """A single utterance within a Seance.

    Public-facing fields are sigil + content + timestamps. seeker_id is held
    only for moderation and audit; the schemas never expose it. A whisper
    survives the Presence that uttered it, so the sigil at the time of
    utterance is snapshotted onto the row rather than joined-in at read time.

    deleted_at is set (soft-delete) when a warden or moderator redacts a
    whisper. The row is retained for audit; the content is replaced with a
    sentinel in API responses.
    """

    __tablename__ = "whispers"
    __table_args__ = (Index("ix_whispers_seance_id_id", "seance_id", "id"),)

    id         = Column(Integer, primary_key=True, index=True)
    content    = Column(Text, nullable=False)
    sigil      = Column(String(80), nullable=False)
    seance_id  = Column(Integer, ForeignKey("seances.id", ondelete="CASCADE"), nullable=False)
    seeker_id  = Column(Integer, ForeignKey("seekers.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    seeker = relationship("Seeker", back_populates="whispers")
    seance = relationship("Seance", back_populates="whispers")
