"""/start, /help, /ping and the inline navigation callbacks."""

from __future__ import annotations

import logging
import time

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, Message

from config import Config
from database import get_db
from helpers import animate as anim
from helpers import keyboards as k
from helpers import texts as t
from helpers.state import Runtime

log = logging.getLogger("start")

BOOT_STEPS = ("Linking session", "Reading permissions", "Arming request watcher")


@Client.on_message(filters.command("start") & filters.private)
async def start_private(client: Client, message: Message) -> None:
    user = message.from_user
    db = get_db()
    await db.add_user(user.id, user.first_name or "", user.username or "")

    is_admin = Config.is_admin(user.id)
    final = t.render(t.START_PRIVATE, {"name": t.esc(Runtime.bot_name)})
    markup = k.home(Runtime.bot_username, is_admin)

    frames = anim.build_steps("Connecting", BOOT_STEPS, sub=1)
    await anim.send_and_play(
        client,
        message.chat.id,
        frames,
        final=final,
        keyboard=markup,
        skip=not Runtime.allow_animation(user.id),
    )


@Client.on_message(filters.command("start") & (filters.group | filters.channel))
async def start_group(client: Client, message: Message) -> None:
    text = t.render(t.START_GROUP, {"chat": t.esc(message.chat.title or "this chat")})
    try:
        await message.reply_text(text, parse_mode=ParseMode.HTML, quote=True)
    except Exception:
        pass


@Client.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message) -> None:
    is_admin = Config.is_admin(message.from_user.id)
    await message.reply_text(
        t.HELP_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=k.help_screen(is_admin),
        disable_web_page_preview=True,
    )


@Client.on_message(filters.command("ping") & filters.private)
async def ping(client: Client, message: Message) -> None:
    started = time.time()
    sent = await message.reply_text("<code>pinging</code>", parse_mode=ParseMode.HTML)
    latency = (time.time() - started) * 1000

    await anim.safe_edit(
        sent,
        "<b>Online</b>\n\n<blockquote>Response: <code>%.0f ms</code>\n"
        "Uptime: <code>%s</code></blockquote>"
        % (latency, t.human_time(time.time() - Runtime.started_at)),
    )


# ----------------------------------------------------------------------
# navigation
# ----------------------------------------------------------------------
@Client.on_callback_query(filters.regex(r"^nav:"))
async def navigate(client: Client, query: CallbackQuery) -> None:
    action = query.data.split(":", 1)[1]
    user = query.from_user
    is_admin = Config.is_admin(user.id)

    if action == "close":
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    if action == "home":
        await query.answer()
        await anim.safe_edit(
            query.message,
            t.render(t.START_PRIVATE, {"name": t.esc(Runtime.bot_name)}),
            k.home(Runtime.bot_username, is_admin),
        )
        return

    if action == "help":
        await query.answer()
        await anim.safe_edit(query.message, t.HELP_TEXT, k.help_screen(is_admin))
        return

    if action == "stats":
        if not is_admin:
            await query.answer("Owner only.", show_alert=True)
            return

        from plugins.stats import render_stats  # local import avoids a cycle

        await query.answer()
        await anim.safe_edit(query.message, await render_stats(), k.stats_screen())
        return

    if action == "set":
        if not is_admin:
            await query.answer("Owner only.", show_alert=True)
            return
        from plugins.settings import settings_panel

        await query.answer()
        text, markup = await settings_panel()
        await anim.safe_edit(query.message, text, markup)
        return

    await query.answer()


# Every owner-restricted command, so a non-owner gets one clear reply instead of
# silence. Group 1 means this only runs when the gated handler did not match.
OWNER_GUARDED = ["stats", "set", "preview", "reset", "bcast"]


@Client.on_message(filters.command(OWNER_GUARDED) & filters.private, group=1)
async def owner_command_denied(client: Client, message: Message) -> None:
    await message.reply_text(t.OWNER_ONLY, parse_mode=ParseMode.HTML)
