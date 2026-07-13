from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    public_base_url: str = "http://localhost:8766"
    stream_idle_timeout: int = 30
    stream_bitrate: str = "160k"
    stream_sample_rate: int = 44100
    stream_volume: float = 1.8
    stream_chunk_ms: int = 50
    subscriber_queue_size: int = 24
    streamlink_live_edge: int = 3
    streamlink_quality: str = "best"
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    admin_username: str = ""
    admin_password: str = ""
    log_level: str = "INFO"
    tz: str = "Europe/Copenhagen"
    database_path: Path = Path("/app/data/tuxplayer.db")

    @classmethod
    def from_env(cls) -> "Settings":
        default_db = Path("/app/data/tuxplayer.db")
        if not default_db.parent.exists():
            default_db = Path.cwd() / "data" / "tuxplayer.db"
        settings = cls(
            public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8766").rstrip("/"),
            stream_idle_timeout=max(1, int(os.getenv("STREAM_IDLE_TIMEOUT", "30"))),
            stream_bitrate=os.getenv("STREAM_BITRATE", "160k"),
            stream_sample_rate=max(8000, int(os.getenv("STREAM_SAMPLE_RATE", "44100"))),
            stream_volume=max(0.1, float(os.getenv("STREAM_VOLUME", "1.8"))),
            stream_chunk_ms=min(250, max(20, int(os.getenv("STREAM_CHUNK_MS", "50")))),
            subscriber_queue_size=min(128, max(4, int(os.getenv("SUBSCRIBER_QUEUE_SIZE", "24")))),
            streamlink_live_edge=min(6, max(1, int(os.getenv("STREAMLINK_LIVE_EDGE", "3")))),
            streamlink_quality=os.getenv("STREAMLINK_QUALITY", "best").strip() or "best",
            twitch_client_id=os.getenv("TWITCH_CLIENT_ID", "").strip(),
            twitch_client_secret=os.getenv("TWITCH_CLIENT_SECRET", ""),
            admin_username=os.getenv("ADMIN_USERNAME", "").strip(),
            admin_password=os.getenv("ADMIN_PASSWORD", ""),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            tz=os.getenv("TZ", "Europe/Copenhagen"),
            database_path=Path(os.getenv("DATABASE_PATH", str(default_db))),
        )
        settings.validate_admin_credentials()
        return settings

    @property
    def stream_url(self) -> str:
        return f"{self.public_base_url}/stream/"

    @property
    def admin_auth_enabled(self) -> bool:
        return bool(self.admin_username and self.admin_password)

    def validate_admin_credentials(self) -> None:
        username_set = bool(self.admin_username)
        password_set = bool(self.admin_password)
        password_has_content = bool(self.admin_password.strip())

        if not username_set and not password_set:
            return
        if password_set and not password_has_content:
            raise ValueError("ADMIN_PASSWORD must contain at least one non-whitespace character.")
        if not username_set or not password_set:
            raise ValueError("ADMIN_USERNAME and ADMIN_PASSWORD must either both be set or both be empty.")
