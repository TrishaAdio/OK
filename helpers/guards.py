"""Custom Pyrogram filters."""

from __future__ import annotations

from pyrogram import filters

from config import Config


def _is_admin(_, __, update) -> bool:
    user = getattr(update, "from_user", None)
    return bool(user) and Config.is_admin(user.id)


def _is_owner(_, __, update) -> bool:
    user = getattr(update, "from_user", None)
    return bool(user) and user.id == Config.OWNER_ID


admin_only = filters.create(_is_admin, name="AdminOnly")
owner_only = filters.create(_is_owner, name="OwnerOnly")
