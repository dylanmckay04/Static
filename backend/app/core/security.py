import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt
from jose import jwt, JWTError

from app.core.config import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours
SOCKET_TOKEN_EXPIRE_SECONDS = 60


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def _prehash(password: str) -> bytes:
    """SHA-256 hex digest of the password, encoded for bcrypt.

    bcrypt itself silently truncates inputs longer than 72 bytes; prehashing
    means we never lose entropy from long passphrases.
    """
    return hashlib.sha256(password.encode()).hexdigest().encode()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(_prehash(plain), hashed.encode())


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

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
    """Mint a one-time socket token and return ``(token, jti)``.

    The caller is responsible for registering ``jti`` in Redis so that the
    WebSocket endpoint can atomically consume it.
    """
    jti = uuid4().hex
    token = _create_signed_token(
        {**data, "jti": jti},
        timedelta(seconds=SOCKET_TOKEN_EXPIRE_SECONDS),
        "socket",
    )
    return token, jti


def _decode_token(token: str | None, expected_type: str) -> dict | None:
    """Decode a JWT, returning the payload dict or ``None`` on any failure.

    Returning ``None`` (rather than raising) keeps decoding cheap and free of
    HTTP semantics — callers that need an HTTP response (e.g. the FastAPI
    dependency) translate ``None`` into a 401 themselves.
    """
    if not token:
        return None

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

    if payload.get("token_type") != expected_type:
        return None
    return payload


def decode_access_token(token: str | None) -> dict | None:
    return _decode_token(token, "access")


def decode_socket_token(token: str | None) -> dict | None:
    return _decode_token(token, "socket")


def create_invite_token(data: dict, expires_delta_seconds: int) -> tuple[str, str]:
    """Mint a single-use invite token and return ``(token, jti)``.

    Unlike socket tokens (which live in Redis), invites are persisted in
    the ``invites`` DB table so they can be audited.
    """
    jti = uuid4().hex
    token = _create_signed_token(
        {**data, "jti": jti},
        timedelta(seconds=expires_delta_seconds),
        "invite",
    )
    return token, jti


def decode_invite_token(token: str | None) -> dict | None:
    return _decode_token(token, "invite")
