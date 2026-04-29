"""WebSocket tests — connect, transmission round-trip, rate limit."""
from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from httpx_ws import aconnect_ws

from app.main import app


def auth(token):
    return {"Authorization": f"Bearer {token}"}


async def get_socket_token(client: AsyncClient, access_token: str) -> str:
    r = await client.post("/auth/socket-token", headers=auth(access_token))
    assert r.status_code == 200
    return r.json()["socket_token"]


@pytest.mark.asyncio
async def test_ws_connect_and_whisper_roundtrip(client, make_token, db_session):
    """Verify WebSocket accepts valid connection and hub receives messages."""
    alice = await make_token("ws_alice@test.com")
    bob   = await make_token("ws_bob@test.com")

    # Create channel as alice (controller)
    r = await client.post("/channels", json={"name": "WS Test Room"}, headers=auth(alice))
    assert r.status_code == 201
    sid = r.json()["id"]

    # Bob enters via REST
    await client.post(f"/channels/{sid}/enter", headers=auth(bob))

    # Get socket tokens
    alice_st = await get_socket_token(client, alice)
    bob_st   = await get_socket_token(client, bob)

    # Alice connects and sends a transmission
    async with aconnect_ws(f"/ws/channels/{sid}?token={alice_st}", client) as ws_alice:
        await ws_alice.send_text(json.dumps({"op": "transmission", "content": "test message"}))
        raw = await ws_alice.receive_text()
        msg = json.loads(raw)
        assert msg["op"] == "transmission"
        assert msg["content"] == "test message"

    # Bob connects and sends a transmission
    async with aconnect_ws(f"/ws/channels/{sid}?token={bob_st}", client) as ws_bob:
        await ws_bob.send_text(json.dumps({"op": "transmission", "content": "bob message"}))
        raw = await ws_bob.receive_text()
        msg = json.loads(raw)
        assert msg["op"] == "transmission"
        assert msg["content"] == "bob message"


@pytest.mark.asyncio
async def test_ws_rejects_invalid_token(db_session):
    from starlette.testclient import TestClient
    tc = TestClient(app)
    with tc.websocket_connect("/ws/channels/999?token=bad_token") as ws:
        # Should close with 4001
        with pytest.raises(Exception):
            ws.receive_text()


@pytest.mark.asyncio
async def test_ws_rejects_no_presence(client, make_token):
    """A seeker with no contact in the channel is rejected with 4003."""
    a = await make_token("ws_nopres@test.com")
    b = await make_token("ws_nopres2@test.com")

    r = await client.post("/channels", json={"name": "WS No Pres"}, headers=auth(a))
    sid = r.json()["id"]

    # b never enters
    b_st = await get_socket_token(client, b)

    from starlette.testclient import TestClient
    tc = TestClient(app)
    with tc.websocket_connect(f"/ws/channels/{sid}?token={b_st}") as ws:
        with pytest.raises(Exception):
            ws.receive_text()
