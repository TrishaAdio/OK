#!/usr/bin/env python3
"""Offline self-test. Exercises everything that does not need Telegram.

    python3 selftest.py

Runs against a scratch database, so it is safe to run on a live install.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Credentials good enough to satisfy Config.load() without contacting Telegram.
os.environ.setdefault("API_ID", "1234567")
os.environ.setdefault("API_HASH", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("BOT_TOKEN", "1234567890:AAFakeTokenForOfflineSelfTest_xxxxxxx")
os.environ.setdefault("OWNER_ID", "42")

FAILURES = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print("  pass  %s" % label)
    else:
        print("  FAIL  %s %s" % (label, detail))
        FAILURES.append(label)


def section(name: str) -> None:
    print("\n%s" % name)


async def main() -> None:
    section("config")
    from config import Config

    Config.load()
    check("API_ID parsed", Config.API_ID == 1234567)
    check("OWNER_ID parsed", Config.OWNER_ID == 42)
    check("owner is admin", Config.is_admin(42))
    check("stranger is not admin", not Config.is_admin(99))
    check("None is not admin", not Config.is_admin(None))
    check("anim speed clamped", 0.12 <= Config.ANIM_SPEED <= 2.0)

    section("database")
    from database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "t.db"))
    await db.connect()

    check("new user reported new", await db.add_user(1, "Ann", "ann") is True)
    check("same user reported existing", await db.add_user(1, "Ann", "ann") is False)
    await db.add_user(2, "Bob", "")
    await db.add_user(3, "Cid", "")
    check("total users", await db.total_users() == 3)

    await db.add_chat(-100123, "Main Channel", "channel")
    await db.add_chat(-100123, "Renamed Channel", "channel")
    check("chat upsert does not duplicate", await db.total_chats() == 1)

    for uid in (1, 2, 3, 1):
        await db.log_request(uid, -100123)
    await db.log_request(2, -100999)

    check("total requests", await db.total_requests() == 5)
    check("per-chat count", await db.chat_request_count(-100123) == 4)
    check("unique requesters", await db.unique_requesters() == 3)
    check("requests in last day", await db.requests_since(86400) == 5)
    check("requests in last 0s", await db.requests_since(0) == 0)

    top = await db.top_chats(limit=5)
    check("top chats ordered", top and top[0]["chat_id"] == -100123 and top[0]["count"] == 4)

    await db.deactivate_user(3)
    check("active users after deactivate", await db.total_users(only_active=True) == 2)
    check("total users unchanged", await db.total_users() == 3)
    check("active id list", await db.get_user_ids(only_active=True) == [1, 2])

    await db.set("welcome_text", "<b>hi</b>")
    check("setting round trip", await db.get("welcome_text") == "<b>hi</b>")
    await db.delete("welcome_text")
    check("setting deleted", await db.get("welcome_text") is None)
    check("setting default honoured", await db.get("nope", "fallback") == "fallback")
    check("db size positive", db.size_bytes() > 0)

    await db.close()

    section("placeholders")
    from helpers import texts as t

    class U:
        id = 777
        first_name = "Ann"
        last_name = "Lee"
        username = "annlee"

    class Ch:
        id = -100123
        title = "Main Channel"

    values = t.welcome_values(U(), Ch(), count=9)
    out = t.render("Hi {first} {last} -> {chat} #{count} [{username}] {id}", values)
    check("placeholders substituted", out == "Hi Ann Lee -> Main Channel #9 [@annlee] 777", out)

    check("unknown tag left intact", t.render("{nope}", values) == "{nope}")
    # The regex renderer must survive braces that str.format would reject.
    check("stray brace survives", t.render("100% {", values) == "100% {")
    check("json-ish text survives", t.render('{"a": 1}', values) == '{"a": 1}')
    check("mention is a tg link", 'href="tg://user?id=777"' in values["mention"])

    class Evil:
        id = 5
        first_name = "<script>x</script>"
        last_name = ""
        username = ""

    evil = t.welcome_values(Evil(), Ch(), 0)
    check("html escaped in name", "&lt;script&gt;" in evil["first"])
    check("html escaped in mention", "<script>" not in evil["mention"])

    check("human_time short", t.human_time(59) == "59s")
    check("human_time hours", t.human_time(3661) == "1h 1m 1s")
    check("human_time days", t.human_time(90061).startswith("1d"))
    check("human_bytes", t.human_bytes(2048) == "2.0 KB")
    check("group_num", t.group_num(1234567) == "1,234,567")
    check("placeholders block renders", "{mention}" in t.placeholders_block())

    section("animation")
    from helpers import animate as anim

    check("bar empty", anim.smooth_bar(0.0, 10) == anim.EMPTY * 10)
    check("bar full", anim.smooth_bar(1.0, 10) == anim.FULL * 10)
    check("bar clamps low", anim.smooth_bar(-5, 10) == anim.EMPTY * 10)
    check("bar clamps high", anim.smooth_bar(9, 10) == anim.FULL * 10)

    widths = {len(anim.smooth_bar(i / 97.0, 14)) for i in range(98)}
    check("bar width is constant", widths == {14}, str(widths))

    # A sliding bar must never move backwards as the fraction grows.
    filled = [anim.smooth_bar(i / 200.0, 14).count(anim.FULL) for i in range(201)]
    check("bar is monotonic", all(b >= a for a, b in zip(filled, filled[1:])))

    partials = {anim.smooth_bar(i / 200.0, 14)[-14:] for i in range(201)}
    check("bar has sub-steps", len(partials) > 14, "only %d distinct frames" % len(partials))

    check("percent formatting", anim.percent(0.5) == " 50%" and anim.percent(1) == "100%")

    frames = anim.build_steps("Working", ("One", "Two", "Three"), sub=2)
    check("frame count", len(frames) == 7, str(len(frames)))
    check("first frame at 0%", "  0%" in frames[0])
    check("last frame at 100%", "100%" in frames[-1])
    check("last frame all ticks", frames[-1].count("✓") == 3)
    check("frames are distinct", len(set(frames)) == len(frames))
    check("progress block renders", "<code>" in anim.progress_block("T", 0.4, "detail"))

    section("keyboards")
    from helpers import keyboards as k

    check("native styles available", k.STYLES_AVAILABLE)
    check("style enum wired", str(k.DANGER) in ("ButtonStyle.DANGER", "danger"), str(k.DANGER))

    home = k.home("testbot", is_admin=True)
    flat = [b for row in home.inline_keyboard for b in row]
    check("home has buttons", len(flat) >= 6)
    check("owner sees welcome button", any("Welcome" in b.text for b in flat))
    check("styles applied", any(getattr(b, "style", None) == k.PRIMARY for b in flat))
    check("danger applied", any(getattr(b, "style", None) == k.DANGER for b in flat))
    check("success applied", any(getattr(b, "style", None) == k.SUCCESS for b in flat))

    check("owner sees stats button", any("Stats" in b.text for b in flat))

    guest = k.home("testbot", is_admin=False)
    guest_flat = [b for row in guest.inline_keyboard for b in row]
    check("guest hides welcome button", not any("Welcome" in b.text for b in guest_flat))
    check("guest hides stats button", not any("Stats" in b.text for b in guest_flat))
    check(
        "guest has no stats callback",
        not any("stats" in (b.callback_data or "") for b in guest_flat),
        str([b.callback_data for b in guest_flat]),
    )
    check("guest still gets add + help buttons", len(guest_flat) >= 4)

    check("startchannel deep link", any("startchannel" in (b.url or "") for b in flat))

    # Every callback button must round-trip through Telegram's 64-byte cap.
    oversized = [
        b.callback_data for b in flat
        if b.callback_data and len(b.callback_data.encode()) > 64
    ]
    check("callback_data within 64 bytes", not oversized, str(oversized))

    for name, markup in (
        ("help", k.help_screen(True)),
        ("stats", k.stats_screen()),
        ("settings", k.settings_screen(True, True)),
        ("settings plain", k.settings_screen(False, False)),
        ("confirm", k.confirm("a:yes", "a:no")),
        ("broadcast", k.broadcast_running()),
        ("close", k.close_only()),
        ("back", k.back_only()),
        ("log entry", k.log_entry(12345)),
    ):
        rows = markup.inline_keyboard
        check("%s keyboard builds" % name, bool(rows) and all(rows))

    check("no photo button when absent",
          not any("photo" in b.text.lower()
                  for row in k.settings_screen(False, True).inline_keyboard for b in row))
    check("welcome keyboard None without link", k.welcome_for_user("X", None) is None)
    check("welcome keyboard with link", k.welcome_for_user("X", "https://t.me/x") is not None)

    long_title = "T" * 200
    label = k.welcome_for_user(long_title, "https://t.me/x").inline_keyboard[0][0].text
    check("long chat title truncated", len(label) <= 60, "len=%d" % len(label))

    section("plugin imports")
    import importlib

    for module in (
        "plugins.acceptor",
        "plugins.start",
        "plugins.settings",
        "plugins.stats",
        "plugins.broadcast",
        "plugins.inline",
    ):
        try:
            importlib.import_module(module)
            check("%s imports" % module, True)
        except Exception as exc:
            check("%s imports" % module, False, repr(exc))

    section("handler registration")
    from pyrogram import Client

    # Smart plugins are discovered by Client at start-up; verify the tree the
    # loader will walk is importable and the decorators produced handlers.
    import plugins.acceptor as acceptor_mod

    check("join-request handler present", hasattr(acceptor_mod, "on_join_request"))
    check("approve helper present", hasattr(acceptor_mod, "_approve"))

    import plugins.broadcast as bc

    check("flag -f parsed", bc._flags("-f hello") == (True, "hello"))
    check("no flag parsed", bc._flags("hello there") == (False, "hello there"))
    report = bc._report(
        {"sent": 10, "blocked": 1, "deleted": 2, "failed": 0}, 13, 5.0, False
    )
    check("report counts users", "13" in report and "10" in report)
    check("cancelled report differs", "stopped" in bc._report(
        {"sent": 1, "blocked": 0, "deleted": 0, "failed": 0}, 9, 1.0, True).lower())

    section("owner-only access")
    import plugins.stats as stats_mod
    import plugins.start as start_mod

    def filter_names(f):
        """Names of every filter in a tree. `&` nests them as base/other."""
        found = {type(f).__name__}
        for attr in ("base", "other"):
            child = getattr(f, attr, None)
            if child is not None:
                found |= filter_names(child)
        return found

    # Every /stats entry point must be gated, or the lockdown leaks.
    for name in ("stats_command", "stats_callbacks"):
        handlers = getattr(getattr(stats_mod, name), "handlers", [])
        gated = all("AdminOnly" in filter_names(h.filters) for h, _ in handlers)
        check(
            "%s is admin-gated" % name,
            bool(handlers) and gated,
            str([filter_names(h.filters) for h, _ in handlers]),
        )

    denied = getattr(stats_mod, "stats_callback_denied", None)
    check("stats callback fallback exists", denied is not None)
    if denied is not None:
        groups = [g for _, g in denied.handlers]
        check("fallback sits in a later group", groups == [1], str(groups))

    guard = getattr(start_mod, "owner_command_denied", None)
    check("owner command fallback exists", guard is not None)
    check("stats is in the guarded list", "stats" in start_mod.OWNER_GUARDED)
    for command in ("set", "preview", "reset", "bcast"):
        check("%s is guarded" % command, command in start_mod.OWNER_GUARDED)

    import bot as bot_mod

    public = [c.command for c in bot_mod.PUBLIC_COMMANDS]
    owner = [c.command for c in bot_mod.OWNER_COMMANDS]
    check("stats not advertised publicly", "stats" not in public, str(public))
    check("stats advertised to owner", "stats" in owner)
    check("owner list is a superset", set(public).issubset(set(owner)))

    check("stats_screen takes no args", stats_mod.k.stats_screen() is not None)

    section("state")
    from helpers.state import Runtime

    Runtime._anim_seen.clear()
    check("first animation allowed", Runtime.allow_animation(1) is True)
    check("second is throttled", Runtime.allow_animation(1) is False)
    check("other user unaffected", Runtime.allow_animation(2) is True)

    print()
    if FAILURES:
        print("%d check(s) failed:" % len(FAILURES))
        for name in FAILURES:
            print("  - %s" % name)
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    asyncio.run(main())
