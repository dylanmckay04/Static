import secrets

import httpx
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token
from app.models.operator import Operator
from app.services.redis import redis_client

GITHUB_STATE_TTL = 600
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_USER_EMAILS_URL = "https://api.github.com/user/emails"


async def generate_github_login_url() -> dict:
    state = secrets.token_urlsafe(32)
    await redis_client.setex(f"github_oauth_state:{state}", GITHUB_STATE_TTL, "valid")
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": settings.GITHUB_REDIRECT_URI,
        "scope": "user:email",
        "state": state,
    }
    url = str(httpx.URL(GITHUB_AUTHORIZE_URL).copy_with(params=params))
    return {"url": url, "state": state}


async def _validate_state(state: str) -> None:
    value = await redis_client.getdel(f"github_oauth_state:{state}")
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state.",
        )


async def _exchange_code_for_token(code: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": settings.GITHUB_REDIRECT_URI,
            },
            headers={"Accept": "application/json"},
        )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitHub OAuth error: {data.get('error_description', data['error'])}",
        )
    return data["access_token"]


async def _fetch_github_user(github_token: str) -> tuple[str, str]:
    """Return (github_id_str, email). Falls back to /user/emails when email is private."""
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(GITHUB_USER_URL, headers=headers)
        user_resp.raise_for_status()
        user_data = user_resp.json()
        github_id = str(user_data["id"])
        email = user_data.get("email")

        if not email:
            emails_resp = await client.get(GITHUB_USER_EMAILS_URL, headers=headers)
            emails_resp.raise_for_status()
            emails = emails_resp.json()
            email = next(
                (e["email"] for e in emails if e.get("primary") and e.get("verified")),
                next((e["email"] for e in emails if e.get("verified")), None),
            )
            if not email:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Your GitHub account has no verified email address.",
                )

    return github_id, email


def _find_or_create_operator(github_id: str, email: str, db: Session) -> Operator:
    """Three-way lookup: by github_id → by email (link) → create new."""
    operator = db.query(Operator).filter(Operator.github_id == github_id).first()
    if operator:
        return operator

    operator = db.query(Operator).filter(Operator.email == email).first()
    if operator:
        operator.github_id = github_id
        db.commit()
        db.refresh(operator)
        return operator

    operator = Operator(email=email, hashed_password=None, github_id=github_id)
    db.add(operator)
    db.commit()
    db.refresh(operator)
    return operator


async def github_callback(code: str, state: str, db: Session) -> str:
    await _validate_state(state)
    github_token = await _exchange_code_for_token(code)
    github_id, email = await _fetch_github_user(github_token)
    operator = _find_or_create_operator(github_id, email, db)
    return create_access_token(data={"sub": str(operator.id)})
