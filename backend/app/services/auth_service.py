from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import (
    SOCKET_TOKEN_EXPIRE_SECONDS,
    create_access_token,
    create_socket_token,
    hash_password,
    verify_password,
)
from app.models.operator import Operator
from app.schemas.operator import OperatorCreate
from app.services.redis import redis_client


def register_operator(payload: OperatorCreate, db: Session) -> Operator:
    existing = db.query(Operator).filter(Operator.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    operator = Operator(
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )
    db.add(operator)
    db.commit()
    db.refresh(operator)
    return operator


def login_operator(email: str, password: str, db: Session) -> str:
    """Validate credentials and return a signed access token."""
    operator = db.query(Operator).filter(Operator.email == email).first()
    if (
        not operator
        or operator.hashed_password is None
        or not verify_password(password, operator.hashed_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    return create_access_token(data={"sub": str(operator.id)})


async def issue_socket_token(operator: Operator) -> tuple[str, str]:
    """Mint a short-lived socket token and register its JTI in Redis."""
    token, jti = create_socket_token(data={"sub": str(operator.id)})

    await redis_client.setex(
        f"socket_jti:{jti}",
        SOCKET_TOKEN_EXPIRE_SECONDS + 5,
        "valid",
    )

    return token, jti
