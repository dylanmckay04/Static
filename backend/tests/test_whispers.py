"""Transmission tests — send, paginate, redact."""
import pytest


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_send_and_list_whispers(client, make_token):
    t = await make_token("wh_send@test.com")
    r = await client.post("/channels", json={"name": "Whisper Test"}, headers=auth(t))
    sid = r.json()["id"]

    # Post a transmission via REST
    r = await client.post(f"/channels/{sid}/transmissions",
                          json={"content": "Hello darkness"}, headers=auth(t))
    assert r.status_code == 201
    wid = r.json()["id"]

    r = await client.get(f"/channels/{sid}/transmissions", headers=auth(t))
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(w["id"] == wid for w in items)


@pytest.mark.asyncio
async def test_whisper_pagination(client, make_token):
    t = await make_token("wh_page@test.com")
    r = await client.post("/channels", json={"name": "Page Test"}, headers=auth(t))
    sid = r.json()["id"]

    # Post 5 transmissions
    ids = []
    for i in range(5):
        r = await client.post(f"/channels/{sid}/transmissions",
                               json={"content": f"msg {i}"}, headers=auth(t))
        ids.append(r.json()["id"])

    # Fetch newest 3
    r = await client.get(f"/channels/{sid}/transmissions?limit=3", headers=auth(t))
    page = r.json()
    assert len(page["items"]) == 3
    assert page["next_before_id"] is not None

    # Fetch next page
    before = page["next_before_id"]
    r = await client.get(f"/channels/{sid}/transmissions?limit=3&before_id={before}", headers=auth(t))
    page2 = r.json()
    assert len(page2["items"]) == 2  # 5 total, 3 fetched, 2 remaining
    assert page2["next_before_id"] is None


@pytest.mark.asyncio
async def test_redact_whisper(client, make_token):
    controller = await make_token("wh_redact_w@test.com")
    listener = await make_token("wh_redact_a@test.com")

    r = await client.post("/channels", json={"name": "Redact Test"}, headers=auth(controller))
    sid = r.json()["id"]
    await client.post(f"/channels/{sid}/enter", headers=auth(listener))

    # Listener sends a transmission via REST
    r = await client.post(f"/channels/{sid}/transmissions",
                          json={"content": "bad words"}, headers=auth(listener))
    wid = r.json()["id"]

    # Listener cannot redact (403)
    r = await client.delete(f"/channels/{sid}/transmissions/{wid}", headers=auth(listener))
    assert r.status_code == 403

    # Controller redacts (204)
    r = await client.delete(f"/channels/{sid}/transmissions/{wid}", headers=auth(controller))
    assert r.status_code == 204

    # Transmission now shows as deleted in listing
    r = await client.get(f"/channels/{sid}/transmissions", headers=auth(controller))
    item = next(w for w in r.json()["items"] if w["id"] == wid)
    assert item["is_deleted"] is True
    assert item["content"] == "⸻ redacted ⸻"


@pytest.mark.asyncio
async def test_attendant_cannot_whisper_without_presence(client, make_token):
    a = await make_token("wh_nopresence@test.com")
    b = await make_token("wh_nopresence2@test.com")

    r = await client.post("/channels", json={"name": "No Presence Test"}, headers=auth(a))
    sid = r.json()["id"]

    # b has no contact
    r = await client.post(f"/channels/{sid}/transmissions",
                          json={"content": "ghost whisper"}, headers=auth(b))
    assert r.status_code == 403
