import enum
from sqlalchemy import Column, Integer, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class MemberRole(str, enum.Enum):
    owner = "owner"
    member = "member"


class RoomMember(Base):
    __tablename__ = "room_members"
    
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    room_id = Column(Integer, ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True)
    role = Column(Enum(MemberRole), default=MemberRole.member, nullable=False)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    
    
    user = relationship("User", back_populates="room_members")
    room = relationship("Room", back_populates="members")
