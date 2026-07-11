from __future__ import annotations

import secrets
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app.models import ChannelCreate, ChannelUpdate

router = APIRouter()
_security = HTTPBasic(auto_error=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _require_admin(request: Request, credentials: Optional[HTTPBasicCredentials] = Depends(_security)) -> None:
    settings = request.app.state.settings
    if not settings.admin_auth_enabled:
        return
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})
    if not (
        secrets.compare_digest(credentials.username, settings.admin_username)
        and secrets.compare_digest(credentials.password, settings.admin_password)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})


def _ensure_csrf_cookie(request: Request, response) -> str:
    token = request.cookies.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(24)
        response.set_cookie("csrf_token", token, httponly=False, samesite="strict")
    return token


def _check_csrf(request: Request, token: str) -> None:
    cookie_token = request.cookies.get("csrf_token")
    if not cookie_token or not secrets.compare_digest(cookie_token, token):
        raise HTTPException(status_code=403, detail="Ugyldig CSRF-token.")


@router.get("/", dependencies=[Depends(_require_admin)])
def index(request: Request, notice: str = ""):
    database = request.app.state.database
    stream_manager = request.app.state.stream_manager
    channels = database.list_channels()
    active_channel = database.get_active_channel()
    csrf_token = request.cookies.get("csrf_token") or secrets.token_urlsafe(24)
    response = templates.TemplateResponse(
        request,
        "index.html",
        {
            "notice": notice,
            "request": request,
            "settings": request.app.state.settings,
            "status": stream_manager.get_status(),
            "channels": channels,
            "active_channel": active_channel,
            "csrf_token": csrf_token,
        },
    )
    if request.cookies.get("csrf_token") != csrf_token:
        response.set_cookie("csrf_token", csrf_token, httponly=False, samesite="strict")
    return response


@router.post("/channels", dependencies=[Depends(_require_admin)])
def create_channel(
    request: Request,
    csrf_token: str = Form(...),
    twitch_name: str = Form(...),
    display_name: str = Form(...),
    favorite: Optional[str] = Form(default=None),
    enabled: Optional[str] = Form(default=None),
):
    _check_csrf(request, csrf_token)
    payload = ChannelCreate(
        twitch_name=twitch_name,
        display_name=display_name,
        favorite=bool(favorite),
        enabled=enabled == "1",
    )
    request.app.state.database.create_channel(payload)
    return RedirectResponse(url="/?notice=DJ+tilf%C3%B8jet", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/channels/{channel_id}/update", dependencies=[Depends(_require_admin)])
def update_channel(
    channel_id: int,
    request: Request,
    csrf_token: str = Form(...),
    twitch_name: str = Form(...),
    display_name: str = Form(...),
    favorite: Optional[str] = Form(default=None),
    enabled: Optional[str] = Form(default=None),
):
    _check_csrf(request, csrf_token)
    payload = ChannelUpdate(
        twitch_name=twitch_name,
        display_name=display_name,
        favorite=bool(favorite),
        enabled=enabled == "1",
    )
    request.app.state.database.update_channel(channel_id, payload)
    return RedirectResponse(url="/?notice=DJ+opdateret", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/channels/{channel_id}/delete", dependencies=[Depends(_require_admin)])
def delete_channel(channel_id: int, request: Request, csrf_token: str = Form(...)):
    _check_csrf(request, csrf_token)
    request.app.state.database.delete_channel(channel_id)
    request.app.state.stream_manager.select_channel(request.app.state.database.get_active_channel_id())
    return RedirectResponse(url="/?notice=DJ+slettet", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/channels/{channel_id}/select", dependencies=[Depends(_require_admin)])
def select_channel(channel_id: int, request: Request, csrf_token: str = Form(...)):
    _check_csrf(request, csrf_token)
    request.app.state.stream_manager.select_channel(channel_id)
    return RedirectResponse(url="/?notice=Aktiv+DJ+valgt", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/channels/{channel_id}/favorite", dependencies=[Depends(_require_admin)])
def favorite_channel(channel_id: int, request: Request, csrf_token: str = Form(...)):
    _check_csrf(request, csrf_token)
    request.app.state.database.toggle_favorite(channel_id)
    return RedirectResponse(url="/?notice=Favorit+opdateret", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/channels/{channel_id}/test", dependencies=[Depends(_require_admin)])
def test_channel(channel_id: int, request: Request, csrf_token: str = Form(...)):
    _check_csrf(request, csrf_token)
    channel = request.app.state.database.get_channel(channel_id)
    if not channel:
        return RedirectResponse(url="/?notice=DJ+ikke+fundet", status_code=status.HTTP_303_SEE_OTHER)
    result = request.app.state.stream_manager.test_channel(channel["twitch_name"])
    message = "Test+OK" if result.get("ok") else "Test+fejlede"
    return RedirectResponse(url=f"/?notice={message}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/stream/stop", dependencies=[Depends(_require_admin)])
def stop_stream(request: Request, csrf_token: str = Form(...)):
    _check_csrf(request, csrf_token)
    request.app.state.stream_manager.stop_source_only()
    return RedirectResponse(url="/?notice=Twitch-kilde+stoppet", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/stream/restart", dependencies=[Depends(_require_admin)])
def restart_stream(request: Request, csrf_token: str = Form(...)):
    _check_csrf(request, csrf_token)
    request.app.state.stream_manager.restart_source()
    return RedirectResponse(url="/?notice=Twitch-kilde+genstartet", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/settings/volume", dependencies=[Depends(_require_admin)])
def update_volume(request: Request, csrf_token: str = Form(...), stream_volume: str = Form(...)):
    _check_csrf(request, csrf_token)
    try:
        volume = float(stream_volume)
    except ValueError:
        return RedirectResponse(url="/?notice=Ugyldig+volumen", status_code=status.HTTP_303_SEE_OTHER)
    request.app.state.stream_manager.set_volume(volume)
    return RedirectResponse(url="/?notice=Volumen+gemt", status_code=status.HTTP_303_SEE_OTHER)
