from __future__ import annotations

import logging

from app.config import Settings
from app.database import Database
from app.stream_manager import StreamManager
from app.twitch import TwitchStatusClient


def build_manager(tmp_path):
    settings = Settings(
        public_base_url="http://127.0.0.1:8766",
        stream_idle_timeout=30,
        stream_bitrate="160k",
        stream_sample_rate=44100,
        stream_volume=1.8,
        stream_chunk_ms=50,
        subscriber_queue_size=24,
        streamlink_live_edge=3,
        streamlink_quality="best",
        database_path=tmp_path / "tuxplayer.db",
    )
    database = Database(settings.database_path)
    database.initialize()
    database.ensure_default_settings(settings.public_base_url, settings.stream_idle_timeout, settings.stream_volume)
    logger = logging.getLogger("tuxplayer-test")
    twitch_client = TwitchStatusClient(settings, logger)
    manager = StreamManager(settings, database, twitch_client, logger)
    return manager, twitch_client


def test_streamlink_command_uses_more_compatible_defaults(tmp_path):
    manager, twitch_client = build_manager(tmp_path)
    try:
        command = manager._streamlink_command("djpowersandy")
        assert "--hls-live-edge" in command
        assert "3" in command
        assert "--ringbuffer-size" in command
        assert "8M" in command
        assert command[-1] == "best"
        assert "--hls-segment-stream-data" not in command
    finally:
        manager.shutdown()
        twitch_client.close()


def test_decoder_and_encoder_commands_apply_latency_and_volume_tuning(tmp_path):
    manager, twitch_client = build_manager(tmp_path)
    try:
        decoder_command = manager._decoder_command()
        encoder_command = manager._encoder_command()
        assert "libmp3lame" in encoder_command
        assert manager._mp3_chunk_size == 1024
        assert manager.settings.subscriber_queue_size == 24
        assert manager.settings.stream_volume == 1.8
        assert "-fflags" not in decoder_command
        assert "-af" not in encoder_command
    finally:
        manager.shutdown()
        twitch_client.close()
