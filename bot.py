#!/usr/bin/env python3

from __future__ import annotations

import importlib
import inspect
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

from plugins.url_service import URLService

try:
    _version_info = importlib.import_module("version_info")
    version_line = _version_info.version_line
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
    pymysql = importlib.import_module("pymysql")
except ImportError:
    pymysql = None


from plugin_system import MessageContext, PluginManager


URL_PATTERN = re.compile(r'https?://[^\s<>"]+', re.IGNORECASE)

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
INVALID_HOSTMASK_MESSAGE = "Invalid hostmask. Expected format: ident@host."
INVALID_CHANNEL_MESSAGE = "Invalid channel."
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
    perform: list[str] | None = None
    sasl_enabled: bool = False
    sasl_username: str = ""
    sasl_password: str = ""
    sasl_authzid: str = ""
    language: str = "en"
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

        language_raw = str(raw.get("language", "en")).strip().lower()
        language = language_raw if language_raw in {"de", "en"} else "en"

        def _parse_string_list(value: object) -> list[str]:
            if isinstance(value, str):
                return [value]
            if isinstance(value, list):
                return [str(item) for item in value]
            return []

        def _parse_string_dict(value: object) -> dict[str, str]:
            if not isinstance(value, dict):
                return {}

            parsed: dict[str, str] = {}
            for key, item in value.items():
                normalized_key = str(key).strip()
                normalized_value = str(item).strip()
                if normalized_key and normalized_value:
                    parsed[normalized_key] = normalized_value
            return parsed

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
                config = BotConfig._from_raw(merged)
                config.raw_config = merged
                configs.append(config)
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


class DatabaseConnection:
    def __init__(self, host, port, user, password, database):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database

    def open(self, with_database=True):
        if pymysql is None:
            return None

        def connect(password_value):
            db = self.database if with_database else None
            return pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=password_value,
                database=db,
                charset="utf8mb4",
                autocommit=True,
                connect_timeout=5,
                cursorclass=pymysql.cursors.DictCursor,
            )

        try:
            return connect(self.password)
        except UnicodeEncodeError:
            try:
                return connect(self.password.encode("utf-8"))
            except Exception:
                return None
        except Exception:
            return None

    def open_db(self):
        return self.open(with_database=True)

    def open_server(self):
        return self.open(with_database=False)


def create_database(db_conn, db_name):
    if not db_name or not all(c.isalnum() or c == "_" for c in db_name):
        raise ValueError(f"Invalid database name: {db_name}")
    with db_conn.cursor() as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )


class ChannelRepository:
    def __init__(self, db_conn, network_key):
        self.db_conn = db_conn
        self.network_key = network_key

    def load_saved(self):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute("SELECT channel FROM bot_channels WHERE network = %s ORDER BY channel ASC", (self.network_key,))
                rows = cur.fetchall() or []
            return [str(row.get("channel", "")).strip() for row in rows if str(row.get("channel", "")).strip()]
        except Exception:
            return []

    def store_if_missing(self, channel, current_time):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(
                    "INSERT IGNORE INTO bot_channels (network, channel, joined_at) VALUES (%s, %s, %s)",
                    (self.network_key, channel, current_time),
                )
        except Exception:
            pass

    def delete(self, channel):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute("DELETE FROM bot_channels WHERE network = %s AND channel = %s", (self.network_key, channel))
        except Exception:
            pass


def ensure_tables(bot, db_conn, network_key, current_time):
    for hook in bot.plugin_manager.get_hooks("ensure_tables"):
        try:
            sig = inspect.signature(hook)
            if len(sig.parameters) >= 3:
                hook(db_conn, network_key, current_time)
            else:
                hook(db_conn)
        except Exception as exc:
            print(f"Table setup failed: {exc}")
    with db_conn.cursor() as cur:
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


