from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.twitch import TwitchChannelStatus, TwitchStatusClient


def test_default_config_does_not_contain_internal_ip():
    settings = Settings()
    assert settings.public_base_url == "http://localhost:8766"
    loaded = Settings.from_env()
    assert loaded.public_base_url == "http://localhost:8766"


def test_twitch_http_errors_do_not_log_client_secret_or_token_url(caplog):
    settings = Settings(
        public_base_url="http://localhost:8766",
        twitch_client_id="test-client-id",
        twitch_client_secret="super-secret-value",
    )
    logger = logging.getLogger("twitch-http-error-test")
    client = TwitchStatusClient(settings, logger)
    request = httpx.Request(
        "POST",
        "https://id.twitch.tv/oauth2/token?client_secret=super-secret-value&grant_type=client_credentials",
    )
    response = httpx.Response(status_code=401, request=request)
    error = httpx.HTTPStatusError("bad auth", request=request, response=response)

    def raise_error() -> str:
        raise error

    client._ensure_token = raise_error  # type: ignore[method-assign]

    with caplog.at_level(logging.WARNING, logger="twitch-http-error-test"):
        status = client.get_channel_status("djpowersandy")

    assert status == TwitchChannelStatus(state="unknown")
    assert "super-secret-value" not in caplog.text
    assert "client_secret=" not in caplog.text
    assert "https://id.twitch.tv/oauth2/token" not in caplog.text
    assert "HTTP 401" in caplog.text
    client.close()


def test_twitch_token_request_uses_post_body_not_query_string():
    settings = Settings(
        public_base_url="http://localhost:8766",
        twitch_client_id="test-client-id",
        twitch_client_secret="super-secret-value",
    )
    logger = logging.getLogger("twitch-request-test")
    client = TwitchStatusClient(settings, logger)
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs):
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        captured["data"] = kwargs.get("data")

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {"access_token": "fake-token", "expires_in": 3600}

        return FakeResponse()

    client._client.post = fake_post  # type: ignore[method-assign]
    token = client._ensure_token()
    assert token == "fake-token"
    assert captured["url"] == "https://id.twitch.tv/oauth2/token"
    assert captured["params"] is None
    assert captured["data"] == {
        "client_id": "test-client-id",
        "client_secret": "super-secret-value",
        "grant_type": "client_credentials",
    }
    assert "client_secret=" not in str(captured["url"])
    assert "client_id=" not in str(captured["url"])
    assert "grant_type=" not in str(captured["url"])
    client.close()


def test_admin_config_allows_both_empty():
    settings = Settings(admin_username="", admin_password="")
    settings.validate_admin_credentials()
    assert settings.admin_auth_enabled is False


def test_admin_config_allows_both_set():
    settings = Settings(admin_username="admin", admin_password="secret")
    settings.validate_admin_credentials()
    assert settings.admin_auth_enabled is True


def test_admin_config_rejects_username_only():
    with pytest.raises(ValueError, match="ADMIN_USERNAME and ADMIN_PASSWORD must either both be set or both be empty."):
        Settings(admin_username="admin", admin_password="").validate_admin_credentials()


def test_admin_config_rejects_password_only_without_leaking_secret():
    with pytest.raises(ValueError) as excinfo:
        Settings(admin_username="", admin_password="very-secret").validate_admin_credentials()
    message = str(excinfo.value)
    assert "ADMIN_USERNAME and ADMIN_PASSWORD must either both be set or both be empty." in message
    assert "very-secret" not in message


def test_from_env_preserves_twitch_secret_and_admin_password_whitespace(monkeypatch):
    monkeypatch.setenv("TWITCH_CLIENT_ID", "  client-id  ")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", " secret with spaces ")
    monkeypatch.setenv("ADMIN_USERNAME", "  admin  ")
    monkeypatch.setenv("ADMIN_PASSWORD", " password with spaces ")

    settings = Settings.from_env()

    assert settings.twitch_client_id == "client-id"
    assert settings.twitch_client_secret == " secret with spaces "
    assert settings.admin_username == "admin"
    assert settings.admin_password == " password with spaces "
    assert settings.admin_auth_enabled is True


def test_from_env_rejects_trimmed_username_with_whitespace_only_password_without_leaking_secret(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "   ")
    monkeypatch.setenv("ADMIN_PASSWORD", "   ")

    with pytest.raises(ValueError) as excinfo:
        Settings.from_env()

    message = str(excinfo.value)
    assert "ADMIN_USERNAME and ADMIN_PASSWORD must either both be set or both be empty." in message
    assert "   " not in message
