#!/usr/bin/env python3
"""Interactive installer.

Asks for the credentials, writes config.env, installs the dependencies and
starts the bot inside a detached GNU screen session named `request`.

    python3 setup.py                 # full interactive run
    python3 setup.py --reconfigure   # re-ask every question
    python3 setup.py --no-deps       # skip pip install
    python3 setup.py --no-start      # configure only
    python3 setup.py --restart       # restart the screen session
    python3 setup.py --stop          # kill the screen session
    python3 setup.py --dry-run       # show what would happen, change nothing

Non-interactive (reads API_ID, API_HASH, BOT_TOKEN, OWNER_ID, LOG_CHANNEL from
the environment):

    python3 setup.py --non-interactive
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / "config.env"
REQUIREMENTS = BASE_DIR / "requirements.txt"
SESSION = "request"

RE_API_HASH = re.compile(r"^[a-fA-F0-9]{32}$")
RE_TOKEN = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{30,}$")

DRY_RUN = False


# ----------------------------------------------------------------------
# output helpers
# ----------------------------------------------------------------------
class C:
    if sys.stdout.isatty() and os.name != "nt":
        DIM = "\033[2m"
        BOLD = "\033[1m"
        RED = "\033[31m"
        GREEN = "\033[32m"
        YELLOW = "\033[33m"
        BLUE = "\033[36m"
        OFF = "\033[0m"
    else:
        DIM = BOLD = RED = GREEN = YELLOW = BLUE = OFF = ""


def banner() -> None:
    print()
    print("%s  REQUEST ACCEPTOR%s" % (C.BOLD, C.OFF))
    print("%s  auto-approve join requests · setup%s" % (C.DIM, C.OFF))
    print()


def say(message: str) -> None:
    print("  %s" % message)


def ok(message: str) -> None:
    print("  %s+%s %s" % (C.GREEN, C.OFF, message))


def warn(message: str) -> None:
    print("  %s!%s %s" % (C.YELLOW, C.OFF, message))


def fail(message: str) -> None:
    print("  %sx%s %s" % (C.RED, C.OFF, message))


def step(message: str) -> None:
    print()
    print("  %s%s%s" % (C.BLUE, message, C.OFF))


# ----------------------------------------------------------------------
# prompting
# ----------------------------------------------------------------------
def ask(
    label: str,
    hint: str = "",
    default: Optional[str] = None,
    validator=None,
    error: str = "That does not look right.",
    allow_blank: bool = False,
    non_interactive_value: Optional[str] = None,
) -> str:
    if non_interactive_value is not None:
        value = non_interactive_value.strip()
        if validator and value and not validator(value):
            fail("%s: %s" % (label, error))
            sys.exit(1)
        return value

    if hint:
        print("  %s%s%s" % (C.DIM, hint, C.OFF))

    suffix = " [%s]" % default if default else ""
    while True:
        try:
            raw = input("  %s%s: " % (label, suffix)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            fail("Cancelled.")
            sys.exit(1)

        if not raw and default is not None:
            raw = default
        if not raw:
            if allow_blank:
                return ""
            fail("This one is required.")
            continue
        if validator and not validator(raw):
            fail(error)
            continue
        return raw


def confirm(question: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    try:
        raw = input("  %s (%s): " % (question, suffix)).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not raw:
        return default
    return raw in ("y", "yes")


def is_int(value: str) -> bool:
    return value.lstrip("-").isdigit()


# ----------------------------------------------------------------------
# config.env
# ----------------------------------------------------------------------
def read_env() -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip()
    return values


def mask(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return "%s...%s" % (value[:4], value[-4:])


def verify_token(token: str) -> Optional[dict]:
    """Ask Telegram who this token belongs to. Returns the User dict or None."""
    url = "https://api.telegram.org/bot%s/getMe" % token
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("ok"):
            return payload.get("result")
        return None
    except urllib.error.HTTPError:
        return None
    except Exception:
        # No network during setup should not be fatal.
        return {"__unverified__": True}


def collect(existing: Dict[str, str], reconfigure: bool, non_interactive: bool) -> Dict[str, str]:
    def prior(key: str) -> Optional[str]:
        if reconfigure:
            return None
        return existing.get(key) or None

    def env_value(key: str) -> Optional[str]:
        if not non_interactive:
            return None
        return os.getenv(key, existing.get(key, ""))

    step("Telegram credentials")

    api_id = ask(
        "API_ID",
        hint="From my.telegram.org > API development tools (a number).",
        default=prior("API_ID"),
        validator=is_int,
        error="API_ID must be numeric.",
        non_interactive_value=env_value("API_ID"),
    )

    api_hash = ask(
        "API_HASH",
        hint="From the same page: 32 hexadecimal characters.",
        default=prior("API_HASH"),
        validator=lambda v: bool(RE_API_HASH.match(v)),
        error="API_HASH must be 32 hex characters.",
        non_interactive_value=env_value("API_HASH"),
    )

    bot_token = ask(
        "BOT_TOKEN",
        hint="From @BotFather, looks like 123456789:AA...",
        default=prior("BOT_TOKEN"),
        validator=lambda v: bool(RE_TOKEN.match(v)),
        error="That is not a valid bot token.",
        non_interactive_value=env_value("BOT_TOKEN"),
    )

    if not DRY_RUN:
        info = verify_token(bot_token)
        if info is None:
            fail("Telegram rejected that token.")
            if not non_interactive and not confirm("Keep it anyway?", default=False):
                sys.exit(1)
        elif info.get("__unverified__"):
            warn("Could not reach Telegram to verify the token; continuing.")
        else:
            ok("Token belongs to @%s" % info.get("username", "unknown"))
            if not info.get("can_join_groups", True):
                warn("Group privacy is on. Disable it in @BotFather if you need groups.")

    step("Ownership")

    owner_id = ask(
        "OWNER_ID",
        hint="Your numeric Telegram id. @userinfobot will tell you.",
        default=prior("OWNER_ID"),
        validator=is_int,
        error="OWNER_ID must be numeric.",
        non_interactive_value=env_value("OWNER_ID"),
    )

    log_channel = ask(
        "LOG_CHANNEL",
        hint="Optional channel id for approval logs, like -100123456789. Blank to skip.",
        default=prior("LOG_CHANNEL"),
        validator=is_int,
        error="A channel id is numeric and usually starts with -100.",
        allow_blank=True,
        non_interactive_value=env_value("LOG_CHANNEL"),
    )

    return {
        "API_ID": api_id,
        "API_HASH": api_hash,
        "BOT_TOKEN": bot_token,
        "OWNER_ID": owner_id,
        "LOG_CHANNEL": log_channel or "",
    }


TEMPLATE = """# Generated by setup.py on {stamp}
# Credentials live here. Keep this file private; it is gitignored.

