from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_user
from app.core.limiter import limiter
from app.models.user import User
from app.schemas.room import RoomCreate, RoomResponse, RoomDetail
from app.schemas.room_member import RoomMemberResponse
from app.services import room_service

router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.post("", response_model=RoomResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_room(
    payload: RoomCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return room_service.create_room(payload, current_user, db)


@router.get("", response_model=list[RoomResponse])
@limiter.limit("60/minute")
async def list_rooms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return room_service.list_rooms(current_user, db)


@router.get("/{room_id}", response_model=RoomDetail)
@limiter.limit("60/minute")
async def get_room(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return room_service.get_room(room_id, current_user, db)


@router.post("/{room_id}/join", response_model=RoomMemberResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def join_room(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return room_service.join_room(room_id, current_user, db)


@router.delete("/{room_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def leave_room(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    room_service.leave_room(room_id, current_user, db)


@router.get("/{room_id}/members", response_model=list[RoomMemberResponse])
@limiter.limit("60/minute")
async def get_members(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    room_service.get_members(room_id, current_user, db)


@router.delete("/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def delete_room(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    room_service.delete_room(room_id, current_user, db)
