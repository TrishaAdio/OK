# Request Acceptor

Telegram bot that approves join requests to your channel or group the instant
they arrive, then sends each new member a message you control.

## Install

```bash
python3 setup.py
```

It asks for your `API_ID`, `API_HASH`, `BOT_TOKEN` and `OWNER_ID`, verifies the
token against Telegram, writes `config.env`, installs the dependencies and
starts the bot in a detached screen session named `request`.

```
attach   screen -r request
detach   Ctrl-A then D
restart  python3 setup.py --restart
stop     python3 setup.py --stop
logs     tail -f bot.log
```

Other flags: `--reconfigure`, `--no-deps`, `--no-start`, `--dry-run`,
`--non-interactive`.

## Connecting it to a chat

1. Add the bot to the channel or group as an **admin with the Add Members
   right**. Approval fails without it, and the bot will tell you so once.
2. Create an invite link with **Request Admin Approval** turned on, or enable it
   on the link you already share.
3. Share that link.

## Commands

| Command | Who | What |
| --- | --- | --- |
| `/start` | anyone | Menu |
| `/help` | anyone | Setup steps |
| `/ping` | anyone | Latency and uptime |
| `/stats` | owner | Approval totals, reach and health |
| `/set` | owner | Set the welcome message |
| `/preview` | owner | See the message as a member receives it |
| `/reset` | owner | Restore the default message |
| `/bcast` | owner | Send a message to every known user |

Owner commands are restricted to `OWNER_ID` plus anyone listed in
`SUDO_USERS`. For everyone else they are absent from the command menu, the
Stats button is not rendered, and running one returns a short refusal. Pressing
a stale owner button answers with an alert rather than acting.

Inline mode works too: type `@yourbot` in any chat, optionally with `share`,
`help` or `welcome`. Inline statistics are owner-only as well.

### /set

```
/set Welcome {mention}, glad you made it to {chat}.
```

Also accepts a reply: `/set` while replying to any message copies its text, and
its photo if it has one. Formatting you apply in your Telegram client is kept,
and raw HTML tags work as well.

| Placeholder | Value |
| --- | --- |
| `{mention}` | clickable mention |
| `{first}` `{last}` `{full}` | name parts |
| `{username}` | `@username`, or first name if unset |
| `{id}` | user id |
| `{chat}` `{chat_id}` | chat title and id |
| `{count}` | approvals so far in that chat |

Supported tags: `b`, `u`, `s`, `code`, `pre`, `a href`, `blockquote`.

### /bcast

Reply to the message you want sent, or write it inline. Add `-f` to forward
instead of copy. Progress updates live and can be stopped mid-run. Users who
blocked the bot or deleted their account are detected and skipped from then on.

## Coloured buttons

Buttons are coloured with the native `style` field added to
`InlineKeyboardButton` in [Bot API 9.4](https://core.telegram.org/bots/api-changelog)
(9 February 2026) — `primary`, `success`, `danger` — not emoji standing in for
colour. `helpers/keyboards.py` is the only place styles are assigned.

Two consequences worth knowing:

- Telegram clients released before February 2026 render the buttons uncoloured.
  Nothing breaks; the colour is simply absent.
- This is why `requirements.txt` pins **kurigram** rather than `pyrogram`.
  Upstream pyrogram 2.0.106 is frozen at an older TL layer and has no
  `ButtonStyle` at all. `helpers/keyboards.py` detects support at import time
  and drops the field if it is missing, so the bot still runs either way.
  `/start` logs which mode it is in.

## Animations

Telegram has no animation primitive for text messages, so motion comes from
editing one message repeatedly. `helpers/animate.py` keeps that from looking
cheap: progress bars advance in eighth-of-a-character steps using Unicode
partial blocks, and every frame is padded to a fixed width inside `<code>` so
the message never reflows mid-animation. Keyboards are attached only to the
final frame, so buttons do not flicker.

Every edit goes through `safe_edit`, which absorbs `MessageNotModified` and
backs off on `FloodWait`. Animations are throttled to once per user per six
seconds. Set `ANIM_ENABLED=false` in `config.env` for a completely static UI, or
tune `ANIM_SPEED`.

## config.env

| Key | Default | Meaning |
| --- | --- | --- |
| `API_ID`, `API_HASH` | — | from my.telegram.org |
| `BOT_TOKEN` | — | from @BotFather |
| `OWNER_ID` | — | your numeric id |
| `LOG_CHANNEL` | off | channel that logs every approval |
| `SUDO_USERS` | empty | extra ids allowed to run owner commands |
| `WELCOME_ENABLED` | `true` | send the welcome message |
| `APPROVE_DELAY` | `0` | seconds to wait before approving |
| `ANIM_ENABLED` | `true` | message animations |
| `ANIM_SPEED` | `0.34` | seconds per frame |
| `BCAST_CONCURRENCY` | `5` | parallel sends during `/bcast` |

## Layout

```
bot.py          client bootstrap, logging, command registration
config.py       config.env loader and validation
database.py     SQLite (users, chats, requests, settings)
setup.py        interactive installer and screen supervisor
selftest.py     offline checks, needs no credentials
helpers/        animate, keyboards, texts, guards, state
plugins/        acceptor, start, settings, stats, broadcast, inline
```

`plugins/acceptor.py` is the actual feature; everything else is interface.

## Checks

```bash
python3 selftest.py
```

Runs about 90 assertions over the database, placeholder rendering, HTML
escaping, animation geometry and every keyboard, against a scratch database.
Needs no credentials and is safe on a live install.

## Notes

- Members are greeted by direct message. Telegram only allows that if they have
  started the bot, so greetings to people who never have are counted as
  undeliverable in `/stats` rather than treated as errors.
- `config.env` holds your credentials, is written `chmod 600`, and is gitignored.
- If `screen` is missing, `setup.py` installs it. On minimal images it also
  repairs `/run/screen` permissions, which otherwise break screen silently.
