from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,25}$")


def validate_twitch_name(value: str) -> str:
    candidate = (value or "").strip()
    if not USERNAME_PATTERN.fullmatch(candidate):
        raise ValueError("Twitch-brugernavn må kun indeholde A-Z, a-z, 0-9 og underscore (maks 25 tegn).")
    return candidate


class ChannelBase(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    favorite: bool = False
    enabled: bool = True


class ChannelCreate(ChannelBase):
    twitch_name: str = Field(min_length=1, max_length=25)

    @field_validator("twitch_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_twitch_name(value)


class ChannelUpdate(BaseModel):
    twitch_name: Optional[str] = Field(default=None, min_length=1, max_length=25)
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    favorite: Optional[bool] = None
    enabled: Optional[bool] = None

    @field_validator("twitch_name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return validate_twitch_name(value)


class ChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    twitch_name: str
    display_name: str
    favorite: bool
    enabled: bool
    created_at: str
    updated_at: str


class StatusResponse(BaseModel):
    status: str
    active_channel: Optional[str]
    source_state: str
    stream_running: bool
    listeners: int
    stream_url: str
    uptime_seconds: int
    last_error: Optional[str]
    streamlink_pid: Optional[int]
    ffmpeg_pid: Optional[int]
    cpu_percent: Optional[float]
    memory_mb: Optional[float]
    stream_volume: float
    title: Optional[str] = None
    viewer_count: Optional[int] = None
    profile_image_url: Optional[str] = None
