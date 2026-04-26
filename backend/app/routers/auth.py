from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_user
from app.core.limiter import limiter
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, SocketTokenResponse
from app.schemas.user import UserCreate, UserResponse
from app.services.auth_service import register_user, login_user, issue_socket_tocken

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=201)
@limiter.limit("10/minute")
async def register(
    request: Request,
    payload: UserCreate,
    db: Session = Depends(get_db)
):
    user = register_user(payload, db)
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit("20/minute")
async def login(
    request: Request,
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    access_token = login_user(payload.email, payload.password, db)
    return TokenResponse(access_token=access_token)


@router.post("/socket-token", response_model=SocketTokenResponse)
@limiter.limit("30/minute")
async def get_socket_token(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    token, jti = await issue_socket_tocken(current_user)
    return SocketTokenResponse(socket_token=token, jti=jti)
