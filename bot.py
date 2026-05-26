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
import queue
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
    from version_info import version_line
except ModuleNotFoundError:
    _REPOSITORY_URL = "https://github.com/WarPigs1602/ircbot-python"

    def _detect_version_fallback() -> str:
        repo_root = Path(__file__).resolve().parent
        try:
            branch = subprocess.check_output(
                ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            commit = subprocess.check_output(
                ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.SubprocessError):
            return "unbekannt"

        if branch and commit:
            return f"{branch}@{commit}"
        if commit:
            return commit
        return "unbekannt"

    def version_line() -> str:
        return f"Python IRC Bot {_detect_version_fallback()} | GitHub: {_REPOSITORY_URL}"

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
ADMIN_SESSION_TTL_SECONDS = 1800
ROLE_FLAG_COLUMNS = {
    "admin": "is_admin",
    "raw": "can_raw",
}
INVALID_HOSTMASK_MESSAGE = "Ungültige Hostmask."
ROLE_EXISTS_QUERY = "SELECT 1 FROM bot_admin_roles WHERE network = %s AND role_name = %s LIMIT 1"
CONFIG_FILE_NAME = "config.json"
CONFIG_MISSING_MESSAGE = "config.json fehlt / is missing. Kopiere config.example.json zu config.json und passe die Werte an."
SASL_RESULT_COMMANDS = frozenset({"900", "902", "903", "904", "905", "906", "907", "908"})
STARTUP_COMPLETE_COMMANDS = frozenset({"376", "422"})
CHANNEL_JOIN_FAILURE_COMMANDS = frozenset({"403", "405", "471", "473", "474", "475", "476", "477", "489"})


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
    weather_appid: str = ""
    youtube_api_key: str = ""
    perform: list[str] | None = None
    sasl_enabled: bool = False
    sasl_username: str = ""
    sasl_password: str = ""
    sasl_authzid: str = ""
    language: str = "de"
    flood_protection_enabled: bool = True
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
            weather_appid=str(raw.get("weather_appid", "")).strip(),
            youtube_api_key=str(raw.get("youtube_api_key", "")),
            perform=perform_list,
            sasl_enabled=bool(raw.get("sasl_enabled", False)),
            sasl_username=str(raw.get("sasl_username", "")),
            sasl_password=str(raw.get("sasl_password", "")),
            sasl_authzid=str(raw.get("sasl_authzid", "")),
            language=language,
            flood_protection_enabled=bool(raw.get("flood_protection_enabled", True)),
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
        self.user_modes: set[str] = set()
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
        self.userhost_in_names_enabled = False
        self.active_capabilities: set[str] = set()
        self._admin_sessions: dict[str, dict[str, object]] = {}
        self._admin_bootstrap_warned = False
        self._send_lock = threading.RLock()
        self._who_queue: queue.Queue[str] = queue.Queue()
        self._who_worker = threading.Thread(target=self._who_queue_worker, daemon=True, name="who-worker")
        self._who_worker.start()
        self._url_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="urlsniff")
        self._runtime_stop_event = threading.Event()
        self._plugin_tick_thread: threading.Thread | None = None
        self._url_service = None
        self.spam_words = SPAM_WORDS
        self.spam_hosts = SPAM_HOSTS
        self.dangerous_content_types = DANGEROUS_CONTENT_TYPES
        self.plugin_manager = PluginManager(self, Path(__file__).resolve().parent / "plugins")

    def _get_url_service(self):
        if self._url_service is None:
            from plugins.url_service import URLService

            self._url_service = URLService()
        return self._url_service

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
                "weather_appid_missing": "Weather-App-ID fehlt. Bitte weather_appid in der Konfiguration setzen.",
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
                "weather_appid_missing": "Weather app ID is missing. Please set weather_appid in the configuration.",
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
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = True
            ctx.verify_mode = ssl.CERT_REQUIRED
            ctx.load_default_certs()
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
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
            self.cache_own_user_mode_command(line)
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
        if not self.config.flood_protection_enabled:
            return

        if "B" in self.user_modes:
            return

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
        normalized = [ch.strip() for ch in channels if ch and ch.strip()]
        if not normalized:
            return
        self.send_raw(f"JOIN {','.join(normalized)}")

    def request_channel_modes(self, channel: str) -> None:
        # Intentionally disabled: no explicit MODE/TOPIC polling on join/startup.
        return

    def request_user_modes(self) -> None:
        if self.current_nick:
            self.send_raw(f"MODE {self.current_nick}")

    def request_channel_members(self, channel: str) -> None:
        normalized_channel = channel.strip()
        if normalized_channel:
            self.channel_members[self.normalize_channel_name(normalized_channel)] = {}
            self.send_raw(f"NAMES {normalized_channel}")

    def _who_queue_worker(self) -> None:
        while True:
            channel = self._who_queue.get()
            if channel is None:
                break
            try:
                self.send_raw(f"WHO {channel}")
            except Exception:
                pass
            time.sleep(2.0)

    def request_channel_who(self, channel: str) -> None:
        if self.userhost_in_names_enabled:
            return
        normalized_channel = channel.strip()
        if normalized_channel:
            self._who_queue.put(normalized_channel)

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

    def normalize_channel_member_nick(self, nick: str) -> str:
        cleaned = self.strip_channel_member_prefixes(nick)
        member_nick, _, _ = self.split_hostmask(cleaned)
        return member_nick.strip()

    def parse_names_member_hostmask(self, value: str) -> tuple[str, str, str]:
        cleaned = self.strip_channel_member_prefixes(value)
        nick, ident, host = self.split_hostmask(cleaned)
        return nick.strip(), ident.strip(), host.strip()

    def add_channel_member(self, channel: str, nick: str) -> None:
        normalized_channel = self.normalize_channel_name(channel)
        cleaned_nick = self.normalize_channel_member_nick(nick)
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
        cleaned_nick = self.normalize_channel_member_nick(nick)
        if not normalized_channel or not cleaned_nick:
            return
        self.clear_member_mode_retry(normalized_channel, cleaned_nick)
        members = self.channel_members.get(normalized_channel)
        if members is not None:
            members.pop(cleaned_nick.lower(), None)

    def rename_channel_member(self, old_nick: str, new_nick: str) -> None:
        cleaned_old_nick = self.normalize_channel_member_nick(old_nick)
        cleaned_new_nick = self.normalize_channel_member_nick(new_nick)
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
        cleaned_nick = self.normalize_channel_member_nick(nick)
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
        cleaned_nick = self.normalize_channel_member_nick(nick)
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

    def apply_user_mode_delta(self, mode_changes: str) -> None:
        active = set(self.user_modes)
        sign = "+"
        for char in mode_changes:
            if char in {"+", "-"}:
                sign = char
                continue
            if sign == "+":
                active.add(char)
            else:
                active.discard(char)
        self.user_modes = active

    def cache_own_user_mode_command(self, line: str) -> None:
        parts = line.split()
        if len(parts) < 3 or parts[0].upper() != "MODE":
            return
        if parts[1].startswith("#") or parts[1].lower() != self.current_nick.lower():
            return
        self.apply_user_mode_delta(parts[2])

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
        cleaned_nick = self.normalize_channel_member_nick(nick).lower()
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
        cleaned_nick = self.normalize_channel_member_nick(nick).lower()
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
        self.request_user_modes()
        self.join_channels(self.config.channels)
        if self.config.flood_protection_enabled and not self.userhost_in_names_enabled:
            self.public_trigger_activation_at = time.monotonic() + 60.0
        else:
            self.public_trigger_activation_at = 0.0
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

    @staticmethod
    def _extract_cap_list_param(params: list[str]) -> str:
        if len(params) >= 4 and params[2] == "*":
            return params[3]
        if len(params) >= 3:
            return params[2]
        return ""

    @staticmethod
    def _parse_cap_tokens(caps_text: str) -> set[str]:
        parsed: set[str] = set()
        for token in caps_text.split():
            normalized = token.strip().lower().lstrip(":")
            if not normalized:
                continue
            if normalized[0] in {"+", "-", "~", "="}:
                normalized = normalized[1:]
            if not normalized:
                continue
            parsed.add(normalized.split("=", 1)[0])
        return parsed

    def handle_cap_message(self, params: list[str]) -> None:
        if len(params) < 2:
            return

        subcommand = params[1].upper()
        caps_text = self._extract_cap_list_param(params)
        cap_tokens = self._parse_cap_tokens(caps_text)

        if subcommand == "LS":
            self._handle_cap_ls(cap_tokens)
            return

        if subcommand == "ACK":
            self._handle_cap_ack(cap_tokens)
            return

        if subcommand in {"NAK", "DEL"}:
            self._handle_cap_nak_or_del(subcommand, cap_tokens)

    def _handle_cap_ls(self, cap_tokens: set[str]) -> None:
        requested_caps: list[str] = []
        if self.should_use_sasl() and "sasl" in cap_tokens:
            requested_caps.append("sasl")
        if "userhost-in-names" in cap_tokens:
            requested_caps.append("userhost-in-names")
        if requested_caps:
            self.send_raw(f"CAP REQ :{' '.join(requested_caps)}")
            return
        self.end_cap_negotiation()

    def _handle_cap_ack(self, cap_tokens: set[str]) -> None:
        self.active_capabilities.update(cap_tokens)
        if "userhost-in-names" in cap_tokens:
            self.userhost_in_names_enabled = True
            if self.startup_actions_completed:
                self.public_trigger_activation_at = 0.0
        if self.should_use_sasl() and "sasl" in cap_tokens:
            self.send_raw("AUTHENTICATE PLAIN")
            return
        self.end_cap_negotiation()

    def _handle_cap_nak_or_del(self, subcommand: str, cap_tokens: set[str]) -> None:
        if subcommand == "DEL":
            self.active_capabilities.difference_update(cap_tokens)
        if "userhost-in-names" in cap_tokens:
            self.userhost_in_names_enabled = False
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

            if self._handle_server_command(prefix, command, params):
                continue

    def _handle_server_command(self, prefix: str, command: str, params: list[str]) -> bool:
        handlers = (
            self._handle_capability_and_startup_command,
            self._handle_membership_command,
            self._handle_server_feedback_command,
            self._handle_channel_state_command,
            self._handle_privmsg_command,
        )
        for handler in handlers:
            if handler(prefix, command, params):
                return True
        return False

    def _handle_capability_and_startup_command(self, _prefix: str, command: str, params: list[str]) -> bool:
        if command == "CAP":
            self.handle_cap_message(params)
            return True
        if command == "005":
            self.handle_isupport_message(params)
            return True
        if command == "PONG":
            self.handle_pong_message(params)
            return True
        if command == "AUTHENTICATE":
            self.handle_authenticate_message(params)
            return True
        if command in SASL_RESULT_COMMANDS:
            self.handle_sasl_result(command)
            return True
        if command == "001":
            self.send_nickserv_identify()
            self.try_reclaim_preferred_nick(force=True)
            self.complete_startup_actions()
            return True
        if command in STARTUP_COMPLETE_COMMANDS:
            self.complete_startup_actions()
            return True
        return False

    def _handle_membership_command(self, prefix: str, command: str, params: list[str]) -> bool:
        if command == "NICK" and len(params) >= 1:
            self._handle_nick_change(prefix, params[0])
            return True
        if command == "JOIN" and len(params) >= 1:
            self._handle_join(prefix, params[0])
            return True
        if command == "PART" and len(params) >= 1:
            self._handle_part(prefix, params[0])
            return True
        if command == "KICK" and len(params) >= 2:
            self._handle_kick(params[0], params[1])
            return True
        if command == "QUIT":
            quit_nick = prefix.split("!", 1)[0] if prefix else ""
            self.remove_channel_member_from_all(quit_nick)
            return True
        if command == "INVITE" and len(params) >= 2:
            self._handle_invite(prefix, params[0], params[1])
            return True
        return False

    def _handle_server_feedback_command(self, _prefix: str, command: str, params: list[str]) -> bool:
        if command == "433":
            old_nick = self.current_nick
            if self.current_nick.lower() != self.fallback_nick.lower():
                self.current_nick = self.fallback_nick
                print(self.tr("nick_taken", old_nick=old_nick, new_nick=self.current_nick))
                self.send_raw(f"NICK {self.current_nick}")
            else:
                print(self.tr("nick_taken", old_nick=old_nick, new_nick=self.current_nick))
            return True

        if command in CHANNEL_JOIN_FAILURE_COMMANDS and len(params) >= 2:
            failed_channel = params[1].lstrip(":")
            if failed_channel.startswith("#"):
                print(self.tr("channel_not_joinable", channel=failed_channel))
                self.forget_channel(failed_channel)
            return True

        return False

    def _handle_channel_state_command(self, _prefix: str, command: str, params: list[str]) -> bool:
        if command == "353" and len(params) >= 4:
            self._handle_names_reply(params[2], params[3])
            return True
        if command == "324" and len(params) >= 3:
            channel = params[1]
            modes = params[2]
            self.channel_modes[channel] = self.parse_mode_snapshot(modes)
            return True
        if command == "221" and len(params) >= 2:
            self.user_modes = self.parse_mode_snapshot(params[1])
            return True
        if command == "MODE" and len(params) >= 2:
            target = params[0]
            modes = params[1]
            if target.startswith("#"):
                self.apply_mode_delta(target, modes)
            elif target.lower() == self.current_nick.lower():
                self.apply_user_mode_delta(modes)
            return True
        return False

    def _handle_privmsg_command(self, prefix: str, command: str, params: list[str]) -> bool:
        if command != "PRIVMSG" or len(params) < 2:
            return False
        target = params[0]
        message = params[1]
        source_nick, source_ident, source_host = self.split_hostmask(prefix)
        self.handle_privmsg(source_nick, source_ident, source_host, target, message)
        return True

    def _handle_nick_change(self, prefix: str, new_nick_raw: str) -> None:
        changed_nick = prefix.split("!", 1)[0] if prefix else ""
        new_nick = new_nick_raw.lstrip(":")
        if changed_nick.lower() == self.current_nick.lower() and new_nick:
            self.current_nick = new_nick
            if new_nick.lower() == self.preferred_nick.lower():
                self.last_nick_reclaim_attempt_at = 0.0
        self.rename_channel_member(changed_nick, new_nick)
        self.update_admin_session_nick(changed_nick, new_nick)

    def _handle_join(self, prefix: str, joined_channel_raw: str) -> None:
        joined_channel = joined_channel_raw.lstrip(":")
        joined_nick, joined_ident, joined_host = self.split_hostmask(prefix)
        self.add_channel_member(joined_channel, joined_nick)
        if joined_nick.lower() == self.current_nick.lower() and joined_channel:
            self.remember_channel(joined_channel)
            if not self.userhost_in_names_enabled:
                self.request_channel_modes(joined_channel)
            self.request_channel_members(joined_channel)
            self.request_channel_who(joined_channel)
            return
        if joined_channel:
            self.apply_configured_channel_modes(joined_channel, joined_nick, joined_ident, joined_host)

    def _handle_part(self, prefix: str, parted_channel_raw: str) -> None:
        parted_channel = parted_channel_raw.lstrip(":")
        parted_nick = prefix.split("!", 1)[0] if prefix else ""
        self.remove_channel_member(parted_channel, parted_nick)
        if parted_nick.lower() == self.current_nick.lower() and parted_channel:
            self.forget_channel(parted_channel)

    def _handle_kick(self, kicked_channel_raw: str, kicked_nick: str) -> None:
        kicked_channel = kicked_channel_raw.lstrip(":")
        self.remove_channel_member(kicked_channel, kicked_nick)
        if kicked_nick.lower() == self.current_nick.lower() and kicked_channel:
            self.forget_channel(kicked_channel)

    def _handle_invite(self, prefix: str, invited_nick: str, invited_channel: str) -> None:
        inviter_nick = prefix.split("!", 1)[0] if prefix else ""
        if invited_nick.lower() != self.current_nick.lower():
            return
        self.remember_channel(invited_channel)
        self.send_raw(f"JOIN {invited_channel}")
        if not self.userhost_in_names_enabled:
            self.request_channel_modes(invited_channel)
        self.request_channel_members(invited_channel)
        if inviter_nick:
            self.send_action(
                invited_channel,
                f"slaps {inviter_nick} around a bit with a large {self.current_nick}",
            )

    def _handle_names_reply(self, names_channel: str, names_param: str) -> None:
        names_members = names_param.lstrip(":").split()
        self.add_channel_members(names_channel, names_members)
        if not self.userhost_in_names_enabled:
            return
        for member in names_members:
            member_nick, member_ident, member_host = self.parse_names_member_hostmask(member)
            if member_nick and member_ident and member_host:
                self.apply_configured_channel_modes(names_channel, member_nick, member_ident, member_host)

    def handle_privmsg(self, source_nick: str, source_ident: str, source_host: str, target: str, message: str) -> None:
        prefix = self.config.command_prefix
        is_private_message = target.lower() == self.current_nick.lower()
        reply_target = source_nick if is_private_message else target
        source_mask = self.user_mask_from_parts(source_ident, source_host) or ""
        if self._handle_ctcp(source_nick, message):
            return
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

    def _handle_ctcp(self, source_nick: str, message: str) -> bool:
        if not source_nick:
            return False
        if not (message.startswith("\x01") and message.endswith("\x01") and len(message) >= 2):
            return False

        payload = message[1:-1].strip()
        if payload.upper() != "VERSION":
            return False

        self.send_notice(source_nick, f"\x01VERSION {version_line()}\x01")
        return True

    def build_url_usage_text(self, prefix: str) -> str:
        max_id = self._get_url_service().get_max_url_id(self)
        if max_id is None:
            return self.tr("usage_url", prefix=prefix, command=self.primary_command_name("url"))
        return self.tr("usage_url_with_max", prefix=prefix, command=self.primary_command_name("url"), max_id=max_id)

    def format_target_nick(self, target_nick: str) -> str:
        if target_nick.lower() == self.current_nick.lower():
            return self.tr("self_target")
        return target_nick

    def get_weather_text(self, location_query: str, command_prefix: str, reply_target: str) -> str:
        location = location_query.strip() or self.config.weather_default_location.strip()
        if not location:
            return self.tr("usage_weather", prefix=command_prefix, command=self.primary_command_name("weather"))
        return self.render_openweather_weather_text(location, reply_target)

    def render_openweather_weather_text(self, location: str, reply_target: str) -> str:
        if not self.config.weather_appid.strip():
            return self.tr("weather_appid_missing")

        weather_url = self.build_openweather_url(location)
        if weather_url is None:
            return self.tr("weather_not_found", location=location)

        weather_data, weather_status = self.fetch_json_with_status(weather_url)
        if not weather_data:
            return self.openweather_error_text(weather_status, location)

        if str(weather_data.get("cod", "")).strip() == "404":
            return self.tr("weather_not_found", location=location)

        weather_details = self.extract_openweather_weather_details(weather_data, location)
        if weather_details is None:
            return self.tr("weather_not_found", location=location)

        display_place = str(weather_details["display_place"])
        condition = str(weather_details["condition"])
        temperature = weather_details["temperature"]
        feels_like = weather_details["feels_like"]
        humidity = weather_details["humidity"]
        wind_speed = weather_details["wind_speed"]
        wind_direction = weather_details["wind_direction"]

        temperature_text = self.format_localized_number(temperature)
        feels_like_text = self.format_localized_number(feels_like)
        humidity_text = self.format_localized_number(humidity)
        wind_speed_text = self.format_localized_number(wind_speed)

        if self.allows_control_codes(reply_target):
            return self.format_weather_with_control_codes(
                display_place,
                temperature,
                feels_like,
                humidity,
                condition,
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
            wind_speed=wind_speed_text,
        )

    def resolve_weather_location(self, location: str) -> dict[str, object] | None:
        postal_code = self.extract_postal_code(location)
        if postal_code:
            postal_location = self.geocode_postal_code(postal_code, location)
            if postal_location:
                return postal_location

        return self.geocode_location_name(location)

    def build_openweather_url(self, location: str) -> str | None:
        parsed_location = self.parse_openweather_location(location)
        if parsed_location is None:
            return None

        query_location, zip_location = parsed_location

        url = (
            "https://api.openweathermap.org/data/2.5/weather?"
            f"q={quote_plus(query_location)}"
            f"&appid={quote_plus(self.config.weather_appid)}"
            "&units=metric"
            f"&lang={quote_plus(self.config.language)}"
        )
        if zip_location is not None:
            url += f"&zip={quote_plus(zip_location)}"
        return url

    def parse_openweather_location(self, location: str) -> tuple[str, str | None] | None:
        weather_location = location.strip()
        if not weather_location:
            return None

        if "," in weather_location:
            zip_code = weather_location.split(",", 1)[0].strip()
            if not self.is_integer_text(zip_code):
                return weather_location, None
            return "", weather_location

        if not self.is_integer_text(weather_location):
            return weather_location, None
        return "", f"{weather_location},de"

    @staticmethod
    def is_integer_text(value: str) -> bool:
        return bool(re.fullmatch(r"\d+", value.strip()))

    def extract_openweather_weather_details(self, weather_data: dict[str, object], fallback_location: str) -> dict[str, object] | None:
        if not isinstance(weather_data, dict):
            return None

        return {
            "display_place": self.openweather_display_place(weather_data, fallback_location),
            "condition": self.openweather_condition(weather_data),
            "temperature": self.openweather_main_value(weather_data, "temp"),
            "feels_like": self.openweather_main_value(weather_data, "feels_like"),
            "humidity": self.openweather_main_value(weather_data, "humidity"),
            "wind_speed": self.openweather_wind_speed(weather_data),
            "wind_direction": self.openweather_wind_direction(weather_data),
        }

    @staticmethod
    def dict_or_empty(value: object) -> dict[str, object]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def list_or_empty(value: object) -> list[object]:
        return value if isinstance(value, list) else []

    def openweather_display_place(self, weather_data: dict[str, object], fallback_location: str) -> str:
        place_name = str(weather_data.get("name", "")).strip() or fallback_location
        country = str(self.dict_or_empty(weather_data.get("sys")).get("country", "")).strip()
        return ", ".join(part for part in (place_name, country) if part)

    def openweather_condition(self, weather_data: dict[str, object]) -> str:
        weather_list = self.list_or_empty(weather_data.get("weather"))
        first_weather = weather_list[0] if weather_list and isinstance(weather_list[0], dict) else {}
        return str(first_weather.get("description", "")).strip() or self.tr("unknown")

    def openweather_main_value(self, weather_data: dict[str, object], key: str) -> object:
        return self.dict_or_empty(weather_data.get("main")).get(key)

    def openweather_wind_speed(self, weather_data: dict[str, object]) -> object:
        wind_speed_value = self.dict_or_empty(weather_data.get("wind")).get("speed")
        speed = self.safe_float(wind_speed_value)
        return speed * 3.6 if speed is not None else None

    def openweather_wind_direction(self, weather_data: dict[str, object]) -> object:
        return self.dict_or_empty(weather_data.get("wind")).get("deg")

    def openweather_error_text(self, status: int | None, location: str) -> str:
        if status is not None and 400 <= status < 500:
            return self.tr("weather_not_found", location=location)
        return self.tr("weather_unreachable", location=location)

    def geocode_postal_code(self, postal_code: str, location: str) -> dict[str, object] | None:
        zip_result = self._geocode_postal_code_zippopotam(postal_code)
        if zip_result:
            return zip_result
        return self._geocode_postal_code_nominatim(postal_code, location)

    def _geocode_postal_code_zippopotam(self, postal_code: str) -> dict[str, object] | None:
        zippopotam_url = f"https://api.zippopotam.us/de/{quote(postal_code)}"
        zip_data = self.fetch_json(zippopotam_url)
        if not isinstance(zip_data, dict):
            return None

        places = zip_data.get("places") or []
        if not places:
            return None

        place = places[0]
        place_name = str(place.get("place name", ""))
        state = str(place.get("state", ""))
        latitude = self.safe_float(place.get("latitude"))
        longitude = self.safe_float(place.get("longitude"))
        if latitude is None or longitude is None:
            return None

        return {
            "name": place_name or postal_code,
            "admin1": state,
            "country": str(zip_data.get("country", "Germany" if self.config.language == "en" else "Deutschland")),
            "latitude": latitude,
            "longitude": longitude,
        }

    def _geocode_postal_code_nominatim(self, postal_code: str, location: str) -> dict[str, object] | None:

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
        wind_speed: object,
        wind_direction: object,
    ) -> str:
        bold = "\x02"
        reset = "\x0f"
        blue = "\x0312"
        red = "\x0304"
        green = "\x0303"
        orange = "\x0307"
        gray = "\x0314"

        temp_value = self.format_localized_number(temperature)
        feel_value = self.format_localized_number(feels_like)
        humidity_value = self.format_localized_number(humidity)
        wind_value = self.format_localized_number(wind_speed)
        direction_value = self.format_localized_number(wind_direction)
        temp_color = self.weather_temperature_color(temperature)
        feel_color = self.weather_temperature_color(feels_like)
        temp_text = (
            f"{temp_color}{bold}{temp_value}°C{reset}" if temperature is not None else f"{gray}n/a{reset}"
        )
        feel_text = f"{feel_color}{feel_value}°C{reset}" if feels_like is not None else f"{gray}n/a{reset}"
        humidity_text = f"{blue}{humidity_value}%{reset}" if humidity is not None else f"{gray}n/a{reset}"
        wind_text = f"{orange}{wind_value} km/h{reset}" if wind_speed is not None else f"{gray}n/a{reset}"
        direction_text = self.format_weather_wind_direction(wind_direction, direction_value)
        condition_text = f"{bold}{condition}{reset}"
        feels_like_label = "gef\u00fchlt" if self.config.language == "de" else "feels like"

        details = [
            f"{green}Temp:{reset} {temp_text}",
            f"{green}{feels_like_label}:{reset} {feel_text}",
            f"{green}{self.tr('humidity')}:{reset} {humidity_text}",
            f"{green}{self.tr('wind')}:{reset} {wind_text} {direction_text}",
        ]

        return (
            f"{bold}{red}{self.tr('weather_cc', location=display_place)}{reset} :: "
            f"{condition_text} ({' | '.join(details)})"
        )

    def weather_temperature_color(self, value: object) -> str:
        numeric_value = self.safe_float(value)
        if numeric_value is None:
            return "\x0314"
        if numeric_value < 0:
            return "\x0312"
        if numeric_value < 20:
            return "\x0303"
        if numeric_value < 30:
            return "\x0307"
        return "\x0304"

    def format_weather_wind_direction(self, wind_direction: object, direction_value: str) -> str:
        gray = "\x0314"
        if wind_direction is None:
            return f"{gray}(n/a){'\x0f'}"

        numeric_direction = self.safe_float(wind_direction)
        if numeric_direction is None:
            return f"{gray}(n/a){'\x0f'}"

        arrows = ("N", "NO", "O", "SO", "S", "SW", "W", "NW") if self.config.language == "de" else (
            "N",
            "NE",
            "E",
            "SE",
            "S",
            "SW",
            "W",
            "NW",
        )
        index = int((numeric_direction + 22.5) // 45) % 8
        cardinal = arrows[index]
        return f"{gray}({direction_value}° {cardinal}){'\x0f'}"

    def fetch_json(self, url: str) -> dict[str, object] | None:
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0 IRCBot"})
            with urlopen(request, timeout=10) as response:
                payload = response.read()
            decoded = payload.decode("utf-8", errors="replace")
            parsed = json.loads(decoded)
            return parsed
        except (OSError, ValueError):
            return None

    def fetch_json_with_status(self, url: str) -> tuple[dict[str, object] | None, int | None]:
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0 IRCBot"})
            with urlopen(request, timeout=10) as response:
                payload = response.read()
                status = getattr(response, "status", None)
            decoded = payload.decode("utf-8", errors="replace")
            parsed = json.loads(decoded)
            return parsed, status
        except HTTPError as exc:
            try:
                payload = exc.read()
                decoded = payload.decode("utf-8", errors="replace")
                parsed = json.loads(decoded)
            except Exception:
                parsed = None
            return parsed, exc.code
        except (OSError, ValueError):
            return None, None

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

        def open_connection(password_value: str | bytes):
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
        self._get_url_service().sniff_urls_in_message(self, message, channel, source_nick)

    def handle_url_result(
        self,
        result: dict[str, str | int | bool | None] | None,
        reply_target: str,
        requested_by: str,
        show_max_id: bool = False,
    ) -> None:
        self._get_url_service().handle_url_result(self, result, reply_target, requested_by, show_max_id)

    def fetch_url_by_id(self, url_id: int) -> dict[str, str | int | bool | None] | None:
        if pymysql is None:
            return {"status": "error", "message": "pymysql missing." if self.config.language == "en" else "Python-Paket 'pymysql' fehlt."}
        return self._get_url_service().fetch_url_by_id(self, url_id)

    def fetch_random_url(self) -> dict[str, str | int | bool | None] | None:
        if pymysql is None:
            return {"status": "error", "message": "pymysql missing." if self.config.language == "en" else "Python-Paket 'pymysql' fehlt."}
        return self._get_url_service().fetch_random_url(self)

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
                self.reset_mondgesicht_excluded_nick_points()
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

    def seed_default_mondgesicht_texts(self, created_by: str, *, replace_existing: bool = False) -> tuple[bool, int]:
        from plugins.moonface.plugin import seed_default_mondgesicht_texts as _fn
        return _fn(self, created_by, replace_existing=replace_existing)

    def reset_mondgesicht_excluded_nick_points(self) -> None:
        from plugins.moonface.plugin import reset_mondgesicht_excluded_nick_points as _fn
        _fn(self)

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


def _run_bot_cycle(config: BotConfig, stop_event: threading.Event | None) -> tuple[bool, float, IRCBot]:
    bot = IRCBot(config)
    bot.setup_oidentd_conf()
    bot.ensure_database_setup()
    bot.ensure_admin_bootstrap(sys.stdin.isatty())
    connected_at = time.monotonic()
    should_stop = _execute_bot_cycle(bot, config, stop_event)
    uptime = time.monotonic() - connected_at
    return should_stop, uptime, bot


def _execute_bot_cycle(bot: IRCBot, config: BotConfig, stop_event: threading.Event | None) -> bool:
    try:
        print(f"[{config.display_name()}] " + bot.tr("connecting", server=config.server, port=config.port, tls=config.use_tls))
        bot.connect()
        bot.run()
        print(f"[{config.display_name()}] " + bot.tr("connection_closed"))
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            print(f"[{config.display_name()}] " + bot.tr("shutting_down"))
            if stop_event:
                stop_event.set()
            return True
        if isinstance(exc, OSError):
            print(f"[{config.display_name()}] " + bot.tr("network_error", error=exc))
            return False
        raise
    finally:
        bot.close()
    return False


def _wait_for_reconnect(stop_event: threading.Event | None, retry_wait: int) -> bool:
    if stop_event:
        return stop_event.wait(retry_wait)
    time.sleep(retry_wait)
    return False


def _next_retry_wait(base_retry_wait: int, current_retry_wait: int, max_retry_wait: int, uptime: float) -> int:
    if uptime >= 300:
        return base_retry_wait
    return min(max_retry_wait, max(base_retry_wait, current_retry_wait * 2))


def run_bot_forever(config: BotConfig, stop_event: threading.Event | None = None) -> None:
    base_retry_wait = max(30, config.reconnect_delay_seconds)
    retry_wait = base_retry_wait
    max_retry_wait = 300
    while not (stop_event and stop_event.is_set()):
        should_stop, uptime, bot = _run_bot_cycle(config, stop_event)
        if should_stop:
            break

        if stop_event and stop_event.is_set():
            break

        print(f"[{config.display_name()}] " + bot.tr("reconnect_in", seconds=retry_wait))
        if _wait_for_reconnect(stop_event, retry_wait):
            break

        retry_wait = _next_retry_wait(base_retry_wait, retry_wait, max_retry_wait, uptime)


def run_multiple_bots_forever(configs: list[BotConfig]) -> None:
    stop_event = threading.Event()
    threads = _start_bot_threads(configs, stop_event)

    try:
        _join_threads_until_stopped(threads)
    except KeyboardInterrupt:
        print("Beende Bots.")
    finally:
        stop_event.set()
        _join_alive_threads(threads, timeout=2)


def _start_bot_threads(configs: list[BotConfig], stop_event: threading.Event) -> list[threading.Thread]:
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
    return threads


def _join_threads_until_stopped(threads: list[threading.Thread]) -> None:
    while any(thread.is_alive() for thread in threads):
        for thread in threads:
            thread.join(timeout=0.5)


def _join_alive_threads(threads: list[threading.Thread], timeout: float) -> None:
    for thread in threads:
        if thread.is_alive():
            thread.join(timeout=timeout)


def _load_configs_or_exit() -> list[BotConfig]:
    config_path = Path(CONFIG_FILE_NAME)
    if not config_path.exists():
        raise SystemExit(CONFIG_MISSING_MESSAGE)

    try:
        return BotConfig.load_from_file(config_path)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _prepare_background_start() -> None:
    configs = _load_configs_or_exit()
    ensure_admin_bootstrap_for_configs(configs, sys.stdin.isatty())


def _setup_foreground_pid_handling(pid_file: Path) -> None:
    if pid_file.exists():
        raise SystemExit(f"Start verweigert: PID-Datei existiert bereits ({pid_file}).")

    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    atexit.register(lambda: remove_pid_file(pid_file))

    def _shutdown_handler(_signum, _frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)


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
        _prepare_background_start()
        start_background_process(pid_file)
        return

    if args.start:
        _prepare_background_start()
        start_background_process(pid_file)
        return

    configs = _load_configs_or_exit()

    if args.run_foreground:
        _setup_foreground_pid_handling(pid_file)

    if len(configs) == 1:
        run_bot_forever(configs[0])
        return

    print(f"Starte {len(configs)} Netzwerke parallel.")
    run_multiple_bots_forever(configs)


if __name__ == "__main__":
    main()
