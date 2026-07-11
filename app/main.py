from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import router as api_router
from app.config import Settings
from app.database import Database
from app.logging_buffer import RingBufferHandler
from app.stream_manager import StreamManager
from app.twitch import TwitchStatusClient
from app.web import router as web_router


def configure_logging(level: str) -> tuple[logging.Logger, RingBufferHandler]:
    logger = logging.getLogger("tuxplayer")
    logger.setLevel(level)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    ring_handler = RingBufferHandler(capacity=500)
    ring_handler.setFormatter(formatter)
    logger.addHandler(ring_handler)

    logger.propagate = False
    return logger, ring_handler


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    logger, log_buffer = configure_logging(app_settings.log_level)
    database = Database(app_settings.database_path)
    database.initialize()
    database.ensure_default_settings(app_settings.public_base_url, app_settings.stream_idle_timeout, app_settings.stream_volume)
    twitch_client = TwitchStatusClient(app_settings, logger)
    stream_manager = StreamManager(app_settings, database, twitch_client, logger)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        stream_manager.shutdown()
        twitch_client.close()

    app = FastAPI(title="TuxPlayer", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.database = database
    app.state.stream_manager = stream_manager
    app.state.log_buffer = log_buffer
    app.state.logger = logger

    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app.include_router(api_router)
    app.include_router(web_router)
    return app


app = create_app()
