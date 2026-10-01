"""Entry point. Run with `python3 bot.py`, or use setup.py to launch it in screen."""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

# Smart plugins are imported by module path ("plugins.*"), so the project root
# must be importable no matter which directory the bot was launched from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pyrogram import Client, __version__ as pyro_version
from pyrogram.enums import ParseMode
from pyrogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
)

from config import BASE_DIR, Config, load_or_exit
from database import get_db
from helpers import keyboards as k
from helpers.state import Runtime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(str(BASE_DIR / "bot.log")),
        logging.StreamHandler(sys.stdout),
    ],
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)

log = logging.getLogger("bot")

PUBLIC_COMMANDS = [
    BotCommand("start", "Open the menu"),
    BotCommand("help", "How to set it up"),
    BotCommand("ping", "Check the bot is alive"),
]

# /stats is owner-only, so it is not advertised in the public command list.
OWNER_COMMANDS = PUBLIC_COMMANDS + [
    BotCommand("stats", "Approval totals and reach"),
    BotCommand("set", "Set the welcome message"),
    BotCommand("preview", "Preview the welcome message"),
    BotCommand("reset", "Restore the default message"),
    BotCommand("bcast", "Broadcast to every user"),
]


class RequestAcceptor(Client):
    def __init__(self) -> None:
        super().__init__(
            name=Config.SESSION_NAME,
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            bot_token=Config.BOT_TOKEN,
            workdir=str(BASE_DIR),
            parse_mode=ParseMode.HTML,
            plugins={"root": "plugins"},
            sleep_threshold=30,
            max_concurrent_transmissions=4,
        )

    # Signatures mirror the library's and forward everything through, because
    # Client.run() calls start() with keyword arguments of its own.
    async def start(self, **kwargs) -> None:  # type: ignore[override]
        await get_db().connect()
        await super().start(**kwargs)

        me = await self.get_me()
        Runtime.bot_id = me.id
        Runtime.bot_username = me.username or ""
        Runtime.bot_name = me.first_name or "Request Acceptor"
        Runtime.started_at = time.time()

        await self._publish_commands()
        self._banner(me)
        await self._notify_start()

    async def stop(self, *args, **kwargs) -> None:  # type: ignore[override]
        try:
            await get_db().close()
        except Exception:
            pass
        await super().stop(*args, **kwargs)
        log.info("stopped cleanly")

    # ------------------------------------------------------------------
    async def _publish_commands(self) -> None:
        try:
            await self.set_bot_commands(
                PUBLIC_COMMANDS, scope=BotCommandScopeAllPrivateChats()
            )
            if Config.OWNER_ID:
                await self.set_bot_commands(
                    OWNER_COMMANDS, scope=BotCommandScopeChat(chat_id=Config.OWNER_ID)
                )
        except Exception as exc:
            log.warning("could not publish command list: %s", exc)

    def _banner(self, me) -> None:
        styled = "yes" if k.STYLES_AVAILABLE else "no (library too old)"
        log.info("=" * 58)
        log.info(" %s  @%s  (id %s)", Runtime.bot_name, Runtime.bot_username, me.id)
        log.info(" pyrogram/kurigram %s", pyro_version)
        log.info(" coloured buttons: %s", styled)
        log.info(" owner: %s", Config.OWNER_ID)
        log.info(" log channel: %s", Config.LOG_CHANNEL or "disabled")
        log.info(" animations: %s @ %ss", Config.ANIM_ENABLED, Config.ANIM_SPEED)
        log.info("=" * 58)
        # setup.py watches bot.log for this exact phrase to confirm a good
        # start, so keep the wording in sync with READY_MARKER there.
        log.info("startup complete, listening for join requests")

    async def _notify_start(self) -> None:
        db = get_db()
        total = await db.total_requests()

        text = (
            "<b>Online</b>\n\n"
            "<blockquote>Bot: @%s\n"
            "Approved so far: <b>%s</b>\n"
            "Coloured buttons: %s</blockquote>"
            % (
                Runtime.bot_username,
                "{:,}".format(total),
                "supported" if k.STYLES_AVAILABLE else "unavailable",
            )
        )

        for target in (Config.LOG_CHANNEL, Config.OWNER_ID):
            if not target:
                continue
            try:
                await self.send_message(target, text)
                break
            except Exception as exc:
                log.debug("startup notice to %s failed: %s", target, exc)


def main() -> None:
    load_or_exit()
    app = RequestAcceptor()
    try:
        app.run()
    except KeyboardInterrupt:
        log.info("interrupted")
    except Exception:
        # Without this the traceback would only reach stderr, which is lost
        # when the process is running detached inside screen.
        log.exception("fatal error, shutting down")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
