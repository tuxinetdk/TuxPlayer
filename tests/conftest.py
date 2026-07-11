from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        public_base_url="http://127.0.0.1:8766",
        stream_idle_timeout=30,
        stream_bitrate="160k",
        stream_sample_rate=44100,
        database_path=tmp_path / "tuxplayer.db",
    )
    app = create_app(settings)
    original_manager = app.state.stream_manager

    class FakeStreamManager:
        def __init__(self, original):
            self.original = original
            self.volume = original.get_volume()

        def subscribe(self):
            def generator():
                yield b"ID3"
            return generator()

        def get_status(self):
            active_channel = self.original.database.get_active_channel()
            return {
                "status": "ok",
                "active_channel": active_channel["twitch_name"] if active_channel else None,
                "source_state": "silence",
                "stream_running": True,
                "listeners": 0,
                "stream_url": settings.stream_url,
                "uptime_seconds": 0,
                "last_error": None,
                "streamlink_pid": None,
                "ffmpeg_pid": None,
                "cpu_percent": None,
                "memory_mb": None,
                "stream_volume": self.volume,
            }

        def select_channel(self, channel_id):
            self.original.database.set_active_channel(channel_id)

        def restart_source(self):
            return None

        def stop_source_only(self):
            return None

        def test_channel(self, twitch_name):
            return {"ok": True, "state": "live", "title": twitch_name}

        def shutdown(self):
            return None

        def get_volume(self):
            return self.volume

        def set_volume(self, value):
            self.volume = round(float(value), 1)
            self.original.database.set_setting("stream_volume", str(self.volume))
            return self.volume

    original_manager.shutdown()
    app.state.stream_manager = FakeStreamManager(original_manager)
    with TestClient(app) as test_client:
        yield test_client
