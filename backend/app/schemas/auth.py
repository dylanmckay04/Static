from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SocketTokenResponse(BaseModel):
    """Short-lived, single-use token for opening a WebSocket to a Seance."""

    socket_token: str
    jti: str


class GitHubLoginURLResponse(BaseModel):
    url: str
    state: str


class GitHubCallbackRequest(BaseModel):
    code: str
    state: str
