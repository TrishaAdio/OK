"""Mutable process-wide runtime state."""

from __future__ import annotations

import time
from typing import Dict


class Runtime:
    bot_id: int = 0
    bot_username: str = ""
    bot_name: str = "Request Acceptor"

    # Set once the client is connected. Lives here rather than in config so
    # that `from ... import` cannot capture a stale copy of the value.
    started_at: float = time.time()

    # counters for the current process lifetime
    approved: int = 0
    approve_errors: int = 0
    welcome_failed: int = 0

    # broadcast control
    broadcast_running: bool = False
    broadcast_cancel: bool = False

    # per-user cooldown for animated replies (user_id -> last timestamp)
    _anim_seen: Dict[int, float] = {}

    @classmethod
    def allow_animation(cls, user_id: int, cooldown: float = 6.0) -> bool:
        """Animate at most once per cooldown window per user."""
        now = time.time()
        last = cls._anim_seen.get(user_id, 0.0)
        if now - last < cooldown:
            return False
        cls._anim_seen[user_id] = now
        if len(cls._anim_seen) > 4096:
            cutoff = now - 600
            cls._anim_seen = {
                uid: ts for uid, ts in cls._anim_seen.items() if ts > cutoff
            }
        return True
