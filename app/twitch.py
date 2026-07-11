from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

import httpx

from app.config import Settings


@dataclass(slots=True)
class TwitchChannelStatus:
    state: str
    title: Optional[str] = None
    viewer_count: Optional[int] = None
    profile_image_url: Optional[str] = None


class TwitchStatusClient:
    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        self.settings = settings
        self.logger = logger
        self._client = httpx.Client(timeout=8.0)
        self._lock = threading.Lock()
        self._token: Optional[str] = None
        self._token_expires_at = 0.0
        self._cache: Dict[str, tuple[float, TwitchChannelStatus]] = {}

    def get_channel_status(self, twitch_name: str) -> TwitchChannelStatus:
        if not self.settings.twitch_client_id or not self.settings.twitch_client_secret:
            return TwitchChannelStatus(state="unknown")
        now = time.time()
        cache_key = twitch_name.lower()
        cached = self._cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]
        try:
            token = self._ensure_token()
            user = self._fetch_user(token, twitch_name)
            if not user:
                status = TwitchChannelStatus(state="unknown")
            else:
                headers = self._auth_headers(token)
                stream_response = self._client.get(
                    "https://api.twitch.tv/helix/streams",
                    headers=headers,
                    params={"user_id": user["id"]},
                )
                stream_response.raise_for_status()
                items = stream_response.json().get("data", [])
                if items:
                    stream = items[0]
                    status = TwitchChannelStatus(
                        state="live",
                        title=stream.get("title"),
                        viewer_count=stream.get("viewer_count"),
                        profile_image_url=user.get("profile_image_url"),
                    )
                else:
                    status = TwitchChannelStatus(
                        state="offline",
                        profile_image_url=user.get("profile_image_url"),
                    )
            self._cache[cache_key] = (now + 45, status)
            return status
        except Exception as exc:
            self.logger.warning("Twitch API status failed for %s: %s", twitch_name, exc)
            return TwitchChannelStatus(state="unknown")

    def close(self) -> None:
        self._client.close()

    def _ensure_token(self) -> str:
        with self._lock:
            if self._token and self._token_expires_at > time.time() + 60:
                return self._token
            response = self._client.post(
                "https://id.twitch.tv/oauth2/token",
                params={
                    "client_id": self.settings.twitch_client_id,
                    "client_secret": self.settings.twitch_client_secret,
                    "grant_type": "client_credentials",
                },
            )
            response.raise_for_status()
            payload = response.json()
            self._token = payload["access_token"]
            self._token_expires_at = time.time() + int(payload.get("expires_in", 3600))
            return self._token

    def _fetch_user(self, token: str, twitch_name: str) -> Optional[Dict]:
        response = self._client.get(
            "https://api.twitch.tv/helix/users",
            headers=self._auth_headers(token),
            params={"login": twitch_name},
        )
        response.raise_for_status()
        users = response.json().get("data", [])
        return users[0] if users else None

    def _auth_headers(self, token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Client-Id": self.settings.twitch_client_id,
        }
