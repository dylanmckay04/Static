from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_operator, get_db
from app.core.limiter import limiter
from app.core.metrics import SOCKET_TOKENS_TOTAL
from app.models.operator import Operator
from app.schemas.auth import GitHubCallbackRequest, GitHubLoginURLResponse, GoogleCallbackRequest, GoogleLoginURLResponse, LoginRequest, SocketTokenResponse, TokenResponse
from app.schemas.operator import OperatorCreate, OperatorResponse
from app.services.auth_service import issue_socket_token, login_operator, register_operator
from app.services.github_service import generate_github_login_url, github_callback
from app.services.google_service import generate_google_login_url, google_callback


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=OperatorResponse, status_code=201)
@limiter.limit("10/minute")
async def register(
    request: Request,
    payload: OperatorCreate,
    db: Session = Depends(get_db),
):
    return register_operator(payload, db)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("20/minute")
async def login(
    request: Request,
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    access_token = login_operator(payload.email, payload.password, db)
    return TokenResponse(access_token=access_token)


@router.get("/github", response_model=GitHubLoginURLResponse)
@limiter.limit("20/minute")
async def github_login(request: Request):
    return await generate_github_login_url()


@router.post("/github/callback", response_model=TokenResponse)
@limiter.limit("20/minute")
async def github_login_callback(
    request: Request,
    payload: GitHubCallbackRequest,
    db: Session = Depends(get_db),
):
    access_token = await github_callback(payload.code, payload.state, db)
    return TokenResponse(access_token=access_token)


@router.get("/google", response_model=GoogleLoginURLResponse)
@limiter.limit("20/minute")
async def google_login(request: Request):
    return await generate_google_login_url()


@router.post("/google/callback", response_model=TokenResponse)
@limiter.limit("20/minute")
async def google_login_callback(
    request: Request,
    payload: GoogleCallbackRequest,
    db: Session = Depends(get_db),
):
    access_token = await google_callback(payload.code, payload.state, db)
    return TokenResponse(access_token=access_token)


@router.post("/socket-token", response_model=SocketTokenResponse)
@limiter.limit("30/minute")
async def get_socket_token(
    request: Request,
    current_operator: Operator = Depends(get_current_operator),
):
    token, jti = await issue_socket_token(current_operator)
    SOCKET_TOKENS_TOTAL.labels(event="minted").inc()
    return SocketTokenResponse(socket_token=token, jti=jti)
