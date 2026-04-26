from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_socket_token,
    SOCKET_TOKEN_EXPIRE_SECONDS,
)
from app.services.redis import redis_client
from app.models.user import User
from app.schemas.user import UserCreate


def register_user(payload: UserCreate, db: Session) -> User:
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )
    
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def login_user(email: str, password: str, db: Session) -> str:
    """Validate credentials and return a signed access token."""
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password."
        )
    
    return create_access_token(data={"sub": str(user.id)})


async def issue_socket_tocken(user: User) -> tuple[str, str]:
    """
    Create a short-lived socket token and register its JTI in Redis.
 
    The JTI is stored with a TTL matching the token lifetime so that
    the WebSocket endpoint can verify the token has not already been
    consumed (one-time-use).
    """
    token, jti = create_socket_token(data={"sub": str(user.id)})
    
    await redis_client.setex(
        f"socket_id:{jti}",
        SOCKET_TOKEN_EXPIRE_SECONDS + 5,
        "valid",
    )
    
    return token, jti
