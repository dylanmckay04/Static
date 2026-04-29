from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Channel(Base):
    """A chat room. Can be open or encrypted (is_encrypted=True).

    transmission_ttl_seconds — when set, transmissions older than this many
    seconds are periodically soft-deleted by the background pruning task.
    """

    __tablename__ = "channels"

    id                       = Column(Integer, primary_key=True, index=True)
    name                     = Column(String(100), unique=True, index=True, nullable=False)
    description              = Column(String(300), nullable=True)
    is_encrypted             = Column(Boolean, default=False, nullable=False)
    transmission_ttl_seconds = Column(Integer, nullable=True)
    created_by               = Column(Integer, ForeignKey("operators.id", ondelete="SET NULL"), nullable=True)
    created_at               = Column(DateTime(timezone=True), server_default=func.now())

    controller   = relationship("Operator", back_populates="controlled_channels", foreign_keys=[created_by])
    contacts     = relationship("Contact", back_populates="channel", cascade="all, delete-orphan")
    transmissions = relationship("Transmission", back_populates="channel", cascade="all, delete-orphan")
    cipher_keys  = relationship("CipherKey", back_populates="channel", cascade="all, delete-orphan", foreign_keys="CipherKey.channel_id")
