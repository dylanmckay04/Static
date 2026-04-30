"""GitHub OAuth tests — URL generation, callback (3 linking cases), error paths."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

import app.services.redis as _redis_module
from app.models.operator import Operator

GITHUB_USER_DATA = {"id": 12345, "email": "gh@example.com", "login": "ghuser"}
GITHUB_EMAILS_DATA = [{"email": "gh@example.com", "primary": True, "verified": True}]
FAKE_GH_TOKEN = "gha_fake_token"


def _mock_github_http(
    token_json=None,
    user_json=None,
    emails_json=None,
):
    token_resp = MagicMock()
    token_resp.raise_for_status = MagicMock()
    token_resp.json.return_value = token_json or {"access_token": FAKE_GH_TOKEN}

    user_resp = MagicMock()
    user_resp.raise_for_status = MagicMock()
    user_resp.json.return_value = user_json if user_json is not None else GITHUB_USER_DATA

    emails_resp = MagicMock()
    emails_resp.raise_for_status = MagicMock()
    emails_resp.json.return_value = emails_json or GITHUB_EMAILS_DATA

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=token_resp)
    mock_client.get = AsyncMock(side_effect=[user_resp, emails_resp])
    return mock_client


@pytest_asyncio.fixture()
async def valid_state():
    state = "test_state_abc123xyz"
    await _redis_module.redis_client.setex(f"github_oauth_state:{state}", 600, "valid")
    return state


@pytest.mark.asyncio
async def test_github_login_url_returns_url_and_state(client):
    r = await client.get("/auth/github")
    assert r.status_code == 200
    body = r.json()
    assert "github.com/login/oauth/authorize" in body["url"]
    assert "state" in body and len(body["state"]) > 10


@pytest.mark.asyncio
async def test_github_callback_creates_new_operator(client, db_session, valid_state):
    with patch("app.services.github_service.httpx.AsyncClient", return_value=_mock_github_http()):
        r = await client.post(
            "/auth/github/callback",
            json={"code": "abc", "state": valid_state},
        )
    assert r.status_code == 200
    assert "access_token" in r.json()

    operator = db_session.query(Operator).filter(Operator.github_id == "12345").first()
    assert operator is not None
    assert operator.email == "gh@example.com"
    assert operator.hashed_password is None


@pytest.mark.asyncio
async def test_github_callback_links_existing_email_account(client, db_session, valid_state):
    await client.post("/auth/register", json={"email": "gh@example.com", "password": "hunter2"})
    existing = db_session.query(Operator).filter(Operator.email == "gh@example.com").first()
    assert existing.github_id is None
    existing_id = existing.id

    with patch("app.services.github_service.httpx.AsyncClient", return_value=_mock_github_http()):
        r = await client.post(
            "/auth/github/callback",
            json={"code": "abc", "state": valid_state},
        )
    assert r.status_code == 200

    db_session.refresh(existing)
    assert existing.github_id == "12345"
    assert existing.id == existing_id


@pytest.mark.asyncio
async def test_github_callback_logs_in_already_linked_account(client, db_session, valid_state):
    operator = Operator(email="linked@example.com", hashed_password=None, github_id="12345")
    db_session.add(operator)
    db_session.commit()

    with patch("app.services.github_service.httpx.AsyncClient", return_value=_mock_github_http()):
        r = await client.post(
            "/auth/github/callback",
            json={"code": "abc", "state": valid_state},
        )
    assert r.status_code == 200
    count = db_session.query(Operator).filter(Operator.github_id == "12345").count()
    assert count == 1


@pytest.mark.asyncio
async def test_github_callback_invalid_state(client):
    r = await client.post(
        "/auth/github/callback",
        json={"code": "abc", "state": "totally_bogus_state"},
    )
    assert r.status_code == 400
    assert "state" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_github_callback_invalid_code(client, valid_state):
    bad_token_resp = MagicMock()
    bad_token_resp.raise_for_status = MagicMock()
    bad_token_resp.json.return_value = {
        "error": "bad_verification_code",
        "error_description": "The code passed is incorrect or expired.",
    }
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=bad_token_resp)

    with patch("app.services.github_service.httpx.AsyncClient", return_value=mock_client):
        r = await client.post(
            "/auth/github/callback",
            json={"code": "bad_code", "state": valid_state},
        )
    assert r.status_code == 400
    assert "GitHub OAuth error" in r.json()["detail"]


@pytest.mark.asyncio
async def test_github_only_account_cannot_use_password_login(client, db_session, valid_state):
    with patch("app.services.github_service.httpx.AsyncClient", return_value=_mock_github_http()):
        await client.post(
            "/auth/github/callback",
            json={"code": "abc", "state": valid_state},
        )

    r = await client.post(
        "/auth/login",
        json={"email": "gh@example.com", "password": "anypassword"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_github_callback_private_email_fallback(client, db_session, valid_state):
    user_no_email = {"id": 99999, "email": None, "login": "private_gh_user"}
    private_emails = [{"email": "private@example.com", "primary": True, "verified": True}]

    with patch(
        "app.services.github_service.httpx.AsyncClient",
        return_value=_mock_github_http(user_json=user_no_email, emails_json=private_emails),
    ):
        r = await client.post(
            "/auth/github/callback",
            json={"code": "abc", "state": valid_state},
        )
    assert r.status_code == 200

    operator = db_session.query(Operator).filter(Operator.github_id == "99999").first()
    assert operator is not None
    assert operator.email == "private@example.com"
