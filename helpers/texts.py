"""Message templates and the welcome-message placeholder renderer."""

from __future__ import annotations

import html
import re
import time
from typing import Any, Dict, Optional

DEFAULT_WELCOME = (
    "<b>Request approved</b>\n\n"
    "Welcome to <b>{chat}</b>, {mention}."
)

PLACEHOLDERS = (
    ("{mention}", "clickable mention of the member"),
    ("{first}", "first name"),
    ("{last}", "last name"),
    ("{full}", "first + last name"),
    ("{username}", "@username, or the first name if unset"),
    ("{id}", "numeric user id"),
    ("{chat}", "chat title"),
    ("{chat_id}", "numeric chat id"),
    ("{count}", "total approvals in that chat"),
)

_TAG_RE = re.compile(r"\{(\w+)\}")


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


def mention_of(user_id: int, name: str) -> str:
    label = esc(name) or "there"
    return '<a href="tg://user?id=%d">%s</a>' % (user_id, label)


def render(template: str, values: Dict[str, Any]) -> str:
    """Substitute {placeholders}.

    Uses a regex rather than str.format so that stray braces in owner-written
    text can never raise, and unknown tags are left visible instead of blowing
    up the send.
    """

    def swap(match: "re.Match") -> str:
        key = match.group(1)
        if key in values:
            return str(values[key])
        return match.group(0)

    return _TAG_RE.sub(swap, template)


def welcome_values(user, chat, count: int = 0) -> Dict[str, Any]:
    first = getattr(user, "first_name", "") or ""
    last = getattr(user, "last_name", "") or ""
    username = getattr(user, "username", "") or ""
    full = (first + " " + last).strip()
    title = getattr(chat, "title", "") or ""

    return {
        "mention": mention_of(user.id, first or full or "there"),
        "first": esc(first),
        "last": esc(last),
        "full": esc(full),
        "username": ("@" + username) if username else esc(first),
        "id": user.id,
        "chat": esc(title),
        "chat_id": getattr(chat, "id", 0),
        "count": count,
    }


# ----------------------------------------------------------------------
# formatting utilities
# ----------------------------------------------------------------------
def human_time(seconds: float) -> str:
    seconds = int(max(0, seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    parts = []
    if days:
        parts.append("%dd" % days)
    if hours:
        parts.append("%dh" % hours)
    if minutes:
        parts.append("%dm" % minutes)
    parts.append("%ds" % seconds)
    # Keep the three most significant units: "1d 2h 3m", not "2h 3m 4s".
    return " ".join(parts[:3])


def human_bytes(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return "%d %s" % (size, unit)
            return "%.1f %s" % (size, unit)
        size /= 1024.0
    return "%d B" % size


def group_num(value: int) -> str:
    return "{:,}".format(int(value))


# ----------------------------------------------------------------------
# static screens
# ----------------------------------------------------------------------
START_PRIVATE = (
    "<b>{name}</b>\n\n"
    "Join requests to your channel or group are approved the moment they "
    "arrive, and each new member gets a message from you.\n\n"
    "<blockquote>Add me as an admin with <b>Add Members</b> permission, then "
    "turn on <b>Approve New Members</b> in the chat's invite link.</blockquote>"
)

START_GROUP = (
    "<b>Active here.</b>\n"
    "Join requests in <b>{chat}</b> will be approved automatically."
)

HELP_TEXT = (
    "<b>How it works</b>\n\n"
    "<blockquote>1. Add me to your channel or group as an admin with the "
    "<b>Add Members</b> right.\n"
    "2. Create an invite link with <b>Request Admin Approval</b> enabled, or "
    "switch it on for the existing link.\n"
    "3. Share that link. Every request is approved on arrival and the member "
    "receives your welcome message.</blockquote>\n\n"
    "<b>Owner commands</b>\n"
    "<code>/set</code> — the message new members receive\n"
    "<code>/preview</code> — see it as they will\n"
    "<code>/reset</code> — restore the default message\n"
    "<code>/stats</code> — approvals, users, chats\n"
    "<code>/bcast</code> — send a message to every user"
)

OWNER_ONLY = "<b>Restricted</b>\n\nThis command is limited to the bot owner."

SETUP_HINT = (
    "<b>Missing permission</b>\n\n"
    "I could not approve a request in <b>{chat}</b>. Promote me to admin there "
    "with the <b>Add Members</b> right."
)


def placeholders_block() -> str:
    lines = "\n".join(
        "<code>%s</code> — %s" % (tag, desc) for tag, desc in PLACEHOLDERS
    )
    return (
        "<b>Placeholders</b>\n\n"
        "<blockquote>%s</blockquote>\n\n"
        "HTML tags <code>b</code>, <code>u</code>, <code>s</code>, "
        "<code>code</code>, <code>a href</code> and <code>blockquote</code> "
        "all work." % lines
    )
