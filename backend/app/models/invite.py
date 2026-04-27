from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Invite(Base):
    """A single-use invitation token for a sealed Seance.

    The warden mints an Invite; a Seeker presents the token at
    POST /seances/join to gain a Presence. Once used, used_at is set and
    the token is rejected on any future attempt.

    jti — the JWT ID from the signed invite token; used for lookup and
    replay prevention.
    """

    __tablename__ = "invites"

    id         = Column(Integer, primary_key=True)
    seance_id  = Column(Integer, ForeignKey("seances.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("seekers.id", ondelete="SET NULL"), nullable=True)
    used_by    = Column(Integer, ForeignKey("seekers.id", ondelete="SET NULL"), nullable=True)
    jti        = Column(String(64), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at    = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    seance     = relationship("Seance", back_populates="invites", foreign_keys=[seance_id])
    creator    = relationship("Seeker", foreign_keys=[created_by])
    consumer   = relationship("Seeker", foreign_keys=[used_by])
