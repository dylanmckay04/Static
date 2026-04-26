from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.room import Room
from app.models.room_member import RoomMember, MemberRole
from app.models.user import User
from app.schemas.room import RoomCreate, RoomDetail


# Internal Helpers

def _get_room_or_404(room_id: int, db: Session) -> Room:
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found"
        )
    return room


def _get_membership(room_id: int, user_id: int, db: Session) -> RoomMember | None:
    return (
        db.query(RoomMember)
        .filter(RoomMember.room_id == room_id, RoomMember.user_id == user_id)
        .first()
    )


def _require_membership(room: Room, user_id: int, db: Session) -> RoomMember:
    """Raise 403 if the user is not a member of a private room."""
    if not room.is_private:
        membership = _get_membership(room.id, user_id, db)
        return membership
    
    membership = _get_membership(room.id, user_id, db)
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this room.",
        )
    return membership


def _require_owner(room: Room, user_id: int, db: Session) -> RoomMember:
    membership = _get_membership(room.id, user_id, db)
    if not membership or membership.role != MemberRole.owner:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Only the room owner can perform this action.",
        )
    return membership


def _build_room_detail(room: Room, db: Session) -> RoomDetail:
    """Construct a RoomDetail, computing member_count from the DB."""
    member_count = (
        db.query(RoomMember).filter(RoomMember.room_id == room.id).count()
    )
    return RoomDetail(
        id=room.id,
        name=room.name,
        description=room.description,
        is_private=room.is_private,
        created_at=room.created_at,
        creator=room.creator,
        member_count=member_count,
    )
    

# Create

def create_room(payload: RoomCreate, current_user: User, db: Session) -> Room:
    existing = db.query(Room).filter(Room.name == payload.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A room with this name already exists.",
        )
    
    room = Room(
        name=payload.name,
        description=payload.description,
        is_private=payload.is_private,
        created_by=current_user.id,
    )
    db.add(room)
    db.flush()
    
    membership = RoomMember(
        user_id=current_user.id,
        room_id=room.id,
        role=MemberRole.owner,
    )
    db.add(membership)
    db.commit()
    db.refresh(room)
    return room


# List

def list_rooms(current_user: User, db: Session) -> list[Room]:
    """Return all public rooms plus any private rooms the user belongs to."""
    public_rooms = db.query(Room).filter(Room.is_private == False).all()
    
    private_rooms = (
        db.query(Room)
        .join(RoomMember, RoomMember.room_id == Room.id)
        .filter(
            Room.is_private == True,
            RoomMember.user_id == current_user.id
        )
        .all()
    )
    
    # Deduplicate rooms by ID using a dict
    rooms_dict = {room.id: room for room in (public_rooms + private_rooms)}
    
    # Sort by creation date and return
    return sorted(rooms_dict.values(), key=lambda r: r.created_at)


# Get single room

def get_room(room_id: int, current_user: User, db: Session) -> RoomDetail:
    room = _get_room_or_404(room_id, db)
    _require_membership(room, current_user.id, db)
    return _build_room_detail(room, db)


# Join

def join_room(room_id: int, current_user: User, db: Session) -> RoomMember:
    room = _get_room_or_404(room_id, db)
    
    if room.is_private:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This room is private. You must be invited to join.",
        )
    
    existing = _get_membership(room_id, current_user.id, db)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already a member of this room.",
        )
    
    membership = RoomMember(
        user_id=current_user.id,
        room_id=room_id,
        role=MemberRole.member,
    )
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership


# Leave

def leave_room(room_id: int, current_user: User, db: Session) -> None:
    membership = _get_membership(room_id, current_user.id, db)
    
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are not a member of this room."
        )
    
    if membership.role == MemberRole.owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Room owners cannot leave. "
                "Delete the room or transfer ownership first."
            ),
        )
    
    db.delete(membership)
    db.commit()


# Get members

def get_members(room_id: int, current_user: User, db: Session) -> list[RoomMember]:
    room = _get_room_or_404(room_id, db)
    _require_membership(room, current_user.id, db)
    return db.query(RoomMember).filter(RoomMember.room_id == room_id).all()


# Delete room

def delete_room(room_id: int, current_user: User, db: Session):
    room = _get_room_or_404(room_id, db)
    _require_owner(room, current_user.id, db)
    db.delete(room)
    db.commit()

