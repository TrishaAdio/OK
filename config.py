"""Runtime configuration, loaded from config.env (written by setup.py)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / "config.env"

load_dotenv(ENV_FILE)


class ConfigError(RuntimeError):
    pass


def _raw(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _req_int(name: str) -> int:
    value = _raw(name)
    if not value:
        raise ConfigError("%s is missing" % name)
    try:
        return int(value)
    except ValueError:
        raise ConfigError("%s must be a number, got %r" % (name, value))


def _req_str(name: str) -> str:
    value = _raw(name)
    if not value:
        raise ConfigError("%s is missing" % name)
    return value


def _opt_int(name: str, default: int = 0) -> int:
    value = _raw(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _opt_float(name: str, default: float) -> float:
    value = _raw(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _opt_bool(name: str, default: bool) -> bool:
    value = _raw(name).lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "y", "on", "enable", "enabled")


def _opt_ids(name: str) -> List[int]:
    out: List[int] = []
    for chunk in _raw(name).replace(",", " ").split():
        try:
            out.append(int(chunk))
        except ValueError:
            continue
    return out


class Config:
    # --- credentials -------------------------------------------------
    API_ID: int = 0
    API_HASH: str = ""
    BOT_TOKEN: str = ""
    OWNER_ID: int = 0

    # --- optional ----------------------------------------------------
    LOG_CHANNEL: int = 0
    SUDO_USERS: List[int] = []

    # --- behaviour ---------------------------------------------------
    DB_PATH: str = str(BASE_DIR / "requests.db")
    SESSION_NAME: str = "request_acceptor"
    APPROVE_DELAY: float = 0.0
    WELCOME_ENABLED: bool = True

    # --- animation ---------------------------------------------------
    ANIM_ENABLED: bool = True
    ANIM_SPEED: float = 0.34

    # --- broadcast ---------------------------------------------------
    BCAST_CONCURRENCY: int = 5

    @classmethod
    def load(cls) -> None:
        cls.API_ID = _req_int("API_ID")
        cls.API_HASH = _req_str("API_HASH")
        cls.BOT_TOKEN = _req_str("BOT_TOKEN")
        cls.OWNER_ID = _req_int("OWNER_ID")

        cls.LOG_CHANNEL = _opt_int("LOG_CHANNEL", 0)
        cls.SUDO_USERS = _opt_ids("SUDO_USERS")

        cls.DB_PATH = _raw("DB_PATH") or str(BASE_DIR / "requests.db")
        cls.SESSION_NAME = _raw("SESSION_NAME") or "request_acceptor"
        cls.APPROVE_DELAY = max(0.0, _opt_float("APPROVE_DELAY", 0.0))
        cls.WELCOME_ENABLED = _opt_bool("WELCOME_ENABLED", True)

        cls.ANIM_ENABLED = _opt_bool("ANIM_ENABLED", True)
        cls.ANIM_SPEED = min(2.0, max(0.12, _opt_float("ANIM_SPEED", 0.34)))

        cls.BCAST_CONCURRENCY = min(20, max(1, _opt_int("BCAST_CONCURRENCY", 5)))

    @classmethod
    def is_admin(cls, user_id: Optional[int]) -> bool:
        if user_id is None:
            return False
        return user_id == cls.OWNER_ID or user_id in cls.SUDO_USERS


def load_or_exit() -> None:
    """Load config, printing a human-readable hint instead of a traceback."""
    try:
        Config.load()
    except ConfigError as exc:
        print("\n  Configuration error: %s" % exc)
        if not ENV_FILE.exists():
            print("  No config.env found at %s" % ENV_FILE)
        print("  Run the interactive setup to fix this:\n")
        print("      python3 setup.py\n")
        sys.exit(1)
