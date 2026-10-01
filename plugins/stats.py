"""/stats — owner only. Approval counters, reach and process health."""

from __future__ import annotations

import logging
import time

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, Message

from database import get_db
from helpers import animate as anim
from helpers import keyboards as k
from helpers import texts as t
from helpers.guards import admin_only
from helpers.state import Runtime

log = logging.getLogger("stats")

DAY = 86400.0


async def render_stats() -> str:
    """The full picture. Never shown to anyone but the owner."""
    db = get_db()

    total = await db.total_requests()
    today = await db.requests_since(DAY)
    week = await db.requests_since(DAY * 7)
    hour = await db.requests_since(3600)
    chats = await db.total_chats()
    users = await db.total_users()
    active = await db.total_users(only_active=True)
    unique = await db.unique_requesters()

    lines = [
        "Total approved: <b>%s</b>" % t.group_num(total),
        "Last 24 hours: <b>%s</b>" % t.group_num(today),
        "Last 7 days: <b>%s</b>" % t.group_num(week),
        "Last hour: <b>%s</b>" % t.group_num(hour),
        "Chats served: <b>%s</b>" % t.group_num(chats),
        "",
        "Users reachable: <b>%s</b> of %s"
        % (t.group_num(active), t.group_num(users)),
        "Unique members: <b>%s</b>" % t.group_num(unique),
        "Approved this run: <b>%s</b>" % t.group_num(Runtime.approved),
        "Failed approvals: <b>%s</b>" % t.group_num(Runtime.approve_errors),
        "Undeliverable greetings: <b>%s</b>" % t.group_num(Runtime.welcome_failed),
        "Database: <b>%s</b>" % t.human_bytes(db.size_bytes()),
    ]

    return (
        "<b>Statistics</b>\n\n"
        "<blockquote>%s</blockquote>\n\n"
        "Uptime <code>%s</code>"
        % ("\n".join(lines), t.human_time(time.time() - Runtime.started_at))
    )


async def render_top_chats() -> str:
    db = get_db()
    rows = await db.top_chats(limit=10)

    if not rows:
        return "<b>Top chats</b>\n\nNo approvals recorded yet."

    lines = []
    for index, row in enumerate(rows, start=1):
        title = t.esc(row["title"]) or "<code>%d</code>" % row["chat_id"]
        lines.append("%d. %s — <b>%s</b>" % (index, title, t.group_num(row["count"])))

    return "<b>Top chats</b>\n\n<blockquote>%s</blockquote>" % "\n".join(lines)


@Client.on_message(filters.command("stats") & filters.private & admin_only)
async def stats_command(client: Client, message: Message) -> None:
    final = await render_stats()

    frames = anim.build_steps(
        "Collecting", ("Counting approvals", "Measuring reach"), sub=1, width=12
    )
    await anim.send_and_play(
        client,
        message.chat.id,
        frames,
        final=final,
        keyboard=k.stats_screen(),
        skip=not Runtime.allow_animation(message.from_user.id),
    )


@Client.on_callback_query(filters.regex(r"^stats:") & admin_only)
async def stats_callbacks(client: Client, query: CallbackQuery) -> None:
    action = query.data.split(":", 1)[1]

    if action == "chats":
        await query.answer()
        await anim.safe_edit(query.message, await render_top_chats(), k.stats_screen())
        return

    await query.answer("Updated")
    await anim.safe_edit(query.message, await render_stats(), k.stats_screen())


# Group 1: reached only when the gated handler above did not match, i.e. the
# sender is not the owner. The message-level equivalent lives in start.py so a
# single fallback covers every owner command.
@Client.on_callback_query(filters.regex(r"^stats:"), group=1)
async def stats_callback_denied(client: Client, query: CallbackQuery) -> None:
    await query.answer("Owner only.", show_alert=True)
