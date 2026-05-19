# Python IRC Bot

A Python IRC bot with reconnect logic, command handling, URL sniffing, weather lookup, and optional YouTube metadata.

## Features
- TLS connection support (`use_tls`, enabled by default)
- Multi-network support via required `networks` array (one bot connection per entry)
- Per-network `enabled` flag and reconnect delay (`reconnect_delay_seconds`)
- Automatic reconnect loop on network errors
- Responds to server `PING` with `PONG`
- Joins and tracks multiple channels
- Optional oidentd.conf generation for ident spoofing (`oidentd_conf` path)
- Saves joined channels in MySQL and restores them on restart
- Optional flood protection for outgoing chat messages
- Optional SASL PLAIN authentication (`CAP` negotiation)
- Optional NickServ identify command and nickname reclaiming
- Optional `perform` commands after successful connect (for example: user mode)
- URL sniffing in channel messages:
  - Detects posted `http/https` links
  - Fetches HTML title / first heading topic
  - Filters common spam patterns
  - Flags blocked/dead links in database
- Weather command using Open-Meteo (no API key required)
- Postal code fallback (German ZIP code lookup)
- Optional YouTube link parsing via YouTube Data API
- German/English output (`language: "de"` or `"en"`)

## Requirements
- Python 3.10+
- MySQL/MariaDB (required for dart stats, URL storage, and persistent channels)

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
  - Optional: `weather_default_location`, `youtube_api_key`, `language`, SASL/NickServ options, `oidentd_conf` (path to .oidentd.conf file, e.g., `~/.oidentd.conf`)
5. Install dependencies:
  - `python -m pip install -r requirements.txt`

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
- If `!dart` has no argument, the caller nickname is used.
- `!lag` measures latency in nanoseconds and displays a readable millisecond value (for sub-millisecond latency as decimal, e.g. `0.123 ms`) plus raw `ns` in parentheses.
- If `weather_default_location` is set, weather can be requested without arguments.

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

## License
This project is licensed under the MIT License. See `LICENSE` for details.
