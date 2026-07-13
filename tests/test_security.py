from __future__ import annotations

import logging

import httpx

from app.config import Settings
from app.twitch import TwitchChannelStatus, TwitchStatusClient


def test_default_config_does_not_contain_internal_ip():
    settings = Settings()
    assert "192.168.2.124" not in settings.public_base_url
    loaded = Settings.from_env()
    assert "192.168.2.124" not in loaded.public_base_url


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
