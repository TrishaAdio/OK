"""Inline keyboards built on native Bot API 9.4 button styles.

`style` was added to InlineKeyboardButton in Bot API 9.4 (9 Feb 2026) and lets a
bot colour a button: default / primary / danger / success. It is honoured by
Telegram clients released after that date; older clients simply render the
button uncoloured, so it degrades cleanly with no branching needed.

The `_SUPPORTS_*` probes exist so this module keeps working if it is ever run
against a library build that predates those fields (e.g. upstream pyrogram).
"""

from __future__ import annotations

import inspect
from typing import List, Optional, Sequence, Tuple

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

try:  # kurigram >= 2.2, mirrors Bot API 9.4
    from pyrogram.enums import ButtonStyle

    DEFAULT = ButtonStyle.DEFAULT
    PRIMARY = ButtonStyle.PRIMARY
    DANGER = ButtonStyle.DANGER
    SUCCESS = ButtonStyle.SUCCESS
except ImportError:  # pragma: no cover
    ButtonStyle = None  # type: ignore[assignment]
    DEFAULT = PRIMARY = DANGER = SUCCESS = None  # type: ignore[assignment]

try:
    _PARAMS = set(inspect.signature(InlineKeyboardButton.__init__).parameters)
except (TypeError, ValueError):  # pragma: no cover
    _PARAMS = set()

_SUPPORTS_STYLE = "style" in _PARAMS
_SUPPORTS_ICON = "icon_custom_emoji_id" in _PARAMS
_SUPPORTS_COPY = "copy_text" in _PARAMS

STYLES_AVAILABLE = _SUPPORTS_STYLE and ButtonStyle is not None


def btn(
    text: str,
    *,
    data: Optional[str] = None,
    url: Optional[str] = None,
    style: Optional[object] = None,
    switch_inline: Optional[str] = None,
    switch_inline_here: Optional[str] = None,
    copy_text: Optional[str] = None,
    icon: Optional[str] = None,
) -> InlineKeyboardButton:
    """Build one inline button, applying optional fields only when supported."""
    kwargs = {"text": text}

    if data is not None:
        kwargs["callback_data"] = data
    if url is not None:
        kwargs["url"] = url
    if switch_inline is not None:
        kwargs["switch_inline_query"] = switch_inline
    if switch_inline_here is not None:
        kwargs["switch_inline_query_current_chat"] = switch_inline_here
    if copy_text is not None and _SUPPORTS_COPY:
        kwargs["copy_text"] = copy_text
    if style is not None and _SUPPORTS_STYLE:
        kwargs["style"] = style
    if icon is not None and _SUPPORTS_ICON:
        kwargs["icon_custom_emoji_id"] = icon

    return InlineKeyboardButton(**kwargs)


def kb(rows: Sequence[Sequence[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([list(r) for r in rows if r])


def grid(
    items: Sequence[Tuple[str, str]], columns: int = 2, style: Optional[object] = None
) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for text, data in items:
        row.append(btn(text, data=data, style=style))
        if len(row) == columns:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


# ----------------------------------------------------------------------
# screens
# ----------------------------------------------------------------------
def home(bot_username: str, is_admin: bool = False) -> InlineKeyboardMarkup:
    add_channel = "https://t.me/%s?startchannel&admin=invite_users" % bot_username
    add_group = "https://t.me/%s?startgroup&admin=invite_users" % bot_username

    rows: List[List[InlineKeyboardButton]] = [
        [btn("Add to channel", url=add_channel, style=PRIMARY)],
        [btn("Add to group", url=add_group, style=PRIMARY)],
        [
            btn("How it works", data="nav:help"),
            btn("Share", switch_inline=""),
        ],
    ]
    # Statistics are owner-only, so the entry point is not shown to anyone else.
    if is_admin:
        rows.append(
            [
                btn("Welcome message", data="nav:set", style=SUCCESS),
                btn("Stats", data="nav:stats"),
            ]
        )

    rows.append([btn("Close", data="nav:close", style=DANGER)])
    return kb(rows)


def help_screen(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [[btn("Back", data="nav:home", style=PRIMARY)]]
    if is_admin:
        rows[0].append(btn("Welcome message", data="nav:set", style=SUCCESS))
    rows.append([btn("Close", data="nav:close", style=DANGER)])
    return kb(rows)


def stats_screen() -> InlineKeyboardMarkup:
    """Only the owner ever reaches this screen, so every control is present."""
    return kb(
        [
            [
                btn("Refresh", data="stats:refresh", style=PRIMARY),
                btn("Top chats", data="stats:chats"),
            ],
            [btn("Back", data="nav:home"), btn("Close", data="nav:close", style=DANGER)],
        ]
    )


def settings_screen(has_photo: bool, is_custom: bool) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = [
        [btn("Preview", data="set:preview", style=PRIMARY)],
    ]

    second: List[InlineKeyboardButton] = [btn("Placeholders", data="set:tags")]
    if has_photo:
        second.append(btn("Remove photo", data="set:nophoto", style=DANGER))
    rows.append(second)

    if is_custom:
        rows.append([btn("Reset to default", data="set:reset", style=DANGER)])

    rows.append(
        [btn("Back", data="nav:home"), btn("Close", data="nav:close", style=DANGER)]
    )
    return kb(rows)


def confirm(yes_data: str, no_data: str, yes_text: str = "Confirm") -> InlineKeyboardMarkup:
    return kb(
        [
            [
                btn(yes_text, data=yes_data, style=SUCCESS),
                btn("Cancel", data=no_data, style=DANGER),
            ]
        ]
    )


def broadcast_running() -> InlineKeyboardMarkup:
    return kb([[btn("Stop broadcast", data="bcast:cancel", style=DANGER)]])


def close_only() -> InlineKeyboardMarkup:
    return kb([[btn("Close", data="nav:close", style=DANGER)]])


def back_only() -> InlineKeyboardMarkup:
    return kb(
        [[btn("Back", data="nav:set", style=PRIMARY), btn("Close", data="nav:close", style=DANGER)]]
    )


def welcome_for_user(chat_title: str, invite_link: Optional[str] = None) -> Optional[InlineKeyboardMarkup]:
    """Keyboard attached to the DM a newly approved member receives."""
    if not invite_link:
        return None
    label = "Open %s" % chat_title if chat_title else "Open chat"
    return kb([[btn(label[:60], url=invite_link, style=SUCCESS)]])


def log_entry(user_id: int) -> InlineKeyboardMarkup:
    return kb(
        [
            [
                btn("Profile", url="tg://user?id=%d" % user_id),
                btn("Copy ID", copy_text=str(user_id)),
            ]
        ]
    )
