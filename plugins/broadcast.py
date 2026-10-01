"""/bcast — deliver a message to every user the bot has seen."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import (
    FloodWait,
    InputUserDeactivated,
    PeerIdInvalid,
    UserIsBlocked,
)
from pyrogram.types import CallbackQuery, Message

from config import Config
from database import get_db
from helpers import animate as anim
from helpers import keyboards as k
from helpers import texts as t
from helpers.guards import admin_only
from helpers.state import Runtime

log = logging.getLogger("broadcast")

USAGE = (
    "<b>Broadcast</b>\n\n"
    "Reply to the message you want delivered, or write it inline.\n\n"
    "<blockquote><code>/bcast</code> — reply to any message\n"
    "<code>/bcast -f</code> — forward instead of copy\n"
    "<code>/bcast Hello everyone</code> — plain text</blockquote>"
)

# How often the progress message is edited, in seconds. Kept above 1s so a
# large broadcast cannot trip the edit rate limit.
REFRESH_EVERY = 1.4


def _flags(text: str):
    forward = False
    tokens = text.split()
    kept: List[str] = []
    for token in tokens:
        if token == "-f":
            forward = True
        else:
            kept.append(token)
    return forward, " ".join(kept)


async def _deliver(client: Client, user_id: int, source: Message, body: str, forward: bool) -> str:
    """Send to one user. Returns one of sent / blocked / deleted / failed."""
    for attempt in (1, 2):
        try:
            if source is not None and forward:
                await client.forward_messages(user_id, source.chat.id, source.id)
            elif source is not None:
                await client.copy_message(user_id, source.chat.id, source.id)
            else:
                await client.send_message(
                    user_id, body, parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            return "sent"
        except UserIsBlocked:
            return "blocked"
        except (InputUserDeactivated, PeerIdInvalid):
            return "deleted"
        except FloodWait as exc:
            wait = getattr(exc, "value", None) or getattr(exc, "x", 1)
            if attempt == 2 or wait > 60:
                return "failed"
            await asyncio.sleep(float(wait) + 1)
        except Exception as exc:
            log.debug("broadcast to %s failed: %s", user_id, exc)
            return "failed"
    return "failed"


def _report(counts: Dict[str, int], total: int, elapsed: float, cancelled: bool) -> str:
    heading = "Broadcast stopped" if cancelled else "Broadcast complete"
    processed = sum(counts.values())

    lines = [
        "Delivered: <b>%s</b>" % t.group_num(counts["sent"]),
        "Blocked the bot: <b>%s</b>" % t.group_num(counts["blocked"]),
        "Deleted accounts: <b>%s</b>" % t.group_num(counts["deleted"]),
        "Failed: <b>%s</b>" % t.group_num(counts["failed"]),
        "Processed: <b>%s</b> of %s" % (t.group_num(processed), t.group_num(total)),
    ]

    return (
        "<b>%s</b>\n\n<blockquote>%s</blockquote>\n\nTook <code>%s</code>"
        % (heading, "\n".join(lines), t.human_time(elapsed))
    )


@Client.on_message(filters.command("bcast") & filters.private & admin_only)
async def broadcast(client: Client, message: Message) -> None:
    if Runtime.broadcast_running:
        await message.reply_text(
            "A broadcast is already running.", parse_mode=ParseMode.HTML
        )
        return

    raw = ""
    if message.text:
        parts = str(message.text).split(None, 1)
        raw = parts[1] if len(parts) > 1 else ""

    forward, body = _flags(raw)
    source = message.reply_to_message

    if source is None and not body.strip():
        await message.reply_text(
            USAGE, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
        return

    db = get_db()
    users = await db.get_user_ids(only_active=True)
    total = len(users)

    if total == 0:
        await message.reply_text(
            "No users on record yet. The list fills up as members are approved.",
            parse_mode=ParseMode.HTML,
        )
        return

    Runtime.broadcast_running = True
    Runtime.broadcast_cancel = False

    counts = {"sent": 0, "blocked": 0, "deleted": 0, "failed": 0}
    started = time.time()

    status = await message.reply_text(
        anim.progress_block("Broadcasting", 0.0, "queued %s users" % t.group_num(total)),
        parse_mode=ParseMode.HTML,
        reply_markup=k.broadcast_running(),
    )

    semaphore = asyncio.Semaphore(Config.BCAST_CONCURRENCY)
    stale: List[int] = []
    spin = 0
    last_refresh = 0.0
    processed = 0

    async def worker(user_id: int) -> None:
        nonlocal processed
        async with semaphore:
            outcome = await _deliver(client, user_id, source, body, forward)
        counts[outcome] += 1
        processed += 1
        if outcome in ("blocked", "deleted"):
            stale.append(user_id)

    batch_size = max(10, Config.BCAST_CONCURRENCY * 5)

    try:
        for offset in range(0, total, batch_size):
            if Runtime.broadcast_cancel:
                break

            batch = users[offset : offset + batch_size]
            await asyncio.gather(*(worker(uid) for uid in batch))

            now = time.time()
            if now - last_refresh >= REFRESH_EVERY or processed >= total:
                last_refresh = now
                spin = (spin + 1) % len(anim.BRAILLE)
                detail = "%s delivered · %s blocked · %s failed" % (
                    t.group_num(counts["sent"]),
                    t.group_num(counts["blocked"] + counts["deleted"]),
                    t.group_num(counts["failed"]),
                )
                await anim.safe_edit(
                    status,
                    anim.progress_block(
                        "Broadcasting",
                        processed / total,
                        detail,
                        spin=anim.BRAILLE[spin],
                    ),
                    k.broadcast_running(),
                )
    finally:
        cancelled = Runtime.broadcast_cancel
        Runtime.broadcast_running = False
        Runtime.broadcast_cancel = False

        # Prune users who can never be reached again.
        for user_id in stale:
            try:
                await db.deactivate_user(user_id)
            except Exception:
                pass

        await anim.safe_edit(
            status,
            _report(counts, total, time.time() - started, cancelled),
            k.close_only(),
        )


@Client.on_callback_query(filters.regex(r"^bcast:cancel$") & admin_only)
async def cancel_broadcast(client: Client, query: CallbackQuery) -> None:
    if not Runtime.broadcast_running:
        await query.answer("Nothing is running.")
        return
    Runtime.broadcast_cancel = True
    await query.answer("Stopping after the current batch", show_alert=False)


@Client.on_callback_query(filters.regex(r"^bcast:"), group=1)
async def cancel_denied(client: Client, query: CallbackQuery) -> None:
    await query.answer("Owner only.", show_alert=True)
