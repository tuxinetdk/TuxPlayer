from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.models import ChannelCreate, ChannelOut, ChannelUpdate, StatusResponse

router = APIRouter()
_security = HTTPBasic(auto_error=False)


def _require_admin(request: Request, credentials: Optional[HTTPBasicCredentials] = Depends(_security)) -> None:
    settings = request.app.state.settings
    if not settings.admin_auth_enabled:
        return
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})
    valid_username = secrets.compare_digest(credentials.username, settings.admin_username)
    valid_password = secrets.compare_digest(credentials.password, settings.admin_password)
    if not (valid_username and valid_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/stream")
def stream_redirect() -> RedirectResponse:
    return RedirectResponse(url="/stream/", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/stream/")
def stream(request: Request) -> StreamingResponse:
    generator = request.app.state.stream_manager.subscribe()
    headers = {
        "Cache-Control": "no-cache, no-store",
        "Pragma": "no-cache",
        "X-Accel-Buffering": "no",
        "Content-Disposition": 'inline; filename="tuxplayer.mp3"',
    }
    return StreamingResponse(generator, media_type="audio/mpeg", headers=headers)


@router.get("/api/status", response_model=StatusResponse)
def api_status(request: Request) -> dict:
    return request.app.state.stream_manager.get_status()


@router.get("/api/channels", response_model=list[ChannelOut])
def list_channels(request: Request) -> list[dict]:
    return request.app.state.database.list_channels()


@router.post("/api/channels", response_model=ChannelOut, dependencies=[Depends(_require_admin)], status_code=status.HTTP_201_CREATED)
def create_channel(payload: ChannelCreate, request: Request) -> dict:
    database = request.app.state.database
    if database.get_channel_by_twitch_name(payload.twitch_name):
        raise HTTPException(status_code=409, detail="Kanal findes allerede.")
    try:
        return database.create_channel(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/api/channels/{channel_id}", response_model=ChannelOut, dependencies=[Depends(_require_admin)])
@router.patch("/api/channels/{channel_id}", response_model=ChannelOut, dependencies=[Depends(_require_admin)])
def update_channel(channel_id: int, payload: ChannelUpdate, request: Request) -> dict:
    database = request.app.state.database
    try:
        channel = database.update_channel(channel_id, payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not channel:
        raise HTTPException(status_code=404, detail="Kanal ikke fundet.")
    return channel


@router.delete("/api/channels/{channel_id}", dependencies=[Depends(_require_admin)])
def delete_channel(channel_id: int, request: Request) -> dict[str, bool]:
    database = request.app.state.database
    deleted = database.delete_channel(channel_id)
    if deleted:
        request.app.state.stream_manager.select_channel(database.get_active_channel_id())
        return {"deleted": True}
    raise HTTPException(status_code=404, detail="Kanal ikke fundet.")


@router.post("/api/channels/{channel_id}/select", dependencies=[Depends(_require_admin)])
def select_channel(channel_id: int, request: Request) -> dict[str, str]:
    database = request.app.state.database
    channel = database.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Kanal ikke fundet.")
    request.app.state.stream_manager.select_channel(channel_id)
    return {"status": "ok"}


@router.post("/api/channels/{channel_id}/favorite", response_model=ChannelOut, dependencies=[Depends(_require_admin)])
def toggle_favorite(channel_id: int, request: Request) -> dict:
    channel = request.app.state.database.toggle_favorite(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Kanal ikke fundet.")
    return channel


@router.post("/api/channels/{channel_id}/test", dependencies=[Depends(_require_admin)])
def test_channel(channel_id: int, request: Request) -> dict:
    channel = request.app.state.database.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Kanal ikke fundet.")
    return request.app.state.stream_manager.test_channel(channel["twitch_name"])


@router.post("/api/stream/stop", dependencies=[Depends(_require_admin)])
def stop_stream(request: Request) -> dict[str, str]:
    request.app.state.stream_manager.stop_source_only()
    return {"status": "ok"}


@router.post("/api/stream/restart", dependencies=[Depends(_require_admin)])
def restart_stream(request: Request) -> dict[str, str]:
    request.app.state.stream_manager.restart_source()
    return {"status": "ok"}


@router.get("/api/logs", dependencies=[Depends(_require_admin)])
def logs(request: Request, limit: int = 100) -> dict[str, list[str]]:
    return {"logs": request.app.state.log_buffer.tail(limit=max(1, min(limit, 200)))}
