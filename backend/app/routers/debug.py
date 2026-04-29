from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import settings
from app.core.dependencies import get_current_operator
from app.core.security import ALGORITHM
from app.models.operator import Operator

router = APIRouter(prefix="/debug", tags=["debug"])
http_bearer = HTTPBearer()


@router.get("/token-inspect")
def inspect_token(credentials: HTTPAuthorizationCredentials = Depends(http_bearer)):
    """Decode an access token and report what the server sees.

    Intended for local debugging only — do not enable in production.
    """
    token = credentials.credentials
    secret = settings.SECRET_KEY

    result: dict = {
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


@router.get("/me")
def get_current_operator_info(operator: Operator = Depends(get_current_operator)):
    """Return the current operator's ID and email.

    Intended for local debugging only — do not enable in production.
    """
    return {"id": operator.id, "email": operator.email}
