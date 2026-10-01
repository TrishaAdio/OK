"""Frame-based message animation.

Telegram has no animation primitive for text messages, so motion is produced by
editing one message repeatedly. Two things make that look smooth rather than
janky:

* sub-cell progress bars — the bar advances in 1/8th-of-a-character steps using
  the Unicode partial block glyphs, so it slides instead of jumping;
* fixed-width framing — every frame is padded to the same visual width and
  wrapped in <code>, so the message box never reflows between edits.

Every edit is funnelled through `safe_edit`, which swallows the errors that are
expected during animation (MessageNotModified) and backs off on FloodWait.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, Sequence

from pyrogram.enums import ParseMode
from pyrogram.errors import (
    FloodWait,
    MessageIdInvalid,
    MessageNotModified,
)
from pyrogram.types import InlineKeyboardMarkup, Message

from config import Config

log = logging.getLogger("animate")

# " " then the eight partial blocks, index 0..8
PARTIALS = " ▏▎▍▌▋▊▉█"
FULL = "█"
EMPTY = "░"

SPINNER = ("◐", "◓", "◑", "◒")
BRAILLE = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


def smooth_bar(fraction: float, width: int = 14) -> str:
    """A progress bar with 1/8-character resolution."""
    fraction = max(0.0, min(1.0, float(fraction)))
    exact = fraction * width
    whole = int(exact)
    remainder = exact - whole

    bar = FULL * whole
    if whole < width:
        step = int(remainder * 8)
        if step > 0:
            bar += PARTIALS[step]
        bar += EMPTY * (width - len(bar))
    return bar[:width]


def percent(fraction: float) -> str:
    return "%3d%%" % int(max(0.0, min(1.0, fraction)) * 100)


def steps_frame(
    title: str,
    steps: Sequence[str],
    current: int,
    fraction: float,
    width: int = 14,
) -> str:
    """Render a checklist where completed steps tick off as the bar advances."""
    lines: List[str] = []
    for index, label in enumerate(steps):
        if index < current:
            marker = "✓"
        elif index == current:
            marker = "▸"
        else:
            marker = "·"
        lines.append("%s %s" % (marker, label))

    body = "\n".join(lines)
    bar = smooth_bar(fraction, width)
    return "<b>%s</b>\n\n<blockquote>%s</blockquote>\n<code>%s %s</code>" % (
        title,
        body,
        bar,
        percent(fraction),
    )


def build_steps(
    title: str, steps: Sequence[str], sub: int = 2, width: int = 14
) -> List[str]:
    """Expand a step list into animation frames (sub frames per step)."""
    frames: List[str] = []
    total = max(1, len(steps))
    for index in range(total):
        for k in range(max(1, sub)):
            fraction = (index + (k / max(1, sub))) / total
            frames.append(steps_frame(title, steps, index, fraction, width))
    frames.append(steps_frame(title, steps, total, 1.0, width))
    return frames


def progress_block(
    title: str,
    fraction: float,
    detail: str = "",
    width: int = 14,
    spin: Optional[str] = None,
) -> str:
    """A single live progress frame, used by /bcast."""
    head = "<b>%s</b>" % title
    if spin:
        head = "<b>%s</b> %s" % (title, spin)
    out = "%s\n\n<code>%s %s</code>" % (head, smooth_bar(fraction, width), percent(fraction))
    if detail:
        out += "\n<blockquote>%s</blockquote>" % detail
    return out


# ----------------------------------------------------------------------
# edit helpers
# ----------------------------------------------------------------------
async def safe_edit(
    message: Message,
    text: str,
    keyboard: Optional[InlineKeyboardMarkup] = None,
    parse_mode: ParseMode = ParseMode.HTML,
) -> bool:
    """Edit a message, tolerating the errors animation naturally produces.

    Returns False when the message is gone and animation should stop.
    """
    for attempt in (1, 2):
        try:
            await message.edit_text(
                text, parse_mode=parse_mode, reply_markup=keyboard
            )
            return True
        except MessageNotModified:
            return True
        except FloodWait as exc:
            wait = getattr(exc, "value", None) or getattr(exc, "x", 1)
            if attempt == 2 or wait > 10:
                log.warning("animation gave up after FloodWait %ss", wait)
                return False
            await asyncio.sleep(float(wait) + 0.5)
        except MessageIdInvalid:
            return False
        except Exception as exc:  # message deleted, chat blocked, ...
            log.debug("safe_edit stopped: %s", exc)
            return False
    return False


async def play(
    message: Message,
    frames: Sequence[str],
    *,
    final: Optional[str] = None,
    keyboard: Optional[InlineKeyboardMarkup] = None,
    delay: Optional[float] = None,
    skip: bool = False,
) -> Message:
    """Play `frames` over an existing message, then settle on `final`.

    The keyboard is attached only to the final frame so buttons do not flicker
    in and out during playback.
    """
    tail = final if final is not None else (frames[-1] if frames else "")

    if skip or not Config.ANIM_ENABLED or not frames:
        await safe_edit(message, tail, keyboard)
        return message

    step = Config.ANIM_SPEED if delay is None else delay

    for frame in frames:
        if not await safe_edit(message, frame):
            return message
        await asyncio.sleep(step)

    await safe_edit(message, tail, keyboard)
    return message


async def send_and_play(
    client,
    chat_id: int,
    frames: Sequence[str],
    *,
    final: str,
    keyboard: Optional[InlineKeyboardMarkup] = None,
    delay: Optional[float] = None,
    skip: bool = False,
    reply_to: Optional[int] = None,
) -> Optional[Message]:
    """Send the first frame as a new message, then animate to `final`."""
    if skip or not Config.ANIM_ENABLED or not frames:
        try:
            return await client.send_message(
                chat_id,
                final,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                reply_to_message_id=reply_to,
                disable_web_page_preview=True,
            )
        except Exception as exc:
            log.debug("send_and_play failed: %s", exc)
            return None

    try:
        message = await client.send_message(
            chat_id,
            frames[0],
            parse_mode=ParseMode.HTML,
            reply_to_message_id=reply_to,
            disable_web_page_preview=True,
        )
    except Exception as exc:
        log.debug("send_and_play failed: %s", exc)
        return None

    await asyncio.sleep(Config.ANIM_SPEED if delay is None else delay)
    return await play(
        message, frames[1:], final=final, keyboard=keyboard, delay=delay
    )
