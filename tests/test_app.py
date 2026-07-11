from __future__ import annotations

import re

from app.models import validate_twitch_name


def test_validate_twitch_name_accepts_valid_name():
    assert validate_twitch_name("DJ_Power123") == "DJ_Power123"


def test_validate_twitch_name_rejects_shell_injection():
    try:
        validate_twitch_name("bad;rm -rf /")
    except ValueError:
        assert True
        return
    assert False, "Forventede ValueError for ugyldigt Twitch-navn"


def test_create_channel(client):
    response = client.post(
        "/api/channels",
        json={
            "twitch_name": "djpowersandy",
            "display_name": "DJ Power Sandy",
            "favorite": True,
            "enabled": True,
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["twitch_name"] == "djpowersandy"
    assert payload["favorite"] is True


def test_select_active_channel(client):
    created = client.post(
        "/api/channels",
        json={
            "twitch_name": "gulvbass",
            "display_name": "GulvBasS",
            "favorite": False,
            "enabled": True,
        },
    ).json()
    response = client.post("/api/channels/{0}/select".format(created["id"]))
    assert response.status_code == 200
    status_payload = client.get("/api/status").json()
    assert status_payload["status"] == "ok"
    assert status_payload["active_channel"] == "gulvbass"


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_api_status(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["stream_url"] == "http://127.0.0.1:8766/stream/"
    assert payload["stream_volume"] == 1.8


def test_stream_returns_audio_mpeg_without_active_channel(client):
    with client.stream("GET", "/stream/") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("audio/mpeg")


def test_delete_active_channel_resets_active_channel(client):
    created = client.post(
        "/api/channels",
        json={
            "twitch_name": "partytest",
            "display_name": "Party Test",
            "favorite": False,
            "enabled": True,
        },
    ).json()
    client.post("/api/channels/{0}/select".format(created["id"]))
    delete_response = client.delete("/api/channels/{0}".format(created["id"]))
    assert delete_response.status_code == 200
    channels = client.get("/api/channels").json()
    assert len(channels) == 0
    assert client.get("/api/status").json()["active_channel"] is None


def test_web_form_sets_csrf_cookie_and_accepts_post(client):
    response = client.get("/")
    assert response.status_code == 200
    cookie_token = client.cookies.get("csrf_token")
    assert cookie_token
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match
    form_token = match.group(1)
    assert form_token == cookie_token

    post_response = client.post(
        "/channels",
        data={
            "csrf_token": form_token,
            "twitch_name": "djwebform",
            "display_name": "DJ Web Form",
            "favorite": "1",
            "enabled": "1",
        },
        follow_redirects=False,
    )
    assert post_response.status_code == 303
    channels = client.get("/api/channels").json()
    assert len(channels) == 1
    assert channels[0]["twitch_name"] == "djwebform"


def test_web_form_create_respects_unchecked_enabled(client):
    response = client.get("/")
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match
    form_token = match.group(1)

    post_response = client.post(
        "/channels",
        data={
            "csrf_token": form_token,
            "twitch_name": "djdisabled",
            "display_name": "DJ Disabled",
        },
        follow_redirects=False,
    )
    assert post_response.status_code == 303
    channels = client.get("/api/channels").json()
    assert len(channels) == 1
    assert channels[0]["enabled"] is False


def test_web_form_updates_volume_setting(client):
    response = client.get("/")
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match
    form_token = match.group(1)

    post_response = client.post(
        "/settings/volume",
        data={
            "csrf_token": form_token,
            "stream_volume": "2.4",
        },
        follow_redirects=False,
    )
    assert post_response.status_code == 303
    status_payload = client.get("/api/status").json()
    assert status_payload["stream_volume"] == 2.4
