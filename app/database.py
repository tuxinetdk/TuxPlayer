from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from app.models import ChannelCreate, ChannelUpdate


class Database:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    twitch_name TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    favorite INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = sqlite3.connect(self.database_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def ensure_default_settings(self, public_base_url: str, idle_timeout: int, stream_volume: float) -> None:
        if self.get_setting("public_base_url") is None:
            self.set_setting("public_base_url", public_base_url)
        if self.get_setting("idle_timeout") is None:
            self.set_setting("idle_timeout", str(idle_timeout))
        if self.get_setting("active_channel") is None:
            self.set_setting("active_channel", "")
        if self.get_setting("stream_volume") is None:
            self.set_setting("stream_volume", str(stream_volume))

    def list_channels(self) -> List[Dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, twitch_name, display_name, favorite, enabled, created_at, updated_at
                FROM channels
                ORDER BY favorite DESC, display_name COLLATE NOCASE ASC
                """
            ).fetchall()
        return [self._row_to_channel(row) for row in rows]

    def get_channel(self, channel_id: int) -> Optional[Dict]:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT id, twitch_name, display_name, favorite, enabled, created_at, updated_at
                FROM channels
                WHERE id = ?
                """,
                (channel_id,),
            ).fetchone()
        return self._row_to_channel(row) if row else None

    def get_channel_by_twitch_name(self, twitch_name: str) -> Optional[Dict]:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT id, twitch_name, display_name, favorite, enabled, created_at, updated_at
                FROM channels
                WHERE twitch_name = ?
                """,
                (twitch_name,),
            ).fetchone()
        return self._row_to_channel(row) if row else None

    def create_channel(self, payload: ChannelCreate) -> Dict:
        now = self._timestamp()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO channels (twitch_name, display_name, favorite, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.twitch_name,
                    payload.display_name.strip(),
                    int(payload.favorite),
                    int(payload.enabled),
                    now,
                    now,
                ),
            )
            channel_id = cursor.lastrowid
        channel = self.get_channel(int(channel_id))
        assert channel is not None
        return channel

    def update_channel(self, channel_id: int, payload: ChannelUpdate) -> Optional[Dict]:
        existing = self.get_channel(channel_id)
        if not existing:
            return None
        updated = {
            "twitch_name": payload.twitch_name if payload.twitch_name is not None else existing["twitch_name"],
            "display_name": payload.display_name.strip() if payload.display_name is not None else existing["display_name"],
            "favorite": int(payload.favorite if payload.favorite is not None else existing["favorite"]),
            "enabled": int(payload.enabled if payload.enabled is not None else existing["enabled"]),
        }
        now = self._timestamp()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE channels
                SET twitch_name = ?, display_name = ?, favorite = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    updated["twitch_name"],
                    updated["display_name"],
                    updated["favorite"],
                    updated["enabled"],
                    now,
                    channel_id,
                ),
            )
        active_id = self.get_setting("active_channel")
        if active_id and active_id == str(channel_id):
            self.set_setting("active_channel", str(channel_id))
        return self.get_channel(channel_id)

    def delete_channel(self, channel_id: int) -> bool:
        with self.connection() as conn:
            cursor = conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        deleted = cursor.rowcount > 0
        if deleted and self.get_setting("active_channel") == str(channel_id):
            self.set_setting("active_channel", "")
        return deleted

    def set_active_channel(self, channel_id: Optional[int]) -> None:
        value = "" if channel_id is None else str(channel_id)
        self.set_setting("active_channel", value)

    def get_active_channel_id(self) -> Optional[int]:
        value = self.get_setting("active_channel")
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def get_active_channel(self) -> Optional[Dict]:
        channel_id = self.get_active_channel_id()
        if channel_id is None:
            return None
        return self.get_channel(channel_id)

    def toggle_favorite(self, channel_id: int) -> Optional[Dict]:
        channel = self.get_channel(channel_id)
        if not channel:
            return None
        return self.update_channel(channel_id, ChannelUpdate(favorite=not channel["favorite"]))

    def get_setting(self, key: str) -> Optional[str]:
        with self.connection() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def _row_to_channel(self, row: sqlite3.Row) -> Dict:
        return {
            "id": int(row["id"]),
            "twitch_name": str(row["twitch_name"]),
            "display_name": str(row["display_name"]),
            "favorite": bool(row["favorite"]),
            "enabled": bool(row["enabled"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()
