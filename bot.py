import json
import base64
import argparse
import atexit
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
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

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

WEATHER_CODE_MAP_DE = {
    0: "klar",
    1: "ueberwiegend klar",
    2: "leicht bewolkt",
    3: "bewolkt",
    45: "Nebel",
    48: "Reifnebel",
    51: "leichter Nieselregen",
    53: "Nieselregen",
    55: "starker Nieselregen",
    61: "leichter Regen",
    63: "Regen",
    65: "starker Regen",
    71: "leichter Schneefall",
    73: "Schneefall",
    75: "starker Schneefall",
    80: "Regenschauer",
    81: "starke Regenschauer",
    82: "heftige Regenschauer",
    95: "Gewitter",
    96: "Gewitter mit Hagel",
    99: "Gewitter mit Hagel",
}

WEATHER_CODE_MAP_EN = {
    0: "clear",
    1: "mostly clear",
    2: "partly cloudy",
    3: "cloudy",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "drizzle",
    55: "dense drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    80: "rain showers",
    81: "strong rain showers",
    82: "violent rain showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with hail",
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
    flood_min_interval_ms: int = 700
    nick_protection_enabled: bool = False
    nick_protection_nick: str = ""
    nick_reclaim_interval_seconds: int = 60
    nickserv_password: str = ""
    nickserv_identify_command: str = "PRIVMSG NickServ :IDENTIFY {password}"
    oidentd_conf: str = ""
    network_key: str = ""
    reconnect_delay_seconds: int = 30
    url_timeout_seconds: float = 3.0
    url_sniff_max_bytes: int = 65536
    url_max_content_length_bytes: int = 2097152

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
            flood_min_interval_ms=max(0, int(raw.get("flood_min_interval_ms", 700))),
            nick_protection_enabled=bool(raw.get("nick_protection_enabled", False)),
            nick_protection_nick=str(raw.get("nick_protection_nick", nick)).strip(),
            nick_reclaim_interval_seconds=max(5, int(raw.get("nick_reclaim_interval_seconds", 60))),
            nickserv_password=str(raw.get("nickserv_password", "")),
            nickserv_identify_command=str(raw.get("nickserv_identify_command", "PRIVMSG NickServ :IDENTIFY {password}")),
            oidentd_conf=str(raw.get("oidentd_conf", "")).strip(),
            network_key=network_key,
            reconnect_delay_seconds=max(1, int(raw.get("reconnect_delay_seconds", 30))),
            url_timeout_seconds=max(0.5, float(raw.get("url_timeout_seconds", 3.0))),
            url_sniff_max_bytes=max(1024, int(raw.get("url_sniff_max_bytes", 65536))),
            url_max_content_length_bytes=max(65536, int(raw.get("url_max_content_length_bytes", 2097152))),
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
        self._send_lock = threading.RLock()
        self._url_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="urlsniff")

    def tr(self, key: str, **kwargs) -> str:
        language = self.config.language if self.config.language in {"de", "en"} else "de"
        messages = {
            "de": {
                "not_connected": "Nicht verbunden",
                "sasl_failed": "SASL-Authentifizierung fehlgeschlagen.",
                "nick_taken": "Nickname {old_nick} ist belegt, verwende {new_nick}",
                "channel_not_joinable": "Channel nicht joinbar, entferne aus Liste: {channel}",
                "help": "Befehle: {prefix}help, {prefix}ping, {prefix}echo <text>, {prefix}slap <nick>, {prefix}dart <nick>, {prefix}darttop10, {prefix}wetter <ort>, {prefix}url <id>, {prefix}randomurl",
                "lag_now": "Aktueller Lag: {ms} ms ({ns} ns)",
                "usage_echo": "Nutzung: {prefix}{command} <text>",
                "usage_slap": "Nutzung: {prefix}{command} <nick>",
                "usage_dart": "Nutzung: {prefix}{command} <nick>",
                "usage_weather": "Nutzung: {prefix}{command} <ort>",
                "usage_url": "Nutzung: {prefix}{command} <id>",
                "usage_url_with_max": "Nutzung: {prefix}{command} <id> (max: {max_id})",
                "url_not_found": "URL nicht gefunden.",
                "url_blocked": "URL geblockt (Spamverdacht).",
                "url_dead": "URL ist tot oder keine HTML-Seite.",
                "url_too_large": "URL ist zu gross zum Sniffen.",
                "url_max_id": "Max-ID {max_id}",
                "url_error": "URL Fehler: {message}",
                "url_no_html_topic": "{url} (kein HTML-Topic gefunden)",
                "url_without_title": "{url} :: {topic} (ohne title) (Requested by {requested_by})",
                "yt_channel": "Kanal {channel}",
                "yt_duration": "Dauer {duration}",
                "yt_published": "veröffentlicht {published}",
                "yt_views": "{count} Aufrufe",
                "yt_likes": "{count} Likes",
                "yt_comments": "{count} Kommentare",
                "weather_not_found": "Wetter für {location}: Ort nicht gefunden.",
                "weather_unreachable": "Wetter für {location}: Daten nicht erreichbar.",
                "weather_for": "Wetter für {location}: {temperature}°C, {condition}, gefühlt {feels_like}°C, Luftfeuchtigkeit {humidity}%, Niederschlag {precipitation} mm, Wind {wind_speed} km/h",
                "weather_short": "Wetter für {location}: {condition}",
                "weather_cc": "Wetter für {location}",
                "humidity": "Luftfeuchtigkeit",
                "precipitation": "Niederschlag",
                "wind": "Wind",
                "yt_api_no_metadata": "YouTube-API konnte keine Metadaten liefern.",
                "yt_invalid_id": "Keine gueltige YouTube-Video-ID gefunden.",
                "yt_missing_key": "YouTube-API-Key fehlt in der Konfiguration.",
                "yt_api_unreachable": "YouTube-API nicht erreichbar.",
                "unknown_error": "unbekannter Fehler",
                "yt_no_data": "YouTube-API lieferte keine Video-Daten.",
                "yt_no_title": "YouTube-API lieferte keinen Titel.",
                "unknown": "unbekannt",
                "dart_db_missing_pkg": "Fehler: Python-Paket 'pymysql' fehlt. Bitte 'pip install -r requirements.txt' ausfuehren.",
                "dart_db_unreachable": "Dart-DB nicht erreichbar: {error}",
                "dart_top_failed": "Dart-Top10 fehlgeschlagen: {error}",
                "dart_no_data": "Keine Dart-Daten vorhanden.",
                "dart_top": "Dart Top10: {items}",
                "dart_top_entry": "{index}. {nick} {points}P/{throws}W",
                "dart_hit": "{bot} benutzt {target} als Dartpfeil und trifft {hit} ({points} Punkte) (Requested by {requested_by})",
                "dart_destroy": "{bot} benutzt {target} als Dartpfeil und zerstoert die Dartscheibe! ({points} Punkte) ({hit}) (Requested by {requested_by})",
                "dart_stats_missing_pkg": "Dart-Stats nicht verfuegbar: Python-Paket 'pymysql' fehlt.",
                "dart_stats_unavailable": "Dart-Stats momentan nicht verfuegbar.",
                "dart_stats_empty": "Du hast noch keine Dart-Statistiken.",
                "dart_stats": "Deine Dart-Stats: {points} Punkte aus {throws} Würfen (Ø {average}) | Rang #{rank}/{total}",
                "db_setup_skip": "Hinweis: Konnte MySQL-Server nicht erreichen, DB-Setup wird uebersprungen.",
                "db_create_failed": "Hinweis: DB-Erstellung fehlgeschlagen: {error}",
                "db_connect_failed": "Hinweis: Konnte keine Verbindung zur Bot-Datenbank herstellen.",
                "db_table_setup_failed": "Hinweis: Tabellen-Setup fehlgeschlagen: {error}",
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
                "help": "Commands: {prefix}help, {prefix}ping, {prefix}echo <text>, {prefix}slap <nick>, {prefix}dart <nick>, {prefix}darttop10, {prefix}wetter <location>, {prefix}url <id>, {prefix}randomurl",
                "lag_now": "Current lag: {ms} ms ({ns} ns)",
                "usage_echo": "Usage: {prefix}{command} <text>",
                "usage_slap": "Usage: {prefix}{command} <nick>",
                "usage_dart": "Usage: {prefix}{command} <nick>",
                "usage_weather": "Usage: {prefix}{command} <location>",
                "usage_url": "Usage: {prefix}{command} <id>",
                "usage_url_with_max": "Usage: {prefix}{command} <id> (max: {max_id})",
                "url_not_found": "URL not found.",
                "url_blocked": "URL blocked (suspected spam).",
                "url_dead": "URL is dead or not an HTML page.",
                "url_too_large": "URL is too large to sniff.",
                "url_max_id": "Max ID {max_id}",
                "url_error": "URL error: {message}",
                "url_no_html_topic": "{url} (no HTML topic found)",
                "url_without_title": "{url} :: {topic} (without title) (Requested by {requested_by})",
                "yt_channel": "Channel {channel}",
                "yt_duration": "Duration {duration}",
                "yt_published": "published {published}",
                "yt_views": "{count} views",
                "yt_likes": "{count} likes",
                "yt_comments": "{count} comments",
                "weather_not_found": "Weather for {location}: location not found.",
                "weather_unreachable": "Weather for {location}: data unavailable.",
                "weather_for": "Weather for {location}: {temperature}°C, {condition}, feels like {feels_like}°C, humidity {humidity}%, precipitation {precipitation} mm, wind {wind_speed} km/h",
                "weather_short": "Weather for {location}: {condition}",
                "weather_cc": "Weather for {location}",
                "humidity": "Humidity",
                "precipitation": "Precipitation",
                "wind": "Wind",
                "yt_api_no_metadata": "YouTube API returned no metadata.",
                "yt_invalid_id": "No valid YouTube video ID found.",
                "yt_missing_key": "YouTube API key is missing in config.",
                "yt_api_unreachable": "YouTube API unavailable.",
                "unknown_error": "unknown error",
                "yt_no_data": "YouTube API returned no video data.",
                "yt_no_title": "YouTube API returned no title.",
                "unknown": "unknown",
                "dart_db_missing_pkg": "Error: Python package 'pymysql' is missing. Run 'pip install -r requirements.txt'.",
                "dart_db_unreachable": "Dart DB not reachable: {error}",
                "dart_top_failed": "Dart Top10 failed: {error}",
                "dart_no_data": "No dart data available.",
                "dart_top": "Dart Top 10: {items}",
                "dart_top_entry": "{index}. {nick} {points}pts/{throws}th",
                "dart_hit": "{bot} uses {target} as a dart and hits {hit} ({points} points) (Requested by {requested_by})",
                "dart_destroy": "{bot} uses {target} as a dart and destroys the dartboard! ({points} points) ({hit}) (Requested by {requested_by})",
                "dart_stats_missing_pkg": "Dart stats unavailable: Python package 'pymysql' is missing.",
                "dart_stats_unavailable": "Dart stats are currently unavailable.",
                "dart_stats_empty": "You do not have any dart stats yet.",
                "dart_stats": "Your dart stats: {points} points from {throws} throws (avg {average}) | Rank #{rank}/{total}",
                "db_setup_skip": "Notice: Could not reach MySQL server, skipping DB setup.",
                "db_create_failed": "Notice: DB creation failed: {error}",
                "db_connect_failed": "Notice: Could not connect to bot database.",
                "db_table_setup_failed": "Notice: Table setup failed: {error}",
                "config_missing": "config.json is missing. Copy config.example.json to config.json and adjust values.",
                "connecting": "Connecting to {server}:{port} (TLS={tls}) ...",
                "connection_closed": "Connection closed.",
                "network_error": "Network error: {error}",
                "shutting_down": "Stopping bot.",
                "reconnect_in": "Reconnect in {seconds} seconds ...",
            },
        }
        template = messages.get(language, messages["de"]).get(key, key)
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

    def remember_channel(self, channel: str) -> None:
        normalized_channel = channel.strip()
        if normalized_channel and normalized_channel not in self.config.channels:
            self.config.channels.append(normalized_channel)
        if normalized_channel:
            self.store_channel_if_missing(normalized_channel)

    def forget_channel(self, channel: str) -> None:
        normalized_channel = channel.strip()
        if not normalized_channel:
            return

        self.config.channels = [ch for ch in self.config.channels if ch.lower() != normalized_channel.lower()]
        self.channel_modes.pop(normalized_channel, None)
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
        self.startup_actions_completed = True

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
        aliases = {
            "help": ["help", "hilfe"],
            "ping": ["ping"],
            "pong": ["pong"],
            "lag": ["lag"],
            "echo": ["echo"],
            "slap": ["slap"],
            "dart": ["dart"],
            "darttop10": ["darttop10"],
            "mydartstats": ["mydartstats", "meinedartstats"],
            "weather": ["weather", "wetter"],
            "url": ["url"],
            "randomurl": ["randomurl", "zufallsurl"],
        }
        return aliases

    def primary_command_name(self, canonical: str) -> str:
        language = self.config.language
        if canonical == "help":
            return "hilfe" if language == "de" else "help"
        if canonical == "weather":
            return "wetter" if language == "de" else "weather"
        if canonical == "randomurl":
            return "zufallsurl" if language == "de" else "randomurl"
        if canonical == "mydartstats":
            return "meinedartstats" if language == "de" else "mydartstats"
        return canonical

    def resolve_command(self, token: str) -> str | None:
        lowered = token.lower()
        for canonical, aliases in self.command_aliases().items():
            if lowered in aliases:
                return canonical
        return None

    def build_help_text(self, prefix: str) -> str:
        ordered = ["help", "ping", "pong", "lag", "echo", "slap", "dart", "darttop10", "mydartstats", "weather", "url", "randomurl"]
        rendered = []
        for name in ordered:
            cmd = self.primary_command_name(name)
            if name in {"echo"}:
                rendered.append(f"{prefix}{cmd} <text>")
            elif name in {"slap", "dart"}:
                rendered.append(f"{prefix}{cmd} <nick>")
            elif name == "weather":
                rendered.append(f"{prefix}{cmd} <{'ort' if self.config.language == 'de' else 'location'}>")
            elif name == "url":
                rendered.append(f"{prefix}{cmd} <id>")
            else:
                rendered.append(f"{prefix}{cmd}")
        label = "Befehle" if self.config.language == "de" else "Commands"
        return f"{label}: " + ", ".join(rendered)

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

        for line in self.file:
            line = line.rstrip("\r\n")
            if not line:
                continue

            print(f"<<< {line}")

            if line.startswith("PING "):
                self.send_raw("PONG " + line[5:])
                continue

            prefix, command, params = self.parse_irc_line(line)

            self.try_reclaim_preferred_nick()

            if command == "CAP":
                self.handle_cap_message(params)
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
                continue

            if command == "JOIN" and len(params) >= 1:
                joined_channel = params[0].lstrip(":")
                joined_nick = prefix.split("!", 1)[0] if prefix else ""
                if joined_nick.lower() == self.current_nick.lower() and joined_channel:
                    self.remember_channel(joined_channel)
                    self.request_channel_modes(joined_channel)
                continue

            if command == "PART" and len(params) >= 1:
                parted_channel = params[0].lstrip(":")
                parted_nick = prefix.split("!", 1)[0] if prefix else ""
                if parted_nick.lower() == self.current_nick.lower() and parted_channel:
                    self.forget_channel(parted_channel)
                continue

            if command == "KICK" and len(params) >= 2:
                kicked_channel = params[0].lstrip(":")
                kicked_nick = params[1]
                if kicked_nick.lower() == self.current_nick.lower() and kicked_channel:
                    self.forget_channel(kicked_channel)
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
                    if inviter_nick:
                        self.send_action(
                            invited_channel,
                            f"slaps {inviter_nick} around a bit with a large {self.current_nick}",
                        )
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
                source_nick = prefix.split("!", 1)[0] if prefix else ""
                self.handle_privmsg(source_nick, target, message)

    def handle_privmsg(self, source_nick: str, target: str, message: str) -> None:
        self.schedule_url_sniff(message, target, source_nick)

        if re.search(r"\bunreal\b", message, re.IGNORECASE):
            action_target = source_nick if target.lower() == self.current_nick.lower() else target
            self.send_action(action_target, "rocketjumps!")

        prefix = self.config.command_prefix
        if not message.startswith(prefix):
            return

        cmdline = message[len(prefix) :].strip()
        if not cmdline:
            return

        parts = cmdline.split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        command = self.resolve_command(command) or command

        reply_target = source_nick if target.lower() == self.current_nick.lower() else target

        if command == "help":
            self.send_notice(source_nick, self.build_help_text(prefix))
            return

        if command == "ping":
            target_nick = arg.strip() if arg.strip() else source_nick
            self.send_action(reply_target, f"slaps {target_nick} around a bit with a large !pong")
            return

        if command == "pong":
            target_nick = arg.strip() if arg.strip() else source_nick
            self.send_action(reply_target, f"slaps {target_nick} around a bit with a large !ping")
            return

        if command == "lag":
            self.send_lag_probe(reply_target)
            return

        if command == "echo":
            if arg:
                self.send_notice(source_nick, arg)
            else:
                self.send_notice(source_nick, self.tr("usage_echo", prefix=prefix, command=self.primary_command_name("echo")))
            return

        if command == "slap":
            target_nick = arg.strip() if arg.strip() else source_nick
            if not target_nick:
                self.send_privmsg(reply_target, self.tr("usage_slap", prefix=prefix, command=self.primary_command_name("slap")))
                return

            self.send_action(
                reply_target,
                f"slaps {target_nick} around a bit with a large {self.current_nick}",
            )
            return

        if command == "dart":
            if arg.strip().lower() == "top10":
                leaderboard = self.get_dart_top10_text()
                self.send_privmsg(reply_target, leaderboard)
                return

            target_nick = arg.strip() if arg.strip() else source_nick
            if not target_nick:
                self.send_privmsg(reply_target, self.tr("usage_dart", prefix=prefix, command=self.primary_command_name("dart")))
                return

            stats_text = self.get_dart_stats_text(target_nick, source_nick)
            self.send_privmsg(reply_target, stats_text)
            return

        if command == "darttop10":
            leaderboard = self.get_dart_top10_text()
            self.send_privmsg(reply_target, leaderboard)
            return

        if command == "mydartstats":
            stats_text = self.get_my_dart_stats_text(source_nick)
            self.send_notice(source_nick, stats_text)
            return

        if command == "weather":
            weather_text = self.get_weather_text(arg.strip(), prefix, reply_target)
            self.send_privmsg(reply_target, weather_text)
            return

        if command == "url":
            if not arg.strip():
                self.send_privmsg(reply_target, self.build_url_usage_text(prefix))
                return

            url_id = self.parse_int(arg.strip())
            if url_id is None:
                self.send_privmsg(reply_target, self.build_url_usage_text(prefix))
                return

            result = self.fetch_url_by_id(url_id)
            self.handle_url_result(result, reply_target, requested_by=source_nick, show_max_id=True)
            return

        if command == "randomurl":
            result = self.fetch_random_url()
            self.handle_url_result(result, reply_target, requested_by=source_nick, show_max_id=True)
            return

    def build_url_usage_text(self, prefix: str) -> str:
        max_id = self.get_max_url_id()
        if max_id is None:
            return self.tr("usage_url", prefix=prefix, command=self.primary_command_name("url"))
        return self.tr("usage_url_with_max", prefix=prefix, command=self.primary_command_name("url"), max_id=max_id)

    def get_weather_text(self, location_query: str, command_prefix: str, reply_target: str) -> str:
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
        weather_map = WEATHER_CODE_MAP_EN if self.config.language == "en" else WEATHER_CODE_MAP_DE
        condition = weather_map.get(int(weather_code), f"Code {weather_code}") if weather_code is not None else self.tr("unknown")

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
            temperature=temperature,
            condition=condition,
            feels_like=feels_like,
            humidity=humidity,
            precipitation=precipitation,
            wind_speed=wind_speed,
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
                        "country": str(zip_data.get("country", "Deutschland")),
                        "latitude": latitude,
                        "longitude": longitude,
                    }

        geocode_url = (
            "https://nominatim.openstreetmap.org/search?"
            f"postalcode={quote(postal_code)}&countrycodes=de&format=jsonv2&limit=5&addressdetails=1"
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
                    return result

        return results[0]

    @staticmethod
    def safe_float(value: object) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def geocode_location_name(self, location: str) -> dict[str, object] | None:
        geocode_url = (
            "https://geocoding-api.open-meteo.com/v1/search?name="
            f"{quote(location)}&count=5&language=de&format=json"
        )

        geocode_data = self.fetch_json(geocode_url)
        if not geocode_data:
            return None

        results = geocode_data.get("results") or []
        if not results:
            return None

        return results[0]

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
        temp_text = f"\x0303{temperature}°C{reset}" if temperature is not None else "n/a"
        feel_text = f"{feels_like}°C" if feels_like is not None else "n/a"
        humidity_text = f"{humidity}%" if humidity is not None else "n/a"
        precipitation_text = f"{precipitation} mm" if precipitation is not None else "n/a"
        wind_text = f"{wind_speed} km/h" if wind_speed is not None else "n/a"
        direction_text = f"{wind_direction}°" if wind_direction is not None else "n/a"

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
        if points == 31337:
            return self.tr(
                "dart_destroy",
                bot=self.current_nick,
                target=target_nick,
                points=self.format_points(points),
                hit=hit_text,
                requested_by=requested_by,
            )

        return self.tr(
            "dart_hit",
            bot=self.current_nick,
            target=target_nick,
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
            self.send_privmsg(reply_target, f"{self.tr('url_dead')}{max_id_suffix}")
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
        topic_value = row.get("topic")
        topic = str(topic_value).strip() if topic_value is not None else ""
        if not topic:
            return None

        return {
            "status": "ok",
            "id": self.safe_int(row.get("id")),
            "url": str(row.get("url", "")),
            "topic": topic,
            "title_missing": bool(int(row.get("title_missing", 0) or 0)),
        }

    def fetch_url_topic(self, url: str) -> dict[str, str | int | bool | None]:
        if self.is_spammy(url):
            self.block_url(url)
            return {"status": "blocked", "url": url}

        try:
            max_sniff_bytes = self.config.url_sniff_max_bytes
            request = Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 IRCBot",
                    "Range": f"bytes=0-{max_sniff_bytes - 1}",
                },
            )
            with urlopen(request, timeout=self.config.url_timeout_seconds) as response:
                content_type = response.headers.get_content_type()
                if content_type not in {"text/html", "application/xhtml+xml"}:
                    self.mark_deadlink(url)
                    return {"status": "deadlink", "url": url}

                content_length = self.safe_int(response.headers.get("Content-Length"))
                if content_length is not None and content_length > self.config.url_max_content_length_bytes:
                    return {"status": "too_large", "url": url}

                raw_bytes = response.read(max_sniff_bytes + 1)
                if len(raw_bytes) > max_sniff_bytes:
                    return {"status": "too_large", "url": url}

                encoding = response.headers.get_content_charset() or "utf-8"
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


def run_bot_forever(config: BotConfig, stop_event: threading.Event | None = None) -> None:
    base_retry_wait = max(30, config.reconnect_delay_seconds)
    retry_wait = base_retry_wait
    max_retry_wait = 300
    while not (stop_event and stop_event.is_set()):
        bot = IRCBot(config)
        bot.setup_oidentd_conf()
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
        start_background_process(pid_file)
        return

    if args.start:
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
