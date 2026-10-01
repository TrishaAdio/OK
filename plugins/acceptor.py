"""The core feature: approve every incoming join request, then greet the member."""

from __future__ import annotations

import asyncio
import logging

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import (
    ChatAdminRequired,
    FloodWait,
    InputUserDeactivated,
    PeerIdInvalid,
    UserAlreadyParticipant,
    UserIsBlocked,
)
from pyrogram.types import ChatJoinRequest

from config import Config
from database import get_db
from helpers import keyboards as k
from helpers import texts as t
from helpers.state import Runtime

log = logging.getLogger("acceptor")

# One warning per chat when the bot lacks the Add Members right.
_warned_chats = set()


async def _approve(client: Client, request: ChatJoinRequest) -> bool:
    """Approve, retrying once through a FloodWait. True when the user is in."""
    chat_id = request.chat.id
    user_id = request.from_user.id

    for attempt in (1, 2):
        try:
            await client.approve_chat_join_request(chat_id, user_id)
            return True
        except UserAlreadyParticipant:
            return True
        except FloodWait as exc:
            wait = getattr(exc, "value", None) or getattr(exc, "x", 1)
            if attempt == 2:
                log.warning("approve gave up after FloodWait %ss", wait)
                return False
            await asyncio.sleep(float(wait) + 1)
        except ChatAdminRequired:
            await _warn_owner(client, request.chat)
            return False
        except Exception as exc:
            log.error("approve failed in %s for %s: %s", chat_id, user_id, exc)
            return False
    return False


async def _warn_owner(client: Client, chat) -> None:
    if chat.id in _warned_chats:
        return
    _warned_chats.add(chat.id)

    text = t.render(t.SETUP_HINT, {"chat": t.esc(chat.title or chat.id)})
    for target in (Config.LOG_CHANNEL, Config.OWNER_ID):
        if not target:
            continue
        try:
            await client.send_message(target, text, parse_mode=ParseMode.HTML)
            return
        except Exception:
            continue


async def _welcome(client: Client, request: ChatJoinRequest, count: int) -> None:
    """DM the freshly approved member. Silently skipped if they block DMs."""
    if not Config.WELCOME_ENABLED:
        return

    db = get_db()
    template = await db.get("welcome_text", None)
    photo = await db.get("welcome_photo", None)

    if template is None:
        template = t.DEFAULT_WELCOME

    if not template.strip() and not photo:
        return

    body = t.render(template, t.welcome_values(request.from_user, request.chat, count))
    link = getattr(request.invite_link, "invite_link", None)
    markup = k.welcome_for_user(request.chat.title or "", link)
    user_id = request.from_user.id

    try:
        if photo:
            await client.send_photo(
                user_id,
                photo,
                caption=body[:1024],
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        else:
            await client.send_message(
                user_id,
                body,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
    except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid):
        # Expected: the member never started the bot, so DMs are closed.
        Runtime.welcome_failed += 1
    except FloodWait as exc:
        wait = getattr(exc, "value", None) or getattr(exc, "x", 1)
        await asyncio.sleep(float(wait) + 1)
        try:
            await client.send_message(user_id, body, parse_mode=ParseMode.HTML)
        except Exception:
            Runtime.welcome_failed += 1
    except Exception as exc:
        Runtime.welcome_failed += 1
        log.debug("welcome DM failed for %s: %s", user_id, exc)


async def _log_approval(client: Client, request: ChatJoinRequest, count: int) -> None:
    if not Config.LOG_CHANNEL:
        return

    user = request.from_user
    chat = request.chat
    username = ("@" + user.username) if user.username else "none"

    text = (
        "<b>Approved</b>\n\n"
        "<blockquote>Member: %s\n"
        "Username: %s\n"
        "User ID: <code>%d</code>\n"
        "Chat: %s\n"
        "Chat ID: <code>%d</code>\n"
        "Approvals here: %s</blockquote>"
        % (
            t.mention_of(user.id, user.first_name or "user"),
            t.esc(username),
            user.id,
            t.esc(chat.title or "unknown"),
            chat.id,
            t.group_num(count),
        )
    )

    try:
        await client.send_message(
            Config.LOG_CHANNEL,
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=k.log_entry(user.id),
            disable_web_page_preview=True,
        )
    except Exception as exc:
        log.debug("log channel write failed: %s", exc)


@Client.on_chat_join_request(group=-1)
async def on_join_request(client: Client, request: ChatJoinRequest) -> None:
    user = request.from_user
    chat = request.chat

    if user is None or chat is None:
        return

    if Config.APPROVE_DELAY:
        await asyncio.sleep(Config.APPROVE_DELAY)

    approved = await _approve(client, request)
    if not approved:
        Runtime.approve_errors += 1
        return

    Runtime.approved += 1

    db = get_db()
    await db.add_user(user.id, user.first_name or "", user.username or "")
    await db.add_chat(chat.id, chat.title or "", str(getattr(chat.type, "value", "")))
    await db.log_request(user.id, chat.id)

    # {count} is documented as approvals in *this* chat, so scope it per chat.
    count = await db.chat_request_count(chat.id)

    await _welcome(client, request, count)
    await _log_approval(client, request, count)
