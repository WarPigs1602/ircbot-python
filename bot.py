#!/usr/bin/env python3

import json
import base64
import argparse
import atexit
import getpass
import hashlib
import hmac
import math
import os
import random
import re
import socket
import ssl
import subprocess
import sys
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, quote_plus, urlparse
from urllib.request import Request, urlopen

from plugin_system import MessageContext, PluginManager

try:
    import pymysql
except ImportError:
    pymysql = None


URL_PATTERN = re.compile(r'https?://[^\s<>"]+', re.IGNORECASE)
SPAM_WORDS = (
    "casino",
    "viagra",
    "porn",
    "xxx",
    "sex",
    "adult",
    "pharmacy",
    "loan",
    "crypto",
    "bitcoin",
    "bet",
    "bonus",
    "click",
    "free money",
    "win money",
)
SPAM_HOSTS = (
    "bit.ly",
    "tinyurl.com",
    "t.co",
    "goo.gl",
    "is.gd",
    "cutt.ly",
    "rebrand.ly",
)

DANGEROUS_CONTENT_TYPES = frozenset({
    # Generic binaries
    "application/octet-stream",
    # Windows executables / installers
    "application/x-msdownload",
    "application/x-ms-dos-executable",
    "application/vnd.microsoft.portable-executable",
    "application/x-executable",
    "application/x-msi",
    "application/x-msdos-program",
    # Scripts
    "application/x-sh",
    "application/x-csh",
    "application/x-bash",
    "application/x-perl",
    "application/x-python-code",
    "text/x-sh",
    "text/x-bash",
    "text/x-perl",
    "text/x-python",
    "text/x-ruby",
    "application/x-ruby",
    "application/x-bat",
    "application/x-powershell",
    "text/x-powershell",
    # Archives / compressed
    "application/zip",
    "application/x-zip-compressed",
    "application/x-rar-compressed",
    "application/vnd.rar",
    "application/x-7z-compressed",
    "application/x-tar",
    "application/x-gzip",
    "application/x-bzip2",
    "application/x-xz",
    "application/zstd",
    "application/x-lzma",
    # JVM / mobile
    "application/java-archive",
    "application/x-java-archive",
    "application/vnd.android.package-archive",
    # macOS
    "application/x-apple-diskimage",
    "application/x-macos-pkg",
    # Linux packages
    "application/x-deb",
    "application/x-rpm",
    # Office macros / legacy formats
    "application/vnd.ms-excel.sheet.macroEnabled.12",
    "application/vnd.ms-word.document.macroEnabled.12",
    "application/vnd.ms-powerpoint.presentation.macroEnabled.12",
    "application/vnd.ms-office",
    # Flash (legacy, still seen in the wild)
    "application/x-shockwave-flash",
    # HTA / CHM
    "application/x-ms-application",
    "application/x-ms-xbap",
    "application/vnd.ms-htmlhelp",
})

DEFAULT_PREFIX_MODES = {
    "q": "~",
    "a": "&",
    "o": "@",
    "h": "%",
    "v": "+",
}
MONDGESICHT_CHANNEL_PLAYER_COUNT_QUERY = "SELECT COUNT(*) AS total_players FROM bot_mondgesicht_scores WHERE network = %s AND channel = %s"
ADMIN_SESSION_TTL_SECONDS = 1800
ROLE_FLAG_COLUMNS = {
    "admin": "is_admin",
    "raw": "can_raw",
}
INVALID_HOSTMASK_MESSAGE = "Ungültige Hostmask."
ROLE_EXISTS_QUERY = "SELECT 1 FROM bot_admin_roles WHERE network = %s AND role_name = %s LIMIT 1"
DEFAULT_MONDGESICHT_TEXT_SEED = {
    "de": {
        "punkt1": [
            "{nick} setzt den ersten Punkt.",
            "Der erste Punkt sitzt: {nick}.",
            "{nick} setzt den ersten Punkt ins Gesicht.",
        ],
        "punkt2": [
            "{nick} setzt den zweiten Punkt.",
            "Noch ein Punkt von {nick}.",
            "{nick} macht das zweite Äuglein fertig.",
        ],
        "komma": [
            "{nick} malt das Komma in das Gesicht.",
            "Das Komma kommt von {nick}.",
            "{nick} setzt das Komma schön mittig.",
        ],
        "strich": [
            "Pünktchen, Pünktchen, Komma, Strich: fertig ist das Mondgesicht.",
            "Mondgesicht komplett in {channel}: {participants} haben {points} Punkte geholt.",
            "So schön kann ein Mondgesicht sein: {participants} waren daran beteiligt.",
        ],
    },
    "en": {
        "punkt1": [
            "{nick} places the first point.",
            "The first point belongs to {nick}.",
            "{nick} places the first point on the face.",
        ],
        "punkt2": [
            "{nick} places the second point.",
            "Another point from {nick}.",
            "{nick} finishes the second eye.",
        ],
        "komma": [
            "{nick} adds the comma.",
            "The comma comes from {nick}.",
            "{nick} places the comma neatly in the middle.",
        ],
        "strich": [
            "Point, point, comma, stroke: the moonface is complete.",
            "Moonface complete in {channel}: {participants} earned {points} points.",
            "That moonface looks great: {participants} made it happen.",
        ],
    },
}


@dataclass
class BotConfig:
    server: str
    port: int
    use_tls: bool
    nick: str
    username: str
    realname: str
    channels: list[str]
    bind_ip: str = ""
    password: str = ""
    command_prefix: str = "!"
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "nullbot"
    weather_default_location: str = ""
    youtube_api_key: str = ""
    perform: list[str] | None = None
    sasl_enabled: bool = False
    sasl_username: str = ""
    sasl_password: str = ""
    sasl_authzid: str = ""
    language: str = "de"
    flood_burst: int = 4
    flood_window_seconds: float = 2.0
    flood_min_interval_ms: int = 2000
    nick_protection_enabled: bool = False
    nick_protection_nick: str = ""
    nick_reclaim_interval_seconds: int = 60
    nickserv_password: str = ""
    nickserv_identify_command: str = "PRIVMSG NickServ :IDENTIFY {password}"
    oidentd_conf: str = ""
    network_key: str = ""
    reconnect_delay_seconds: int = 30
    raw_chat_logging_enabled: bool = False
    url_timeout_seconds: float = 3.0
    url_sniff_max_bytes: int = 65536
    url_max_content_length_bytes: int = 2097152
    enabled_plugins: list[str] | None = None
    disabled_plugins: list[str] | None = None
    mondgesicht_url_enabled: bool = False
    mondgesicht_url: str = ""

    @staticmethod
    def _from_raw(raw: dict[str, object]) -> "BotConfig":
        server = str(raw["server"])
        port = int(raw.get("port", 6697))
        nick = str(raw["nick"])

        perform_raw = raw.get("perform", [])
        if isinstance(perform_raw, str):
            perform_list = [perform_raw]
        elif isinstance(perform_raw, list):
            perform_list = [str(item) for item in perform_raw]
        else:
            perform_list = []

        language_raw = str(raw.get("language", "de")).strip().lower()
        language = language_raw if language_raw in {"de", "en"} else "de"

        def _parse_string_list(value: object) -> list[str]:
            if isinstance(value, str):
                return [value]
            if isinstance(value, list):
                return [str(item) for item in value]
            return []

        configured_network_key = str(raw.get("network_key", "")).strip()
        network_key = configured_network_key or f"{server}:{port}:{nick}".lower()

        return BotConfig(
            server=server,
            port=port,
            use_tls=bool(raw.get("use_tls", True)),
            nick=nick,
            bind_ip=str(raw.get("bind_ip", "")).strip(),
            username=str(raw.get("username", nick)),
            realname=str(raw.get("realname", "Python IRC Bot")),
            channels=list(raw.get("channels", [])),
            password=str(raw.get("password", "")),
            command_prefix=str(raw.get("command_prefix", "!")),
            mysql_host=str(raw.get("mysql_host", "127.0.0.1")),
            mysql_port=int(raw.get("mysql_port", 3306)),
            mysql_user=str(raw.get("mysql_user", "root")),
            mysql_password=str(raw.get("mysql_password", "")),
            mysql_database=str(raw.get("mysql_database", "nullbot")),
            weather_default_location=str(raw.get("weather_default_location", "")),
            youtube_api_key=str(raw.get("youtube_api_key", "")),
            perform=perform_list,
            sasl_enabled=bool(raw.get("sasl_enabled", False)),
            sasl_username=str(raw.get("sasl_username", "")),
            sasl_password=str(raw.get("sasl_password", "")),
            sasl_authzid=str(raw.get("sasl_authzid", "")),
            language=language,
            flood_burst=max(1, int(raw.get("flood_burst", 4))),
            flood_window_seconds=max(0.1, float(raw.get("flood_window_seconds", 2.0))),
            flood_min_interval_ms=max(0, int(raw.get("flood_min_interval_ms", 2000))),
            nick_protection_enabled=bool(raw.get("nick_protection_enabled", False)),
            nick_protection_nick=str(raw.get("nick_protection_nick", nick)).strip(),
            nick_reclaim_interval_seconds=max(5, int(raw.get("nick_reclaim_interval_seconds", 60))),
            nickserv_password=str(raw.get("nickserv_password", "")),
            nickserv_identify_command=str(raw.get("nickserv_identify_command", "PRIVMSG NickServ :IDENTIFY {password}")),
            oidentd_conf=str(raw.get("oidentd_conf", "")).strip(),
            network_key=network_key,
            reconnect_delay_seconds=max(1, int(raw.get("reconnect_delay_seconds", 30))),
            raw_chat_logging_enabled=bool(raw.get("raw_chat_logging_enabled", False)),
            url_timeout_seconds=max(0.5, float(raw.get("url_timeout_seconds", 3.0))),
            url_sniff_max_bytes=max(1024, int(raw.get("url_sniff_max_bytes", 65536))),
            url_max_content_length_bytes=max(65536, int(raw.get("url_max_content_length_bytes", 2097152))),
            enabled_plugins=_parse_string_list(raw.get("enabled_plugins", [])),
            disabled_plugins=_parse_string_list(raw.get("disabled_plugins", [])),
            mondgesicht_url_enabled=bool(raw.get("mondgesicht_url_enabled", False)),
            mondgesicht_url=str(raw.get("mondgesicht_url", "")).strip(),
        )

    @staticmethod
    def load_from_file(path: Path) -> list["BotConfig"]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        networks_raw = raw.get("networks")

        if not isinstance(networks_raw, list) or not networks_raw:
            raise ValueError("config.json muss ein nicht-leeres 'networks' Array enthalten.")

        base = {k: v for k, v in raw.items() if k != "networks"}
        configs: list[BotConfig] = []

        for index, network_raw in enumerate(networks_raw, start=1):
            if not isinstance(network_raw, dict):
                raise ValueError(f"networks[{index - 1}] muss ein Objekt sein.")

            if not bool(network_raw.get("enabled", True)):
                continue

            merged = dict(base)
            merged.update(network_raw)
            try:
                configs.append(BotConfig._from_raw(merged))
            except KeyError as exc:
                missing_key = exc.args[0]
                raise ValueError(f"networks[{index - 1}] fehlt Pflichtfeld: {missing_key}") from exc

        if not configs:
            raise ValueError("Kein aktives Netzwerk in 'networks' gefunden (enabled=true).")

        seen_keys: set[str] = set()
        for config in configs:
            if config.network_key in seen_keys:
                raise ValueError(f"Doppelter network_key gefunden: {config.network_key}")
            seen_keys.add(config.network_key)

        return configs

    def display_name(self) -> str:
        return f"{self.server}:{self.port}"

