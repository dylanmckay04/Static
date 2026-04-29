from sqlalchemy import Column, String, Integer, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Operator(Base):
    __tablename__ = "operators"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    controlled_channels = relationship("Channel", back_populates="controller", foreign_keys="Channel.created_by")
    contacts = relationship("Contact", back_populates="operator", cascade="all, delete-orphan")
    transmissions = relationship("Transmission", back_populates="operator")
