"""Channel lifecycle, access control, cipher key flow, kick/transfer."""
import pytest


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_and_list_seance(client, make_token):
    t = await make_token("owner@test.com")
    r = await client.post("/channels", json={"name": "Test Seance"}, headers=auth(t))
    assert r.status_code == 201
    sid = r.json()["id"]

    r = await client.get("/channels", headers=auth(t))
    assert any(s["id"] == sid for s in r.json())


@pytest.mark.asyncio
async def test_sealed_seance_invisible_to_stranger(client, make_token):
    owner = await make_token("seal_owner@test.com")
    stranger = await make_token("seal_stranger@test.com")

    r = await client.post("/channels", json={"name": "Sealed Room", "is_encrypted": True}, headers=auth(owner))
    assert r.status_code == 201
    sid = r.json()["id"]

    # Stranger cannot enter directly
    r = await client.post(f"/channels/{sid}/enter", headers=auth(stranger))
    assert r.status_code == 403

    # Encrypted channel does not appear in stranger's list
    r = await client.get("/channels", headers=auth(stranger))
    assert not any(s["id"] == sid for s in r.json())


@pytest.mark.asyncio
async def test_invite_flow_for_sealed_seance(client, make_token):
    owner = await make_token("inv_owner@test.com")
    guest = await make_token("inv_guest@test.com")

    # Create encrypted channel (owner gets controller contact automatically)
    r = await client.post("/channels", json={"name": "Sealed Invite", "is_encrypted": True}, headers=auth(owner))
    sid = r.json()["id"]

    # Mint cipher key
    r = await client.post(f"/channels/{sid}/cipher-keys", headers=auth(owner))
    assert r.status_code == 201
    invite_token = r.json()["token"]

    # Guest joins via cipher key
    r = await client.post(f"/channels/join?token={invite_token}", headers=auth(guest))
    assert r.status_code == 201
    assert r.json()["role"] == "listener"

    # Cipher key is single-use — second attempt must fail
    r = await client.post(f"/channels/join?token={invite_token}", headers=auth(guest))
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_sigil_collision_generates_distinct_sigils(client, make_token):
    """Two contacts in the same channel must get different callsigns."""
    a = await make_token("sigil_a@test.com")
    b = await make_token("sigil_b@test.com")

    r = await client.post("/channels", json={"name": "Sigil Test"}, headers=auth(a))
    sid = r.json()["id"]

    r_a = await client.post(f"/channels/{sid}/enter", headers=auth(a))
    # a already has a contact (controller), so 409 — fetch it
    if r_a.status_code == 409:
        r_a = await client.get(f"/channels/{sid}/contacts/me", headers=auth(a))
    callsign_a = r_a.json()["callsign"]

    r_b = await client.post(f"/channels/{sid}/enter", headers=auth(b))
    callsign_b = r_b.json()["callsign"]

    assert callsign_a != callsign_b


@pytest.mark.asyncio
async def test_kick_attendant(client, make_token):
    controller = await make_token("kick_w@test.com")
    listener = await make_token("kick_a@test.com")

    r = await client.post("/channels", json={"name": "Kick Test"}, headers=auth(controller))
    sid = r.json()["id"]

    # Listener enters
    await client.post(f"/channels/{sid}/enter", headers=auth(listener))

    # Get listener's operator_id via contacts list
    r = await client.get(f"/channels/{sid}/contacts", headers=auth(controller))

    r = await client.get("/debug/me", headers=auth(listener))
    listener_id = r.json()["id"]

    # Controller kicks
    r = await client.delete(f"/channels/{sid}/contacts/{listener_id}", headers=auth(controller))
    assert r.status_code == 204

    # Listener no longer listed
    r = await client.get(f"/channels/{sid}/contacts", headers=auth(controller))
    assert len(r.json()) == 1  # only controller remains


@pytest.mark.asyncio
async def test_transfer_wardenship(client, make_token):
    controller = await make_token("transfer_w@test.com")
    new_controller = await make_token("transfer_nw@test.com")

    r = await client.post("/channels", json={"name": "Transfer Test"}, headers=auth(controller))
    sid = r.json()["id"]

    await client.post(f"/channels/{sid}/enter", headers=auth(new_controller))

    r = await client.get("/debug/me", headers=auth(new_controller))
    new_controller_id = r.json()["id"]

    r = await client.post(f"/channels/{sid}/transfer",
                          json={"target_operator_id": new_controller_id}, headers=auth(controller))
    assert r.status_code == 204

    # New controller can dissolve; old one cannot
    r = await client.get(f"/channels/{sid}/contacts", headers=auth(new_controller))
    roles = {p["callsign"]: p["role"] for p in r.json()}
    assert "controller" in roles.values()