class IRCBot:
    def __init__(self, config: BotConfig, configured_peer_nicks: Iterable[str] | None = None) -> None:
        self.config = config
        self.raw_config = getattr(config, "raw_config", {})
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
        self.configured_peer_nicks = {nick.lower() for nick in (configured_peer_nicks or [])}
        self._pending_part_checks: dict[str, float] = {}
        self.plugin_manager = PluginManager(
            self, Path(__file__).resolve().parent / "plugins"
        )
        self.plugin_manager.call_config_hooks(self)
        self._db_connection = None

    @property
    def db(self):
        if self._db_connection is None:
            self._db_connection = DatabaseConnection(
                host=self.config.mysql_host,
                port=self.config.mysql_port,
                user=self.config.mysql_user,
                password=self.config.mysql_password,
                database=self.config.mysql_database,
            )
        return self._db_connection

    def _get_url_service(self):
        if self._url_service is None:
            self._url_service = URLService()
        return self._url_service

    def tr(self, key: str, **kwargs) -> str:
        language = self.config.language if self.config.language in {"de", "en"} else "en"
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
                "admin_prompt_mask": "Admin ident@host: ",
                "admin_prompt_password": "Admin Passwort: ",
                "admin_prompt_password_confirm": "Passwort wiederholen: ",
                "weather_appid_missing": "Weather-App-ID fehlt. Bitte weather_appid in der Konfiguration setzen.",
                "config_missing": "config.json fehlt. Kopiere config.example.json zu config.json und passe die Werte an.",
                "connecting": "Verbinde zu {server}:{port} (TLS={tls}) ...",
                "connection_closed": "Verbindung beendet.",
                "network_error": "Netzwerkfehler: {error}",
                "shutting_down": "Beende Bot.",
                "reconnect_in": "Reconnect in {seconds} Sekunden ...",
                "bot_part_other_bot_present": "Verlasse {channel}, da bereits ein anderer konfigurierter Bot ({nick}) anwesend ist.",
                "invalid_hostmask": "Ungültige Hostmask. Erwartet wird ident@host.",
                "invalid_channel": "Ungültiger Channel.",
                "invalid_nick": "Ungültiger Nick.",
                "admin_password_empty": "Passwort darf nicht leer sein.",
                "admin_password_mismatch": "Passwörter stimmen nicht überein.",
                "admin_password_wrong": "Passwort falsch.",
                "admin_login_success": "Login erfolgreich für {mask}.",
                "admin_channel_modes_applied": "Höchste Channel-Rechte gesetzt: {applied_count}.",
                "admin_help_header": "--- Admin-Befehle ---",
                "admin_role_admin_on": "Admin-Flag für Rolle {role} ist jetzt an.",
                "admin_role_admin_off": "Admin-Flag für Rolle {role} ist jetzt aus.",
                "admin_role_raw_on": "RAW-Flag für Rolle {role} ist jetzt an.",
                "admin_role_raw_off": "RAW-Flag für Rolle {role} ist jetzt aus.",
                "admin_role_created": "Rolle {role} angelegt.",
                "admin_role_exists": "Rolle {role} existiert bereits.",
                "admin_role_missing": "Rolle {role} existiert nicht.",
                "admin_user_created": "Benutzer {mask} mit Rolle {role} angelegt.",
                "admin_user_exists": "Benutzer {mask} existiert bereits.",
                "admin_user_deleted": "Benutzer {mask} gelöscht.",
                "admin_user_not_found": "Benutzer {mask} nicht gefunden.",
                "admin_role_set": "Rolle {role} für {mask} gesetzt.",
                "admin_no_configured_modes": "Keine Rechte für {mask} in {channel} konfiguriert.",
                "admin_modes_set": "Rollenrecht {role} {channel} +{mode} gesetzt.",
                "admin_modes_removed": "Rollenrecht {role} {channel} +{mode} entfernt.",
                "admin_user_modes_set": "Benutzerrecht {mask} {channel} +{mode} gesetzt.",
                "admin_user_modes_removed": "Benutzerrecht {mask} {channel} +{mode} entfernt.",
                "admin_session_expired": "Admin-Session abgelaufen.",
                "admin_session_revoked": "Admin-Session widerrufen.",
                "admin_access_denied": "Zugriff verweigert.",
                "admin_usage": "Nutzung: {prefix}{command} <subcommand> [args...]",
                "admin_invalid_role": "Ungültiger Rollenname. Erlaubt sind a-z, 0-9, _ und -.",
                "admin_invalid_channel": "Ungültiger Channel.",
                "admin_invalid_mode": "Ungültiger Modus.",
                "admin_invalid_user_mask": "Ungültige Hostmask. Erwartet wird ident@host.",
                "admin_db_unavailable": "Datenbank nicht erreichbar.",
                "admin_pymysql_missing": "Python-Paket 'pymysql' fehlt. Bitte 'pip install -r requirements.txt' ausführen.",
                "admin_command_not_found": "Befehl nicht gefunden.",
                "admin_help_not_available": "Keine Hilfe verfügbar.",
                "admin_raw_chat_logging_enabled": "RAW-Chat-Logging aktiviert.",
                "admin_raw_chat_logging_disabled": "RAW-Chat-Logging deaktiviert.",
                "no_running_bot": "Kein laufender Bot gefunden (PID-Datei fehlt oder ungueltig).",
                "stopping_bots": "Beende Bots.",
                "url_not_found": "URL nicht gefunden.",
                "url_blocked": "URL geblockt (Spamverdacht).",
                "url_dead": "URL ist tot oder keine HTML-Seite.",
                "url_dangerous_file": "⚠ Sicherheitswarnung",
                "url_too_large": "URL ist zu gross zum Sniffen.",
                "url_max_id": "Max-ID {max_id}",
                "url_error": "URL Fehler: {message}",
                "url_no_html_topic": "{url} (kein HTML-Topic gefunden)",
                "url_without_title_no_topic": "{url} (HTML-Seite ohne title oder Topic)",
                "url_without_title": "{url} :: {topic} (ohne title)",
                "url_requested_by_only": "angefragt von {requested_by}",
                "url_first_posted_by_only": "zuerst gepostet von {posted_by}",
                "url_first_posted_and_requested_by": "zuerst gepostet von {posted_by} | angefragt von {requested_by}",
                "yt_prefix": "YouTube",
                "yt_detail_channel_label": "Kanal",
                "yt_detail_published_label": "Veröffentlicht",
                "yt_detail_duration_label": "Dauer",
                "yt_detail_views_label": "Aufrufe",
                "yt_detail_likes_label": "Likes",
                "yt_detail_comments_label": "Kommentare",
                "yt_channel": "Kanal {channel}",
                "yt_duration": "Dauer {duration}",
                "yt_published": "veröffentlicht {published}",
                "yt_views": "{count} Aufrufe",
                "yt_likes": "{count} Likes",
                "yt_comments": "{count} Kommentare",
                "yt_api_no_metadata": "YouTube-API konnte keine Metadaten liefern.",
                "yt_invalid_id": "Keine gueltige YouTube-Video-ID gefunden.",
                "yt_missing_key": "YouTube-API-Key fehlt in der Konfiguration.",
                "yt_api_unreachable": "YouTube-API nicht erreichbar.",
                "unknown_error": "unbekannter Fehler",
                "yt_no_data": "YouTube-API lieferte keine Video-Daten.",
                "yt_no_title": "YouTube-API lieferte keinen Titel.",
                "unknown": "unbekannt",
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
                "admin_prompt_mask": "Admin ident@host: ",
                "admin_prompt_password": "Admin password: ",
                "admin_prompt_password_confirm": "Repeat password: ",
                "weather_appid_missing": "Weather app ID is missing. Please set weather_appid in the configuration.",
                "config_missing": "config.json is missing. Copy config.example.json to config.json and adjust values.",
                "connecting": "Connecting to {server}:{port} (TLS={tls}) ...",
                "connection_closed": "Connection closed.",
                "network_error": "Network error: {error}",
                "shutting_down": "Stopping bot.",
                "reconnect_in": "Reconnect in {seconds} seconds ...",
                "bot_part_other_bot_present": "Leaving {channel} because another configured bot ({nick}) is already present.",
                "invalid_hostmask": "Invalid hostmask. Expected format: ident@host.",
                "invalid_channel": "Invalid channel.",
                "invalid_nick": "Invalid nick.",
                "admin_password_empty": "Password cannot be empty.",
                "admin_password_mismatch": "Passwords do not match.",
                "admin_password_wrong": "Incorrect password.",
                "admin_login_success": "Login successful for {mask}.",
                "admin_channel_modes_applied": "Highest channel modes set: {applied_count}.",
                "admin_help_header": "--- Admin Commands ---",
                "admin_role_admin_on": "Admin flag for role {role} is now enabled.",
                "admin_role_admin_off": "Admin flag for role {role} is now disabled.",
                "admin_role_raw_on": "RAW flag for role {role} is now enabled.",
                "admin_role_raw_off": "RAW flag for role {role} is now disabled.",
                "admin_role_created": "Role {role} created.",
                "admin_role_exists": "Role {role} already exists.",
                "admin_role_missing": "Role {role} does not exist.",
                "admin_user_created": "User {mask} with role {role} created.",
                "admin_user_exists": "User {mask} already exists.",
                "admin_user_deleted": "User {mask} deleted.",
                "admin_user_not_found": "User {mask} not found.",
                "admin_role_set": "Role {role} set for {mask}.",
                "admin_no_configured_modes": "No modes configured for {mask} in {channel}.",
                "admin_modes_set": "Role right {role} {channel} +{mode} set.",
                "admin_modes_removed": "Role right {role} {channel} +{mode} removed.",
                "admin_user_modes_set": "User right {mask} {channel} +{mode} set.",
                "admin_user_modes_removed": "User right {mask} {channel} +{mode} removed.",
                "admin_session_expired": "Admin session expired.",
                "admin_session_revoked": "Admin session revoked.",
                "admin_access_denied": "Access denied.",
                "admin_usage": "Usage: {prefix}{command} <subcommand> [args...]",
                "admin_invalid_role": "Invalid role name. Allowed: a-z, 0-9, _ and -.",
                "admin_invalid_channel": "Invalid channel.",
                "admin_invalid_mode": "Invalid mode.",
                "admin_invalid_user_mask": "Invalid hostmask. Expected format: ident@host.",
                "admin_db_unavailable": "Database unavailable.",
                "admin_pymysql_missing": "Python package 'pymysql' is missing. Run 'pip install -r requirements.txt'.",
                "admin_command_not_found": "Command not found.",
                "admin_help_not_available": "No help available.",
                "admin_raw_chat_logging_enabled": "RAW chat logging enabled.",
                "admin_raw_chat_logging_disabled": "RAW chat logging disabled.",
                "no_running_bot": "No running bot found (PID file missing or invalid).",
                "stopping_bots": "Stopping bots.",
                "url_not_found": "URL not found.",
                "url_blocked": "URL blocked (suspected spam).",
                "url_dead": "URL is dead or not an HTML page.",
                "url_dangerous_file": "⚠ Security warning",
                "url_too_large": "URL is too large to sniff.",
                "url_max_id": "Max ID {max_id}",
                "url_error": "URL error: {message}",
                "url_no_html_topic": "{url} (no HTML topic found)",
                "url_without_title_no_topic": "{url} (HTML page without title or topic)",
                "url_without_title": "{url} :: {topic} (without title)",
                "url_requested_by_only": "requested by {requested_by}",
                "url_first_posted_by_only": "first posted by {posted_by}",
                "url_first_posted_and_requested_by": "first posted by {posted_by} | requested by {requested_by}",
                "yt_prefix": "YouTube",
                "yt_detail_channel_label": "Channel",
                "yt_detail_published_label": "Published",
                "yt_detail_duration_label": "Duration",
                "yt_detail_views_label": "Views",
                "yt_detail_likes_label": "Likes",
                "yt_detail_comments_label": "Comments",
                "yt_channel": "Channel {channel}",
                "yt_duration": "Duration {duration}",
                "yt_published": "published {published}",
                "yt_views": "{count} views",
                "yt_likes": "{count} likes",
                "yt_comments": "{count} comments",
                "yt_api_no_metadata": "YouTube API returned no metadata.",
                "yt_invalid_id": "No valid YouTube video ID found.",
                "yt_missing_key": "YouTube API key is missing in config.",
                "yt_api_unreachable": "YouTube API unavailable.",
                "unknown_error": "unknown error",
                "yt_no_data": "YouTube API returned no video data.",
                "yt_no_title": "YouTube API returned no title.",
                "unknown": "unknown",
            },
        }
        plugin_manager = getattr(self, "plugin_manager", None)
        plugin_template = None if plugin_manager is None else plugin_manager.translation(key, language)
        if plugin_template is None and language != "de" and plugin_manager is not None:
            plugin_template = plugin_manager.translation(key, "de")

        template = plugin_template
        if template is None:
            template = core_messages.get(language, core_messages["en"]).get(
                key,
                core_messages["en"].get(key, key),
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
            if self.configured_peer_nicks:
                self._pending_part_checks[self.normalize_channel_name(joined_channel)] = time.monotonic()
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
        if self.configured_peer_nicks:
            self._pending_part_checks[self.normalize_channel_name(invited_channel)] = time.monotonic()
        if inviter_nick:
            self.send_action(
                invited_channel,
                f"slaps {inviter_nick} around a bit with a large {self.current_nick}",
            )

    def _handle_names_reply(self, names_channel: str, names_param: str) -> None:
        names_members = names_param.lstrip(":").split()
        self.add_channel_members(names_channel, names_members)
        normalized = self.normalize_channel_name(names_channel)
        pending = self._pending_part_checks.get(normalized)
        if pending is not None and self.configured_peer_nicks:
            if time.monotonic() - pending > 10.0:
                del self._pending_part_checks[normalized]
            else:
                for member in names_members:
                    cleaned = self.normalize_channel_member_nick(member)
                    if cleaned and cleaned.lower() in self.configured_peer_nicks:
                        self.send_privmsg(names_channel, self.tr("bot_part_other_bot_present", channel=names_channel, nick=cleaned))
                        self.send_raw(f"PART {names_channel}")
                        self.forget_channel(names_channel)
                        del self._pending_part_checks[normalized]
                        break
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

    def format_target_nick(self, target_nick: str) -> str:
        if target_nick.lower() == self.current_nick.lower():
            return self.tr("self_target")
        return target_nick

    def get_weather_text(self, location_query: str, command_prefix: str, reply_target: str) -> str:
        location = location_query.strip() or getattr(self, "_weather_default_location", "").strip()
        if not location:
            return self.tr("usage_weather", prefix=command_prefix, command=self.primary_command_name("weather"))
        return self.render_openweather_weather_text(location, reply_target)

    def render_openweather_weather_text(self, location: str, reply_target: str) -> str:
        if not getattr(self, "_weather_appid", "").strip():
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
            f"&appid={quote_plus(getattr(self, '_weather_appid', ''))}"
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
        return self.db.open_db()

    def open_server_connection(self):
        return self.db.open_server()

    def ensure_database_setup(self) -> None:
        if self.db_initialized or pymysql is None:
            return

        server_conn = self.open_server_connection()
        if server_conn is None:
            print(self.tr("db_setup_skip"))
            return

        try:
            with server_conn.cursor() as cur:
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
            ensure_tables(self, conn, self.config.network_key, self.current_time_string())
            for hook in self.plugin_manager.get_hooks("ensure_schema"):
                hook(conn.cursor(), self.config.mysql_database)
            for hook in self.plugin_manager.get_hooks("seed_database"):
                hook(self, self.current_time_string())
            self.db_initialized = True
        except Exception as exc:
            print(self.tr("db_table_setup_failed", error=exc))
        finally:
            conn.close()

    def load_saved_channels(self) -> list[str]:
        conn = self.open_db_connection()
        if conn is None:
            return []
        try:
            return ChannelRepository(conn, self.config.network_key).load_saved()
        finally:
            conn.close()

    def store_channel_if_missing(self, channel: str) -> None:
        conn = self.open_db_connection()
        if conn is None:
            return
        try:
            ChannelRepository(conn, self.config.network_key).store_if_missing(channel, self.current_time_string())
        finally:
            conn.close()

    def delete_saved_channel(self, channel: str) -> None:
        conn = self.open_db_connection()
        if conn is None:
            return
        try:
            ChannelRepository(conn, self.config.network_key).delete(channel)
        finally:
            conn.close()

    def parse_rss_announce_channels(self, value: str) -> list[str]:
        channels: list[str] = []
        for token in value.replace(";", ",").split(","):
            normalized = self.normalize_channel_name(token)
            if normalized.startswith("#") and normalized not in channels:
                channels.append(normalized)
        return channels

    def load_rss_announce_channels_from_cursor(self, cur) -> list[str]:
        cur.execute(
            "SELECT channel FROM bot_rss_announce_channels WHERE network = %s ORDER BY channel ASC",
            (self.config.network_key,),
        )
        rows = cur.fetchall() or []

        channels: list[str] = []
        for row in rows:
            channel = self.normalize_channel_name(str(row.get("channel", "")).strip())
            if channel.startswith("#") and channel not in channels:
                channels.append(channel)
        return channels

    def seed_rss_announce_channels(self, cur, channels: list[str]) -> None:
        if not channels:
            return
        now = self.current_time_string()
        for channel in channels:
            cur.execute(
                """
                INSERT IGNORE INTO bot_rss_announce_channels (network, channel, updated_at)
                VALUES (%s, %s, %s)
                """,
                (self.config.network_key, channel, now),
            )

    def set_rss_announce_channel(self, channel: str) -> tuple[bool, str]:
        normalized_channel = self.normalize_channel_name(channel)
        hook = self.plugin_manager.get_hook("set_rss_announce_channels")
        if not normalized_channel:
            return hook(self, []) if hook is not None else (False, "")
        if not normalized_channel.startswith("#"):
            return False, self.tr("invalid_channel")
        return hook(self, [normalized_channel]) if hook is not None else (False, "")

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
        hook = self.plugin_manager.get_hook("has_admin_users")
        return bool(hook(self)) if hook is not None else False

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
            entered_mask = input(self.tr("admin_prompt_mask")).strip()
            normalized_mask = self.normalize_user_mask(entered_mask)
            if normalized_mask is None:
                print(self.tr("invalid_hostmask"))
                continue
            admin_mask = normalized_mask

        password = ""
        while not password:
            first = getpass.getpass(self.tr("admin_prompt_password"))
            second = getpass.getpass(self.tr("admin_prompt_password_confirm"))
            if not first:
                print(self.tr("admin_password_empty"))
                continue
            if first != second:
                print(self.tr("admin_password_mismatch"))
                continue
            password = first

        hook = self.plugin_manager.get_hook("ensure_default_admin_role")
        if hook is not None:
            hook(self)

        hook = self.plugin_manager.get_hook("hash_admin_password")
        salt_hex, hash_hex = hook(password) if hook is not None else (None, None)
        hook = self.plugin_manager.get_hook("create_admin_user")
        created_user, user_message = hook(
            self,
            display_name="bootstrap",
            user_mask=admin_mask,
            password=password,
            role_name="admin",
            created_by="bootstrap",
        ) if hook is not None else (False, "")
        if not created_user:
            print(user_message)
            print(self.tr("admin_bootstrap_skipped"))
            return

        print(self.tr("admin_bootstrap_created", mask=admin_mask, network=self.config.network_key))

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

        hook = self.plugin_manager.get_hook("load_admin_user")
        row = hook(self, normalized_mask) if hook is not None else None
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
        hook = self.plugin_manager.get_hook("load_admin_user")
        row = hook(self, user_mask) if hook is not None else None
        if row is None:
            return False, "Unbekannte Hostmask."

        salt = str(row.get("password_salt", ""))
        expected_hash = str(row.get("password_hash", ""))
        if not salt or not expected_hash or not self.verify_admin_password(password, salt, expected_hash):
            return False, self.tr("admin_password_wrong")

        normalized_mask = self.normalize_user_mask(user_mask)
        if normalized_mask is None:
            return False, self.tr("invalid_hostmask")

        self._admin_sessions[normalized_mask] = {
            "expires_at": time.time() + ADMIN_SESSION_TTL_SECONDS,
            "nick": nick.strip(),
        }
        applied_count = self.apply_login_modes_for_user(normalized_mask, nick.strip())
        suffix = self.tr("admin_channel_modes_applied", applied_count=applied_count) if applied_count > 0 else ""
        return True, f"{self.tr('admin_login_success', mask=normalized_mask)}{suffix}"

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

    def apply_login_modes_for_user(self, user_mask: str, nick: str) -> int:
        normalized_mask = self.normalize_user_mask(user_mask)
        target_nick = nick.strip()
        if normalized_mask is None or not target_nick:
            return 0

        applied = 0
        hook = self.plugin_manager.get_hook("get_user_assigned_channels")
        for channel in (hook(self, normalized_mask) if hook is not None else ()):
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
        hook_channels = self.plugin_manager.get_hook("get_user_assigned_channels")
        hook_modes = self.plugin_manager.get_hook("get_configured_user_channel_modes")
        for channel in (hook_channels(self, normalized_mask) if hook_channels is not None else ()):
            modes = hook_modes(self, normalized_mask, channel) if hook_modes is not None else ()
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

    def apply_channel_modes_for_mask(self, channel: str, nick: str, user_mask: str) -> tuple[bool, str]:
        normalized_mask = self.normalize_user_mask(user_mask)
        normalized_channel = self.normalize_channel_name(channel)
        target_nick = self.strip_channel_member_prefixes(nick)
        if normalized_mask is None:
            return False, self.tr("invalid_hostmask")
        if not normalized_channel.startswith("#"):
            return False, self.tr("invalid_channel")
        if not target_nick:
            return False, self.tr("invalid_nick")

        if not self.is_nick_in_channel(normalized_channel, self.current_nick):
            return False, f"Bot ist nicht in {normalized_channel}."
        if not self.is_nick_in_channel(normalized_channel, target_nick):
            return False, f"Nick {target_nick} ist nicht in {normalized_channel}."

        hook = self.plugin_manager.get_hook("get_configured_user_channel_modes")
        modes = hook(self, normalized_mask, normalized_channel) if hook is not None else ()
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
        print("No running bot found (PID file missing or invalid).")
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


def _run_bot_cycle(config: BotConfig, stop_event: threading.Event | None, configured_peer_nicks: set[str] | None = None) -> tuple[bool, float, IRCBot]:
    bot = IRCBot(config, configured_peer_nicks)
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


def run_bot_forever(config: BotConfig, stop_event: threading.Event | None = None, configured_peer_nicks: set[str] | None = None) -> None:
    base_retry_wait = max(30, config.reconnect_delay_seconds)
    retry_wait = base_retry_wait
    max_retry_wait = 300
    while not (stop_event and stop_event.is_set()):
        should_stop, uptime, bot = _run_bot_cycle(config, stop_event, configured_peer_nicks)
        if should_stop:
            break

        if stop_event and stop_event.is_set():
            break

        print(f"[{config.display_name()}] " + bot.tr("reconnect_in", seconds=retry_wait))
        if _wait_for_reconnect(stop_event, retry_wait):
            break

        retry_wait = _next_retry_wait(base_retry_wait, retry_wait, max_retry_wait, uptime)


def run_multiple_bots_forever(configs: list[BotConfig], peer_nicks_by_config: dict[str, set[str]]) -> None:
    stop_event = threading.Event()
    threads = _start_bot_threads(configs, stop_event, peer_nicks_by_config)

    try:
        _join_threads_until_stopped(threads)
    except KeyboardInterrupt:
        print("Stopping bots.")
    finally:
        stop_event.set()
        _join_alive_threads(threads, timeout=2)


def _start_bot_threads(configs: list[BotConfig], stop_event: threading.Event, peer_nicks_by_config: dict[str, set[str]]) -> list[threading.Thread]:
    threads: list[threading.Thread] = []
    for config in configs:
        thread = threading.Thread(
            target=run_bot_forever,
            args=(config, stop_event, peer_nicks_by_config.get(config.network_key)),
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

    peer_nicks_by_config = _build_peer_nicks(configs)
    print(f"Starte {len(configs)} Netzwerke parallel.")
    run_multiple_bots_forever(configs, peer_nicks_by_config)


def _build_peer_nicks(configs: list[BotConfig]) -> dict[str, set[str]]:
    by_network: dict[str, set[str]] = {}
    for config in configs:
        key = f"{config.server}:{config.port}"
        by_network.setdefault(key, set()).add(config.nick)

    return {
        config.network_key: (by_network.get(f"{config.server}:{config.port}", set()) - {config.nick})
        for config in configs
    }


if __name__ == "__main__":
    main()
