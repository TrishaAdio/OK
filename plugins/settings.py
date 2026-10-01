"""/set, /preview and /reset — the owner-configurable welcome message."""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from pyrogram import Client, filters
from pyrogram.enums import MessageEntityType, ParseMode
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from database import get_db
from helpers import animate as anim
from helpers import keyboards as k
from helpers import texts as t
from helpers.guards import admin_only

log = logging.getLogger("settings")

MAX_TEXT = 3900
MAX_CAPTION = 1000


def _payload(message: Message) -> str:
    """Text after the command.

    If the owner formatted the message with their Telegram client we take the
    HTML rendering; if they typed raw tags we take the literal text. Both styles
    therefore work.
    """
    source = message.text
    if source is None:
        return ""

    entities = message.entities or []
    styled = any(e.type != MessageEntityType.BOT_COMMAND for e in entities)
    body = source.html if styled else str(source)

    parts = body.split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ""


def _from_reply(reply: Message) -> Tuple[str, Optional[str]]:
    """Return (html_body, photo_file_id) taken from a replied-to message."""
    photo = reply.photo.file_id if reply.photo else None

    source = reply.text if reply.text is not None else reply.caption
    if source is None:
        return "", photo

    entities = reply.entities or reply.caption_entities or []
    body = source.html if entities else str(source)
    return body.strip(), photo


async def settings_panel() -> Tuple[str, InlineKeyboardMarkup]:
    db = get_db()
    stored = await db.get("welcome_text", None)
    photo = await db.get("welcome_photo", None)

    is_custom = stored is not None
    template = stored if is_custom else t.DEFAULT_WELCOME

    origin = "custom" if is_custom else "default"
    attachment = "photo attached" if photo else "text only"

    shown = t.esc(template) if template.strip() else "(empty)"

    text = (
        "<b>Welcome message</b>\n\n"
        "<blockquote>%s</blockquote>\n\n"
        "Source: %s · %s" % (shown, origin, attachment)
    )
    return text, k.settings_screen(bool(photo), is_custom)


@Client.on_message(filters.command("set") & filters.private & admin_only)
async def set_welcome(client: Client, message: Message) -> None:
    db = get_db()
    reply = message.reply_to_message
    body = _payload(message)

    # /set alone -> open the panel
    if not body and reply is None:
        text, markup = await settings_panel()
        await message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup,
            disable_web_page_preview=True,
        )
        return

    photo: Optional[str] = None

    if reply is not None and not body:
        body, photo = _from_reply(reply)
        if not body and not photo:
            await message.reply_text(
                "That message has no text or photo to copy.",
                parse_mode=ParseMode.HTML,
            )
            return
    elif reply is not None and reply.photo:
        photo = reply.photo.file_id

    limit = MAX_CAPTION if photo else MAX_TEXT
    if len(body) > limit:
        await message.reply_text(
            "Too long: <code>%d</code> characters, limit is <code>%d</code>%s."
            % (len(body), limit, " for a photo caption" if photo else ""),
            parse_mode=ParseMode.HTML,
        )
        return

    await db.set("welcome_text", body)
    if photo:
        await db.set("welcome_photo", photo)

    sent = await message.reply_text("<code>saving</code>", parse_mode=ParseMode.HTML)
    frames = anim.build_steps(
        "Saving", ("Validating markup", "Writing to database"), sub=1, width=12
    )
    text, markup = await settings_panel()
    await anim.play(sent, frames, final=text, keyboard=markup)


@Client.on_message(filters.command("preview") & filters.private & admin_only)
async def preview(client: Client, message: Message) -> None:
    await _send_preview(client, message.chat.id, message.from_user)


@Client.on_message(filters.command("reset") & filters.private & admin_only)
async def reset(client: Client, message: Message) -> None:
    await message.reply_text(
        "<b>Reset the welcome message?</b>\n\nThe default text will be used again.",
        parse_mode=ParseMode.HTML,
        reply_markup=k.confirm("set:reset:yes", "nav:set", "Reset"),
    )


async def _send_preview(client: Client, chat_id: int, user) -> None:
    """Render the stored template exactly as a new member would receive it."""
    db = get_db()
    stored = await db.get("welcome_text", None)
    photo = await db.get("welcome_photo", None)
    template = stored if stored is not None else t.DEFAULT_WELCOME

    class _FakeChat:
        id = chat_id
        title = "Your Channel"

    body = t.render(template, t.welcome_values(user, _FakeChat(), count=1))
    if not body.strip():
        body = "(empty message)"

    markup = k.welcome_for_user("Your Channel", "https://t.me/telegram")

    try:
        if photo:
            await client.send_photo(
                chat_id,
                photo,
                caption=body[:1024],
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        else:
            await client.send_message(
                chat_id,
                body,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
    except Exception as exc:
        await client.send_message(
            chat_id,
            "<b>That message could not be sent.</b>\n\n<blockquote>%s</blockquote>\n\n"
            "Check the HTML tags with /set." % t.esc(exc),
            parse_mode=ParseMode.HTML,
        )


# ----------------------------------------------------------------------
# callbacks
# ----------------------------------------------------------------------
@Client.on_callback_query(filters.regex(r"^set:") & admin_only)
async def settings_callbacks(client: Client, query: CallbackQuery) -> None:
    action = query.data.split(":", 1)[1]
    db = get_db()

    if action == "preview":
        await query.answer("Sending preview")
        await _send_preview(client, query.message.chat.id, query.from_user)
        return

    if action == "tags":
        await query.answer()
        await anim.safe_edit(query.message, t.placeholders_block(), k.back_only())
        return

    if action == "nophoto":
        await db.delete("welcome_photo")
        await query.answer("Photo removed")
        text, markup = await settings_panel()
        await anim.safe_edit(query.message, text, markup)
        return

    if action == "reset":
        await query.answer()
        await anim.safe_edit(
            query.message,
            "<b>Reset the welcome message?</b>\n\nThe default text will be used again.",
            k.confirm("set:reset:yes", "nav:set", "Reset"),
        )
        return

    if action == "reset:yes":
        await db.delete("welcome_text")
        await db.delete("welcome_photo")
        await query.answer("Reset")
        text, markup = await settings_panel()
        await anim.safe_edit(query.message, text, markup)
        return

    await query.answer()


# Group 1: only reached when the admin-gated handler above did not match,
# i.e. a non-owner pressed one of these buttons.
@Client.on_callback_query(filters.regex(r"^set:"), group=1)
async def settings_denied(client: Client, query: CallbackQuery) -> None:
    await query.answer("Owner only.", show_alert=True)