API_ID={API_ID}
API_HASH={API_HASH}
BOT_TOKEN={BOT_TOKEN}
OWNER_ID={OWNER_ID}

# Optional channel that receives an entry for every approval.
LOG_CHANNEL={LOG_CHANNEL}

# Extra user ids allowed to run owner commands, space or comma separated.
SUDO_USERS=

# Send the welcome message to approved members.
WELCOME_ENABLED=true

# Seconds to wait before approving. 0 approves instantly.
APPROVE_DELAY=0

# Message animations. Set ANIM_ENABLED=false for a completely static UI.
ANIM_ENABLED=true
ANIM_SPEED=0.34

# Parallel sends during /bcast (1-20).
BCAST_CONCURRENCY=5
"""


def write_env(values: Dict[str, str]) -> None:
    body = TEMPLATE.format(stamp=time.strftime("%Y-%m-%d %H:%M:%S"), **values)

    if DRY_RUN:
        say("would write %s" % ENV_FILE)
        return

    # Preserve any tuning the user already changed by hand.
    if ENV_FILE.exists():
        previous = read_env()
        keep = (
            "SUDO_USERS", "WELCOME_ENABLED", "APPROVE_DELAY",
            "ANIM_ENABLED", "ANIM_SPEED", "BCAST_CONCURRENCY",
        )
        for key in keep:
            old = previous.get(key)
            if old:
                body = re.sub(
                    r"^%s=.*$" % key, "%s=%s" % (key, old), body, flags=re.MULTILINE
                )

    ENV_FILE.write_text(body, encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass
    ok("Wrote %s" % ENV_FILE.name)


# ----------------------------------------------------------------------
# dependencies
# ----------------------------------------------------------------------
def run(cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
    if DRY_RUN:
        say("would run: %s" % " ".join(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return subprocess.run(cmd, **kwargs)


def install_deps() -> bool:
    step("Dependencies")

    if not REQUIREMENTS.exists():
        warn("requirements.txt is missing; skipping.")
        return False

    base = [sys.executable, "-m", "pip", "install", "-q", "-r", str(REQUIREMENTS)]
    say("pip install -r requirements.txt")

    result = run(base, capture_output=True, text=True)
    if result.returncode == 0:
        ok("Dependencies ready")
        return True

    combined = (result.stdout or "") + (result.stderr or "")

    # PEP 668: system Python refuses to install without an explicit override.
    if "externally-managed-environment" in combined or "break-system-packages" in combined:
        warn("This Python is externally managed; retrying with an override.")
        result = run(base + ["--break-system-packages"], capture_output=True, text=True)
        if result.returncode == 0:
            ok("Dependencies ready")
            return True
        combined = (result.stdout or "") + (result.stderr or "")

    fail("pip install failed.")
    tail = [l for l in combined.strip().splitlines() if l.strip()][-6:]
    for line in tail:
        print("    %s%s%s" % (C.DIM, line, C.OFF))
    return False


PACKAGE_MANAGERS = (
    (["apt-get", "install", "-y", "screen"], ["apt-get", "update"]),
    (["dnf", "install", "-y", "screen"], None),
    (["yum", "install", "-y", "screen"], None),
    (["pacman", "-S", "--noconfirm", "screen"], None),
    (["apk", "add", "screen"], None),
    (["zypper", "--non-interactive", "install", "screen"], None),
    (["brew", "install", "screen"], None),
)


def ensure_screen() -> bool:
    if shutil.which("screen"):
        return True

    step("GNU screen")
    warn("screen is not installed.")

    prefix: List[str] = []
    is_root = getattr(os, "geteuid", lambda: 0)() == 0
    if not is_root and shutil.which("sudo"):
        prefix = ["sudo"]

    for install_cmd, update_cmd in PACKAGE_MANAGERS:
        if not shutil.which(install_cmd[0]):
            continue
        say("installing with %s" % install_cmd[0])
        if update_cmd:
            run(prefix + update_cmd, capture_output=True, text=True)
        result = run(prefix + install_cmd, capture_output=True, text=True)
        if result.returncode == 0 and (DRY_RUN or shutil.which("screen")):
            ok("screen installed")
            return True

    fail("Could not install screen automatically.")
    say("Install it yourself, for example: apt-get install screen")
    return False


# ----------------------------------------------------------------------
# screen session
# ----------------------------------------------------------------------
RE_SCREEN_PERMS = re.compile(r"Directory '([^']+)' must have mode (\d+)")


def screen_ls() -> str:
    result = subprocess.run(["screen", "-ls"], capture_output=True, text=True)
    return (result.stdout or "") + (result.stderr or "")


def screen_health() -> bool:
    """Repair the socket-directory permissions some minimal images ship with.

    On stripped-down containers and VPS images /run/screen is not world
    writable, and every screen command fails with a message rather than an
    error code. Detect that and fix it, otherwise nothing will ever start.
    """
    output = screen_ls()
    match = RE_SCREEN_PERMS.search(output)
    if not match:
        return True

    directory, mode = match.group(1), match.group(2)
    warn("screen cannot use %s (needs mode %s)." % (directory, mode))

    if DRY_RUN:
        say("would chmod %s %s" % (mode, directory))
        return True

    is_root = getattr(os, "geteuid", lambda: 0)() == 0
    prefix: List[str] = [] if is_root else (["sudo"] if shutil.which("sudo") else [])

    run(prefix + ["chmod", mode, directory], capture_output=True, text=True)

    if RE_SCREEN_PERMS.search(screen_ls()):
        fail("Could not fix %s." % directory)
        say("Run this yourself, then retry: sudo chmod %s %s" % (mode, directory))
        return False

    ok("Fixed %s permissions" % directory)
    return True


def wipe_dead() -> None:
    """Clear tombstones so `screen -r request` cannot land on a dead session."""
    if shutil.which("screen"):
        subprocess.run(["screen", "-wipe"], capture_output=True, text=True)


def bot_process_running() -> bool:
    """Is bot.py actually executing?

    This is the authoritative liveness check. `screen -ls` cannot be trusted
    for it: immediately after the child exits the socket is still advertised as
    "Detached", and only later flips to "Dead ???".
    """
    target = str(BASE_DIR / "bot.py")

    proc_dir = Path("/proc")
    if proc_dir.is_dir():
        for entry in proc_dir.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                cmdline = (entry / "cmdline").read_bytes().decode(
                    "utf-8", errors="replace"
                )
            except (OSError, IOError):
                continue
            if target in cmdline:
                return True
        return False

    if shutil.which("pgrep"):
        result = subprocess.run(
            ["pgrep", "-f", target], capture_output=True, text=True
        )
        return result.returncode == 0

    return session_exists()


def session_exists() -> bool:
    """True only when a *live* session exists.

    `screen -ls` keeps listing crashed sessions as "(Dead ???)", so matching the
    name alone would report a bot that has actually exited as healthy.
    """
    if not shutil.which("screen"):
        return False

    pattern = re.compile(
        r"^\s*\d+\.%s\s+\(([^)]*)\)" % re.escape(SESSION), re.MULTILINE
    )
    output = screen_ls()

    for match in pattern.finditer(output):
        if "dead" not in match.group(1).lower():
            return True

    # A session line with no state in brackets still counts as present.
    if pattern.search(output) is None:
        bare = re.compile(r"^\s*\d+\.%s\s*$" % re.escape(SESSION), re.MULTILINE)
        if bare.search(output):
            return True

    return False


def stop_session(quiet: bool = False) -> None:
    if not session_exists():
        wipe_dead()
        if not quiet:
            say("no session named %s" % SESSION)
        return
    run(["screen", "-S", SESSION, "-X", "quit"], capture_output=True, text=True)
    time.sleep(1.0)
    wipe_dead()
    if not quiet:
        ok("stopped session %s" % SESSION)


def start_session() -> bool:
    step("Starting the bot")

    if not shutil.which("screen") and not DRY_RUN:
        fail("screen is unavailable, cannot start detached.")
        say("Run it in the foreground instead: python3 bot.py")
        return False

    if not DRY_RUN and not screen_health():
        return False

    stop_session(quiet=True)
    wipe_dead()

    # -dmS starts the session already detached, which is what a script needs;
    # attach afterwards with `screen -r request`. -Logfile captures anything the
    # bot writes to stdout/stderr, so a crash inside the session is not silent.
    screen_log = BASE_DIR / "screen.log"
    try:
        if screen_log.exists():
            screen_log.unlink()
    except OSError:
        pass

    # Remember where the log ends so only this run's output is inspected.
    offset = log_size()

    cmd = [
        "screen", "-dmS", SESSION,
        "-L", "-Logfile", str(screen_log),
        sys.executable, str(BASE_DIR / "bot.py"),
    ]
    run(cmd, cwd=str(BASE_DIR))

    if DRY_RUN:
        say("would start: %s" % " ".join(cmd))
        return True

    say("waiting for Telegram authentication")

    outcome = wait_for_ready(offset)

    if outcome == "ready":
        ok("Running in screen session %s" % SESSION)
        return True

    if outcome == "timeout":
        warn("Still starting after %ds." % READY_TIMEOUT)
        say("It may just be slow. Watch it with: tail -f bot.log")
        return bot_process_running()

    fail("The bot did not start.")
    wipe_dead()
    diagnose(offset)
    return False


READY_MARKER = "startup complete"
FAIL_MARKERS = ("fatal error", "Traceback (most recent call last)")
READY_TIMEOUT = 45


def log_size() -> int:
    try:
        return (BASE_DIR / "bot.log").stat().st_size
    except OSError:
        return 0


def new_log_text(offset: int) -> str:
    """Only the log written since the session was launched."""
    log_file = BASE_DIR / "bot.log"
    if not log_file.exists():
        return ""
    try:
        with log_file.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            return handle.read()
    except OSError:
        return ""


def wait_for_ready(offset: int) -> str:
    """Watch the log for a definite success or failure.

    Waiting on process liveness alone is not enough: authentication can take
    longer than any sensible sleep, so a bad token may still look alive when the
    timer runs out. The bot announces itself in the log instead.
    """
    deadline = time.time() + READY_TIMEOUT

    while time.time() < deadline:
        time.sleep(1.0)
        text = new_log_text(offset)

        if READY_MARKER in text:
            return "ready"
        if any(marker in text for marker in FAIL_MARKERS):
            return "failed"
        if not bot_process_running() and not DRY_RUN:
            # Give the log a moment to flush before declaring the reason.
            time.sleep(1.0)
            return "failed"

    return "timeout"


def show_lines(blob: str, lines: int, label: str) -> bool:
    content = [l.rstrip() for l in blob.splitlines() if l.strip()]
    if not content:
        return False
    print()
    say("%s:" % label)
    for line in content[-lines:]:
        print("    %s%s%s" % (C.DIM, line[:200], C.OFF))
    return True


def tail_file(path: Path, lines: int, label: str) -> bool:
    if not path.exists():
        return False
    return show_lines(
        path.read_text(encoding="utf-8", errors="replace"), lines, label
    )


def diagnose(offset: int = 0) -> None:
    """Surface why the bot died, from whichever source actually captured it."""
    shown = show_lines(new_log_text(offset), 14, "what bot.log recorded")
    if not shown:
        shown = tail_file(BASE_DIR / "screen.log", 14, "output inside screen")

    if shown:
        return

    # Nothing was captured, so reproduce the crash in the foreground.
    say("re-running in the foreground to capture the error")
    try:
        result = subprocess.run(
            [sys.executable, str(BASE_DIR / "bot.py")],
            cwd=str(BASE_DIR), capture_output=True, text=True, timeout=45,
        )
        blob = ((result.stdout or "") + (result.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        say("it ran for 45s without exiting, so the credentials are probably fine.")
        say("try starting it again: python3 setup.py --restart")
        return
    except Exception as exc:
        fail("could not re-run: %s" % exc)
        return

    if not blob:
        say("no output at all. Try running it directly: python3 bot.py")
        return

    print()
    for line in blob.splitlines()[-14:]:
        print("    %s%s%s" % (C.DIM, line[:200], C.OFF))


def outro(started: bool) -> None:
    print()
    print("  %s%s%s" % (C.BOLD, "-" * 52, C.OFF))
    if started:
        print("  attach   %sscreen -r %s%s" % (C.BOLD, SESSION, C.OFF))
        print("  detach   %sCtrl-A then D%s" % (C.BOLD, C.OFF))
        print("  restart  %spython3 setup.py --restart%s" % (C.BOLD, C.OFF))
        print("  stop     %spython3 setup.py --stop%s" % (C.BOLD, C.OFF))
        print("  logs     %stail -f bot.log%s" % (C.BOLD, C.OFF))
    else:
        print("  start    %spython3 bot.py%s" % (C.BOLD, C.OFF))
    print("  %s%s%s" % (C.BOLD, "-" * 52, C.OFF))
    print()
    print("  Next: add the bot to your channel as an admin with the")
    print("  Add Members right, then enable request approval on the")
    print("  invite link. Send /set to choose the welcome message.")
    print()


# ----------------------------------------------------------------------
def main() -> None:
    global DRY_RUN

    args = set(sys.argv[1:])
    DRY_RUN = "--dry-run" in args
    reconfigure = "--reconfigure" in args
    non_interactive = "--non-interactive" in args
    skip_deps = "--no-deps" in args
    skip_start = "--no-start" in args

    if "--help" in args or "-h" in args:
        print(__doc__)
        return

    banner()

    if DRY_RUN:
        warn("Dry run: nothing will be written, installed or started.")

    if "--stop" in args:
        stop_session()
        return

    if "--restart" in args:
        if not ENV_FILE.exists():
            fail("No config.env yet. Run setup.py without --restart first.")
            sys.exit(1)
        started = start_session()
        outro(started)
        return

    if sys.version_info < (3, 8):
        fail("Python 3.8 or newer is required (found %d.%d)." % sys.version_info[:2])
        sys.exit(1)

    existing = read_env()
    if existing and not reconfigure and not non_interactive:
        step("Existing configuration")
        for key in ("API_ID", "OWNER_ID", "LOG_CHANNEL"):
            if existing.get(key):
                say("%-12s %s" % (key, existing[key]))
        for key in ("API_HASH", "BOT_TOKEN"):
            if existing.get(key):
                say("%-12s %s" % (key, mask(existing[key])))
        print()
        if not confirm("Change these?", default=False):
            reconfigure = False
            values = {
                "API_ID": existing.get("API_ID", ""),
                "API_HASH": existing.get("API_HASH", ""),
                "BOT_TOKEN": existing.get("BOT_TOKEN", ""),
                "OWNER_ID": existing.get("OWNER_ID", ""),
                "LOG_CHANNEL": existing.get("LOG_CHANNEL", ""),
            }
            if not all(values[k] for k in ("API_ID", "API_HASH", "BOT_TOKEN", "OWNER_ID")):
                warn("Some required values are missing; asking again.")
                values = collect(existing, True, non_interactive)
        else:
            values = collect(existing, True, non_interactive)
    else:
        values = collect(existing, reconfigure, non_interactive)

    write_env(values)

    deps_ok = True
    if not skip_deps:
        deps_ok = install_deps()
    else:
        say("skipping dependency install")

    if not deps_ok:
        warn("Continuing, but the bot may not start without its dependencies.")

    started = False
    if not skip_start:
        if ensure_screen() or DRY_RUN:
            started = start_session()
    else:
        say("skipping start")

    outro(started)


if __name__ == "__main__":
    main()
