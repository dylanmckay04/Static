from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Transmission(Base):
    """A single message within a Channel.

    Public-facing fields are callsign + content + timestamps. operator_id is
    held only for moderation and audit; schemas never expose it. A transmission
    survives the Contact that sent it, so the callsign at the time of posting is
    snapshotted onto the row rather than joined-in at read time.

    deleted_at is set (soft-delete) when a controller or relay redacts a
    transmission. The row is retained for audit; content is replaced with a
    sentinel in API responses.
    """

    __tablename__ = "transmissions"
    __table_args__ = (Index("ix_transmissions_channel_id_id", "channel_id", "id"),)

    id          = Column(Integer, primary_key=True, index=True)
    content     = Column(Text, nullable=False)
    callsign    = Column(String(80), nullable=False)
    channel_id  = Column(Integer, ForeignKey("channels.id", ondelete="CASCADE"), nullable=False)
    operator_id = Column(Integer, ForeignKey("operators.id", ondelete="SET NULL"), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    deleted_at  = Column(DateTime(timezone=True), nullable=True)

    operator = relationship("Operator", back_populates="transmissions")
    channel  = relationship("Channel", back_populates="transmissions")
