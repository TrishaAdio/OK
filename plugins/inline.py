"""Inline mode: @bot <query> results, each carrying a coloured keyboard."""

from __future__ import annotations

import logging

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

from config import Config
from helpers import keyboards as k
from helpers import texts as t
from helpers.state import Runtime

log = logging.getLogger("inline")


def _content(text: str) -> InputTextMessageContent:
    return InputTextMessageContent(
        text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


@Client.on_inline_query()
async def inline_menu(client: Client, query: InlineQuery) -> None:
    term = (query.query or "").strip().lower()
    is_admin = Config.is_admin(query.from_user.id)

    results = []

    share_text = (
        "<b>%s</b>\n\n"
        "Approves join requests to a channel or group the moment they arrive, "
        "and greets every new member." % t.esc(Runtime.bot_name)
    )

    if not term or "share" in term or "about" in term:
        results.append(
            InlineQueryResultArticle(
                title="Share this bot",
                description="Approves join requests automatically",
                input_message_content=_content(share_text),
                reply_markup=k.home(Runtime.bot_username, is_admin=False),
            )
        )

    if not term or "help" in term or "how" in term:
        results.append(
            InlineQueryResultArticle(
                title="How it works",
                description="Setup in three steps",
                input_message_content=_content(t.HELP_TEXT),
                reply_markup=k.help_screen(False),
            )
        )

    if is_admin and (not term or "stat" in term):
        from plugins.stats import render_stats

        results.append(
            InlineQueryResultArticle(
                title="Statistics",
                description="Approvals, reach and uptime",
                input_message_content=_content(await render_stats()),
                reply_markup=k.stats_screen(),
            )
        )

    if is_admin and (not term or "welcome" in term or "preview" in term):
        from database import get_db

        db = get_db()
        stored = await db.get("welcome_text", None)
        template = stored if stored is not None else t.DEFAULT_WELCOME

        class _FakeChat:
            id = 0
            title = "Your Channel"

        rendered = t.render(
            template, t.welcome_values(query.from_user, _FakeChat(), count=1)
        )
        results.append(
            InlineQueryResultArticle(
                title="Welcome message",
                description="Send a copy of the current greeting",
                input_message_content=_content(rendered or "(empty)"),
            )
        )

    if not results:
        results.append(
            InlineQueryResultArticle(
                title="Nothing matched",
                description="Try: share, help, stats, welcome",
                input_message_content=_content(share_text),
                reply_markup=k.home(Runtime.bot_username, is_admin=False),
            )
        )

    try:
        await query.answer(
            results=results,
            cache_time=1 if is_admin else 60,
            is_personal=True,
        )
    except Exception as exc:
        log.debug("inline answer failed: %s", exc)
