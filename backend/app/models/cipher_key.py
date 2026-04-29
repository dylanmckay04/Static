from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class CipherKey(Base):
    """A single-use invitation token for an encrypted Channel.

    The controller mints a CipherKey; an Operator presents the token at
    POST /channels/join to gain a Contact. Once used, used_at is set and
    the token is rejected on any future attempt.

    jti — the JWT ID from the signed cipher key token; used for lookup and
    replay prevention.
    """

    __tablename__ = "cipher_keys"

    id         = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("operators.id", ondelete="SET NULL"), nullable=True)
    used_by    = Column(Integer, ForeignKey("operators.id", ondelete="SET NULL"), nullable=True)
    jti        = Column(String(64), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at    = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    channel  = relationship("Channel", back_populates="cipher_keys", foreign_keys=[channel_id])
    creator  = relationship("Operator", foreign_keys=[created_by])
    consumer = relationship("Operator", foreign_keys=[used_by])
