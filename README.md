# Python IRC Bot

A Python IRC bot with reconnect logic, a plugin-based command and trigger system, URL sniffing, weather lookup, and optional YouTube metadata.

## Contents
- [Quick Start](#quick-start)
- [Features](#features)
- [Plugin System](#plugin-system)
- [Example Basic Plugin](#example-basic-plugin)
- [Example Trigger Plugin](#example-trigger-plugin)
- [Requirements](#requirements)
- [Installation (Linux)](#installation-linux)
- [Installation (Windows)](#installation-windows)
- [Running the Bot](#running-the-bot)
- [Windows Example Function (PowerShell)](#windows-example-function-powershell)
- [Commands](#commands)
- [Admin PM Commands](#admin-pm-commands)
- [URL and YouTube Behavior](#url-and-youtube-behavior)
- [Weather Behavior](#weather-behavior)
- [Database Setup](#database-setup)
- [Nickname Handling](#nickname-handling)
- [Configuration Example](#configuration-example)
- [License](#license)

## Quick Start
1. Copy `config.example.json` to `config.json`.
2. Set at least one enabled network with `server`, `nick`, and `channels`.
3. Install dependencies:
  - with `venv`: `python -m pip install -r requirements.txt`
  - without `venv` on Linux: install `PyMySQL` for the system Python interpreter
4. Start the bot:
  - Linux: `./bot.py` or `python3 bot.py`
  - Windows: `python bot.py`
5. Use [Admin PM Commands](#admin-pm-commands) in a private message if you need administrative setup.

## Features
- TLS connection support (`use_tls`, enabled by default)
- Multi-network support via required `networks` array (one bot connection per entry)
- Built-in plugin system with one plugin per command/trigger under `plugins/`
- Administrative PM commands without prefix, protected by hostmask + password authentication
- Per-network plugin activation via `enabled_plugins` / `disabled_plugins`
- Per-network `enabled` flag and reconnect delay (`reconnect_delay_seconds`)
- Automatic reconnect loop on network errors
- Responds to server `PING` with `PONG`
- Joins and tracks multiple channels
- Optional oidentd.conf generation for ident spoofing (`oidentd_conf` path)
- Saves joined channels in MySQL and restores them on restart
- Optional per-network flood protection for outgoing chat messages
- Optional SASL PLAIN authentication (`CAP` negotiation)
- Optional NickServ identify command and nickname reclaiming
- Optional `perform` commands after successful connect (for example: user mode)
- Role-based channel rights (`+q +a +o +h +v`) according to server-advertised `PREFIX` support, applied on login with the highest configured level
- Optional admin raw command forwarding via PM trigger
- Optional raw logging per network to `log/chat-<network_key>.log`
- URL sniffing in channel messages:
  - Detects posted `http/https` links
  - Fetches HTML title / first heading topic
  - Filters common spam patterns
  - Flags blocked/dead links in database
- Weather command using Open-Meteo (no API key required)
- Postal code fallback (German ZIP code lookup)
- Optional YouTube link parsing via YouTube Data API
- German/English output (`language: "de"` or `"en"`)

## Plugin System
- Built-in plugins live in `plugins/<name>/plugin.py`.
- Commands and triggers are loaded dynamically on bot startup.
- If `enabled_plugins` is empty or omitted, all built-in plugins are loaded except those listed in `disabled_plugins`.
- If `enabled_plugins` contains entries, only these plugins are loaded for that network.

### Available Plugins

**Commands:**
- `help` — Displays available commands and their usage (sent as NOTICE)
- `ping [nick]` — Sends a ping response
- `pong [nick]` — Sends a pong response
- `lag` — Measures latency in milliseconds
- `echo <text>` — Echoes text back to the user (sent as NOTICE)
- `slap <nick>` — Performs a slap action on a user
- `dart [nick]` — Throws a dart at the nick
- `darttop10` — Displays the top 10 dart players
- `mydartstats` — Shows your personal dart statistics (sent as NOTICE)
- `weather <location|plz>` — Looks up weather forecast using postal code or location name
- `url <id>` — Retrieves a stored URL from the database
- `randomurl` — Retrieves a random URL from the database
- `admin` — Provides administrative PM commands (user management, roles, channel modes, raw IRC commands)

**Triggers:**
- `unreal` — Replies with an action when a message contains the word "unreal"
- `urlsniffer` — Automatically scans posted URLs, fetches HTML titles, and stores them in the database

## Example Basic Plugin
A minimal command plugin consists of:

- a folder under `plugins/`
- a `plugin.py` file
- one or more handler functions with the signature `handler(bot, context, arg)`
- a final `PLUGIN = PluginSpec(...)` export

Example structure:

```text
plugins/
  hello/
    plugin.py
```

Example implementation:

```python
from plugin_system import CommandSpec, PluginSpec


def handle_hello(bot, context, arg: str) -> None:
    target = arg.strip() if arg.strip() else context.source_nick
    bot.send_privmsg(context.reply_target, f"Hello {target}!")


PLUGIN = PluginSpec(
    name="hello",
    commands=(
        CommandSpec(canonical="hello", handler=handle_hello, help_sort=30),
    ),
)
```

How it works:

- `name` is the internal plugin name used by `enabled_plugins` / `disabled_plugins`.
- `canonical` is the command token the bot resolves after the normal prefix, so the example becomes `!hello`.
- `context.source_nick` is the nickname of the user who sent the command.
- `context.reply_target` is automatically the channel or the sender nick in a private message.
- `arg` contains everything after the command name.
- `bot.send_privmsg(...)` sends the response back to IRC.

Useful context fields:

- `context.source_nick`
- `context.target`
- `context.message`
- `context.reply_target`
- `context.command_prefix`
- `context.is_private_message`

Useful bot helpers:

- `bot.send_privmsg(target, message)`
- `bot.send_notice(target, message)`
- `bot.send_action(target, message)`
- `bot.primary_command_name("...")`
- `bot.tr("...")` for translated plugin messages

For a very small real example, see the existing ping plugin in `plugins/ping/plugin.py`.

## Example Trigger Plugin
A trigger plugin reacts to normal chat messages without requiring the command prefix.

Example structure:

```text
plugins/
  cheer/
  plugin.py
```

Example implementation:

```python
import re

from plugin_system import MessageHandlerSpec, PluginSpec


def handle_cheer(bot, context) -> None:
  if re.search(r"\bgg\b", context.message, re.IGNORECASE):
    bot.send_action(context.reply_target, "cheers loudly!")


PLUGIN = PluginSpec(
  name="cheer",
  message_handlers=(
    MessageHandlerSpec(handler=handle_cheer),
  ),
)
```

How it works:

- `message_handlers` are called for every incoming `PRIVMSG`.
- A trigger plugin decides on its own whether it wants to react.
- `context.message` contains the full incoming text.
- `context.reply_target` is the channel in public chat and the sender nick in private chat.
- `bot.send_action(...)` sends a CTCP ACTION, similar to `/me` in IRC clients.

Typical uses:

- keyword reactions
- automatic helper replies
- moderation or logging hooks
- URL or content sniffing

For a small real example, see `plugins/unreal/plugin.py`.

## Requirements
- Python 3.10+
- MySQL/MariaDB (required for dart stats, URL storage, and persistent channels)

Setup paths:
- Use a virtual environment if you want isolated Python packages.
- Use the system Python only if `PyMySQL` is installed for that exact interpreter.

## Installation (Linux)
1. Open the project folder:
  - `cd ./ircbot-python`
2. Create your config file:
  - `cp config.example.json config.json`
3. Create and activate a virtual environment:
  - `python3 -m venv .venv`
  - `source .venv/bin/activate`
4. Edit `config.json`:
  - Define `networks` (required) and set per-network values (`server`, `port`, `use_tls`, `nick`, `channels`, ...)
  - Top-level values act as defaults for all entries in `networks`
  - Database settings: `mysql_host`, `mysql_port`, `mysql_user`, `mysql_password`, `mysql_database`
  - Optional: `weather_default_location`, `youtube_api_key`, `language`, `enabled_plugins`, `disabled_plugins`, `raw_chat_logging_enabled`, `flood_protection_enabled`, SASL/NickServ options, `oidentd_conf` (path to .oidentd.conf file, e.g., `~/.oidentd.conf`)

Flood/spam delay behavior:

- `flood_protection_enabled`: globally as default or per network override to fully enable/disable outgoing chat throttling
- `flood_protection_enabled`: globally as default or per network override to fully enable/disable outgoing chat throttling and the startup delay for public triggers
- `flood_min_interval_ms`: minimum delay between outgoing chat messages
- `flood_burst` + `flood_window_seconds`: burst/window rate limiting for outgoing chat messages
5. Install dependencies:
  - `python -m pip install -r requirements.txt`

Linux without virtual environment:

- Ubuntu / Debian:
  - `sudo apt update`
  - `sudo apt install python3-pymysql`
- Fedora:
  - `sudo dnf install python3-PyMySQL`
- Then run the bot with your system Python, for example:
  - `./bot.py`

Note:

- If you run the bot without `venv`, `PyMySQL` must be installed for the same Python interpreter that starts `bot.py`.
- If you prefer `pip` without `venv`, use `python3 -m pip install --user -r requirements.txt` instead of the distro package.

## Installation (Windows)
1. Open the project folder:
  - `cd .\ircbot-python`
2. Create your config file:
  - `Copy-Item config.example.json config.json`
3. Create and activate a virtual environment:
  - `python -m venv .venv`
  - `.\.venv\Scripts\Activate.ps1`
4. Install dependencies:
  - `python -m pip install -r requirements.txt`

## Running the Bot
- Linux foreground (default):
  - `python bot.py`
- Linux background control with PID file:
  - Start: `python bot.py --start`
  - Stop: `python bot.py --stop`
  - Restart: `python bot.py --restart`
- Windows foreground (default):
  - `python bot.py`
- Windows background control with PID file:
  - Start: `python bot.py --start`
  - Stop: `python bot.py --stop`
  - Restart: `python bot.py --restart`

## Windows Example Function (PowerShell)
You can add this helper function to your PowerShell profile and control the bot with one command:

```powershell
function Invoke-IrcBot {
    param(
        [ValidateSet('start','stop','restart','run')]
        [string]$Action = 'run',
    [string]$BotPath = '.'
    )

    Push-Location $BotPath
    try {
        switch ($Action) {
            'start'   { python .\bot.py --start }
            'stop'    { python .\bot.py --stop }
            'restart' { python .\bot.py --restart }
            'run'     { python .\bot.py }
        }
    }
    finally {
        Pop-Location
    }
}
```

Examples:
- `Invoke-IrcBot -Action run`
- `Invoke-IrcBot -Action start`
- `Invoke-IrcBot -Action restart`
- `Invoke-IrcBot -Action stop`

## Commands
Default prefix: `!`

The following commands are available when the corresponding plugins are enabled:

- `!help` / `!hilfe`
- `!ping [nick]`
- `!pong [nick]`
- `!lag`
- `!echo <text>`
- `!slap <nick>`
- `!dart [nick]`
- `!dart top10`
- `!darttop10`
- `!mydartstats` / `!meinedartstats`
- `!weather <location>` / `!wetter <ort|plz>`
- `!url <id>`
- `!randomurl` / `!zufallsurl`

Notes:
- `!help`, `!echo`, and `!mydartstats` are sent as NOTICE to the requesting user.
- If no admin user exists yet, the bot asks in the terminal for an initial `ident@host` and password before a foreground run and also before `--start` / `--restart`.
- Administrative commands only work in a private message to the bot and must be sent without the normal command prefix.
- Admin rights require `login <password>` from the matching `ident@host` first.
- New users default to the non-admin `user` role; channel rights can be assigned per role or per user and are only applied while the matching user is logged in.
- If multiple rights are configured for the same channel, the bot only applies the highest supported mode.
- Supported member modes are limited to what the IRC server advertises via `005 PREFIX=...`.
- If `raw_chat_logging_enabled` is enabled for a network, all incoming and outgoing IRC raw lines are appended to `log/chat-<network_key>.log` in the format `<unix_timestamp_ms> <raw_irc_line>`, for example `1539452142405 NOTICE AUTH :*** Looking up your hostname`.
- If `!dart` has no argument, the caller nickname is used.
- `!lag` measures latency in nanoseconds and displays a readable millisecond value (for sub-millisecond latency as decimal, e.g. `0.123 ms`) plus raw `ns` in parentheses.
- If `weather_default_location` is set, weather can be requested without arguments.

Trigger plugins:
- `unreal`: replies with an action when a message contains `unreal`
- `urlsniffer`: scans posted URLs and stores/sniffs them automatically

## Admin PM Commands
Send these as a private message to the bot, without the normal command prefix:

- `help`
- `help auth`
- `help users`
- `help roles`
- `help modes`
- `help raw`
- `login <password>` authenticates your current hostmask for admin commands.
- `logout` ends the current admin session.
- `whoami` shows your current admin role and rights.
- `listroles` lists all stored roles.
- `listusers` lists all stored admin users.
- `roleadd <role> [admin=on] [raw=on]` creates a new role.
- `roleflag <role> <admin|raw> <on|off>` enables or disables one role flag.
- `adduser <name> <ident@host> <password> [role]` creates an admin user.
- `deluser <ident@host>` deletes an admin user.
- `setrole <ident@host> <role>` assigns a different role to a user.
- `rolemode <role> <#channel> <mode>` allows a channel mode for one role.
- `rolemode-del <role> <#channel> <mode>` removes a role/channel mode rule.
- `usermode <ident@host> <#channel> <mode>` adds a user-specific channel mode rule.
- `usermode-del <ident@host> <#channel> <mode>` removes a user-specific rule.
- `apply <nick> <#channel> <ident@host>` applies stored mode rules to a nick immediately.
- `raw <IRC RAW LINE>` sends one raw IRC line directly to the server.

Examples:
- `login geheim`
- `roleadd ops`
- `rolemode ops #mychan o`
- `adduser alice ident@example.org geheim ops`
- `apply Alice #mychan ident@example.org`

## URL and YouTube Behavior
- Posted URLs are normalized and processed once per runtime session.
- Non-HTML links are marked as dead links.
- Suspicious URLs/topics are blocked by simple spam keyword/domain checks.
- `!url <id>` loads a URL from the `bot_url` table.
- `!randomurl` picks a random non-blocked, non-dead URL from `bot_url`.
- If `youtube_api_key` is configured and a YouTube URL is detected, the bot can show:
  - Title
  - Channel
  - Duration
  - Publish date
  - Views / likes / comments (if available)

## Weather Behavior
- Uses Open-Meteo geocoding + forecast API.
- Supports German postal code lookup fallback.
- Place names and decimal formatting follow the configured bot language (`de`/`en`).
- Returns temperature, "feels like", humidity, precipitation, and wind.
- In channels without mode `+c`, the bot can use IRC control codes (bold/color) for richer output.

## Database Setup
On startup, the bot tries to:
- create the configured database (if missing)
- create required tables:
  - `bot_dart`
  - `bot_url`
  - `bot_channels`

If MySQL is unavailable, startup continues, but DB-backed features may not work.

## Nickname Handling
- If the nickname is already in use (`433`), the bot appends `_`.
- With nickname protection enabled, the bot periodically tries to reclaim the preferred nickname.

## Configuration Example
See `config.example.json` for all available options, including:
- Multi-network mode (`networks`):
  - required (legacy single-network root fields are no longer supported)
  - top-level values are defaults for every network entry
  - each network object can override any setting
  - `enabled` can disable a network without deleting its config (recommended instead of commenting, since JSON has no comments)
  - `reconnect_delay_seconds` controls reconnect interval per network
  - `network_key` can be used to control channel persistence key in `bot_channels.network` (must be unique)
- Plugin control:
  - `enabled_plugins` loads only the listed plugins for a network when not empty
  - `disabled_plugins` excludes listed plugins when `enabled_plugins` is empty
- Optional raw chat logging:
  - `raw_chat_logging_enabled` enables per-network raw logs for all IRC lines
  - the bot creates a `log` directory automatically when needed
  - log files are written as `log/chat-<network_key>.log`
  - top-level value acts as default; each network entry can override it

## License
This project is licensed under the MIT License. See `LICENSE` for details.