class IRCBot:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.sock: socket.socket | None = None
        self.file = None
        self.seen_sniffed_urls: set[str] = set()
        self.channel_modes: dict[str, set[str]] = {}
        self.channel_members: dict[str, dict[str, str]] = {}
        self._member_mode_retry_at: dict[tuple[str, str, str], float] = {}
        self.db_initialized = False
        self.cap_negotiation_active = False
        self.sasl_payload_sent = False
        self._flood_timestamps: deque[float] = deque()
        self._last_chat_send_at: float = 0.0
        self.pending_lag_checks: dict[str, tuple[int, str]] = {}
        self.initial_nick = self.config.nick
        self.current_nick = self.config.nick
        self.preferred_nick = self.config.nick_protection_nick or self.config.nick
        self.fallback_nick = (f"{self.initial_nick}_" if self.initial_nick else "_")[:15]
        self.last_nick_reclaim_attempt_at: float = 0.0
        self.nickserv_identify_sent = False
        self.startup_actions_completed = False
        self.public_trigger_activation_at: float = 0.0
        self.server_prefix_modes: dict[str, str] = dict(DEFAULT_PREFIX_MODES)
        self._admin_sessions: dict[str, dict[str, object]] = {}
        self._admin_bootstrap_warned = False
        self._mondgesicht_channels: list[str] = []
        self._send_lock = threading.RLock()
        self._url_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="urlsniff")
        self._runtime_stop_event = threading.Event()
        self._plugin_tick_thread: threading.Thread | None = None
        self.plugin_manager = PluginManager(self, Path(__file__).resolve().parent / "plugins")

    def tr(self, key: str, **kwargs) -> str:
        language = self.config.language if self.config.language in {"de", "en"} else "de"
        core_messages = {
            "de": {
                "not_connected": "Nicht verbunden",
                "sasl_failed": "SASL-Authentifizierung fehlgeschlagen.",
                "nick_taken": "Nickname {old_nick} ist belegt, verwende {new_nick}",
                "channel_not_joinable": "Channel nicht joinbar, entferne aus Liste: {channel}",
                "db_setup_skip": "Hinweis: Konnte MySQL-Server nicht erreichen, DB-Setup wird übersprungen.",
                "db_create_failed": "Hinweis: DB-Erstellung fehlgeschlagen: {error}",
                "db_connect_failed": "Hinweis: Konnte keine Verbindung zur Bot-Datenbank herstellen.",
                "db_table_setup_failed": "Hinweis: Tabellen-Setup fehlgeschlagen: {error}",
                "admin_bootstrap_missing": "Kein Admin für Netzwerk {network} konfiguriert. Starte den Bot einmal im Vordergrund und lege einen Admin an.",
                "admin_bootstrap_prompt": "Erststart für {network}: initialen Admin anlegen.",
                "admin_bootstrap_created": "Initialer Admin {mask} wurde für Netzwerk {network} angelegt.",
                "admin_bootstrap_skipped": "Admin-Bootstrap übersprungen. Ohne Admin sind keine Verwaltungsbefehle verfügbar.",
                "config_missing": "config.json fehlt. Kopiere config.example.json zu config.json und passe die Werte an.",
                "connecting": "Verbinde zu {server}:{port} (TLS={tls}) ...",
                "connection_closed": "Verbindung beendet.",
                "network_error": "Netzwerkfehler: {error}",
                "shutting_down": "Beende Bot.",
                "reconnect_in": "Reconnect in {seconds} Sekunden ...",
            },
            "en": {
                "not_connected": "Not connected",
                "sasl_failed": "SASL authentication failed.",
                "nick_taken": "Nickname {old_nick} is taken, using {new_nick}",
                "channel_not_joinable": "Channel not joinable, removing from list: {channel}",
                "db_setup_skip": "Notice: Could not reach MySQL server, skipping DB setup.",
                "db_create_failed": "Notice: DB creation failed: {error}",
                "db_connect_failed": "Notice: Could not connect to bot database.",
                "db_table_setup_failed": "Notice: Table setup failed: {error}",
                "admin_bootstrap_missing": "No admin is configured for network {network}. Start the bot once in the foreground and create an admin.",
                "admin_bootstrap_prompt": "First run for {network}: create the initial admin.",
                "admin_bootstrap_created": "Initial admin {mask} was created for network {network}.",
                "admin_bootstrap_skipped": "Admin bootstrap skipped. No administrative commands will be available until an admin is created.",
                "config_missing": "config.json is missing. Copy config.example.json to config.json and adjust values.",
                "connecting": "Connecting to {server}:{port} (TLS={tls}) ...",
                "connection_closed": "Connection closed.",
                "network_error": "Network error: {error}",
                "shutting_down": "Stopping bot.",
                "reconnect_in": "Reconnect in {seconds} seconds ...",
            },
        }
        plugin_manager = getattr(self, "plugin_manager", None)
        plugin_template = None if plugin_manager is None else plugin_manager.translation(key, language)
        if plugin_template is None and language != "de" and plugin_manager is not None:
            plugin_template = plugin_manager.translation(key, "de")

        template = plugin_template
        if template is None:
            template = core_messages.get(language, core_messages["de"]).get(
                key,
                core_messages["de"].get(key, key),
            )
        return template.format(**kwargs)

    def connect(self) -> None:
        source_address = (self.config.bind_ip, 0) if self.config.bind_ip else None
        base_sock = socket.create_connection((self.config.server, self.config.port), timeout=20, source_address=source_address)
        base_sock.settimeout(None)

        if self.config.use_tls:
            ctx = ssl.create_default_context()
            self.sock = ctx.wrap_socket(base_sock, server_hostname=self.config.server)
        else:
            self.sock = base_sock

        self.file = self.sock.makefile("r", encoding="utf-8", errors="replace", newline="\r\n")

        if self.should_use_sasl():
            self.cap_negotiation_active = True
            self.send_raw("CAP LS 302")

        if self.config.password:
            self.send_raw(f"PASS {self.config.password}")

        self.send_raw(f"NICK {self.current_nick}")
        self.send_raw(f"USER {self.config.username} 0 * :{self.config.realname}")
        self.last_nick_reclaim_attempt_at = 0.0
        self.nickserv_identify_sent = False

    def close(self) -> None:
        self._runtime_stop_event.set()
        if self._plugin_tick_thread is not None and self._plugin_tick_thread.is_alive():
            self._plugin_tick_thread.join(timeout=2)
        self._plugin_tick_thread = None

        if self._url_executor is not None:
            self._url_executor.shutdown(wait=False, cancel_futures=True)
            self._url_executor = None

        try:
            if self.file:
                self.file.close()
        finally:
            self.file = None

        try:
            if self.sock:
                self.sock.close()
        finally:
            self.sock = None

    def start_plugin_tick_loop(self) -> None:
        if self._plugin_tick_thread is not None and self._plugin_tick_thread.is_alive():
            return

        self._runtime_stop_event.clear()
        self._plugin_tick_thread = threading.Thread(
            target=self.run_plugin_tick_loop,
            name=f"plugin-tick-{self.config.display_name()}",
            daemon=True,
        )
        self._plugin_tick_thread.start()

    def run_plugin_tick_loop(self) -> None:
        while not self._runtime_stop_event.wait(5.0):
            try:
                self.plugin_manager.handle_tick()
            except Exception as exc:
                print(f"[{self.config.display_name()}] Plugin-Tick-Fehler: {exc}")

    def setup_oidentd_conf(self) -> None:
        if not self.config.oidentd_conf:
            return

        try:
            oidentd_path = Path(self.config.oidentd_conf).expanduser().resolve()
            oidentd_path.parent.mkdir(parents=True, exist_ok=True)

            content = f"""global {{
    reply "{self.config.username}"
}}
"""
            oidentd_path.write_text(content, encoding="utf-8")
            print(f"oidentd.conf created: {oidentd_path}")
        except Exception as exc:
            print(f"Failed to create oidentd.conf: {exc}")

    def send_raw(self, line: str) -> None:
        with self._send_lock:
            if not self.sock:
                raise RuntimeError(self.tr("not_connected"))
            payload = (line + "\r\n").encode("utf-8")
            self.sock.sendall(payload)
            print(f">>> {line}")
            self.log_chat_raw_line(line)

    @staticmethod
    def sanitize_network_key_for_filename(network_key: str) -> str:
        sanitized = re.sub(r'[^A-Za-z0-9._-]+', "_", network_key.strip())
        return sanitized or "network"

    def chat_log_path(self) -> Path:
        filename = f"chat-{self.sanitize_network_key_for_filename(self.config.network_key)}.log"
        return Path("log") / filename

    def log_chat_raw_line(self, line: str) -> None:
        if not self.config.raw_chat_logging_enabled:
            return

        try:
            timestamp_ms = int(time.time() * 1000)
            log_path = self.chat_log_path()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.open("a", encoding="utf-8").write(f"{timestamp_ms} {line}\n")
        except OSError:
            pass

    def send_privmsg(self, target: str, message: str) -> None:
        with self._send_lock:
            self.apply_flood_protection()
            self.send_raw(f"PRIVMSG {target} :{message}")

    def send_notice(self, target: str, message: str) -> None:
        with self._send_lock:
            self.apply_flood_protection()
            self.send_raw(f"NOTICE {target} :{message}")

    def send_action(self, target: str, message: str) -> None:
        with self._send_lock:
            self.apply_flood_protection()
            self.send_raw(f"PRIVMSG {target} :\x01ACTION {message}\x01")

    def schedule_url_sniff(self, message: str, channel: str, source_nick: str) -> None:
        if not URL_PATTERN.search(message):
            return
        if self._url_executor is None:
            return
        self._url_executor.submit(self._safe_sniff_urls_in_message, message, channel, source_nick)

    def _safe_sniff_urls_in_message(self, message: str, channel: str, source_nick: str) -> None:
        try:
            self.sniff_urls_in_message(message, channel, source_nick)
        except Exception as exc:
            print(f"URL sniff worker failed: {exc}")

    def apply_flood_protection(self) -> None:
        now = time.monotonic()

        # Ensure a minimum delay between chat messages.
        # This runs inside the shared send lock, so threaded senders are serialized too.
        min_interval = self.config.flood_min_interval_ms / 1000.0
        if min_interval > 0:
            elapsed = now - self._last_chat_send_at
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
                now = time.monotonic()

        # Enforce a burst/window rate limit.
        window = self.config.flood_window_seconds
        while self._flood_timestamps and (now - self._flood_timestamps[0]) > window:
            self._flood_timestamps.popleft()

        if len(self._flood_timestamps) >= self.config.flood_burst:
            sleep_for = window - (now - self._flood_timestamps[0])
            if sleep_for > 0:
                time.sleep(sleep_for)
                now = time.monotonic()
            while self._flood_timestamps and (now - self._flood_timestamps[0]) > window:
                self._flood_timestamps.popleft()

        self._flood_timestamps.append(now)
        self._last_chat_send_at = now

    def join_channels(self, channels: Iterable[str]) -> None:
        for ch in channels:
            if ch:
                self.send_raw(f"JOIN {ch}")

    def request_channel_modes(self, channel: str) -> None:
        normalized_channel = channel.strip()
        if normalized_channel:
            self.send_raw(f"MODE {normalized_channel}")

    def request_channel_members(self, channel: str) -> None:
        normalized_channel = channel.strip()
        if normalized_channel:
            self.channel_members[self.normalize_channel_name(normalized_channel)] = {}
            self.send_raw(f"NAMES {normalized_channel}")

    @staticmethod
    def parse_prefix_token(value: str) -> dict[str, str] | None:
        token = value[7:] if value.upper().startswith("PREFIX=") else value
        if not token.startswith("(") or ")" not in token:
            return None

        modes_part, prefixes_part = token[1:].split(")", 1)
        if not modes_part or not prefixes_part or len(modes_part) != len(prefixes_part):
            return None

        return dict(zip(modes_part, prefixes_part))

    def handle_isupport_message(self, params: list[str]) -> None:
        if len(params) < 2:
            return

        for token in params[1:]:
            if token.startswith(":"):
                break
            parsed = self.parse_prefix_token(token)
            if parsed is not None:
                self.server_prefix_modes = parsed
                break

    @staticmethod
    def split_hostmask(prefix: str) -> tuple[str, str, str]:
        nick = prefix
        ident = ""
        host = ""

        if "!" in prefix:
            nick, remainder = prefix.split("!", 1)
            if "@" in remainder:
                ident, host = remainder.split("@", 1)
            else:
                ident = remainder
        elif "@" in prefix:
            ident, host = prefix.split("@", 1)

        return nick, ident, host

    @staticmethod
    def normalize_user_mask(mask: str) -> str | None:
        raw = mask.strip()
        if raw.count("@") != 1:
            return None

        ident, host = raw.split("@", 1)
        ident = ident.strip().lower()
        host = host.strip().lower()
        if not ident or not host:
            return None
        return f"{ident}@{host}"

    @staticmethod
    def normalize_role_name(role_name: str) -> str | None:
        role = role_name.strip().lower()
        if not role or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", role):
            return None
        return role

    @staticmethod
    def normalize_channel_name(channel: str) -> str:
        return channel.strip().lower()

    def strip_channel_member_prefixes(self, nick: str) -> str:
        cleaned = nick.strip()
        prefixes = set(self.server_prefix_modes.values())
        while cleaned and cleaned[0] in prefixes:
            cleaned = cleaned[1:]
        return cleaned

    def add_channel_member(self, channel: str, nick: str) -> None:
        normalized_channel = self.normalize_channel_name(channel)
        cleaned_nick = self.strip_channel_member_prefixes(nick)
        if not normalized_channel or not cleaned_nick:
            return
        self.clear_member_mode_retry(normalized_channel, cleaned_nick)
        members = self.channel_members.setdefault(normalized_channel, {})
        members[cleaned_nick.lower()] = cleaned_nick

    def add_channel_members(self, channel: str, nicks: Iterable[str]) -> None:
        for nick in nicks:
            self.add_channel_member(channel, nick)

    def remove_channel_member(self, channel: str, nick: str) -> None:
        normalized_channel = self.normalize_channel_name(channel)
        cleaned_nick = self.strip_channel_member_prefixes(nick)
        if not normalized_channel or not cleaned_nick:
            return
        self.clear_member_mode_retry(normalized_channel, cleaned_nick)
        members = self.channel_members.get(normalized_channel)
        if members is not None:
            members.pop(cleaned_nick.lower(), None)

    def rename_channel_member(self, old_nick: str, new_nick: str) -> None:
        cleaned_old_nick = self.strip_channel_member_prefixes(old_nick)
        cleaned_new_nick = self.strip_channel_member_prefixes(new_nick)
        if not cleaned_old_nick or not cleaned_new_nick:
            return
        for channel in tuple(self.channel_members):
            self.clear_member_mode_retry(channel, cleaned_old_nick)
        lowered_old_nick = cleaned_old_nick.lower()
        lowered_new_nick = cleaned_new_nick.lower()
        for members in self.channel_members.values():
            if lowered_old_nick in members:
                members.pop(lowered_old_nick, None)
                members[lowered_new_nick] = cleaned_new_nick

    def remove_channel_member_from_all(self, nick: str) -> None:
        cleaned_nick = self.strip_channel_member_prefixes(nick)
        if not cleaned_nick:
            return
        for channel in tuple(self.channel_members):
            self.clear_member_mode_retry(channel, cleaned_nick)
        lowered_nick = cleaned_nick.lower()
        for members in self.channel_members.values():
            members.pop(lowered_nick, None)

    def get_channel_member_nicks(self, channel: str) -> tuple[str, ...]:
        normalized_channel = self.normalize_channel_name(channel)
        members = self.channel_members.get(normalized_channel, {})
        return tuple(members.values())

    def is_nick_in_channel(self, channel: str, nick: str) -> bool:
        normalized_channel = self.normalize_channel_name(channel)
        cleaned_nick = self.strip_channel_member_prefixes(nick)
        if not normalized_channel or not cleaned_nick:
            return False
        members = self.channel_members.get(normalized_channel, {})
        return cleaned_nick.lower() in members

    def user_mask_from_parts(self, ident: str, host: str) -> str | None:
        if not ident or not host:
            return None
        return self.normalize_user_mask(f"{ident}@{host}")

    def normalize_member_mode(self, mode_or_prefix: str) -> str | None:
        token = mode_or_prefix.strip()
        if len(token) == 2 and token[0] in {"+", "-"}:
            token = token[1:]
        if len(token) != 1:
            return None

        if token in self.server_prefix_modes:
            return token

        for mode, prefix in self.server_prefix_modes.items():
            if prefix == token:
                return mode

        return None

    @staticmethod
    def parse_mode_snapshot(modes: str) -> set[str]:
        active: set[str] = set()
        for char in modes:
            if char in {"+", "-"}:
                continue
            active.add(char)
        return active

    def apply_mode_delta(self, channel: str, mode_changes: str) -> None:
        active = set(self.channel_modes.get(channel, set()))
        sign = "+"
        for char in mode_changes:
            if char in {"+", "-"}:
                sign = char
                continue
            if sign == "+":
                active.add(char)
            else:
                active.discard(char)
        self.channel_modes[channel] = active

    def apply_member_mode(self, channel: str, nick: str, mode: str) -> None:
        if not channel or not nick or not mode:
            return
        self.send_raw(f"MODE {channel} +{mode} {nick}")

    def remove_member_mode(self, channel: str, nick: str, mode: str) -> None:
        if not channel or not nick or not mode:
            return
        self.clear_member_mode_retry(channel, nick, mode)
        self.send_raw(f"MODE {channel} -{mode} {nick}")

    def clear_member_mode_retry(self, channel: str, nick: str, mode: str = "") -> None:
        normalized_channel = self.normalize_channel_name(channel)
        cleaned_nick = self.strip_channel_member_prefixes(nick).lower()
        if not normalized_channel or not cleaned_nick:
            return
        for key in tuple(self._member_mode_retry_at):
            cached_channel, cached_nick, cached_mode = key
            if cached_channel != normalized_channel or cached_nick != cleaned_nick:
                continue
            if mode and cached_mode != mode:
                continue
            self._member_mode_retry_at.pop(key, None)

    def should_retry_member_mode(self, channel: str, nick: str, mode: str, cooldown_seconds: float) -> bool:
        normalized_channel = self.normalize_channel_name(channel)
        cleaned_nick = self.strip_channel_member_prefixes(nick).lower()
        if not normalized_channel or not cleaned_nick or not mode:
            return False
        key = (normalized_channel, cleaned_nick, mode)
        now = time.monotonic()
        retry_at = self._member_mode_retry_at.get(key, 0.0)
        if retry_at > now:
            return False
        self._member_mode_retry_at[key] = now + max(1.0, cooldown_seconds)
        return True

    def remember_channel(self, channel: str) -> None:
        normalized_channel = channel.strip()
        if normalized_channel and normalized_channel not in self.config.channels:
            self.config.channels.append(normalized_channel)
        if normalized_channel:
            self.channel_members.setdefault(self.normalize_channel_name(normalized_channel), {})
            self.store_channel_if_missing(normalized_channel)

    def forget_channel(self, channel: str) -> None:
        normalized_channel = channel.strip()
        if not normalized_channel:
            return

        self.config.channels = [ch for ch in self.config.channels if ch.lower() != normalized_channel.lower()]
        self.channel_modes.pop(normalized_channel, None)
        self.channel_members.pop(self.normalize_channel_name(normalized_channel), None)
        for key in tuple(self._member_mode_retry_at):
            if key[0] == self.normalize_channel_name(normalized_channel):
                self._member_mode_retry_at.pop(key, None)
        self.delete_saved_channel(normalized_channel)

    def merge_saved_channels(self) -> None:
        for channel in self.load_saved_channels():
            if channel and channel not in self.config.channels:
                self.config.channels.append(channel)

    def should_use_sasl(self) -> bool:
        return bool(
            self.config.sasl_enabled
            and self.config.sasl_username.strip()
            and self.config.sasl_password
        )

    def run_perform_commands(self) -> None:
        commands = self.config.perform or []
        for raw_command in commands:
            command = str(raw_command).strip()
            if not command:
                continue

            resolved = command.replace("{nick}", self.current_nick)
            self.send_raw(resolved)

    def should_use_nickserv_identify(self) -> bool:
        return bool(self.config.nickserv_password and self.config.nickserv_identify_command.strip())

    def send_nickserv_identify(self) -> None:
        if self.nickserv_identify_sent or not self.should_use_nickserv_identify():
            return

        command = self.config.nickserv_identify_command.format(
            password=self.config.nickserv_password,
            nick=self.current_nick,
            preferred_nick=self.preferred_nick,
        ).strip()
        if not command:
            return

        self.send_raw(command)
        self.nickserv_identify_sent = True

    def complete_startup_actions(self) -> None:
        if self.startup_actions_completed:
            return

        self.run_perform_commands()
        self.join_channels(self.config.channels)
        for channel in self.config.channels:
            self.request_channel_modes(channel)
        self.public_trigger_activation_at = time.monotonic() + 60.0
        self.startup_actions_completed = True

    def public_triggers_enabled(self) -> bool:
        return time.monotonic() >= self.public_trigger_activation_at

    def try_reclaim_preferred_nick(self, force: bool = False) -> None:
        if not self.config.nick_protection_enabled:
            return

        if self.current_nick.lower() == self.preferred_nick.lower():
            return

        now = time.monotonic()
        if not force:
            elapsed = now - self.last_nick_reclaim_attempt_at
            if elapsed < self.config.nick_reclaim_interval_seconds:
                return

        self.send_raw(f"NICK {self.preferred_nick}")
        self.last_nick_reclaim_attempt_at = now

    def command_aliases(self) -> dict[str, list[str]]:
        return self.plugin_manager.command_aliases()

    def primary_command_name(self, canonical: str) -> str:
        return self.plugin_manager.primary_command_name(canonical, self.config.language)

    def resolve_command(self, token: str) -> str | None:
        command = self.plugin_manager.resolve_command(token)
        return command.canonical if command is not None else None

    def build_help_entries(self, prefix: str, context=None) -> tuple[str, ...]:
        return self.plugin_manager.build_help_entries(prefix, self.config.language, context)

    def send_lag_probe(self, reply_target: str) -> None:
        token = f"lag-{int(time.time() * 1000)}-{random.randint(1000, 9999)}"
        self.pending_lag_checks[token] = (time.monotonic_ns(), reply_target)
        self.send_raw(f"PING :{token}")

    def handle_pong_message(self, params: list[str]) -> None:
        if not params or not self.pending_lag_checks:
            return

        candidates = [part.lstrip(":") for part in params if part]
        for token in candidates:
            lag_entry = self.pending_lag_checks.pop(token, None)
            if lag_entry is None:
                continue

            started_at_ns, reply_target = lag_entry
            lag_ns = max(0, time.monotonic_ns() - started_at_ns)
            self.send_privmsg(
                reply_target,
                self.tr("lag_now", ms=self.format_lag_ms(lag_ns), ns=self.format_lag_ns(lag_ns)),
            )
            return

    def format_points(self, value: int) -> str:
        formatted = f"{value:,}"
        return formatted.replace(",", ".") if self.config.language == "de" else formatted

    def format_average(self, value: float) -> str:
        text = f"{value:.2f}"
        return text.replace(".", ",") if self.config.language == "de" else text

    def format_lag_ms(self, lag_ns: int) -> str:
        lag_ms = lag_ns / 1_000_000.0
        # If latency is below 1 ms, show 3 decimals (e.g. 0.123 ms).
        text = f"{lag_ms:.3f}" if lag_ns < 1_000_000 else f"{lag_ms:.2f}"
        return text.replace(".", ",") if self.config.language == "de" else text

    def format_lag_ns(self, lag_ns: int) -> str:
        text = f"{lag_ns:,}"
        return text.replace(",", ".") if self.config.language == "de" else text

    def format_localized_number(self, value: object) -> str:
        if value is None:
            return "n/a"

        if isinstance(value, bool):
            return str(value)

        if isinstance(value, int):
            text = str(value)
        elif isinstance(value, float):
            text = str(int(value)) if value.is_integer() else f"{value:.1f}"
        else:
            text = str(value)

        return text.replace(".", ",") if self.config.language == "de" else text

    def end_cap_negotiation(self) -> None:
        if self.cap_negotiation_active:
            self.send_raw("CAP END")
            self.cap_negotiation_active = False

    def handle_cap_message(self, params: list[str]) -> None:
        if len(params) < 2:
            return

        subcommand = params[1].upper()
        caps_text = params[2].lstrip(":") if len(params) >= 3 else ""
        cap_tokens = {token.split("=", 1)[0].lower() for token in caps_text.split()}

        if subcommand == "LS":
            if self.should_use_sasl() and "sasl" in cap_tokens:
                self.send_raw("CAP REQ :sasl")
                return
            self.end_cap_negotiation()
            return

        if subcommand == "ACK":
            if self.should_use_sasl() and "sasl" in cap_tokens:
                self.send_raw("AUTHENTICATE PLAIN")
                return
            self.end_cap_negotiation()
            return

        if subcommand in {"NAK", "DEL"}:
            self.end_cap_negotiation()

    def send_sasl_plain_payload(self) -> None:
        if self.sasl_payload_sent:
            return

        authzid = self.config.sasl_authzid
        authcid = self.config.sasl_username
        password = self.config.sasl_password
        raw_payload = f"{authzid}\x00{authcid}\x00{password}".encode("utf-8")
        encoded = base64.b64encode(raw_payload).decode("ascii")

        for start in range(0, len(encoded), 400):
            self.send_raw(f"AUTHENTICATE {encoded[start:start + 400]}")
        if len(encoded) % 400 == 0:
            self.send_raw("AUTHENTICATE +")

        self.sasl_payload_sent = True

    def handle_authenticate_message(self, params: list[str]) -> None:
        if not self.should_use_sasl() or self.sasl_payload_sent:
            return
        if not params:
            return
        if params[0] == "+":
            self.send_sasl_plain_payload()

    def handle_sasl_result(self, command: str) -> None:
        if command in {"900", "903"}:
            self.end_cap_negotiation()
            return
        if command in {"902", "904", "905", "906", "907", "908"}:
            print(self.tr("sasl_failed"))
            self.end_cap_negotiation()

    def run(self) -> None:
        assert self.file is not None

        self.ensure_database_setup()
        self.merge_saved_channels()
        self._mondgesicht_channels = self.load_saved_mondgesicht_channels()
        self.start_plugin_tick_loop()

        for line in self.file:
            line = line.rstrip("\r\n")
            if not line:
                continue

            print(f"<<< {line}")
            self.log_chat_raw_line(line)

            if line.startswith("PING "):
                self.send_raw("PONG " + line[5:])
                continue

            prefix, command, params = self.parse_irc_line(line)

            self.try_reclaim_preferred_nick()

            if command == "CAP":
                self.handle_cap_message(params)
                continue

            if command == "005":
                self.handle_isupport_message(params)
                continue

            if command == "PONG":
                self.handle_pong_message(params)
                continue

            if command == "AUTHENTICATE":
                self.handle_authenticate_message(params)
                continue

            if command in {"900", "902", "903", "904", "905", "906", "907", "908"}:
                self.handle_sasl_result(command)
                continue

            if command == "001":
                self.send_nickserv_identify()
                self.try_reclaim_preferred_nick(force=True)
                self.complete_startup_actions()
                continue

            if command in {"376", "422"}:
                self.complete_startup_actions()
                continue

            if command == "NICK" and len(params) >= 1:
                changed_nick = prefix.split("!", 1)[0] if prefix else ""
                new_nick = params[0].lstrip(":")
                if changed_nick.lower() == self.current_nick.lower() and new_nick:
                    self.current_nick = new_nick
                    if new_nick.lower() == self.preferred_nick.lower():
                        self.last_nick_reclaim_attempt_at = 0.0
                self.rename_channel_member(changed_nick, new_nick)
                self.update_admin_session_nick(changed_nick, new_nick)
                continue

            if command == "JOIN" and len(params) >= 1:
                joined_channel = params[0].lstrip(":")
                joined_nick, joined_ident, joined_host = self.split_hostmask(prefix)
                self.add_channel_member(joined_channel, joined_nick)
                if joined_nick.lower() == self.current_nick.lower() and joined_channel:
                    self.remember_channel(joined_channel)
                    self.request_channel_modes(joined_channel)
                    self.request_channel_members(joined_channel)
                elif joined_channel:
                    self.apply_configured_channel_modes(joined_channel, joined_nick, joined_ident, joined_host)
                continue

            if command == "PART" and len(params) >= 1:
                parted_channel = params[0].lstrip(":")
                parted_nick = prefix.split("!", 1)[0] if prefix else ""
                self.remove_channel_member(parted_channel, parted_nick)
                if parted_nick.lower() == self.current_nick.lower() and parted_channel:
                    self.forget_channel(parted_channel)
                continue

            if command == "KICK" and len(params) >= 2:
                kicked_channel = params[0].lstrip(":")
                kicked_nick = params[1]
                self.remove_channel_member(kicked_channel, kicked_nick)
                if kicked_nick.lower() == self.current_nick.lower() and kicked_channel:
                    self.forget_channel(kicked_channel)
                continue

            if command == "QUIT":
                quit_nick = prefix.split("!", 1)[0] if prefix else ""
                self.remove_channel_member_from_all(quit_nick)
                continue

            if command == "433":
                old_nick = self.current_nick
                if self.current_nick.lower() != self.fallback_nick.lower():
                    self.current_nick = self.fallback_nick
                    print(self.tr("nick_taken", old_nick=old_nick, new_nick=self.current_nick))
                    self.send_raw(f"NICK {self.current_nick}")
                else:
                    print(self.tr("nick_taken", old_nick=old_nick, new_nick=self.current_nick))
                continue

            if command in {"403", "405", "471", "473", "474", "475", "476", "477", "489"} and len(params) >= 2:
                failed_channel = params[1].lstrip(":")
                if failed_channel.startswith("#"):
                    print(self.tr("channel_not_joinable", channel=failed_channel))
                    self.forget_channel(failed_channel)
                continue

            if command == "INVITE" and len(params) >= 2:
                invited_nick = params[0]
                invited_channel = params[1]
                inviter_nick = prefix.split("!", 1)[0] if prefix else ""

                if invited_nick.lower() == self.current_nick.lower():
                    self.remember_channel(invited_channel)
                    self.send_raw(f"JOIN {invited_channel}")
                    self.request_channel_modes(invited_channel)
                    self.request_channel_members(invited_channel)
                    if inviter_nick:
                        self.send_action(
                            invited_channel,
                            f"slaps {inviter_nick} around a bit with a large {self.current_nick}",
                        )
                continue

            if command == "353" and len(params) >= 4:
                names_channel = params[2]
                self.add_channel_members(names_channel, params[3].lstrip(":").split())
                continue

            if command == "324" and len(params) >= 3:
                channel = params[1]
                modes = params[2]
                self.channel_modes[channel] = self.parse_mode_snapshot(modes)
                continue

            if command == "MODE" and len(params) >= 2:
                channel = params[0]
                modes = params[1]
                self.apply_mode_delta(channel, modes)
                continue

            if command == "PRIVMSG" and len(params) >= 2:
                target = params[0]
                message = params[1]
                source_nick, source_ident, source_host = self.split_hostmask(prefix)
                self.handle_privmsg(source_nick, source_ident, source_host, target, message)

    def handle_privmsg(self, source_nick: str, source_ident: str, source_host: str, target: str, message: str) -> None:
        prefix = self.config.command_prefix
        is_private_message = target.lower() == self.current_nick.lower()
        reply_target = source_nick if is_private_message else target
        source_mask = self.user_mask_from_parts(source_ident, source_host) or ""
        if not is_private_message and source_ident and source_host:
            for mode in self.get_user_channel_modes(source_mask, target):
                if self.should_retry_member_mode(target, source_nick, mode, 60.0):
                    self.apply_member_mode(target, source_nick, mode)
        context = MessageContext(
            source_nick=source_nick,
            source_ident=source_ident,
            source_host=source_host,
            source_mask=source_mask,
            target=target,
            message=message,
            reply_target=reply_target,
            command_prefix=prefix,
            is_private_message=is_private_message,
        )
        self.plugin_manager.handle_privmsg(context)

    def build_url_usage_text(self, prefix: str) -> str:
        max_id = self.get_max_url_id()
        if max_id is None:
            return self.tr("usage_url", prefix=prefix, command=self.primary_command_name("url"))
        return self.tr("usage_url_with_max", prefix=prefix, command=self.primary_command_name("url"), max_id=max_id)

    def format_target_nick(self, target_nick: str) -> str:
        if target_nick.lower() == self.current_nick.lower():
            return self.tr("self_target")
        return target_nick

    def get_weather_text(self, location_query: str, command_prefix: str, reply_target: str) -> str:
        from plugins.weather.plugin import WEATHER_CODE_MAPS

        location = location_query.strip() or self.config.weather_default_location.strip()
        if not location:
            return self.tr("usage_weather", prefix=command_prefix, command=self.primary_command_name("weather"))

        place = self.resolve_weather_location(location)
        if not place:
            return self.tr("weather_not_found", location=location)

        latitude = place.get("latitude")
        longitude = place.get("longitude")
        if latitude is None or longitude is None:
            return self.tr("weather_not_found", location=location)

        forecast_url = (
            "https://api.open-meteo.com/v1/forecast?"
            f"latitude={latitude}&longitude={longitude}"
            "&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,precipitation,wind_speed_10m,wind_direction_10m,is_day"
            "&timezone=auto"
        )

        weather_data = self.fetch_json(forecast_url)
        if not weather_data:
            return self.tr("weather_unreachable", location=location)

        current = weather_data.get("current") or {}
        temperature = current.get("temperature_2m")
        feels_like = current.get("apparent_temperature")
        humidity = current.get("relative_humidity_2m")
        weather_code = current.get("weather_code")
        precipitation = current.get("precipitation")
        wind_speed = current.get("wind_speed_10m")
        wind_direction = current.get("wind_direction_10m")
        weather_map = WEATHER_CODE_MAPS.get(self.config.language, WEATHER_CODE_MAPS["de"])
        condition = weather_map.get(int(weather_code), f"Code {weather_code}") if weather_code is not None else self.tr("unknown")
        temperature_text = self.format_localized_number(temperature)
        feels_like_text = self.format_localized_number(feels_like)
        humidity_text = self.format_localized_number(humidity)
        precipitation_text = self.format_localized_number(precipitation)
        wind_speed_text = self.format_localized_number(wind_speed)

        place_name = place.get("name", location)
        admin1 = place.get("admin1")
        country = place.get("country")
        place_parts = [str(part) for part in (place_name, admin1, country) if part]
        display_place = ", ".join(place_parts)

        if self.allows_control_codes(reply_target):
            return self.format_weather_with_control_codes(
                display_place,
                temperature,
                feels_like,
                humidity,
                condition,
                precipitation,
                wind_speed,
                wind_direction,
            )

        if temperature is None or wind_speed is None:
            return self.tr("weather_short", location=display_place, condition=condition)

        return self.tr(
            "weather_for",
            location=display_place,
            temperature=temperature_text,
            condition=condition,
            feels_like=feels_like_text,
            humidity=humidity_text,
            precipitation=precipitation_text,
            wind_speed=wind_speed_text,
        )

    def resolve_weather_location(self, location: str) -> dict[str, object] | None:
        postal_code = self.extract_postal_code(location)
        if postal_code:
            postal_location = self.geocode_postal_code(postal_code, location)
            if postal_location:
                return postal_location

        return self.geocode_location_name(location)

    def geocode_postal_code(self, postal_code: str, location: str) -> dict[str, object] | None:
        zippopotam_url = f"https://api.zippopotam.us/de/{quote(postal_code)}"
        zip_data = self.fetch_json(zippopotam_url)
        if isinstance(zip_data, dict):
            places = zip_data.get("places") or []
            if places:
                place = places[0]
                place_name = str(place.get("place name", ""))
                state = str(place.get("state", ""))
                latitude = self.safe_float(place.get("latitude"))
                longitude = self.safe_float(place.get("longitude"))
                if latitude is not None and longitude is not None:
                    return {
                        "name": place_name or postal_code,
                        "admin1": state,
                        "country": str(zip_data.get("country", "Germany" if self.config.language == "en" else "Deutschland")),
                        "latitude": latitude,
                        "longitude": longitude,
                    }

        geocode_url = (
            "https://nominatim.openstreetmap.org/search?"
            f"postalcode={quote(postal_code)}&countrycodes=de&format=jsonv2&limit=5&addressdetails=1"
            f"&accept-language={quote(self.config.language)}"
        )
        geocode_data = self.fetch_json(geocode_url)
        if not geocode_data:
            return None

        results = geocode_data if isinstance(geocode_data, list) else []
        if not results:
            return None

        suffix = location.replace(postal_code, "", 1).strip()
        if suffix:
            for result in results:
                display_name = str(result.get("display_name", ""))
                if suffix.lower() in display_name.lower():
                    return self.normalize_nominatim_location(result)

        return self.normalize_nominatim_location(results[0])

    @staticmethod
    def safe_float(value: object) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def geocode_location_name(self, location: str) -> dict[str, object] | None:
        geocode_url = (
            "https://geocoding-api.open-meteo.com/v1/search?name="
            f"{quote(location)}&count=5&language={quote(self.config.language)}&format=json"
        )

        geocode_data = self.fetch_json(geocode_url)
        if not geocode_data:
            return None

        results = geocode_data.get("results") or []
        if not results:
            return None

        return results[0]

    def normalize_nominatim_location(self, result: dict[str, object]) -> dict[str, object] | None:
        address = result.get("address")
        address_dict = address if isinstance(address, dict) else {}
        latitude = self.safe_float(result.get("lat"))
        longitude = self.safe_float(result.get("lon"))
        if latitude is None or longitude is None:
            return None

        name_candidates = (
            address_dict.get("city"),
            address_dict.get("town"),
            address_dict.get("village"),
            address_dict.get("municipality"),
            address_dict.get("hamlet"),
            result.get("name"),
            str(result.get("display_name", "")).split(",", 1)[0],
            result.get("display_name"),
        )
        place_name = next((str(candidate).strip() for candidate in name_candidates if candidate), "")

        return {
            "name": place_name,
            "admin1": str(address_dict.get("state", "")).strip(),
            "country": str(address_dict.get("country", "")).strip(),
            "latitude": latitude,
            "longitude": longitude,
        }

    def extract_postal_code(self, location: str) -> str | None:
        match = re.search(r"\b(\d{5})\b", location)
        return match.group(1) if match else None

    def allows_control_codes(self, reply_target: str) -> bool:
        if not reply_target.startswith("#"):
            return False

        modes = self.channel_modes.get(reply_target, set())
        return "c" not in modes

    def format_weather_with_control_codes(
        self,
        display_place: str,
        temperature: object,
        feels_like: object,
        humidity: object,
        condition: str,
        precipitation: object,
        wind_speed: object,
        wind_direction: object,
    ) -> str:
        bold = "\x02"
        reset = "\x0f"
        temp_value = self.format_localized_number(temperature)
        feel_value = self.format_localized_number(feels_like)
        humidity_value = self.format_localized_number(humidity)
        precipitation_value = self.format_localized_number(precipitation)
        wind_value = self.format_localized_number(wind_speed)
        direction_value = self.format_localized_number(wind_direction)
        temp_text = f"\x0303{temp_value}°C{reset}" if temperature is not None else "n/a"
        feel_text = f"{feel_value}°C" if feels_like is not None else "n/a"
        humidity_text = f"{humidity_value}%" if humidity is not None else "n/a"
        precipitation_text = f"{precipitation_value} mm" if precipitation is not None else "n/a"
        wind_text = f"{wind_value} km/h" if wind_speed is not None else "n/a"
        direction_text = f"{direction_value}°" if wind_direction is not None else "n/a"

        return (
            f"{bold}{self.tr('weather_cc', location=display_place)}{reset}: {temp_text}, {condition}, "
            f"{('gefühlt' if self.config.language == 'de' else 'feels like')} {feel_text}, "
            f"{self.tr('humidity')} {humidity_text}, {self.tr('precipitation')} {precipitation_text}, "
            f"{self.tr('wind')} {wind_text} ({direction_text})"
        )

    def fetch_json(self, url: str) -> dict[str, object] | None:
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0 IRCBot"})
            with urlopen(request, timeout=10) as response:
                payload = response.read()
            decoded = payload.decode("utf-8", errors="replace")
            parsed = json.loads(decoded)
            return parsed
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _is_timeout_error(exc: Exception) -> bool:
        if isinstance(exc, TimeoutError):
            return True
        if isinstance(exc, URLError):
            reason = str(getattr(exc, "reason", "")).lower()
            return "timed out" in reason or "timeout" in reason
        return "timed out" in str(exc).lower()

    def describe_url(self, url: str) -> dict[str, str | int | bool | None]:
        if self.is_youtube_url(url):
            youtube_result = self.fetch_youtube_metadata(url)
            if youtube_result:
                return youtube_result

            return {"status": "error", "message": self.tr("yt_api_no_metadata")}

        return self.fetch_url_topic(url)

    def is_youtube_url(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        return host in {
            "youtu.be",
            "www.youtu.be",
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
            "youtube-nocookie.com",
            "www.youtube-nocookie.com",
        }

    def extract_youtube_video_id(self, url: str) -> str | None:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path.strip("/")

        if host in {"youtu.be", "www.youtu.be"}:
            return path.split("/", 1)[0] or None

        query = {}
        if parsed.query:
            for part in parsed.query.split("&"):
                if "=" in part:
                    key, value = part.split("=", 1)
                    query[key] = value

        if "v" in query:
            return query["v"] or None

        if path.startswith("embed/"):
            return path.split("/", 1)[1] or None

        if path.startswith("shorts/"):
            return path.split("/", 1)[1] or None

        if path.startswith("live/"):
            return path.split("/", 1)[1] or None

        return None

    def fetch_youtube_metadata(self, url: str) -> dict[str, str | int | bool | None] | None:
        video_id = self.extract_youtube_video_id(url)
        if not video_id:
            return {"status": "error", "message": self.tr("yt_invalid_id")}

        if not self.config.youtube_api_key:
            return {"status": "error", "message": self.tr("yt_missing_key")}

        api_url = (
            "https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails,statistics&id="
            f"{quote(video_id)}&key={quote(self.config.youtube_api_key)}"
        )
        data = self.fetch_json_with_timeout(api_url, self.config.url_timeout_seconds)
        if not data:
            return {"status": "error", "message": self.tr("yt_api_unreachable")}

        api_error = data.get("error")
        if api_error:
            if isinstance(api_error, dict):
                message = str(api_error.get("message", self.tr("unknown_error")))
            else:
                message = self.tr("unknown_error")
            return {"status": "error", "message": f"YouTube-API: {message}"}

        items = data.get("items") or []
        if not items:
            return {"status": "error", "message": self.tr("yt_no_data")}

        item = items[0]
        snippet = item.get("snippet") or {}
        content_details = item.get("contentDetails") or {}
        statistics = item.get("statistics") or {}

        title = str(snippet.get("title", ""))
        channel_title = str(snippet.get("channelTitle", ""))
        duration = self.format_iso8601_duration(str(content_details.get("duration", "")))
        view_count = statistics.get("viewCount")
        try:
            view_count = int(view_count) if view_count is not None else None
        except (TypeError, ValueError):
            view_count = None

        like_count = self.safe_int(statistics.get("likeCount"))
        comment_count = self.safe_int(statistics.get("commentCount"))

        if not title:
            return {"status": "error", "message": self.tr("yt_no_title")}

        return {
            "status": "ok",
            "kind": "youtube",
            "url": url,
            "topic": title,
            "channel_title": channel_title,
            "duration_text": duration,
            "view_count": view_count,
            "like_count": like_count,
            "comment_count": comment_count,
            "published_text": self.format_youtube_date(str(snippet.get("publishedAt", ""))),
            "description_text": self.extract_youtube_description(str(snippet.get("description", ""))),
            "title_missing": False,
        }

    def fetch_json_with_timeout(self, url: str, timeout_seconds: float) -> dict[str, object] | None:
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0 IRCBot"})
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = response.read()
            decoded = payload.decode("utf-8", errors="replace")
            parsed = json.loads(decoded)
            return parsed
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
            return None

    def format_iso8601_duration(self, duration: str) -> str:
        match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
        if not match:
            return self.tr("unknown")

        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)

        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    def format_youtube_date(self, published_at: str) -> str:
        if not published_at:
            return self.tr("unknown")

        try:
            timestamp = time.strptime(published_at.replace("Z", "")[:19], "%Y-%m-%dT%H:%M:%S")
            return time.strftime("%d.%m.%Y", timestamp)
        except ValueError:
            return self.tr("unknown")

    def extract_youtube_description(self, description: str) -> str:
        cleaned = description.strip().replace("\r", " ").replace("\n", " ")
        cleaned = re.sub(r"\s+", " ", cleaned)
        if not cleaned:
            return ""
        return cleaned[:180]

    @staticmethod
    def safe_int(value: object) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def format_compact_number(value: object) -> str:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return str(value)

        abs_number = abs(number)
        if abs_number >= 1_000_000_000:
            compact = number / 1_000_000_000
            suffix = "B"
        elif abs_number >= 1_000_000:
            compact = number / 1_000_000
            suffix = "M"
        elif abs_number >= 1_000:
            compact = number / 1_000
            suffix = "K"
        else:
            return str(number)

        text = f"{compact:.1f}".rstrip("0").rstrip(".")
        return f"{text}{suffix}"

    def format_youtube_with_control_codes(
        self,
        title: str,
        channel_title: str,
        duration_text: str,
        published_text: str,
        view_count: object,
        like_count: object,
        comment_count: object,
        requested_by: str,
    ) -> str:
        bold = "\x02"
        reset = "\x0f"
        red = "\x0304"
        green = "\x0303"

        header = f"{bold}{red}YouTube{reset} :: {bold}{title}{reset}"
        details = []
        if channel_title:
            details.append(f"{green}{('Kanal' if self.config.language == 'de' else 'Channel')}:{reset} {channel_title}")
        if published_text:
            details.append(f"{green}{('Veröffentlicht' if self.config.language == 'de' else 'Published')}:{reset} {published_text}")
        if duration_text:
            details.append(f"{green}{('Dauer' if self.config.language == 'de' else 'Duration')}:{reset} {duration_text}")
        if view_count is not None:
            details.append(f"{green}{('Aufrufe' if self.config.language == 'de' else 'Views')}:{reset} {self.format_compact_number(view_count)}")
        if like_count is not None:
            details.append(f"{green}{('Likes' if self.config.language == 'de' else 'Likes')}:{reset} {self.format_compact_number(like_count)}")
        if comment_count is not None:
            details.append(f"{green}{('Kommentare' if self.config.language == 'de' else 'Comments')}:{reset} {self.format_compact_number(comment_count)}")

        details_text = f" ({' | '.join(details)})" if details else ""
        return f"{header}{details_text} (Requested by {requested_by})"

    def get_dart_stats_text(self, target_nick: str, requested_by: str) -> str:
        points, hit_text = self.roll_dart_turn()
        self.record_dart_throw(requested_by, points)
        rendered_target = self.format_target_nick(target_nick)
        if points == 31337:
            return self.tr(
                "dart_destroy",
                bot=self.current_nick,
                target=rendered_target,
                points=self.format_points(points),
                hit=hit_text,
                requested_by=requested_by,
            )

        return self.tr(
            "dart_hit",
            bot=self.current_nick,
            target=rendered_target,
            hit=hit_text,
            points=self.format_points(points),
            requested_by=requested_by,
        )

    def record_dart_throw(self, nick: str, points: int) -> None:
        if pymysql is None:
            return

        conn = self.open_db_connection()
        if conn is None:
            return

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bot_dart (nick, points, `throws`)
                    VALUES (%s, %s, 1)
                    ON DUPLICATE KEY UPDATE
                        points = points + VALUES(points),
                        `throws` = `throws` + 1
                    """,
                    (nick, points),
                )
        except Exception:
            pass
        finally:
            conn.close()

    def mondgesicht_channels(self) -> tuple[str, ...]:
        channels = []
        seen: set[str] = set()
        for channel in self._mondgesicht_channels:
            normalized = channel.strip()
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            channels.append(normalized)
        return tuple(channels)

    @staticmethod
    def _normalize_unique_nicks(values: list[str] | None) -> tuple[str, ...]:
        normalized_values: list[str] = []
        seen: set[str] = set()
        for value in values or []:
            nick = str(value).strip()
            lowered = nick.lower()
            if not lowered or lowered in seen:
                continue
            seen.add(lowered)
            normalized_values.append(nick)
        return tuple(normalized_values)

    @staticmethod
    def _normalize_mondgesicht_access_type(access_type: str) -> str:
        normalized = access_type.strip().lower()
        return normalized if normalized in {"god", "ignore"} else ""

    def get_mondgesicht_channel_access_nicks(self, channel: str, access_type: str) -> tuple[str, ...]:
        normalized_channel = channel.strip()
        normalized_type = self._normalize_mondgesicht_access_type(access_type)
        if not normalized_channel or not normalized_type:
            return ()

        conn = self.open_db_connection()
        if conn is None:
            return ()

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT nick
                    FROM bot_mondgesicht_channel_access
                    WHERE network = %s AND channel = %s AND access_type = %s
                    ORDER BY nick ASC
                    """,
                    (self.config.network_key, normalized_channel, normalized_type),
                )
                rows = cur.fetchall() or []
            entries = [str(row.get("nick", "")).strip() for row in rows]
            return self._normalize_unique_nicks(entries)
        except Exception:
            return ()
        finally:
            conn.close()

    def add_mondgesicht_channel_access_nick(self, channel: str, nick: str, access_type: str, created_by: str) -> str:
        normalized_channel = channel.strip()
        normalized_nick = nick.strip()
        normalized_type = self._normalize_mondgesicht_access_type(access_type)
        if not normalized_channel or normalized_channel[0] not in {"#", "&", "+", "!"}:
            return "invalid_channel"
        if not normalized_nick:
            return "invalid_nick"
        if not normalized_type:
            return "invalid_access_type"

        conn = self.open_db_connection()
        if conn is None:
            return "db_unavailable"

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT IGNORE INTO bot_mondgesicht_channel_access (network, channel, access_type, nick, created_at, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (self.config.network_key, normalized_channel, normalized_type, normalized_nick, self.current_time_string(), created_by),
                )
                return "added" if cur.rowcount > 0 else "exists"
        except Exception:
            return "db_unavailable"
        finally:
            conn.close()

    def delete_mondgesicht_channel_access_nick(self, channel: str, nick: str, access_type: str) -> str:
        normalized_channel = channel.strip()
        normalized_nick = nick.strip()
        normalized_type = self._normalize_mondgesicht_access_type(access_type)
        if not normalized_channel or normalized_channel[0] not in {"#", "&", "+", "!"}:
            return "invalid_channel"
        if not normalized_nick:
            return "invalid_nick"
        if not normalized_type:
            return "invalid_access_type"

        conn = self.open_db_connection()
        if conn is None:
            return "db_unavailable"

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM bot_mondgesicht_channel_access
                    WHERE network = %s AND channel = %s AND access_type = %s AND nick = %s
                    """,
                    (self.config.network_key, normalized_channel, normalized_type, normalized_nick),
                )
                return "deleted" if cur.rowcount > 0 else "missing"
        except Exception:
            return "db_unavailable"
        finally:
            conn.close()

    def mondgesicht_gods_for_channel(self, channel: str) -> tuple[str, ...]:
        return self.get_mondgesicht_channel_access_nicks(channel, "god")

    def mondgesicht_ignore_for_channel(self, channel: str) -> tuple[str, ...]:
        return self.get_mondgesicht_channel_access_nicks(channel, "ignore")

    def is_mondgesicht_god_for_channel(self, channel: str, nick: str) -> bool:
        lowered = nick.strip().lower()
        if not lowered:
            return False

        ignored = {entry.lower() for entry in self.mondgesicht_ignore_for_channel(channel)}
        if lowered in ignored:
            return False

        gods = self.mondgesicht_gods_for_channel(channel)
        if not gods:
            return True

        return lowered in {entry.lower() for entry in gods}

    def add_mondgesicht_channel(self, channel: str) -> str:
        normalized_channel = channel.strip()
        if not normalized_channel or normalized_channel[0] not in {"#", "&", "+", "!"}:
            return "invalid"

        existing = {item.lower() for item in self.mondgesicht_channels()}
        if normalized_channel.lower() in existing:
            return "exists"

        conn = self.open_db_connection()
        if conn is None:
            return "db_unavailable"

        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT IGNORE INTO bot_mondgesicht_channels (network, channel, created_at) VALUES (%s, %s, %s)",
                    (self.config.network_key, normalized_channel, self.current_time_string()),
                )
        except Exception:
            return "db_unavailable"
        finally:
            conn.close()

        self._mondgesicht_channels.append(normalized_channel)
        return "added"

    def delete_mondgesicht_channel(self, channel: str) -> str:
        normalized_channel = channel.strip()
        if not normalized_channel or normalized_channel[0] not in {"#", "&", "+", "!"}:
            return "invalid"

        existing = {item.lower() for item in self.mondgesicht_channels()}
        if normalized_channel.lower() not in existing:
            return "missing"

        conn = self.open_db_connection()
        if conn is None:
            return "db_unavailable"

        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM bot_mondgesicht_channels WHERE network = %s AND channel = %s",
                    (self.config.network_key, normalized_channel),
                )
        except Exception:
            return "db_unavailable"
        finally:
            conn.close()

        self._mondgesicht_channels = [item for item in self._mondgesicht_channels if item.lower() != normalized_channel.lower()]
        return "deleted"

    def record_mondgesicht_add(self, channel: str, nick: str, category: str, text: str) -> str | None:
        if pymysql is None:
            return self.tr("mg_db_missing_pkg")

        conn = self.open_db_connection()
        if conn is None:
            return self.tr("mg_db_unavailable")

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bot_mondgesicht_adds (network, channel, nick, category, entry_text, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (self.config.network_key, channel, nick, category, text, self.current_time_string()),
                )
        except Exception:
            return self.tr("mg_add_store_failed")
        finally:
            conn.close()

        return None

    def add_mondgesicht_points(self, channel: str, nick: str, points: int) -> bool:
        if points == 0 or pymysql is None:
            return False

        conn = self.open_db_connection()
        if conn is None:
            return False

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bot_mondgesicht_scores (network, channel, nick, points, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        points = GREATEST(0, points + VALUES(points)),
                        updated_at = VALUES(updated_at)
                    """,
                    (self.config.network_key, channel, nick, points, self.current_time_string()),
                )
        except Exception:
            return False
        finally:
            conn.close()

        return True

    def unique_mondgesicht_participants(self, participants: list[str], *, preserve_case: bool = True) -> list[str]:
        unique_participants: list[str] = []
        seen: set[str] = set()
        for nick in participants:
            normalized_nick = nick.strip()
            lowered = normalized_nick.lower()
            if not lowered or lowered in seen:
                continue
            seen.add(lowered)
            unique_participants.append(normalized_nick if preserve_case else lowered)
        return unique_participants

    def update_mondgesicht_repetition_streaks(
        self,
        unresolved: set[str],
        streak_rounds: dict[str, int],
        round_nicks: set[str],
    ) -> None:
        for lowered in tuple(unresolved):
            if lowered in round_nicks:
                streak_rounds[lowered] += 1
                continue
            unresolved.remove(lowered)

    def iter_mondgesicht_round_nick_sets(self, conn, channel: str) -> Iterable[set[str]]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT nick,
                       CASE WHEN round_token <> '' THEN round_token ELSE CONCAT('legacy:', created_at) END AS round_key
                FROM bot_mondgesicht_round_awards
                WHERE network = %s AND channel = %s
                ORDER BY id DESC
                """,
                (self.config.network_key, channel),
            )
            current_round_key = None
            current_round_nicks: set[str] = set()
            for row in cur.fetchall() or []:
                round_key = str(row.get("round_key", "")).strip()
                lowered = str(row.get("nick", "")).strip().lower()
                if not round_key or not lowered:
                    continue
                if current_round_key is None:
                    current_round_key = round_key
                if round_key != current_round_key:
                    yield current_round_nicks
                    current_round_key = round_key
                    current_round_nicks = set()
                current_round_nicks.add(lowered)

            if current_round_key is not None:
                yield current_round_nicks

    def normalize_mondgesicht_award_participants(self, participants: list[str]) -> dict[str, dict[str, object]]:
        normalized_participants: dict[str, dict[str, object]] = {}
        for raw_nick in participants:
            nick = raw_nick.strip()
            if not nick:
                continue
            lowered = nick.lower()
            if lowered not in normalized_participants:
                normalized_participants[lowered] = {"nick": nick, "slots": 0}
            normalized_participants[lowered]["slots"] = int(normalized_participants[lowered]["slots"]) + 1
        return normalized_participants

    def get_mondgesicht_repetition_counts(
        self,
        channel: str,
        participants: list[str],
        *,
        conn=None,
    ) -> dict[str, int]:
        if pymysql is None or not participants:
            return {}

        unique_participants = self.unique_mondgesicht_participants(participants, preserve_case=False)
        if not unique_participants:
            return {}

        owns_connection = conn is None
        if owns_connection:
            conn = self.open_db_connection()
        if conn is None:
            return {}

        streak_rounds = dict.fromkeys(unique_participants, 0)
        unresolved = set(unique_participants)

        try:
            for round_nicks in self.iter_mondgesicht_round_nick_sets(conn, channel):
                self.update_mondgesicht_repetition_streaks(unresolved, streak_rounds, round_nicks)
                if not unresolved:
                    break
        except Exception:
            return {}
        finally:
            if owns_connection:
                conn.close()

        return {
            lowered: max(0, streak_length)
            for lowered, streak_length in streak_rounds.items()
        }

    def get_mondgesicht_player_summaries(self, channel: str, participants: list[str]) -> dict[str, dict[str, int]]:
        if pymysql is None or not participants:
            return {}

        unique_participants = self.unique_mondgesicht_participants(participants)
        if not unique_participants:
            return {}

        conn = self.open_db_connection()
        if conn is None:
            return {}

        placeholders = ", ".join(["%s"] * len(unique_participants))
        summaries = {
            nick.lower(): {"current_points": 0, "repetitions": 0}
            for nick in unique_participants
        }
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT nick, points
                    FROM bot_mondgesicht_scores
                    WHERE network = %s AND channel = %s AND nick IN ({placeholders})
                    """,
                    (self.config.network_key, channel, *unique_participants),
                )
                for row in cur.fetchall() or []:
                    nick = str(row.get("nick", "")).strip().lower()
                    if nick in summaries:
                        summaries[nick]["current_points"] = int(row.get("points", 0))

                repeat_counts = self.get_mondgesicht_repetition_counts(channel, unique_participants, conn=conn)
                for nick, repetitions in repeat_counts.items():
                    if nick in summaries:
                        summaries[nick]["repetitions"] = repetitions
        except Exception:
            return {}
        finally:
            conn.close()

        return summaries

    def award_mondgesicht_round_points(self, channel: str, participants: list[str], points: int, round_token: str) -> dict[str, object] | None:
        if points == 0 or pymysql is None or not participants:
            return None

        normalized_participants = self.normalize_mondgesicht_award_participants(participants)
        if not normalized_participants:
            return None

        conn = self.open_db_connection()
        if conn is None:
            return None

        summaries: dict[str, dict[str, int]] = {}
        created_at = self.current_time_string()
        try:
            with conn.cursor() as cur:
                for lowered, participant_info in normalized_participants.items():
                    nick = str(participant_info["nick"])
                    awarded_points = points * int(participant_info["slots"])
                    cur.execute(
                        """
                        SELECT points
                        FROM bot_mondgesicht_scores
                        WHERE network = %s AND channel = %s AND nick = %s
                        LIMIT 1
                        """,
                        (self.config.network_key, channel, nick),
                    )
                    row = cur.fetchone() or {}
                    previous_points = int(row.get("points", 0))

                    cur.execute(
                        """
                        INSERT INTO bot_mondgesicht_scores (network, channel, nick, points, updated_at)
                        VALUES (%s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            points = GREATEST(0, points + VALUES(points)),
                            updated_at = VALUES(updated_at)
                        """,
                        (self.config.network_key, channel, nick, awarded_points, created_at),
                    )
                    cur.execute(
                        """
                        INSERT INTO bot_mondgesicht_round_awards (network, channel, nick, round_token, points_awarded, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (self.config.network_key, channel, nick, round_token, awarded_points, created_at),
                    )
                    summaries[lowered] = {
                        "previous_points": previous_points,
                        "current_points": max(0, previous_points + awarded_points),
                        "repetitions": 0,
                    }

                repeat_counts = self.get_mondgesicht_repetition_counts(
                    channel,
                    [str(info["nick"]) for info in normalized_participants.values()],
                    conn=conn,
                )
                for lowered, repetitions in repeat_counts.items():
                    if lowered in summaries:
                        summaries[lowered]["repetitions"] = repetitions

                cur.execute(
                    """
                    SELECT COUNT(DISTINCT CASE WHEN round_token <> '' THEN round_token ELSE created_at END) AS round_count
                    FROM bot_mondgesicht_round_awards
                    WHERE network = %s AND channel = %s
                    """,
                    (self.config.network_key, channel),
                )
                round_row = cur.fetchone() or {}
        except Exception:
            return None
        finally:
            conn.close()

        return {
            "players": summaries,
            "round_count": int(round_row.get("round_count", 0)),
        }

    def add_mondgesicht_text(self, language: str, category: str, text: str, created_by: str) -> bool:
        if pymysql is None:
            return False

        normalized_language = language.strip().lower()
        normalized_category = category.strip().lower()
        normalized_text = text.strip()
        normalized_created_by = created_by.strip()
        if normalized_language not in {"de", "en"} or not normalized_category or not normalized_text:
            return False

        conn = self.open_db_connection()
        if conn is None:
            return False

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bot_mondgesicht_texts (network, language, category, entry_text, created_at, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self.config.network_key,
                        normalized_language,
                        normalized_category,
                        normalized_text,
                        self.current_time_string(),
                        normalized_created_by,
                    ),
                )
        except Exception:
            return False
        finally:
            conn.close()

        return True

    def replace_mondgesicht_texts(self, entries: list[tuple[str, str, str]], created_by: str) -> bool:
        if pymysql is None:
            return False
        if not entries:
            return False

        normalized_created_by = created_by.strip()
        prepared_entries: list[tuple[str, str, str, str, str, str]] = []
        for language, category, text in entries:
            normalized_language = language.strip().lower()
            normalized_category = category.strip().lower()
            normalized_text = text.strip()
            if normalized_language not in {"de", "en"} or not normalized_category or not normalized_text:
                return False
            prepared_entries.append(
                (
                    self.config.network_key,
                    normalized_language,
                    normalized_category,
                    normalized_text,
                    self.current_time_string(),
                    normalized_created_by,
                )
            )

        conn = self.open_db_connection()
        if conn is None:
            return False

        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM bot_mondgesicht_texts WHERE network = %s", (self.config.network_key,))
                cur.executemany(
                    """
                    INSERT INTO bot_mondgesicht_texts (network, language, category, entry_text, created_at, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    prepared_entries,
                )
        except Exception:
            return False
        finally:
            conn.close()

        return True

    @staticmethod
    def parse_mondgesicht_text_seed_language(
        raw: object,
        language: str,
    ) -> list[tuple[str, str, str]] | None:
        if not isinstance(raw, dict):
            return None

        entries: list[tuple[str, str, str]] = []
        language_values = raw.get(language)
        if not isinstance(language_values, dict):
            return None
        for category in ("punkt1", "punkt2", "komma", "strich"):
            category_values = language_values.get(category)
            if not isinstance(category_values, list):
                return None
            for value in category_values:
                text = str(value).strip()
                if text:
                    entries.append((language, category, text))
        return entries

    @classmethod
    def parse_mondgesicht_text_seed(cls, raw: object) -> list[tuple[str, str, str]] | None:
        de_entries = cls.parse_mondgesicht_text_seed_language(raw, "de")
        if de_entries is None:
            return None
        en_entries = cls.parse_mondgesicht_text_seed_language(raw, "en")
        if en_entries is None:
            return None
        entries = [*de_entries, *en_entries]
        return entries or None

    def default_mondgesicht_text_seed_entries(self) -> list[tuple[str, str, str]] | None:
        return self.parse_mondgesicht_text_seed(DEFAULT_MONDGESICHT_TEXT_SEED)

    def seed_default_mondgesicht_texts(self, created_by: str, *, replace_existing: bool = False) -> tuple[bool, int]:
        entries = self.default_mondgesicht_text_seed_entries()
        if not entries:
            return False, 0

        conn = self.open_db_connection()
        if conn is None:
            return False, 0

        has_existing_entries = False
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM bot_mondgesicht_texts WHERE network = %s LIMIT 1",
                    (self.config.network_key,),
                )
                has_existing_entries = cur.fetchone() is not None
        except Exception:
            return False, 0
        finally:
            conn.close()

        if has_existing_entries and not replace_existing:
            return True, 0
        if not self.replace_mondgesicht_texts(entries, created_by):
            return False, 0
        return True, len(entries)

    def format_mondgesicht_url(self, **kwargs: object) -> str | None:
        if not self.config.mondgesicht_url_enabled:
            return None

        template = self.config.mondgesicht_url.strip()
        if not template:
            return None

        format_values: dict[str, object] = dict(kwargs)
        for key, value in kwargs.items():
            format_values[f"{key}_url"] = quote_plus(str(value))

        try:
            rendered = template.format(**format_values).strip()
        except Exception:
            return None
        return rendered or None

    def delete_mondgesicht_text(self, text_id: int) -> bool:
        if pymysql is None:
            return False

        conn = self.open_db_connection()
        if conn is None:
            return False

        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM bot_mondgesicht_texts WHERE network = %s AND id = %s",
                    (self.config.network_key, text_id),
                )
                return cur.rowcount > 0
        except Exception:
            return False
        finally:
            conn.close()

    def list_mondgesicht_texts(self, language: str, category: str = "", limit: int = 20) -> tuple[dict[str, object], ...]:
        if pymysql is None:
            return ()

        normalized_language = language.strip().lower()
        normalized_category = category.strip().lower()
        if normalized_language not in {"de", "en"}:
            return ()

        conn = self.open_db_connection()
        if conn is None:
            return ()

        safe_limit = max(1, min(limit, 50))
        try:
            with conn.cursor() as cur:
                if normalized_category:
                    cur.execute(
                        """
                        SELECT id, language, category, entry_text, created_at, created_by
                        FROM bot_mondgesicht_texts
                        WHERE network = %s AND language = %s AND category = %s
                        ORDER BY id DESC
                        LIMIT %s
                        """,
                        (self.config.network_key, normalized_language, normalized_category, safe_limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, language, category, entry_text, created_at, created_by
                        FROM bot_mondgesicht_texts
                        WHERE network = %s AND language = %s
                        ORDER BY id DESC
                        LIMIT %s
                        """,
                        (self.config.network_key, normalized_language, safe_limit),
                    )
                rows = cur.fetchall() or []
        except Exception:
            return ()
        finally:
            conn.close()

        return tuple(rows)

    def get_random_mondgesicht_text(self, language: str, category: str) -> str | None:
        if pymysql is None:
            return None

        normalized_language = language.strip().lower()
        normalized_category = category.strip().lower()
        if normalized_language not in {"de", "en"} or not normalized_category:
            return None

        conn = self.open_db_connection()
        if conn is None:
            return None

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT entry_text
                    FROM bot_mondgesicht_texts
                    WHERE network = %s AND language = %s AND category = %s
                    ORDER BY RAND()
                    LIMIT 1
                    """,
                    (self.config.network_key, normalized_language, normalized_category),
                )
                row = cur.fetchone()
                if row:
                    return str(row.get("entry_text", "")).strip() or None

                if normalized_language != "de":
                    cur.execute(
                        """
                        SELECT entry_text
                        FROM bot_mondgesicht_texts
                        WHERE network = %s AND language = 'de' AND category = %s
                        ORDER BY RAND()
                        LIMIT 1
                        """,
                        (self.config.network_key, normalized_category),
                    )
                    fallback_row = cur.fetchone()
                    if fallback_row:
                        return str(fallback_row.get("entry_text", "")).strip() or None
        except Exception:
            return None
        finally:
            conn.close()

        return None

    def get_mondgesicht_top_text(self, channel: str, limit: int = 10) -> str:
        if pymysql is None:
            return self.tr("mg_db_missing_pkg")

        conn = self.open_db_connection()
        if conn is None:
            return self.tr("mg_db_unavailable")

        safe_limit = max(1, min(limit, 50))
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT nick, points
                    FROM bot_mondgesicht_scores
                    WHERE network = %s AND channel = %s
                    ORDER BY points DESC, nick ASC
                    LIMIT %s
                    """,
                    (self.config.network_key, channel, safe_limit),
                )
                rows = cur.fetchall()
        except Exception:
            return self.tr("mg_db_unavailable")
        finally:
            conn.close()

        if not rows:
            return self.tr("mg_top_empty", channel=channel)

        items = [
            self.tr("mg_top_entry", index=index, nick=str(row.get("nick", "?")), points=self.format_points(int(row.get("points", 0))))
            for index, row in enumerate(rows, start=1)
        ]
        return self.tr("mg_top_channel", channel=channel, items=" | ".join(items))

    def get_mondgesicht_global_top_text(self, limit: int = 10) -> str:
        channels = self.mondgesicht_channels()
        if not channels:
            return self.tr("mg_no_channels")
        if pymysql is None:
            return self.tr("mg_db_missing_pkg")

        conn = self.open_db_connection()
        if conn is None:
            return self.tr("mg_db_unavailable")

        safe_limit = max(1, min(limit, 50))
        placeholders = ", ".join(["%s"] * len(channels))
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT nick, SUM(points) AS points
                    FROM bot_mondgesicht_scores
                    WHERE network = %s AND channel IN ({placeholders})
                    GROUP BY nick
                    ORDER BY points DESC, nick ASC
                    LIMIT %s
                    """,
                    (self.config.network_key, *channels, safe_limit),
                )
                rows = cur.fetchall()
        except Exception:
            return self.tr("mg_db_unavailable")
        finally:
            conn.close()

        if not rows:
            return self.tr("mg_global_top_empty")

        items = [
            self.tr("mg_top_entry", index=index, nick=str(row.get("nick", "?")), points=self.format_points(int(row.get("points", 0))))
            for index, row in enumerate(rows, start=1)
        ]
        return self.tr("mg_global_top", items=" | ".join(items))

    def get_mondgesicht_stats_text(self, channel: str, nick: str) -> str:
        if pymysql is None:
            return self.tr("mg_db_missing_pkg")

        conn = self.open_db_connection()
        if conn is None:
            return self.tr("mg_db_unavailable")

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT points
                    FROM bot_mondgesicht_scores
                    WHERE network = %s AND channel = %s AND nick = %s
                    LIMIT 1
                    """,
                    (self.config.network_key, channel, nick),
                )
                row = cur.fetchone()
                if not row:
                    return self.tr("mg_stats_empty", nick=nick, scope=channel)

                points = int(row.get("points", 0))
                cur.execute(
                    MONDGESICHT_CHANNEL_PLAYER_COUNT_QUERY,
                    (self.config.network_key, channel),
                )
                total_row = cur.fetchone() or {}
                total_players = int(total_row.get("total_players", 0))
                cur.execute(
                    """
                    SELECT COUNT(*) + 1 AS rank_pos
                    FROM bot_mondgesicht_scores
                    WHERE network = %s AND channel = %s AND points > %s
                    """,
                    (self.config.network_key, channel, points),
                )
                rank_row = cur.fetchone() or {}
                rank = int(rank_row.get("rank_pos", 1))
        except Exception:
            return self.tr("mg_db_unavailable")
        finally:
            conn.close()

        return self.tr(
            "mg_stats",
            nick=nick,
            points=self.format_points(points),
            rank=rank,
            total=total_players,
            scope=channel,
        )

    def get_mondgesicht_global_stats_text(self, nick: str) -> str:
        channels = self.mondgesicht_channels()
        if not channels:
            return self.tr("mg_no_channels")
        if pymysql is None:
            return self.tr("mg_db_missing_pkg")

        conn = self.open_db_connection()
        if conn is None:
            return self.tr("mg_db_unavailable")

        placeholders = ", ".join(["%s"] * len(channels))
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT nick, SUM(points) AS points
                    FROM bot_mondgesicht_scores
                    WHERE network = %s AND channel IN ({placeholders})
                    GROUP BY nick
                    ORDER BY points DESC, nick ASC
                    """,
                    (self.config.network_key, *channels),
                )
                rows = cur.fetchall()
        except Exception:
            return self.tr("mg_db_unavailable")
        finally:
            conn.close()

        if not rows:
            return self.tr("mg_global_stats_empty", nick=nick)

        lowered_nick = nick.lower()
        for index, row in enumerate(rows, start=1):
            row_nick = str(row.get("nick", ""))
            if row_nick.lower() != lowered_nick:
                continue
            return self.tr(
                "mg_global_stats",
                nick=row_nick,
                points=self.format_points(int(row.get("points", 0))),
                rank=index,
                total=len(rows),
            )

        return self.tr("mg_global_stats_empty", nick=nick)

    @staticmethod
    def mondgesicht_repeat_bonus_value(repetitions: int, player_count: int) -> int:
        if repetitions < 5 or repetitions % 5 != 0:
            return 0

        steps = repetitions // 5
        if player_count < 7:
            factor = 10
        elif player_count > 100:
            factor = 6
        elif player_count > 80:
            factor = 5
        elif player_count > 60:
            factor = 4
        elif player_count > 40:
            factor = 3
        elif player_count > 20:
            factor = 2
        else:
            factor = 1
        return factor * steps

    def get_mondgesicht_channel_player_count(self, channel: str) -> int:
        if pymysql is None:
            return 0

        conn = self.open_db_connection()
        if conn is None:
            return 0

        try:
            with conn.cursor() as cur:
                cur.execute(
                    MONDGESICHT_CHANNEL_PLAYER_COUNT_QUERY,
                    (self.config.network_key, channel),
                )
                row = cur.fetchone() or {}
                return int(row.get("total_players", 0))
        except Exception:
            return 0
        finally:
            conn.close()

    def get_mondgesicht_channel_points(self, channel: str, nick: str) -> int:
        if pymysql is None:
            return 0

        conn = self.open_db_connection()
        if conn is None:
            return 0

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT points
                    FROM bot_mondgesicht_scores
                    WHERE network = %s AND channel = %s AND nick = %s
                    LIMIT 1
                    """,
                    (self.config.network_key, channel, nick),
                )
                row = cur.fetchone() or {}
        except Exception:
            return 0
        finally:
            conn.close()

        return int(row.get("points", 0))

    def get_mondgesicht_channel_leader(self, channel: str) -> dict[str, object] | None:
        if pymysql is None:
            return None

        conn = self.open_db_connection()
        if conn is None:
            return None

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT nick, points
                    FROM bot_mondgesicht_scores
                    WHERE network = %s AND channel = %s
                    ORDER BY points DESC, nick ASC
                    LIMIT 1
                    """,
                    (self.config.network_key, channel),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "nick": str(row.get("nick", "")).strip(),
                    "points": int(row.get("points", 0)),
                }
        except Exception:
            return None
        finally:
            conn.close()

    def get_mondgesicht_jackpot_state(self, channel: str) -> dict[str, object]:
        if pymysql is None:
            return {"jackpot_points": 0, "last_awarded_points": 0, "last_awarded_to": ""}

        conn = self.open_db_connection()
        if conn is None:
            return {"jackpot_points": 0, "last_awarded_points": 0, "last_awarded_to": ""}

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT jackpot_points, last_awarded_points, last_awarded_to
                    FROM bot_mondgesicht_jackpot
                    WHERE network = %s AND channel = %s
                    LIMIT 1
                    """,
                    (self.config.network_key, channel),
                )
                row = cur.fetchone() or {}
        except Exception:
            return {"jackpot_points": 0, "last_awarded_points": 0, "last_awarded_to": ""}
        finally:
            conn.close()

        return {
            "jackpot_points": int(row.get("jackpot_points", 0)),
            "last_awarded_points": int(row.get("last_awarded_points", 0)),
            "last_awarded_to": str(row.get("last_awarded_to", "")).strip(),
        }

    def store_mondgesicht_jackpot_state(self, channel: str, jackpot_points: int, last_awarded_points: int, last_awarded_to: str) -> bool:
        if pymysql is None:
            return False

        conn = self.open_db_connection()
        if conn is None:
            return False

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bot_mondgesicht_jackpot (network, channel, jackpot_points, last_awarded_points, last_awarded_to, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        jackpot_points = VALUES(jackpot_points),
                        last_awarded_points = VALUES(last_awarded_points),
                        last_awarded_to = VALUES(last_awarded_to),
                        updated_at = VALUES(updated_at)
                    """,
                    (
                        self.config.network_key,
                        channel,
                        max(0, int(jackpot_points)),
                        max(0, int(last_awarded_points)),
                        last_awarded_to.strip(),
                        self.current_time_string(),
                    ),
                )
        except Exception:
            return False
        finally:
            conn.close()

        return True

    def apply_mondgesicht_point_changes(self, channel: str, point_changes: dict[str, int]) -> dict[str, int] | None:
        if pymysql is None:
            return None

        normalized_changes: dict[str, dict[str, object]] = {}
        for raw_nick, raw_delta in point_changes.items():
            nick = raw_nick.strip()
            delta = int(raw_delta)
            if not nick or delta == 0:
                continue
            lowered = nick.lower()
            if lowered not in normalized_changes:
                normalized_changes[lowered] = {"nick": nick, "delta": 0}
            normalized_changes[lowered]["delta"] = int(normalized_changes[lowered]["delta"]) + delta

        if not normalized_changes:
            return {}

        conn = self.open_db_connection()
        if conn is None:
            return None

        try:
            with conn.cursor() as cur:
                for payload in normalized_changes.values():
                    cur.execute(
                        """
                        INSERT INTO bot_mondgesicht_scores (network, channel, nick, points, updated_at)
                        VALUES (%s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            points = GREATEST(0, points + VALUES(points)),
                            updated_at = VALUES(updated_at)
                        """,
                        (
                            self.config.network_key,
                            channel,
                            str(payload["nick"]),
                            int(payload["delta"]),
                            self.current_time_string(),
                        ),
                    )

                placeholders = ", ".join(["%s"] * len(normalized_changes))
                cur.execute(
                    f"""
                    SELECT nick, points
                    FROM bot_mondgesicht_scores
                    WHERE network = %s AND channel = %s AND nick IN ({placeholders})
                    """,
                    (self.config.network_key, channel, *(str(payload["nick"]) for payload in normalized_changes.values())),
                )
                rows = cur.fetchall() or []
        except Exception:
            return None
        finally:
            conn.close()

        return {str(row.get("nick", "")).strip().lower(): int(row.get("points", 0)) for row in rows}

    def format_mondgesicht_last_jackpot(self, last_points: int, last_nick: str) -> str:
        if last_points <= 0 or not last_nick.strip():
            return ""
        return self.tr("mg_status_last_jackpot", points=self.format_points(last_points), nick=last_nick)

    def format_mondgesicht_jackpot_details(
        self,
        minimum_points: int,
        maximum_points: int,
        awarded: bool,
        reason: str = "",
    ) -> str:
        reason_text = ""
        if not awarded and reason.strip():
            reason_text = self.tr("mg_jackpot_reason", reason=reason.strip())
        return self.tr(
            "mg_jackpot_details",
            minimum=self.format_points(minimum_points),
            maximum=self.format_points(maximum_points),
            awarded=self.tr("mg_jackpot_awarded_yes" if awarded else "mg_jackpot_awarded_no"),
            reason=reason_text,
        )

    @staticmethod
    def build_mondgesicht_slot_context(slot_participants: list[str]) -> tuple[list[str], dict[str, int], dict[str, str]]:
        distinct_participants: list[str] = []
        seen_participants: set[str] = set()
        slot_counts: dict[str, int] = {}
        display_names: dict[str, str] = {}

        for nick in slot_participants:
            cleaned = nick.strip()
            if not cleaned:
                continue
            lowered = cleaned.lower()
            display_names[lowered] = cleaned
            slot_counts[lowered] = slot_counts.get(lowered, 0) + 1
            if lowered in seen_participants:
                continue
            seen_participants.add(lowered)
            distinct_participants.append(cleaned)

        return distinct_participants, slot_counts, display_names

    def collect_mondgesicht_repeat_and_day_bonuses(
        self,
        channel: str,
        round_count: int,
        distinct_participants: list[str],
        slot_counts: dict[str, int],
        player_summaries: dict[str, dict[str, int]],
    ) -> tuple[dict[str, int], list[str]]:
        bonus_changes: dict[str, int] = {}
        bonus_labels: list[str] = []
        player_count = max(1, self.get_mondgesicht_channel_player_count(channel))

        for nick in distinct_participants:
            lowered = nick.lower()
            repetitions = int(player_summaries.get(lowered, {}).get("repetitions", 0))
            repeat_bonus = self.mondgesicht_repeat_bonus_value(repetitions, player_count)
            if repeat_bonus <= 0:
                continue
            bonus_changes[lowered] = bonus_changes.get(lowered, 0) + (repeat_bonus * slot_counts.get(lowered, 1))
            bonus_labels.append(self.tr("mg_bonus_repeat_summary"))

        day_of_year = max(1, time.localtime().tm_yday)
        if round_count > 0 and day_of_year % round_count == 0:
            for lowered, slots in slot_counts.items():
                bonus_changes[lowered] = bonus_changes.get(lowered, 0) + (5 * slots)
            bonus_labels.append(self.tr("mg_bonus_day_summary"))

        if str(round_count).endswith(f"{day_of_year:03d}"):
            for lowered, slots in slot_counts.items():
                bonus_changes[lowered] = bonus_changes.get(lowered, 0) + (day_of_year * slots)
            bonus_labels.append(self.tr("mg_bonus_day_big_summary"))

        return bonus_changes, bonus_labels

    def collect_mondgesicht_leader_bonus(
        self,
        channel: str,
        distinct_participants: list[str],
    ) -> tuple[dict[str, int], dict[str, str], list[str]]:
        leader = self.get_mondgesicht_channel_leader(channel)
        if leader is None:
            return {}, {}, []

        leader_nick = str(leader.get("nick", "")).strip()
        leader_points = int(leader.get("points", 0))
        distinct_participant_keys = {nick.lower() for nick in distinct_participants}
        if not leader_nick or leader_points <= 0 or leader_nick.lower() in distinct_participant_keys:
            return {}, {}, []

        total_loss = max(1, len(distinct_participants))
        bonus_changes = {leader_nick.lower(): -total_loss}
        display_names = {leader_nick.lower(): leader_nick}
        for nick in distinct_participants:
            cleaned = nick.strip()
            if not cleaned:
                continue
            lowered = cleaned.lower()
            bonus_changes[lowered] = bonus_changes.get(lowered, 0) + 1
            display_names[lowered] = cleaned
        return bonus_changes, display_names, [self.tr("mg_bonus_leader_summary", nick=leader_nick, points=self.format_points(total_loss))]

    def resolve_mondgesicht_jackpot(
        self,
        channel: str,
        distinct_participants: list[str],
        slot_participants: list[str],
        player_summaries: dict[str, dict[str, int]],
        bonus_changes: dict[str, int],
    ) -> tuple[dict[str, int], str]:
        day_of_year = max(1, time.localtime().tm_yday)
        jackpot_state = self.get_mondgesicht_jackpot_state(channel)
        minimum_jackpot = day_of_year
        jackpot_points = max(int(jackpot_state.get("jackpot_points", 0)), day_of_year)
        jackpot_points += max(1, len(slot_participants))
        last_awarded_points = int(jackpot_state.get("last_awarded_points", 0))
        last_awarded_to = str(jackpot_state.get("last_awarded_to", "")).strip()
        max_jackpot = max(day_of_year, int(500 * day_of_year / 183))
        jackpot_points = min(jackpot_points, max_jackpot)
        minimum_jackpot = min(minimum_jackpot, max_jackpot)
        jackpot_awarded = False
        jackpot_reason = ""
        jackpot_message = self.tr(
            "mg_jackpot_pending",
            jackpot=self.format_points(jackpot_points),
            last_jackpot=self.format_mondgesicht_last_jackpot(last_awarded_points, last_awarded_to),
        )

        if jackpot_points >= day_of_year:
            candidate_pool: list[str] = ["-ALL"]
            seen_candidates = {"-all"}
            for nick in self.get_channel_member_nicks(channel):
                lowered_nick = nick.lower()
                if lowered_nick not in seen_candidates:
                    candidate_pool.append(nick)
                    seen_candidates.add(lowered_nick)
            if self.current_nick.lower() not in seen_candidates:
                candidate_pool.append(self.current_nick)
            candidate = random.choice(candidate_pool)
            if candidate == "-ALL" and distinct_participants:
                eligible_participants: list[str] = []
                missing_participants: list[str] = []
                low_point_participants: list[str] = []
                for nick in distinct_participants:
                    if not self.is_nick_in_channel(channel, nick):
                        missing_participants.append(nick)
                        continue
                    lowered = nick.lower()
                    candidate_points = int(player_summaries.get(lowered, {}).get("current_points", 0))
                    if lowered not in player_summaries:
                        candidate_points = self.get_mondgesicht_channel_points(channel, nick)
                    candidate_points += bonus_changes.get(lowered, 0)
                    if candidate_points <= 100:
                        low_point_participants.append(f"{nick} ({self.format_points(candidate_points)})")
                        continue
                    eligible_participants.append(nick)

                if len(eligible_participants) == len(distinct_participants):
                    share = max(1, jackpot_points // max(1, len(eligible_participants)))
                    for nick in eligible_participants:
                        lowered = nick.lower()
                        bonus_changes[lowered] = bonus_changes.get(lowered, 0) + share
                    last_awarded_points = jackpot_points
                    last_awarded_to = ", ".join(eligible_participants)
                    jackpot_awarded = True
                    jackpot_message = self.tr("mg_jackpot_split", points=self.format_points(jackpot_points), nicks=", ".join(eligible_participants))
                    jackpot_points = 0
                elif missing_participants:
                    jackpot_reason = self.tr(
                        "mg_jackpot_not_awarded_split_not_in_channel",
                        nicks=", ".join(missing_participants),
                    )
                else:
                    jackpot_reason = self.tr(
                        "mg_jackpot_not_awarded_split_points",
                        nicks=", ".join(low_point_participants),
                    )
            elif candidate == "-ALL":
                jackpot_reason = self.tr("mg_jackpot_not_awarded_no_participants")
            elif candidate.lower() == self.current_nick.lower():
                jackpot_points = min(max_jackpot, max(jackpot_points + 1, int(round(jackpot_points * random.uniform(1.0, 2.0)))))
                jackpot_message = self.tr("mg_jackpot_rolled", jackpot=self.format_points(jackpot_points))
            elif self.is_nick_in_channel(channel, candidate):
                lowered_candidate = candidate.lower()
                candidate_points = int(player_summaries.get(lowered_candidate, {}).get("current_points", 0))
                if lowered_candidate not in player_summaries:
                    candidate_points = self.get_mondgesicht_channel_points(channel, candidate)
                candidate_points += bonus_changes.get(lowered_candidate, 0)
                if candidate_points > 100:
                    bonus_changes[lowered_candidate] = bonus_changes.get(lowered_candidate, 0) + jackpot_points
                    last_awarded_points = jackpot_points
                    last_awarded_to = candidate
                    jackpot_awarded = True
                    jackpot_message = self.tr("mg_jackpot_awarded", nick=candidate, points=self.format_points(jackpot_points))
                    jackpot_points = 0
                else:
                    jackpot_reason = self.tr(
                        "mg_jackpot_not_awarded_points",
                        nick=candidate,
                        points=self.format_points(candidate_points),
                    )
            else:
                jackpot_reason = self.tr("mg_jackpot_not_awarded_not_in_channel", nick=candidate)

        jackpot_message = "{} {}".format(
            jackpot_message,
            self.format_mondgesicht_jackpot_details(minimum_jackpot, max_jackpot, jackpot_awarded, jackpot_reason),
        ).strip()

        self.store_mondgesicht_jackpot_state(channel, jackpot_points, last_awarded_points, last_awarded_to)
        return bonus_changes, jackpot_message

    def process_mondgesicht_round_extras(
        self,
        channel: str,
        participants: list[str],
        slot_participants: list[str],
        round_count: int,
        player_summaries: dict[str, dict[str, int]],
    ) -> dict[str, object]:
        if not participants:
            return {"players": player_summaries, "messages": ()}

        distinct_participants, slot_counts, display_names = self.build_mondgesicht_slot_context(slot_participants)
        bonus_changes, bonus_labels = self.collect_mondgesicht_repeat_and_day_bonuses(
            channel,
            round_count,
            distinct_participants,
            slot_counts,
            player_summaries,
        )
        leader_changes, leader_display_names, leader_labels = self.collect_mondgesicht_leader_bonus(
            channel,
            distinct_participants,
        )
        display_names.update(leader_display_names)
        for lowered, delta in leader_changes.items():
            bonus_changes[lowered] = bonus_changes.get(lowered, 0) + delta
        bonus_labels.extend(leader_labels)
        bonus_changes, jackpot_message = self.resolve_mondgesicht_jackpot(
            channel,
            distinct_participants,
            slot_participants,
            player_summaries,
            bonus_changes,
        )

        updated_points = self.apply_mondgesicht_point_changes(
            channel,
            {display_names.get(lowered, lowered): delta for lowered, delta in bonus_changes.items()},
        )
        if updated_points is not None:
            for nick in participants:
                lowered = nick.lower()
                if lowered in updated_points and lowered in player_summaries:
                    player_summaries[lowered]["current_points"] = updated_points[lowered]

        messages: list[str] = []
        if bonus_labels:
            messages.append(self.tr("mg_round_extras", details=", ".join(dict.fromkeys(bonus_labels))))
        if jackpot_message:
            messages.append(jackpot_message)

        return {"players": player_summaries, "messages": tuple(messages)}

    def get_mondgesicht_status_text(self, channel: str) -> str:
        if pymysql is None:
            return self.tr("mg_db_missing_pkg")

        channels = self.mondgesicht_channels()
        placeholders = ", ".join(["%s"] * len(channels)) if channels else ""
        conn = self.open_db_connection()
        if conn is None:
            return self.tr("mg_db_unavailable")

        try:
            with conn.cursor() as cur:
                cur.execute(
                    MONDGESICHT_CHANNEL_PLAYER_COUNT_QUERY,
                    (self.config.network_key, channel),
                )
                current_row = cur.fetchone() or {}
                players_current = int(current_row.get("total_players", 0))

                if channels:
                    cur.execute(
                        f"""
                        SELECT COUNT(DISTINCT nick) AS total_players
                        FROM bot_mondgesicht_scores
                        WHERE network = %s AND channel IN ({placeholders})
                        """,
                        (self.config.network_key, *channels),
                    )
                    global_row = cur.fetchone() or {}
                    players_global = int(global_row.get("total_players", 0))
                else:
                    players_global = players_current

                cur.execute(
                    """
                    SELECT COUNT(DISTINCT CASE WHEN round_token <> '' THEN round_token ELSE created_at END) AS round_count
                    FROM bot_mondgesicht_round_awards
                    WHERE network = %s AND channel = %s
                    """,
                    (self.config.network_key, channel),
                )
                round_row = cur.fetchone() or {}
                round_count = int(round_row.get("round_count", 0))
        except Exception:
            return self.tr("mg_db_unavailable")
        finally:
            conn.close()

        leader = self.get_mondgesicht_channel_leader(channel)
        leader_text = self.tr("mg_status_no_leader") if leader is None else self.tr(
            "mg_status_leader",
            nick=str(leader.get("nick", "?")),
            points=self.format_points(int(leader.get("points", 0))),
        )
        jackpot_state = self.get_mondgesicht_jackpot_state(channel)
        last_jackpot = self.format_mondgesicht_last_jackpot(
            int(jackpot_state.get("last_awarded_points", 0)),
            str(jackpot_state.get("last_awarded_to", "")),
        )
        return self.tr(
            "mg_status",
            channel=channel,
            players_current=players_current,
            players_global=players_global,
            round_count=self.format_points(round_count),
            leader=leader_text,
            jackpot=self.format_points(int(jackpot_state.get("jackpot_points", 0))),
            last_jackpot=last_jackpot,
        )

    def get_my_dart_stats_text(self, nick: str) -> str:
        if pymysql is None:
            return self.tr("dart_stats_missing_pkg")

        conn = self.open_db_connection()
        if conn is None:
            return self.tr("dart_stats_unavailable")

        try:
            with conn.cursor() as cur:
                cur.execute("SELECT points, `throws` FROM bot_dart WHERE nick = %s LIMIT 1", (nick,))
                row = cur.fetchone()
                if not row:
                    return self.tr("dart_stats_empty")

                points = int(row.get("points", 0))
                throws = int(row.get("throws", 0))

                cur.execute("SELECT COUNT(*) AS total_players FROM bot_dart")
                total_row = cur.fetchone() or {}
                total_players = int(total_row.get("total_players", 0))

                cur.execute(
                    """
                    SELECT COUNT(*) + 1 AS rank_pos
                    FROM bot_dart
                    WHERE points > %s OR (points = %s AND `throws` > %s)
                    """,
                    (points, points, throws),
                )
                rank_row = cur.fetchone() or {}
                rank = int(rank_row.get("rank_pos", 1))
        except Exception:
            return self.tr("dart_stats_unavailable")
        finally:
            conn.close()

        average = points / throws if throws else 0.0
        return self.tr(
            "dart_stats",
            points=self.format_points(points),
            throws=self.format_points(throws),
            average=self.format_average(average),
            rank=rank,
            total=total_players,
        )

    def get_dart_top10_text(self) -> str:
        if pymysql is None:
            return self.tr("dart_db_missing_pkg")

        def open_connection(password_value: str | bytes) -> "pymysql.connections.Connection":
            return pymysql.connect(
                host=self.config.mysql_host,
                port=self.config.mysql_port,
                user=self.config.mysql_user,
                password=password_value,
                database=self.config.mysql_database,
                charset="utf8mb4",
                autocommit=True,
                connect_timeout=5,
                cursorclass=pymysql.cursors.DictCursor,
            )

        try:
            conn = open_connection(self.config.mysql_password)
        except UnicodeEncodeError:
            try:
                conn = open_connection(self.config.mysql_password.encode("utf-8"))
            except Exception as exc:
                return self.tr("dart_db_unreachable", error=exc)
        except Exception as exc:
            return self.tr("dart_db_unreachable", error=exc)

        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT nick, points, `throws` FROM bot_dart ORDER BY points DESC, `throws` DESC, nick ASC LIMIT 10"
                )
                rows = cur.fetchall()
        except Exception as exc:
            return self.tr("dart_top_failed", error=exc)
        finally:
            conn.close()

        if not rows:
            return self.tr("dart_no_data")

        leaderboard = []
        for index, row in enumerate(rows, start=1):
            nick = str(row.get("nick", "?"))
            points = int(row.get("points", 0))
            throw_count = int(row.get("throws", 0))
            leaderboard.append(
                self.tr(
                    "dart_top_entry",
                    index=index,
                    nick=nick,
                    points=self.format_points(points),
                    throws=self.format_points(throw_count),
                )
            )

        return self.tr("dart_top", items=" | ".join(leaderboard))

    def sniff_urls_in_message(self, message: str, channel: str, source_nick: str) -> None:
        seen_in_message: set[str] = set()
        for raw_url in URL_PATTERN.findall(message):
            normalized_url = self.normalize_url(raw_url)
            if not normalized_url or normalized_url in seen_in_message:
                continue

            seen_in_message.add(normalized_url)
            record = self.fetch_url_by_value(normalized_url)
            if record and self.is_flagged(record):
                continue
            if record:
                cached_result = self.build_cached_url_result(record)
                if cached_result:
                    self.handle_url_result(cached_result, channel, requested_by=source_nick, show_max_id=True)
                    continue

            if self.is_spammy(normalized_url):
                self.block_url(normalized_url)
                continue

            topic_result = self.describe_url(normalized_url)
            if topic_result.get("status") == "ok":
                stored_url_id = self.store_url_if_missing(
                    normalized_url,
                    source_nick,
                    topic=str(topic_result.get("topic", "")) or None,
                    title_missing=bool(topic_result.get("title_missing", False)),
                )
                if stored_url_id is not None:
                    topic_result["id"] = stored_url_id
            self.handle_url_result(topic_result, channel, requested_by=source_nick, show_max_id=True)

    def handle_url_result(
        self,
        result: dict[str, str | int | bool | None] | None,
        reply_target: str,
        requested_by: str,
        show_max_id: bool = False,
    ) -> None:
        max_id = self.safe_int(result.get("max_id")) if (result and show_max_id) else None
        if show_max_id and max_id is None:
            max_id = self.get_max_url_id()
        max_id_suffix = f" | {self.tr('url_max_id', max_id=max_id)}" if max_id is not None else ""

        if not result:
            self.send_privmsg(reply_target, f"{self.tr('url_not_found')}{max_id_suffix}")
            return

        status = str(result.get("status", ""))
        if status == "discarded":
            return
        if status == "blocked":
            self.send_privmsg(reply_target, f"{self.tr('url_blocked')}{max_id_suffix}")
            return
        if status == "deadlink":
            http_status = self.safe_int(result.get("http_status"))
            status_suffix = f" (HTTP {http_status})" if http_status is not None else ""
            self.send_privmsg(reply_target, f"{self.tr('url_dead')}{status_suffix}{max_id_suffix}")
            return
        if status == "too_large":
            self.send_privmsg(reply_target, f"{self.tr('url_too_large')}{max_id_suffix}")
            return
        if status == "error":
            self.send_privmsg(reply_target, f"{self.tr('url_error', message=result.get('message', self.tr('unknown')))}{max_id_suffix}")
            return

        url_id = self.safe_int(result.get("id"))
        id_prefix = f"[#{url_id}] " if url_id is not None else ""

        if str(result.get("kind", "")) == "youtube":
            title = str(result.get("topic", ""))
            channel_title = str(result.get("channel_title", ""))
            duration_text = str(result.get("duration_text", ""))
            published_text = str(result.get("published_text", ""))
            view_count = result.get("view_count")
            like_count = result.get("like_count")
            comment_count = result.get("comment_count")

            if self.allows_control_codes(reply_target):
                self.send_privmsg(
                    reply_target,
                    f"{id_prefix}" + self.format_youtube_with_control_codes(
                        title=title,
                        channel_title=channel_title,
                        duration_text=duration_text,
                        published_text=published_text,
                        view_count=view_count,
                        like_count=like_count,
                        comment_count=comment_count,
                        requested_by=requested_by,
                    ) + max_id_suffix,
                )
                return

            parts = []
            if channel_title:
                parts.append(self.tr("yt_channel", channel=channel_title))
            if duration_text:
                parts.append(self.tr("yt_duration", duration=duration_text))
            if published_text:
                parts.append(self.tr("yt_published", published=published_text))
            if view_count is not None:
                parts.append(self.tr("yt_views", count=view_count))
            if like_count is not None:
                parts.append(self.tr("yt_likes", count=like_count))
            if comment_count is not None:
                parts.append(self.tr("yt_comments", count=comment_count))

            suffix = f" ({' | '.join(parts)})" if parts else ""
            self.send_privmsg(reply_target, f"{id_prefix}YouTube :: {title}{suffix} (Requested by {requested_by}){max_id_suffix}")
            return

        url = str(result.get("url", ""))
        topic = str(result.get("topic", ""))
        title_missing = bool(result.get("title_missing", False))
        if not url:
            self.send_privmsg(reply_target, self.tr("url_not_found"))
            return

        if not topic:
            self.send_privmsg(reply_target, f"{id_prefix}{self.tr('url_no_html_topic', url=url)}{max_id_suffix}")
            return
        if title_missing:
            self.send_privmsg(reply_target, f"{id_prefix}{self.tr('url_without_title', url=url, topic=topic, requested_by=requested_by)}{max_id_suffix}")
            return

        is_dangerous = bool(result.get("is_dangerous", False)) or topic in DANGEROUS_CONTENT_TYPES
        if is_dangerous:
            if self.allows_control_codes(reply_target):
                bold = "\x02"
                red = "\x0304"
                reset_code = "\x0f"
                warn_label = f"{bold}{red}{self.tr('url_dangerous_file')}{reset_code}"
            else:
                warn_label = self.tr("url_dangerous_file")
            self.send_privmsg(reply_target, f"{id_prefix}{url} :: {warn_label}: {topic} (Requested by {requested_by}){max_id_suffix}")
            return

        self.send_privmsg(reply_target, f"{id_prefix}{url} :: {topic} (Requested by {requested_by}){max_id_suffix}")

    def fetch_url_by_id(self, url_id: int) -> dict[str, str | int | bool | None] | None:
        if pymysql is None:
            return {"status": "error", "message": "pymysql missing." if self.config.language == "en" else "Python-Paket 'pymysql' fehlt."}

        conn = self.open_db_connection()
        if conn is None:
            return {"status": "error", "message": "Database unavailable." if self.config.language == "en" else "Datenbank nicht erreichbar."}

        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, url, posted_by, time, is_blocked, is_deadlink, topic, title_missing FROM bot_url WHERE id = %s LIMIT 1",
                    (url_id,),
                )
                row = cur.fetchone()
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        finally:
            conn.close()

        if not row:
            return None

        if int(row.get("is_blocked", 0)):
            return {"status": "blocked", "url": str(row.get("url", ""))}
        if int(row.get("is_deadlink", 0)):
            return {"status": "deadlink", "url": str(row.get("url", ""))}

        cached_result = self.build_cached_url_result(row)
        if cached_result:
            cached_result["max_id"] = self.get_max_url_id()
            return cached_result

        topic_result = self.describe_url(str(row.get("url", "")))
        if topic_result and topic_result.get("status") == "ok":
            topic_result["id"] = int(row.get("id", url_id))
            topic_result["max_id"] = self.get_max_url_id()
            self.store_url_if_missing(
                str(row.get("url", "")),
                str(row.get("posted_by", "")),
                topic=str(topic_result.get("topic", "")) or None,
                title_missing=bool(topic_result.get("title_missing", False)),
            )
            return topic_result
        if topic_result and topic_result.get("status") == "blocked":
            return topic_result
        if topic_result and topic_result.get("status") == "deadlink":
            return topic_result
        return {"status": "error", "message": "URL could not be read." if self.config.language == "en" else "URL konnte nicht gelesen werden."}

    def fetch_random_url(self) -> dict[str, str | int | bool | None] | None:
        if pymysql is None:
            return {"status": "error", "message": "pymysql missing." if self.config.language == "en" else "Python-Paket 'pymysql' fehlt."}

        conn = self.open_db_connection()
        if conn is None:
            return {"status": "error", "message": "Database unavailable." if self.config.language == "en" else "Datenbank nicht erreichbar."}

        try:
            with conn.cursor() as cur:
                for _ in range(10):
                    cur.execute(
                        "SELECT id, url, posted_by, time, is_blocked, is_deadlink, topic, title_missing FROM bot_url WHERE is_blocked = 0 AND is_deadlink = 0 ORDER BY RAND() LIMIT 1"
                    )
                    row = cur.fetchone()
                    if not row:
                        return None

                    cached_result = self.build_cached_url_result(row)
                    if cached_result:
                        cached_result["max_id"] = self.get_max_url_id()
                        return cached_result

                    topic_result = self.describe_url(str(row.get("url", "")))
                    if topic_result.get("status") == "ok":
                        topic_result["id"] = int(row.get("id", 0))
                        topic_result["max_id"] = self.get_max_url_id()
                        self.store_url_if_missing(
                            str(row.get("url", "")),
                            str(row.get("posted_by", "")),
                            topic=str(topic_result.get("topic", "")) or None,
                            title_missing=bool(topic_result.get("title_missing", False)),
                        )
                        return topic_result
                    if topic_result.get("status") == "error":
                        return topic_result
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        finally:
            conn.close()

        return None

    def fetch_url_by_value(self, url: str) -> dict[str, str | int | bool | None] | None:
        if pymysql is None:
            return None

        conn = self.open_db_connection()
        if conn is None:
            return None

        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, url, posted_by, time, is_blocked, is_deadlink, topic, title_missing FROM bot_url WHERE url = %s ORDER BY id DESC LIMIT 1",
                    (url,),
                )
                row = cur.fetchone()
        except Exception:
            return None
        finally:
            conn.close()

        if not row:
            return None

        return row

    def build_cached_url_result(self, row: dict[str, str | int | bool | None]) -> dict[str, str | int | bool | None] | None:
        url = str(row.get("url", ""))
        if self.is_youtube_url(url):
            return None

        topic_value = row.get("topic")
        topic = str(topic_value).strip() if topic_value is not None else ""
        if not topic:
            return None

        return {
            "status": "ok",
            "id": self.safe_int(row.get("id")),
            "url": url,
            "topic": topic,
            "title_missing": bool(int(row.get("title_missing", 0) or 0)),
        }

    def fetch_url_topic(self, url: str) -> dict[str, str | int | bool | None]:
        if self.is_spammy(url):
            self.block_url(url)
            return {"status": "blocked", "url": url}

        try:
            head_request = Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 IRCBot"},
                method="HEAD",
            )
            head_content_type: str | None = None
            try:
                with urlopen(head_request, timeout=self.config.url_timeout_seconds) as response:
                    head_status = getattr(response, "status", None)
                    head_content_type = response.headers.get_content_type()
            except HTTPError as exc:
                head_status = exc.code

            if head_status is not None and head_status not in {405, 501} and not 200 <= head_status < 300:
                self.mark_deadlink(url)
                return {"status": "deadlink", "url": url, "http_status": head_status}

            if head_status not in {405, 501} and head_content_type is not None and head_content_type not in {"text/html", "application/xhtml+xml"}:
                is_dangerous = head_content_type in DANGEROUS_CONTENT_TYPES
                return {
                    "status": "ok",
                    "url": url,
                    "topic": head_content_type,
                    "title_missing": False,
                    "content_type": head_content_type,
                    "is_dangerous": is_dangerous,
                    "http_status": head_status,
                }

            max_sniff_bytes = self.config.url_sniff_max_bytes
            request = Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 IRCBot",
                    "Range": f"bytes=0-{max_sniff_bytes - 1}",
                },
            )
            with urlopen(request, timeout=self.config.url_timeout_seconds) as response:
                response_headers = response.headers
                content_length = self.safe_int(response_headers.get("Content-Length"))
                if content_length is not None and content_length > self.config.url_max_content_length_bytes:
                    return {"status": "too_large", "url": url, "http_status": getattr(response, "status", None)}

                raw_bytes = response.read(max_sniff_bytes + 1)
                if len(raw_bytes) > max_sniff_bytes:
                    return {"status": "too_large", "url": url}

                encoding = response_headers.get_content_charset() or "utf-8"
                html_text = raw_bytes.decode(encoding, errors="replace")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            if self._is_timeout_error(exc):
                return {"status": "discarded", "url": url}
            self.mark_deadlink(url)
            return {"status": "deadlink", "url": url}

        topic, title_missing = self.extract_html_topic(html_text)
        if not topic:
            self.mark_deadlink(url)
            return {"status": "deadlink", "url": url}

        if self.is_spammy(topic):
            self.block_url(url)
            return {"status": "blocked", "url": url}

        return {"status": "ok", "url": url, "topic": topic, "title_missing": title_missing}

    def store_url_if_missing(self, url: str, posted_by: str, topic: str | None = None, title_missing: bool = False) -> int | None:
        conn = self.open_db_connection()
        if conn is None:
            return None

        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM bot_url WHERE url = %s LIMIT 1", (url,))
                existing_row = cur.fetchone()
                if existing_row:
                    if topic:
                        cur.execute(
                            "UPDATE bot_url SET topic = %s, title_missing = %s WHERE url = %s",
                            (topic[:180], 1 if title_missing else 0, url),
                        )
                    return self.safe_int(existing_row.get("id"))

                cur.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM bot_url")
                next_row = cur.fetchone() or {}
                next_id = int(next_row.get("next_id", 1))

                cur.execute(
                    "INSERT INTO bot_url (id, url, posted_by, time, is_blocked, is_deadlink, topic, title_missing) VALUES (%s, %s, %s, %s, 0, 0, %s, %s)",
                    (next_id, url, posted_by, self.current_time_string(), (topic[:180] if topic else None), 1 if title_missing else 0),
                )
                return next_id
        except Exception:
            return None
        finally:
            conn.close()

        return None

    def get_max_url_id(self) -> int | None:
        conn = self.open_db_connection()
        if conn is None:
            return None

        try:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(id) AS max_id FROM bot_url")
                row = cur.fetchone() or {}
                return self.safe_int(row.get("max_id"))
        except Exception:
            return None
        finally:
            conn.close()

    def extract_html_topic(self, html_text: str) -> tuple[str, bool]:
        parser = TopicParser()
        parser.feed(html_text)
        parser.close()
        topic = parser.topic or parser.title
        topic = unescape(topic).strip()
        topic = re.sub(r"\s+", " ", topic)
        title_missing = not bool(parser.title)
        return topic[:180], title_missing

    def is_spammy(self, text: str) -> bool:
        lowered = text.lower()
        if any(host in lowered for host in SPAM_HOSTS):
            return True
        return any(word in lowered for word in SPAM_WORDS)

    def is_flagged(self, row: dict[str, str | int | bool | None]) -> bool:
        return bool(int(row.get("is_blocked", 0))) or bool(int(row.get("is_deadlink", 0)))

    def normalize_url(self, url: str) -> str:
        return url.rstrip(".,;:!?)\"]}")

    def parse_int(self, value: str) -> int | None:
        try:
            return int(value)
        except ValueError:
            return None

    def open_db_connection(self):
        if pymysql is None:
            return None

        def connect_with_password(password_value: str | bytes):
            return pymysql.connect(
                host=self.config.mysql_host,
                port=self.config.mysql_port,
                user=self.config.mysql_user,
                password=password_value,
                database=self.config.mysql_database,
                charset="utf8mb4",
                autocommit=True,
                connect_timeout=5,
                cursorclass=pymysql.cursors.DictCursor,
            )

        try:
            return connect_with_password(self.config.mysql_password)
        except UnicodeEncodeError:
            try:
                return connect_with_password(self.config.mysql_password.encode("utf-8"))
            except Exception:
                return None
        except Exception:
            return None

    def open_server_connection(self):
        if pymysql is None:
            return None

        def connect_with_password(password_value: str | bytes):
            return pymysql.connect(
                host=self.config.mysql_host,
                port=self.config.mysql_port,
                user=self.config.mysql_user,
                password=password_value,
                charset="utf8mb4",
                autocommit=True,
                connect_timeout=5,
                cursorclass=pymysql.cursors.DictCursor,
            )

        try:
            return connect_with_password(self.config.mysql_password)
        except UnicodeEncodeError:
            try:
                return connect_with_password(self.config.mysql_password.encode("utf-8"))
            except Exception:
                return None
        except Exception:
            return None

    def ensure_database_setup(self) -> None:
        if self.db_initialized or pymysql is None:
            return

        server_conn = self.open_server_connection()
        if server_conn is None:
            print(self.tr("db_setup_skip"))
            return

        try:
            with server_conn.cursor() as cur:
                # Database name is not directly parameterizable in MySQL.
                # Only accept alphanumeric and underscore to prevent injection.
                db_name = self.config.mysql_database
                if not db_name or not all(c.isalnum() or c == '_' for c in db_name):
                    raise ValueError(f"Invalid database name: {db_name}")
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
        except Exception as exc:
            print(self.tr("db_create_failed", error=exc))
            return
        finally:
            server_conn.close()

        conn = self.open_db_connection()
        if conn is None:
            print(self.tr("db_connect_failed"))
            return

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_dart (
                        nick VARCHAR(64) NOT NULL,
                        points INT NOT NULL DEFAULT 0,
                        `throws` INT NOT NULL DEFAULT 0,
                        PRIMARY KEY (nick)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_url (
                        id INT NOT NULL,
                        url VARCHAR(2048) NOT NULL,
                        posted_by VARCHAR(64) NOT NULL DEFAULT '',
                        time VARCHAR(32) NOT NULL DEFAULT '',
                        is_blocked TINYINT(1) NOT NULL DEFAULT 0,
                        is_deadlink TINYINT(1) NOT NULL DEFAULT 0,
                        topic VARCHAR(180) NULL,
                        title_missing TINYINT(1) NOT NULL DEFAULT 0,
                        PRIMARY KEY (id),
                        KEY idx_bot_url_flags (is_blocked, is_deadlink)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                self.ensure_bot_url_schema(cur)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_channels (
                        network VARCHAR(255) NOT NULL,
                        channel VARCHAR(128) NOT NULL,
                        joined_at VARCHAR(32) NOT NULL,
                        PRIMARY KEY (network, channel)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_mondgesicht_channels (
                        network VARCHAR(255) NOT NULL,
                        channel VARCHAR(128) NOT NULL,
                        created_at VARCHAR(32) NOT NULL,
                        PRIMARY KEY (network, channel)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_mondgesicht_channel_access (
                        network VARCHAR(255) NOT NULL,
                        channel VARCHAR(128) NOT NULL,
                        access_type VARCHAR(16) NOT NULL,
                        nick VARCHAR(64) NOT NULL,
                        created_at VARCHAR(32) NOT NULL,
                        created_by VARCHAR(255) NOT NULL DEFAULT '',
                        PRIMARY KEY (network, channel, access_type, nick),
                        KEY idx_bot_mondgesicht_channel_access_lookup (network, channel, access_type)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_admin_roles (
                        network VARCHAR(255) NOT NULL,
                        role_name VARCHAR(64) NOT NULL,
                        is_admin TINYINT(1) NOT NULL DEFAULT 0,
                        can_raw TINYINT(1) NOT NULL DEFAULT 0,
                        created_at VARCHAR(32) NOT NULL,
                        PRIMARY KEY (network, role_name)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_admin_users (
                        network VARCHAR(255) NOT NULL,
                        user_mask VARCHAR(255) NOT NULL,
                        display_name VARCHAR(64) NOT NULL DEFAULT '',
                        password_salt VARCHAR(64) NOT NULL,
                        password_hash VARCHAR(128) NOT NULL,
                        role_name VARCHAR(64) NOT NULL,
                        created_at VARCHAR(32) NOT NULL,
                        created_by VARCHAR(64) NOT NULL DEFAULT '',
                        PRIMARY KEY (network, user_mask),
                        KEY idx_bot_admin_users_role (network, role_name)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_admin_role_modes (
                        network VARCHAR(255) NOT NULL,
                        role_name VARCHAR(64) NOT NULL,
                        channel VARCHAR(128) NOT NULL,
                        mode CHAR(1) NOT NULL,
                        created_at VARCHAR(32) NOT NULL,
                        PRIMARY KEY (network, role_name, channel, mode)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_admin_user_modes (
                        network VARCHAR(255) NOT NULL,
                        user_mask VARCHAR(255) NOT NULL,
                        channel VARCHAR(128) NOT NULL,
                        mode CHAR(1) NOT NULL,
                        created_at VARCHAR(32) NOT NULL,
                        PRIMARY KEY (network, user_mask, channel, mode)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_mondgesicht_scores (
                        network VARCHAR(255) NOT NULL,
                        channel VARCHAR(128) NOT NULL,
                        nick VARCHAR(64) NOT NULL,
                        points INT NOT NULL DEFAULT 0,
                        updated_at VARCHAR(32) NOT NULL,
                        PRIMARY KEY (network, channel, nick),
                        KEY idx_bot_mondgesicht_scores_rank (network, channel, points)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_mondgesicht_jackpot (
                        network VARCHAR(255) NOT NULL,
                        channel VARCHAR(128) NOT NULL,
                        jackpot_points INT NOT NULL DEFAULT 0,
                        last_awarded_points INT NOT NULL DEFAULT 0,
                        last_awarded_to VARCHAR(255) NOT NULL DEFAULT '',
                        updated_at VARCHAR(32) NOT NULL,
                        PRIMARY KEY (network, channel)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_mondgesicht_round_awards (
                        id BIGINT NOT NULL AUTO_INCREMENT,
                        network VARCHAR(255) NOT NULL,
                        channel VARCHAR(128) NOT NULL,
                        nick VARCHAR(64) NOT NULL,
                        round_token VARCHAR(64) NOT NULL DEFAULT '',
                        points_awarded INT NOT NULL,
                        created_at VARCHAR(32) NOT NULL,
                        PRIMARY KEY (id),
                        KEY idx_bot_mondgesicht_round_awards_lookup (network, channel, nick, created_at),
                        KEY idx_bot_mondgesicht_round_awards_token (network, channel, round_token)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                self.ensure_mondgesicht_round_awards_schema(cur)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_mondgesicht_adds (
                        id BIGINT NOT NULL AUTO_INCREMENT,
                        network VARCHAR(255) NOT NULL,
                        channel VARCHAR(128) NOT NULL,
                        nick VARCHAR(64) NOT NULL,
                        category VARCHAR(32) NOT NULL,
                        entry_text TEXT NOT NULL,
                        created_at VARCHAR(32) NOT NULL,
                        PRIMARY KEY (id),
                        KEY idx_bot_mondgesicht_adds_lookup (network, channel, category, created_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_mondgesicht_texts (
                        id BIGINT NOT NULL AUTO_INCREMENT,
                        network VARCHAR(255) NOT NULL,
                        language VARCHAR(8) NOT NULL,
                        category VARCHAR(32) NOT NULL,
                        entry_text TEXT NOT NULL,
                        created_at VARCHAR(32) NOT NULL,
                        created_by VARCHAR(255) NOT NULL DEFAULT '',
                        PRIMARY KEY (id),
                        KEY idx_bot_mondgesicht_texts_lookup (network, language, category, id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                self.ensure_mondgesicht_text_storage_utf8mb4(cur)
                seeded, seeded_count = self.seed_default_mondgesicht_texts("system", replace_existing=False)
                if not seeded:
                    print(f"Mondgesicht seed skipped for {self.config.network_key}.")
                elif seeded_count > 0:
                    print(f"Seeded {seeded_count} Mondgesicht texts for {self.config.network_key}.")
            self.db_initialized = True
        except Exception as exc:
            print(self.tr("db_table_setup_failed", error=exc))
        finally:
            conn.close()

    def ensure_bot_url_schema(self, cur) -> None:
        cur.execute(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'bot_url'
            """,
            (self.config.mysql_database,),
        )
        existing_columns = {str(row.get("COLUMN_NAME", "")) for row in (cur.fetchall() or [])}

        if "topic" not in existing_columns:
            cur.execute("ALTER TABLE bot_url ADD COLUMN topic VARCHAR(180) NULL")
        if "title_missing" not in existing_columns:
            cur.execute("ALTER TABLE bot_url ADD COLUMN title_missing TINYINT(1) NOT NULL DEFAULT 0")

    def load_saved_channels(self) -> list[str]:
        conn = self.open_db_connection()
        if conn is None:
            return []

        try:
            with conn.cursor() as cur:
                cur.execute("SELECT channel FROM bot_channels WHERE network = %s ORDER BY channel ASC", (self.config.network_key,))
                rows = cur.fetchall() or []
            return [str(row.get("channel", "")).strip() for row in rows if str(row.get("channel", "")).strip()]
        except Exception:
            return []
        finally:
            conn.close()

    def store_channel_if_missing(self, channel: str) -> None:
        conn = self.open_db_connection()
        if conn is None:
            return

        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT IGNORE INTO bot_channels (network, channel, joined_at) VALUES (%s, %s, %s)",
                    (self.config.network_key, channel, self.current_time_string()),
                )
        except Exception:
            pass
        finally:
            conn.close()

    def delete_saved_channel(self, channel: str) -> None:
        conn = self.open_db_connection()
        if conn is None:
            return

        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM bot_channels WHERE network = %s AND channel = %s", (self.config.network_key, channel))
        except Exception:
            pass
        finally:
            conn.close()

    def load_saved_mondgesicht_channels(self) -> list[str]:
        conn = self.open_db_connection()
        if conn is None:
            return []

        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT channel FROM bot_mondgesicht_channels WHERE network = %s ORDER BY channel ASC",
                    (self.config.network_key,),
                )
                rows = cur.fetchall() or []
            return [str(row.get("channel", "")).strip() for row in rows if str(row.get("channel", "")).strip()]
        except Exception:
            return []
        finally:
            conn.close()

    def ensure_mondgesicht_text_storage_utf8mb4(self, cur) -> None:
        db_name = self.config.mysql_database.replace("`", "``")
        cur.execute(f"ALTER DATABASE `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cur.execute("ALTER TABLE bot_mondgesicht_jackpot CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cur.execute("ALTER TABLE bot_mondgesicht_round_awards CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cur.execute("ALTER TABLE bot_mondgesicht_adds CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cur.execute("ALTER TABLE bot_mondgesicht_texts CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")

    def ensure_mondgesicht_round_awards_schema(self, cur) -> None:
        try:
            cur.execute("ALTER TABLE bot_mondgesicht_round_awards ADD COLUMN round_token VARCHAR(64) NOT NULL DEFAULT '' AFTER nick")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE bot_mondgesicht_round_awards ADD KEY idx_bot_mondgesicht_round_awards_token (network, channel, round_token)")
        except Exception:
            pass

    @staticmethod
    def hash_admin_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
        salt = os.urandom(16).hex() if salt_hex is None else salt_hex
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            200000,
        ).hex()
        return salt, derived

    def verify_admin_password(self, password: str, salt_hex: str, expected_hash: str) -> bool:
        _, derived = self.hash_admin_password(password, salt_hex)
        return hmac.compare_digest(derived, expected_hash)

    def has_admin_users(self) -> bool:
        conn = self.open_db_connection()
        if conn is None:
            return False

        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM bot_admin_users WHERE network = %s LIMIT 1",
                    (self.config.network_key,),
                )
                return cur.fetchone() is not None
        except Exception:
            return False
        finally:
            conn.close()

    def ensure_admin_bootstrap(self, interactive: bool) -> None:
        if not self.db_initialized or self.has_admin_users():
            return

        if not interactive:
            if not self._admin_bootstrap_warned:
                print(self.tr("admin_bootstrap_missing", network=self.config.network_key))
                self._admin_bootstrap_warned = True
            return

        print(self.tr("admin_bootstrap_prompt", network=self.config.network_key))

        admin_mask = ""
        while not admin_mask:
            entered_mask = input("Admin ident@host: ").strip()
            normalized_mask = self.normalize_user_mask(entered_mask)
            if normalized_mask is None:
                print("Ungültige Hostmask. Erwartet wird ident@host.")
                continue
            admin_mask = normalized_mask

        password = ""
        while not password:
            first = getpass.getpass("Admin Passwort: ")
            second = getpass.getpass("Passwort wiederholen: ")
            if not first:
                print("Passwort darf nicht leer sein.")
                continue
            if first != second:
                print("Passwörter stimmen nicht überein.")
                continue
            password = first

        self.ensure_default_admin_role()

        created_user, user_message = self.create_admin_user(
            display_name="bootstrap",
            user_mask=admin_mask,
            password=password,
            role_name="admin",
            created_by="bootstrap",
        )
        if not created_user:
            print(user_message)
            print(self.tr("admin_bootstrap_skipped"))
            return

        print(self.tr("admin_bootstrap_created", mask=admin_mask, network=self.config.network_key))

    def ensure_default_admin_role(self) -> None:
        conn = self.open_db_connection()
        if conn is None:
            return

        try:
            with conn.cursor() as cur:
                cur.execute(ROLE_EXISTS_QUERY, (self.config.network_key, "admin"))
                if cur.fetchone() is not None:
                    cur.execute(
                        "UPDATE bot_admin_roles SET is_admin = 1, can_raw = 1 WHERE network = %s AND role_name = %s",
                        (self.config.network_key, "admin"),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO bot_admin_roles (network, role_name, is_admin, can_raw, created_at)
                        VALUES (%s, %s, 1, 1, %s)
                        """,
                        (self.config.network_key, "admin", self.current_time_string()),
                    )

                cur.execute(ROLE_EXISTS_QUERY, (self.config.network_key, "user"))
                if cur.fetchone() is None:
                    cur.execute(
                        """
                        INSERT INTO bot_admin_roles (network, role_name, is_admin, can_raw, created_at)
                        VALUES (%s, %s, 0, 0, %s)
                        """,
                        (self.config.network_key, "user", self.current_time_string()),
                    )
        except Exception:
            pass
        finally:
            conn.close()

    def load_admin_user(self, user_mask: str) -> dict[str, object] | None:
        normalized_mask = self.normalize_user_mask(user_mask)
        if normalized_mask is None:
            return None

        conn = self.open_db_connection()
        if conn is None:
            return None

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT u.user_mask, u.display_name, u.password_salt, u.password_hash, u.role_name,
                           COALESCE(r.is_admin, 0) AS is_admin,
                           COALESCE(r.can_raw, 0) AS can_raw
                    FROM bot_admin_users u
                    LEFT JOIN bot_admin_roles r
                      ON r.network = u.network AND r.role_name = u.role_name
                    WHERE u.network = %s AND u.user_mask = %s
                    LIMIT 1
                    """,
                    (self.config.network_key, normalized_mask),
                )
                row = cur.fetchone()
                return row if row else None
        except Exception:
            return None
        finally:
            conn.close()

    def get_authenticated_admin(self, user_mask: str, require_admin: bool = False, require_raw: bool = False) -> dict[str, object] | None:
        normalized_mask = self.normalize_user_mask(user_mask)
        if normalized_mask is None:
            return None

        session = self._admin_sessions.get(normalized_mask)
        if session is None:
            return None

        expires_at = float(session.get("expires_at", 0.0))
        if expires_at < time.time():
            self.end_admin_session(normalized_mask, revoke_modes=True)
            return None

        row = self.load_admin_user(normalized_mask)
        if row is None:
            self.end_admin_session(normalized_mask, revoke_modes=True)
            return None

        if require_admin and not bool(int(row.get("is_admin", 0))):
            return None
        if require_raw and not bool(int(row.get("can_raw", 0))):
            return None

        session["expires_at"] = time.time() + ADMIN_SESSION_TTL_SECONDS
        return row

    def login_admin_user(self, user_mask: str, password: str, nick: str = "") -> tuple[bool, str]:
        row = self.load_admin_user(user_mask)
        if row is None:
            return False, "Unbekannte Hostmask."

        salt = str(row.get("password_salt", ""))
        expected_hash = str(row.get("password_hash", ""))
        if not salt or not expected_hash or not self.verify_admin_password(password, salt, expected_hash):
            return False, "Passwort falsch."

        normalized_mask = self.normalize_user_mask(user_mask)
        if normalized_mask is None:
            return False, INVALID_HOSTMASK_MESSAGE

        self._admin_sessions[normalized_mask] = {
            "expires_at": time.time() + ADMIN_SESSION_TTL_SECONDS,
            "nick": nick.strip(),
        }
        applied_count = self.apply_login_modes_for_user(normalized_mask, nick.strip())
        suffix = f" Höchste Channel-Rechte gesetzt: {applied_count}." if applied_count > 0 else ""
        return True, f"Login erfolgreich für {normalized_mask}.{suffix}"

    def logout_admin_user(self, user_mask: str) -> bool:
        normalized_mask = self.normalize_user_mask(user_mask)
        if normalized_mask is None:
            return False
        return self.end_admin_session(normalized_mask, revoke_modes=True)

    def end_admin_session(self, user_mask: str, revoke_modes: bool) -> bool:
        normalized_mask = self.normalize_user_mask(user_mask)
        if normalized_mask is None:
            return False

        session = self._admin_sessions.pop(normalized_mask, None)
        if session is None:
            return False

        if revoke_modes:
            nick = str(session.get("nick", "")).strip()
            self.revoke_login_modes_for_user(normalized_mask, nick)
        return True

    def update_admin_session_nick(self, previous_nick: str, new_nick: str) -> None:
        old = previous_nick.strip().lower()
        if not old or not new_nick:
            return

        for session in self._admin_sessions.values():
            nick = str(session.get("nick", "")).strip()
            if nick.lower() == old:
                session["nick"] = new_nick

    def create_admin_role(self, role_name: str, is_admin: bool = False, can_raw: bool = False) -> tuple[bool, str]:
        normalized_role = self.normalize_role_name(role_name)
        if normalized_role is None:
            return False, "Ungültiger Rollenname. Erlaubt sind a-z, 0-9, _ und - ."

        conn = self.open_db_connection()
        if conn is None:
            return False, self.tr("db_connect_failed")

        try:
            with conn.cursor() as cur:
                cur.execute(
                    ROLE_EXISTS_QUERY,
                    (self.config.network_key, normalized_role),
                )
                if cur.fetchone() is not None:
                    return False, f"Rolle {normalized_role} existiert bereits."

                cur.execute(
                    """
                    INSERT INTO bot_admin_roles (network, role_name, is_admin, can_raw, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (self.config.network_key, normalized_role, 1 if is_admin else 0, 1 if can_raw else 0, self.current_time_string()),
                )
            return True, f"Rolle {normalized_role} angelegt."
        except Exception as exc:
            return False, f"Rolle konnte nicht angelegt werden: {exc}"
        finally:
            conn.close()

    def set_role_flag(self, role_name: str, flag_name: str, enabled: bool) -> tuple[bool, str]:
        normalized_role = self.normalize_role_name(role_name)
        column = ROLE_FLAG_COLUMNS.get(flag_name.strip().lower())
        if normalized_role is None or column is None:
            return False, "Ungültige Rolle oder Flag. Erlaubte Flags: admin, raw."

        conn = self.open_db_connection()
        if conn is None:
            return False, self.tr("db_connect_failed")

        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE bot_admin_roles SET {column} = %s WHERE network = %s AND role_name = %s",
                    (1 if enabled else 0, self.config.network_key, normalized_role),
                )
                if cur.rowcount == 0:
                    return False, f"Rolle {normalized_role} existiert nicht."
            return True, f"Flag {flag_name.lower()} fuer Rolle {normalized_role} ist jetzt {'an' if enabled else 'aus'}."
        except Exception as exc:
            return False, f"Rollenflag konnte nicht gesetzt werden: {exc}"
        finally:
            conn.close()

    def list_admin_roles(self) -> list[dict[str, object]]:
        conn = self.open_db_connection()
        if conn is None:
            return []

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT role_name, is_admin, can_raw
                    FROM bot_admin_roles
                    WHERE network = %s
                    ORDER BY role_name ASC
                    """,
                    (self.config.network_key,),
                )
                return list(cur.fetchall() or [])
        except Exception:
            return []
        finally:
            conn.close()

    def create_admin_user(self, display_name: str, user_mask: str, password: str, role_name: str, created_by: str) -> tuple[bool, str]:
        normalized_mask = self.normalize_user_mask(user_mask)
        normalized_role = self.normalize_role_name(role_name)
        label = display_name.strip()[:64]

        if normalized_mask is None:
            return False, "Ungültige Hostmask. Erwartet wird ident@host."
        if normalized_role is None:
            return False, "Ungültiger Rollenname."
        if not password:
            return False, "Passwort darf nicht leer sein."

        conn = self.open_db_connection()
        if conn is None:
            return False, self.tr("db_connect_failed")

        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM bot_admin_roles WHERE network = %s AND role_name = %s LIMIT 1",
                    (self.config.network_key, normalized_role),
                )
                if cur.fetchone() is None:
                    return False, f"Rolle {normalized_role} existiert nicht."

                cur.execute(
                    "SELECT 1 FROM bot_admin_users WHERE network = %s AND user_mask = %s LIMIT 1",
                    (self.config.network_key, normalized_mask),
                )
                if cur.fetchone() is not None:
                    return False, f"Benutzer {normalized_mask} existiert bereits."

                salt_hex, hash_hex = self.hash_admin_password(password)
                cur.execute(
                    """
                    INSERT INTO bot_admin_users
                        (network, user_mask, display_name, password_salt, password_hash, role_name, created_at, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self.config.network_key,
                        normalized_mask,
                        label,
                        salt_hex,
                        hash_hex,
                        normalized_role,
                        self.current_time_string(),
                        created_by[:64],
                    ),
                )
            return True, f"Benutzer {normalized_mask} mit Rolle {normalized_role} angelegt."
        except Exception as exc:
            return False, f"Benutzer konnte nicht angelegt werden: {exc}"
        finally:
            conn.close()

    def delete_admin_user(self, user_mask: str) -> tuple[bool, str]:
        normalized_mask = self.normalize_user_mask(user_mask)
        if normalized_mask is None:
            return False, INVALID_HOSTMASK_MESSAGE

        conn = self.open_db_connection()
        if conn is None:
            return False, self.tr("db_connect_failed")

        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM bot_admin_user_modes WHERE network = %s AND user_mask = %s",
                    (self.config.network_key, normalized_mask),
                )
                cur.execute(
                    "DELETE FROM bot_admin_users WHERE network = %s AND user_mask = %s",
                    (self.config.network_key, normalized_mask),
                )
                if cur.rowcount == 0:
                    return False, f"Benutzer {normalized_mask} existiert nicht."
            self._admin_sessions.pop(normalized_mask, None)
            return True, f"Benutzer {normalized_mask} geloescht."
        except Exception as exc:
            return False, f"Benutzer konnte nicht geloescht werden: {exc}"
        finally:
            conn.close()

    def set_admin_user_role(self, user_mask: str, role_name: str) -> tuple[bool, str]:
        normalized_mask = self.normalize_user_mask(user_mask)
        normalized_role = self.normalize_role_name(role_name)
        if normalized_mask is None or normalized_role is None:
            return False, "Ungültige Hostmask oder Rolle."

        conn = self.open_db_connection()
        if conn is None:
            return False, self.tr("db_connect_failed")

        try:
            with conn.cursor() as cur:
                cur.execute(
                    ROLE_EXISTS_QUERY,
                    (self.config.network_key, normalized_role),
                )
                if cur.fetchone() is None:
                    return False, f"Rolle {normalized_role} existiert nicht."

                cur.execute(
                    "UPDATE bot_admin_users SET role_name = %s WHERE network = %s AND user_mask = %s",
                    (normalized_role, self.config.network_key, normalized_mask),
                )
                if cur.rowcount == 0:
                    return False, f"Benutzer {normalized_mask} existiert nicht."
            return True, f"Benutzer {normalized_mask} hat jetzt Rolle {normalized_role}."
        except Exception as exc:
            return False, f"Rolle konnte nicht gesetzt werden: {exc}"
        finally:
            conn.close()

    def list_admin_users(self) -> list[dict[str, object]]:
        conn = self.open_db_connection()
        if conn is None:
            return []

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_mask, display_name, role_name
                    FROM bot_admin_users
                    WHERE network = %s
                    ORDER BY user_mask ASC
                    """,
                    (self.config.network_key,),
                )
                return list(cur.fetchall() or [])
        except Exception:
            return []
        finally:
            conn.close()

    def set_role_channel_mode(self, role_name: str, channel: str, mode_or_prefix: str, enabled: bool) -> tuple[bool, str]:
        normalized_role = self.normalize_role_name(role_name)
        normalized_channel = self.normalize_channel_name(channel)
        mode = self.normalize_member_mode(mode_or_prefix)
        if normalized_role is None or not normalized_channel.startswith("#") or mode is None:
            return False, "Ungültige Rolle, Channel oder Modus."

        conn = self.open_db_connection()
        if conn is None:
            return False, self.tr("db_connect_failed")

        try:
            with conn.cursor() as cur:
                cur.execute(
                    ROLE_EXISTS_QUERY,
                    (self.config.network_key, normalized_role),
                )
                if cur.fetchone() is None:
                    return False, f"Rolle {normalized_role} existiert nicht."

                if enabled:
                    cur.execute(
                        """
                        INSERT IGNORE INTO bot_admin_role_modes (network, role_name, channel, mode, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (self.config.network_key, normalized_role, normalized_channel, mode, self.current_time_string()),
                    )
                else:
                    cur.execute(
                        "DELETE FROM bot_admin_role_modes WHERE network = %s AND role_name = %s AND channel = %s AND mode = %s",
                        (self.config.network_key, normalized_role, normalized_channel, mode),
                    )
            action = "gesetzt" if enabled else "entfernt"
            return True, f"Rollenrecht {normalized_role} {normalized_channel} +{mode} {action}."
        except Exception as exc:
            return False, f"Rollenrecht konnte nicht gespeichert werden: {exc}"
        finally:
            conn.close()

    def set_user_channel_mode(self, user_mask: str, channel: str, mode_or_prefix: str, enabled: bool) -> tuple[bool, str]:
        normalized_mask = self.normalize_user_mask(user_mask)
        normalized_channel = self.normalize_channel_name(channel)
        mode = self.normalize_member_mode(mode_or_prefix)
        if normalized_mask is None or not normalized_channel.startswith("#") or mode is None:
            return False, "Ungültige Hostmask, Channel oder Modus."

        conn = self.open_db_connection()
        if conn is None:
            return False, self.tr("db_connect_failed")

        try:
            with conn.cursor() as cur:
                if enabled:
                    cur.execute(
                        """
                        INSERT IGNORE INTO bot_admin_user_modes (network, user_mask, channel, mode, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (self.config.network_key, normalized_mask, normalized_channel, mode, self.current_time_string()),
                    )
                else:
                    cur.execute(
                        "DELETE FROM bot_admin_user_modes WHERE network = %s AND user_mask = %s AND channel = %s AND mode = %s",
                        (self.config.network_key, normalized_mask, normalized_channel, mode),
                    )
            action = "gesetzt" if enabled else "entfernt"
            return True, f"Benutzerrecht {normalized_mask} {normalized_channel} +{mode} {action}."
        except Exception as exc:
            return False, f"Benutzerrecht konnte nicht gespeichert werden: {exc}"
        finally:
            conn.close()

    def get_configured_user_channel_modes(self, user_mask: str, channel: str) -> tuple[str, ...]:
        normalized_mask = self.normalize_user_mask(user_mask)
        normalized_channel = self.normalize_channel_name(channel)
        if normalized_mask is None or not normalized_channel:
            return ()

        conn = self.open_db_connection()
        if conn is None:
            return ()

        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT role_name FROM bot_admin_users WHERE network = %s AND user_mask = %s LIMIT 1",
                    (self.config.network_key, normalized_mask),
                )
                row = cur.fetchone() or {}
                role_name = self.normalize_role_name(str(row.get("role_name", "")))

                modes: set[str] = set()
                if role_name:
                    cur.execute(
                        "SELECT mode FROM bot_admin_role_modes WHERE network = %s AND role_name = %s AND channel = %s",
                        (self.config.network_key, role_name, normalized_channel),
                    )
                    modes.update(
                        mode
                        for mode in (self.normalize_member_mode(str(entry.get("mode", ""))) for entry in (cur.fetchall() or []))
                        if mode is not None
                    )

                cur.execute(
                    "SELECT mode FROM bot_admin_user_modes WHERE network = %s AND user_mask = %s AND channel = %s",
                    (self.config.network_key, normalized_mask, normalized_channel),
                )
                modes.update(
                    mode
                    for mode in (self.normalize_member_mode(str(entry.get("mode", ""))) for entry in (cur.fetchall() or []))
                    if mode is not None
                )
        except Exception:
            return ()
        finally:
            conn.close()

        ordered = [mode for mode in self.server_prefix_modes if mode in modes]
        return tuple(ordered)

    def is_admin_session_active(self, user_mask: str) -> bool:
        normalized_mask = self.normalize_user_mask(user_mask)
        if normalized_mask is None:
            return False

        session = self._admin_sessions.get(normalized_mask)
        if session is None:
            return False

        expires_at = float(session.get("expires_at", 0.0))
        if expires_at < time.time():
            self.end_admin_session(normalized_mask, revoke_modes=True)
            return False
        return True

    def get_user_channel_modes(self, user_mask: str, channel: str) -> tuple[str, ...]:
        configured_modes = self.get_configured_user_channel_modes(user_mask, channel)
        if not configured_modes:
            return ()

        admin_row = self.load_admin_user(user_mask)
        if admin_row is not None and bool(int(admin_row.get("is_admin", 0))) and not self.is_admin_session_active(user_mask):
            return ()

        return configured_modes[:1]

    def get_user_assigned_channels(self, user_mask: str) -> tuple[str, ...]:
        normalized_mask = self.normalize_user_mask(user_mask)
        if normalized_mask is None:
            return ()

        conn = self.open_db_connection()
        if conn is None:
            return ()

        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT role_name FROM bot_admin_users WHERE network = %s AND user_mask = %s LIMIT 1",
                    (self.config.network_key, normalized_mask),
                )
                row = cur.fetchone() or {}
                role_name = self.normalize_role_name(str(row.get("role_name", "")))

                channels: set[str] = set()
                if role_name:
                    cur.execute(
                        "SELECT channel FROM bot_admin_role_modes WHERE network = %s AND role_name = %s",
                        (self.config.network_key, role_name),
                    )
                    channels.update(
                        self.normalize_channel_name(str(entry.get("channel", "")))
                        for entry in (cur.fetchall() or [])
                        if str(entry.get("channel", "")).strip()
                    )

                cur.execute(
                    "SELECT channel FROM bot_admin_user_modes WHERE network = %s AND user_mask = %s",
                    (self.config.network_key, normalized_mask),
                )
                channels.update(
                    self.normalize_channel_name(str(entry.get("channel", "")))
                    for entry in (cur.fetchall() or [])
                    if str(entry.get("channel", "")).strip()
                )
        except Exception:
            return ()
        finally:
            conn.close()

        return tuple(sorted(channel for channel in channels if channel.startswith("#")))

    def apply_login_modes_for_user(self, user_mask: str, nick: str) -> int:
        normalized_mask = self.normalize_user_mask(user_mask)
        target_nick = nick.strip()
        if normalized_mask is None or not target_nick:
            return 0

        applied = 0
        for channel in self.get_user_assigned_channels(normalized_mask):
            modes = self.get_user_channel_modes(normalized_mask, channel)
            if not modes:
                continue
            self.apply_member_mode(channel, target_nick, modes[0])
            applied += 1
        return applied

    def revoke_login_modes_for_user(self, user_mask: str, nick: str) -> int:
        normalized_mask = self.normalize_user_mask(user_mask)
        target_nick = nick.strip()
        if normalized_mask is None or not target_nick:
            return 0

        revoked = 0
        for channel in self.get_user_assigned_channels(normalized_mask):
            modes = self.get_configured_user_channel_modes(normalized_mask, channel)
            if not modes:
                continue
            self.remove_member_mode(channel, target_nick, modes[0])
            revoked += 1
        return revoked

    def apply_configured_channel_modes(self, channel: str, nick: str, ident: str, host: str) -> tuple[str, ...]:
        user_mask = self.user_mask_from_parts(ident, host)
        if user_mask is None:
            return ()

        modes = self.get_user_channel_modes(user_mask, channel)
        for mode in modes:
            self.apply_member_mode(channel, nick, mode)
        return modes

    def apply_channel_modes_for_mask(self, channel: str, nick: str, user_mask: str) -> tuple[bool, str]:
        normalized_mask = self.normalize_user_mask(user_mask)
        normalized_channel = self.normalize_channel_name(channel)
        target_nick = self.strip_channel_member_prefixes(nick)
        if normalized_mask is None:
            return False, INVALID_HOSTMASK_MESSAGE
        if not normalized_channel.startswith("#"):
            return False, "Ungültiger Channel."
        if not target_nick:
            return False, "Ungültiger Nick."

        if not self.is_nick_in_channel(normalized_channel, self.current_nick):
            return False, f"Bot ist nicht in {normalized_channel}."
        if not self.is_nick_in_channel(normalized_channel, target_nick):
            return False, f"Nick {target_nick} ist nicht in {normalized_channel}."

        modes = self.get_configured_user_channel_modes(normalized_mask, normalized_channel)
        if not modes:
            return False, f"Keine Rechte fuer {normalized_mask} in {normalized_channel} konfiguriert."

        for mode in modes:
            self.clear_member_mode_retry(normalized_channel, target_nick, mode)
            self.apply_member_mode(normalized_channel, target_nick, mode)
        rendered_modes = ", ".join(f"+{mode}" for mode in modes)
        return True, f"Modi {rendered_modes} fuer {target_nick} in {normalized_channel} gesendet."

    @staticmethod
    def current_time_string() -> str:
        return time.strftime("%d.%m.%Y %H:%M:%S")

    def block_url(self, url: str) -> None:
        self.update_url_flag(url, "is_blocked")

    def mark_deadlink(self, url: str) -> None:
        self.update_url_flag(url, "is_deadlink")

    def update_url_flag(self, url: str, flag_name: str) -> None:
        conn = self.open_db_connection()
        if conn is None:
            return

        # Validate flag_name to prevent SQL injection (only allow safe column names)
        allowed_flags = {"is_blocked", "is_deadlink"}
        if flag_name not in allowed_flags:
            return

        try:
            with conn.cursor() as cur:
                # Column names cannot be parameterized, use only validated values
                cur.execute(
                    f"UPDATE bot_url SET {flag_name} = 1 WHERE url = %s",
                    (url,),
                )
        except Exception:
            pass
        finally:
            conn.close()

    @staticmethod
    def roll_dart_turn() -> tuple[int, str]:
        if random.randint(1, 777) == 1:
            return 31337, "Dartscheibenzerstoerung"

        roll_type = random.choice(["single", "double", "triple", "bull", "bull"])
        if roll_type == "bull":
            bull_points = random.choice([25, 50])
            return bull_points, "Bull" if bull_points == 25 else "Bullseye"

        segment = random.randint(1, 20)
        multiplier = {"single": 1, "double": 2, "triple": 3}[roll_type]
        points = segment * multiplier
        hit_label = {"single": "Single", "double": "Double", "triple": "Triple"}[roll_type]
        return points, f"{hit_label} {segment}"

    @staticmethod
    def parse_irc_line(line: str) -> tuple[str, str, list[str]]:
        prefix = ""
        if line.startswith(":"):
            prefix, line = line[1:].split(" ", 1)

        if " :" in line:
            left, trailing = line.split(" :", 1)
            args = left.split()
            args.append(trailing)
        else:
            args = line.split()

        command = args[0] if args else ""
        params = args[1:] if len(args) > 1 else []
        return prefix, command, params


class TopicParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.topic = ""
        self._capture_title = False
        self._capture_topic = False
        self._title_parts: list[str] = []
        self._topic_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "title" and not self.title:
            self._capture_title = True
            self._title_parts = []
        elif tag in {"h1", "h2"} and not self.topic:
            self._capture_topic = True
            self._topic_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._capture_title:
            self._capture_title = False
            self.title = "".join(self._title_parts).strip()
        elif tag in {"h1", "h2"} and self._capture_topic:
            self._capture_topic = False
            self.topic = "".join(self._topic_parts).strip()

    def handle_data(self, data: str) -> None:
        if self._capture_topic:
            self._topic_parts.append(data)
        elif self._capture_title:
            self._title_parts.append(data)


def read_pid_file(pid_file: Path) -> int | None:
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def remove_pid_file(pid_file: Path) -> None:
    try:
        if pid_file.exists():
            pid_file.unlink()
    except OSError:
        pass


def is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop_from_pid_file(pid_file: Path) -> bool:
    pid = read_pid_file(pid_file)
    if pid is None:
        print("Kein laufender Bot gefunden (PID-Datei fehlt oder ungueltig).")
        return False

    if not is_process_running(pid):
        print(f"Stale PID-Datei gefunden ({pid}). Entferne {pid_file}.")
        remove_pid_file(pid_file)
        return False

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        print(f"Konnte Bot-Prozess {pid} nicht stoppen: {exc}")
        return False

    deadline = time.time() + 10
    while time.time() < deadline:
        if not is_process_running(pid):
            break
        time.sleep(0.2)

    if is_process_running(pid):
        print(f"Bot-Prozess {pid} laeuft noch.")
        return False

    remove_pid_file(pid_file)
    print(f"Bot-Prozess {pid} gestoppt.")
    return True


def start_background_process(pid_file: Path) -> bool:
    if pid_file.exists():
        print(f"Start verweigert: PID-Datei existiert bereits ({pid_file}).")
        return False

    script_path = Path(__file__).resolve()
    cmd = [sys.executable, str(script_path), "--run-foreground", "--pid-file", str(pid_file)]

    popen_kwargs: dict[str, object] = {
        "cwd": str(script_path.parent),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }

    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen(cmd, **popen_kwargs)
    except OSError as exc:
        print(f"Konnte Bot nicht starten: {exc}")
        return False

    print(f"Bot im Hintergrund gestartet (PID {process.pid}).")
    return True


def ensure_admin_bootstrap_for_configs(configs: list[BotConfig], interactive: bool) -> None:
    for config in configs:
        bot = IRCBot(config)
        try:
            bot.ensure_database_setup()
            bot.ensure_admin_bootstrap(interactive)
        finally:
            bot.close()


def run_bot_forever(config: BotConfig, stop_event: threading.Event | None = None) -> None:
    base_retry_wait = max(30, config.reconnect_delay_seconds)
    retry_wait = base_retry_wait
    max_retry_wait = 300
    while not (stop_event and stop_event.is_set()):
        bot = IRCBot(config)
        bot.setup_oidentd_conf()
        bot.ensure_database_setup()
        bot.ensure_admin_bootstrap(sys.stdin.isatty())
        connected_at = time.monotonic()
        try:
            print(f"[{config.display_name()}] " + bot.tr("connecting", server=config.server, port=config.port, tls=config.use_tls))
            bot.connect()
            bot.run()
            print(f"[{config.display_name()}] " + bot.tr("connection_closed"))
        except (OSError, ssl.SSLError) as exc:
            print(f"[{config.display_name()}] " + bot.tr("network_error", error=exc))
        except KeyboardInterrupt:
            print(f"[{config.display_name()}] " + bot.tr("shutting_down"))
            if stop_event:
                stop_event.set()
            break
        finally:
            bot.close()

        if stop_event and stop_event.is_set():
            break

        print(f"[{config.display_name()}] " + bot.tr("reconnect_in", seconds=retry_wait))
        if stop_event:
            if stop_event.wait(retry_wait):
                break
        else:
            time.sleep(retry_wait)

        uptime = time.monotonic() - connected_at
        if uptime >= 300:
            retry_wait = base_retry_wait
        else:
            retry_wait = min(max_retry_wait, max(base_retry_wait, retry_wait * 2))


def run_multiple_bots_forever(configs: list[BotConfig]) -> None:
    stop_event = threading.Event()
    threads: list[threading.Thread] = []

    for config in configs:
        thread = threading.Thread(
            target=run_bot_forever,
            args=(config, stop_event),
            name=f"bot-{config.display_name()}",
            daemon=True,
        )
        thread.start()
        threads.append(thread)

    try:
        while any(thread.is_alive() for thread in threads):
            for thread in threads:
                thread.join(timeout=0.5)
    except KeyboardInterrupt:
        print("Beende Bots.")
    finally:
        stop_event.set()
        for thread in threads:
            if thread.is_alive():
                thread.join(timeout=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="IRCBot control")
    parser.add_argument("--start", action="store_true", help="Start bot in background")
    parser.add_argument("--stop", action="store_true", help="Stop running background bot")
    parser.add_argument("--restart", action="store_true", help="Restart background bot")
    parser.add_argument("--run-foreground", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--pid-file", default="bot.pid", help="PID file path")
    args = parser.parse_args()

    selected = sum([bool(args.start), bool(args.stop), bool(args.restart), bool(args.run_foreground)])
    if selected > 1:
        raise SystemExit("Nur eine Option aus --start/--stop/--restart gleichzeitig verwenden.")

    pid_file = Path(args.pid_file).resolve()

    if args.stop:
        stop_from_pid_file(pid_file)
        return

    if args.restart:
        stop_from_pid_file(pid_file)
        config_path = Path("config.json")
        if not config_path.exists():
            raise SystemExit(
                "config.json fehlt / is missing. Kopiere config.example.json zu config.json und passe die Werte an."
            )
        try:
            configs = BotConfig.load_from_file(config_path)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        ensure_admin_bootstrap_for_configs(configs, sys.stdin.isatty())
        start_background_process(pid_file)
        return

    if args.start:
        config_path = Path("config.json")
        if not config_path.exists():
            raise SystemExit(
                "config.json fehlt / is missing. Kopiere config.example.json zu config.json und passe die Werte an."
            )
        try:
            configs = BotConfig.load_from_file(config_path)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        ensure_admin_bootstrap_for_configs(configs, sys.stdin.isatty())
        start_background_process(pid_file)
        return

    config_path = Path("config.json")
    if not config_path.exists():
        raise SystemExit(
            "config.json fehlt / is missing. Kopiere config.example.json zu config.json und passe die Werte an."
        )

    try:
        configs = BotConfig.load_from_file(config_path)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if args.run_foreground:
        if pid_file.exists():
            raise SystemExit(f"Start verweigert: PID-Datei existiert bereits ({pid_file}).")

        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        atexit.register(lambda: remove_pid_file(pid_file))

        def _shutdown_handler(_signum, _frame):
            raise KeyboardInterrupt()

        signal.signal(signal.SIGTERM, _shutdown_handler)
        signal.signal(signal.SIGINT, _shutdown_handler)

    if len(configs) == 1:
        run_bot_forever(configs[0])
        return

    print(f"Starte {len(configs)} Netzwerke parallel.")
    run_multiple_bots_forever(configs)


if __name__ == "__main__":
    main()
