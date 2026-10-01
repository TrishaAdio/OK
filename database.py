"""SQLite persistence (users, chats, join requests, settings)."""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    first_name TEXT,
    username   TEXT,
    added_at   REAL    NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS chats (
    chat_id  INTEGER PRIMARY KEY,
    title    TEXT,
    kind     TEXT,
    added_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS requests (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    ts      REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_requests_ts   ON requests (ts);
CREATE INDEX IF NOT EXISTS idx_requests_chat ON requests (chat_id);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._db: Optional[aiosqlite.Connection] = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database.connect() was never awaited")
        return self._db

    async def _scalar(self, query: str, args: Tuple = ()) -> int:
        async with self.db.execute(query, args) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    async def add_user(
        self, user_id: int, first_name: str = "", username: str = ""
    ) -> bool:
        """Insert or refresh a user. Returns True when the user is brand new."""
        async with self.db.execute(
            "SELECT 1 FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            exists = await cur.fetchone() is not None

        if exists:
            await self.db.execute(
                "UPDATE users SET first_name = ?, username = ?, active = 1 "
                "WHERE user_id = ?",
                (first_name, username, user_id),
            )
        else:
            await self.db.execute(
                "INSERT INTO users (user_id, first_name, username, added_at, active) "
                "VALUES (?, ?, ?, ?, 1)",
                (user_id, first_name, username, time.time()),
            )
        await self.db.commit()
        return not exists

    async def get_user_ids(self, only_active: bool = True) -> List[int]:
        query = "SELECT user_id FROM users"
        if only_active:
            query += " WHERE active = 1"
        query += " ORDER BY added_at ASC"
        async with self.db.execute(query) as cur:
            rows = await cur.fetchall()
        return [int(r[0]) for r in rows]

    async def total_users(self, only_active: bool = False) -> int:
        query = "SELECT COUNT(*) FROM users"
        if only_active:
            query += " WHERE active = 1"
        return await self._scalar(query)

    async def deactivate_user(self, user_id: int) -> None:
        await self.db.execute(
            "UPDATE users SET active = 0 WHERE user_id = ?", (user_id,)
        )
        await self.db.commit()

    async def delete_user(self, user_id: int) -> None:
        await self.db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        await self.db.commit()

    # ------------------------------------------------------------------
    # chats
    # ------------------------------------------------------------------
    async def add_chat(self, chat_id: int, title: str = "", kind: str = "") -> None:
        await self.db.execute(
            "INSERT INTO chats (chat_id, title, kind, added_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title, "
            "kind = excluded.kind",
            (chat_id, title, kind, time.time()),
        )
        await self.db.commit()

    async def total_chats(self) -> int:
        return await self._scalar("SELECT COUNT(*) FROM chats")

    async def top_chats(self, limit: int = 5) -> List[Dict[str, Any]]:
        query = (
            "SELECT r.chat_id AS chat_id, COUNT(*) AS n, "
            "COALESCE(c.title, '') AS title "
            "FROM requests r LEFT JOIN chats c ON c.chat_id = r.chat_id "
            "GROUP BY r.chat_id ORDER BY n DESC LIMIT ?"
        )
        async with self.db.execute(query, (limit,)) as cur:
            rows = await cur.fetchall()
        return [
            {"chat_id": int(r["chat_id"]), "count": int(r["n"]), "title": r["title"]}
            for r in rows
        ]

    # ------------------------------------------------------------------
    # requests
    # ------------------------------------------------------------------
    async def log_request(self, user_id: int, chat_id: int) -> None:
        await self.db.execute(
            "INSERT INTO requests (user_id, chat_id, ts) VALUES (?, ?, ?)",
            (user_id, chat_id, time.time()),
        )
        await self.db.commit()

    async def total_requests(self) -> int:
        return await self._scalar("SELECT COUNT(*) FROM requests")

    async def requests_since(self, seconds: float) -> int:
        return await self._scalar(
            "SELECT COUNT(*) FROM requests WHERE ts >= ?", (time.time() - seconds,)
        )

    async def unique_requesters(self) -> int:
        return await self._scalar("SELECT COUNT(DISTINCT user_id) FROM requests")

    async def chat_request_count(self, chat_id: int) -> int:
        return await self._scalar(
            "SELECT COUNT(*) FROM requests WHERE chat_id = ?", (chat_id,)
        )

    # ------------------------------------------------------------------
    # settings
    # ------------------------------------------------------------------
    async def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        async with self.db.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else default

    async def set(self, key: str, value: Optional[str]) -> None:
        if value is None:
            await self.db.execute("DELETE FROM settings WHERE key = ?", (key,))
        else:
            await self.db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        await self.db.commit()

    async def delete(self, key: str) -> None:
        await self.set(key, None)

    # ------------------------------------------------------------------
    # misc
    # ------------------------------------------------------------------
    def size_bytes(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            try:
                total += os.path.getsize(self.path + suffix)
            except OSError:
                pass
        return total



# ----------------------------------------------------------------------
# process-wide singleton
# ----------------------------------------------------------------------
_instance: Optional[Database] = None


def get_db() -> Database:
    """Return the shared Database, constructing it on first use.

    Lazy so that importing this module never depends on Config already
    having been loaded.
    """
    global _instance
    if _instance is None:
        from config import Config

        _instance = Database(Config.DB_PATH)
    return _instance
