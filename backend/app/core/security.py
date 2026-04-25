from datetime import datetime, timedelta, timezone
from uuid import uuid4
from jose import jwt, JWTError
from passlib.context import CryptContext
from app.config import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 hours
SOCKET_TOKEN_EXPIRE_SECONDS = 60

pwd_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _create_signed_token(data: dict, expires_delta: timedelta, token_type: str) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire, "token_type": token_type})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(data: dict) -> str:
    return _create_signed_token(
        data,
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "access",
    )
    

def create_socket_token(data: dict) -> tuple[str, str]:
    jti = uuid4().hex
    token = _create_signed_token(
        {**data, "jti": jti},
        timedelta(seconds=SOCKET_TOKEN_EXPIRE_SECONDS),
        "socket",
    )
    return token, jti


def _decode_token(token: str, expected_type: str) -> dict:
    if not token:
        return None
    
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("token_type") != expected_type:
            return None
        return payload
    except JWTError:
        return None


def decode_access_token(token: str) -> dict:
    return _decode_token(token, "access")


def decode_socket_token(token: str) -> dict:
    return _decode_token(token, "socket")
