from fastapi import APIRouter, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from app.core.config import settings
from app.core.security import ALGORITHM

router = APIRouter(prefix="/debug", tags=["debug"])
http_bearer = HTTPBearer()


@router.get("/token-inspect")
def inspect_token(
    credentials: HTTPAuthorizationCredentials = Depends(http_bearer),
):
    token = credentials.credentials
    secret = settings.SECRET_KEY

    result = {
        "token_preview": token[:30] + "...",
        "secret_key_preview": secret[:6] + "..." if secret else "EMPTY OR MISSING",
        "secret_key_length": len(secret) if secret else 0,
    }

    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
        result["decode_success"] = True
        result["payload"] = payload
    except JWTError as e:
        result["decode_success"] = False
        result["error"] = str(e)

    return result