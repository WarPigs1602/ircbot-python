from __future__ import annotations

import hashlib
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import unescape
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from plugin_system import CommandSpec, PluginSpec, TickHandlerSpec

try:
    import pymysql
except ImportError:
    pymysql = None

RSS_ANNOUNCE_CHANNELS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS bot_rss_announce_channels (
    network VARCHAR(255) NOT NULL,
    channel VARCHAR(128) NOT NULL,
    updated_at VARCHAR(32) NOT NULL,
    PRIMARY KEY (network, channel),
    KEY idx_bot_rss_announce_channels_lookup (network, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


class RSSRepository:
    def __init__(self, db_conn, network_key):
        self.db_conn = db_conn
        self.network_key = network_key

    def get_announce_channels(self, current_time, fallback_channels):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(RSS_ANNOUNCE_CHANNELS_TABLE_SQL)
                cur.execute(
                    "SELECT channel FROM bot_rss_announce_channels WHERE network = %s ORDER BY channel ASC",
                    (self.network_key,),
                )
                rows = cur.fetchall() or []
                db_channels = []
                for row in rows:
                    channel = _normalize_channel(row.get("channel", ""))
                    if channel.startswith("#"):
                        db_channels.append(channel)
                if db_channels:
                    return tuple(db_channels)
                for channel in fallback_channels:
                    cur.execute(
                        "INSERT IGNORE INTO bot_rss_announce_channels (network, channel, updated_at) VALUES (%s, %s, %s)",
                        (self.network_key, channel, current_time),
                    )
                return tuple(fallback_channels)
        except Exception:
            return tuple(fallback_channels)

    def set_announce_channels(self, channels, current_time):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(RSS_ANNOUNCE_CHANNELS_TABLE_SQL)
                cur.execute("DELETE FROM bot_rss_announce_channels WHERE network = %s", (self.network_key,))
                for channel in channels:
                    cur.execute(
                        "INSERT INTO bot_rss_announce_channels (network, channel, updated_at) VALUES (%s, %s, %s)",
                        (self.network_key, channel, current_time),
                    )
            return True
        except Exception:
            return False

    def ensure_seen_table(self):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_rss_seen (
                        network VARCHAR(255) NOT NULL,
                        feed_alias VARCHAR(128) NOT NULL,
                        entry_hash CHAR(64) NOT NULL,
                        entry_id VARCHAR(512) NOT NULL DEFAULT '',
                        entry_link VARCHAR(2048) NOT NULL DEFAULT '',
                        entry_title VARCHAR(512) NOT NULL DEFAULT '',
                        seen_at VARCHAR(32) NOT NULL,
                        PRIMARY KEY (network, feed_alias, entry_hash),
                        KEY idx_bot_rss_seen_lookup (network, feed_alias, seen_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            return True
        except Exception:
            return False

    def register_seen_entry(self, feed_alias, entry_hash, entry_id, entry_link, entry_title, seen_at):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS total_entries FROM bot_rss_seen WHERE network = %s AND feed_alias = %s",
                    (self.network_key, feed_alias),
                )
                row = cur.fetchone() or {}
                known_entries = int(row.get("total_entries", 0) or 0)

                cur.execute(
                    """
                    INSERT IGNORE INTO bot_rss_seen
                        (network, feed_alias, entry_hash, entry_id, entry_link, entry_title, seen_at)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self.network_key,
                        feed_alias,
                        entry_hash,
                        entry_id,
                        entry_link,
                        entry_title,
                        seen_at,
                    ),
                )
                return cur.rowcount > 0, known_entries > 0
        except Exception:
            return False, False


def _normalize_channel(value: str) -> str:
    return str(value).strip().lower()


USER_AGENT = "Mozilla/5.0 IRCBot RSS"
MAX_FEED_BYTES = 1024 * 1024
MAX_REPLY_LENGTH = 320
RSS_POLL_INTERVAL_SECONDS = 600.0


MESSAGES = {
    "de": {
        "usage_rss": "Nutzung: {prefix}{command} <feed|url>",
        "rss_available_feeds": "Verfuegbare RSS-Feeds: {feeds}",
        "rss_invalid_target": "Bitte Feed-Alias oder http(s)-URL angeben.",
        "rss_http_error": "RSS-Feed antwortete mit HTTP {status}: {target}",
        "rss_fetch_failed": "RSS-Feed nicht erreichbar: {target}",
        "rss_too_large": "RSS-Feed ist zu gross: {target}",
        "rss_invalid_feed": "Kein gueltiger RSS/Atom-Feed: {target}",
        "rss_no_entries": "RSS-Feed enthaelt keine Eintraege: {target}",
        "rss_latest_entry": "{feed}: {title} - {link}",
        "rss_latest_entry_no_link": "{feed}: {title}",
        "rss_latest_link_only": "{feed}: {link}",
    },
    "en": {
        "usage_rss": "Usage: {prefix}{command} <feed|url>",
        "rss_available_feeds": "Available RSS feeds: {feeds}",
        "rss_invalid_target": "Please provide a feed alias or an http(s) URL.",
        "rss_http_error": "RSS feed returned HTTP {status}: {target}",
        "rss_fetch_failed": "RSS feed unavailable: {target}",
        "rss_too_large": "RSS feed is too large: {target}",
        "rss_invalid_feed": "Not a valid RSS/Atom feed: {target}",
        "rss_no_entries": "RSS feed has no entries: {target}",
        "rss_latest_entry": "{feed}: {title} - {link}",
        "rss_latest_entry_no_link": "{feed}: {title}",
        "rss_latest_link_only": "{feed}: {link}",
    },
}


@dataclass(frozen=True)
class FeedEntry:
    feed_title: str
    entry_title: str
    entry_link: str
    entry_id: str


def _get_rss_feeds(bot) -> dict[str, str]:
    return dict(getattr(bot, "_rss_feeds", {}) or {})


def _get_rss_announce_channel(bot) -> str:
    return str(getattr(bot, "_rss_announce_channel", "") or "").strip()


def handle_rss(bot, context, arg: str) -> None:
    raw_target = arg.strip()
    configured_feeds = _get_rss_feeds(bot)
    if not raw_target:
        bot.send_privmsg(context.reply_target, bot.tr("usage_rss", prefix=context.command_prefix, command=bot.primary_command_name("rss")))
        if configured_feeds:
            aliases = ", ".join(sorted(configured_feeds, key=str.lower))
            bot.send_privmsg(context.reply_target, bot.tr("rss_available_feeds", feeds=aliases))
        return

    target_url = resolve_feed_target(raw_target, configured_feeds)
    if not target_url:
        bot.send_privmsg(context.reply_target, bot.tr("rss_invalid_target"))
        return

    result = fetch_latest_entry(target_url, timeout_seconds=float(getattr(bot.config, "url_timeout_seconds", 3.0)))
    status = str(result.get("status", ""))
    if status == "http_error":
        bot.send_privmsg(context.reply_target, bot.tr("rss_http_error", status=result.get("http_status", "?"), target=raw_target))
        return
    if status == "fetch_failed":
        bot.send_privmsg(context.reply_target, bot.tr("rss_fetch_failed", target=raw_target))
        return
    if status == "too_large":
        bot.send_privmsg(context.reply_target, bot.tr("rss_too_large", target=raw_target))
        return
    if status == "invalid_feed":
        bot.send_privmsg(context.reply_target, bot.tr("rss_invalid_feed", target=raw_target))
        return
    if status == "no_entries":
        bot.send_privmsg(context.reply_target, bot.tr("rss_no_entries", target=raw_target))
        return

    entry = result.get("entry")
    if not isinstance(entry, FeedEntry):
        bot.send_privmsg(context.reply_target, bot.tr("rss_fetch_failed", target=raw_target))
        return

    display_name = entry.feed_title or raw_target
    reply = render_feed_reply(bot, display_name, entry.entry_title, entry.entry_link)
    bot.send_privmsg(context.reply_target, reply)


def handle_tick(bot) -> None:
    configured_feeds = _get_rss_feeds(bot)
    if not configured_feeds:
        return

    announce_channels = resolve_announce_channels(bot)
    if not announce_channels:
        return

    now_monotonic = time.monotonic()
    if not should_run_periodic_poll(bot, now_monotonic):
        return

    if not ensure_seen_entries_table(bot):
        return

    for feed_alias, entry in iter_new_entries(bot, configured_feeds):
        display_name = entry.feed_title or str(feed_alias)
        message = render_feed_reply(bot, display_name, entry.entry_title, entry.entry_link)
        for channel in announce_channels:
            bot.send_privmsg(channel, message)


def get_rss_announce_channels(bot) -> tuple[str, ...]:
    if pymysql is None:
        return ()

    fallback_channels = [
        channel.strip()
        for channel in _get_rss_announce_channel(bot).replace(";", ",").split(",")
        if channel.strip().startswith("#")
    ]

    conn = bot.open_db_connection()
    if conn is None:
        return tuple(fallback_channels)

    try:
        return RSSRepository(conn, bot.config.network_key).get_announce_channels(
            bot.current_time_string(), fallback_channels
        )
    finally:
        conn.close()


def set_rss_announce_channels(bot, channels: list[str]) -> tuple[bool, str]:
    if pymysql is None:
        return False, "pymysql missing"

    normalized_channels: list[str] = []
    for channel in channels:
        normalized = bot.normalize_channel_name(channel)
        if not normalized or not normalized.startswith("#"):
            return False, "Ungueltiger Channel."
        if normalized not in normalized_channels:
            normalized_channels.append(normalized)

    conn = bot.open_db_connection()
    if conn is None:
        return False, "DB connection failed"

    try:
        return RSSRepository(conn, bot.config.network_key).set_announce_channels(
            normalized_channels, bot.current_time_string()
        ), ""
    except Exception as exc:
        return False, str(exc)
    finally:
        conn.close()


def resolve_announce_channels(bot) -> tuple[str, ...]:
    channels = get_rss_announce_channels(bot)
    if channels:
        return channels

    fallback = _get_rss_announce_channel(bot)
    return (fallback,) if fallback else ()


def iter_new_entries(bot, configured_feeds: dict[str, str]):
    timeout_seconds = float(getattr(bot.config, "url_timeout_seconds", 3.0))
    for feed_alias, feed_url in sorted(configured_feeds.items(), key=lambda item: item[0].lower()):
        target_url = str(feed_url).strip()
        if not target_url.lower().startswith(("http://", "https://")):
            continue

        result = fetch_latest_entry(target_url, timeout_seconds=timeout_seconds)
        entry = result.get("entry")
        if str(result.get("status", "")) != "ok" or not isinstance(entry, FeedEntry):
            continue
        if not register_seen_entry(bot, str(feed_alias), entry):
            continue
        yield str(feed_alias), entry


def should_run_periodic_poll(bot, now_monotonic: float) -> bool:
    last_run = float(getattr(bot, "_rss_poll_last_run", 0.0) or 0.0)
    if now_monotonic - last_run < RSS_POLL_INTERVAL_SECONDS:
        return False
    setattr(bot, "_rss_poll_last_run", now_monotonic)
    return True


def ensure_seen_entries_table(bot) -> bool:
    if bool(getattr(bot, "_rss_seen_table_ready", False)):
        return True

    conn = bot.open_db_connection()
    if conn is None:
        return False

    try:
        result = RSSRepository(conn, bot.config.network_key).ensure_seen_table()
        setattr(bot, "_rss_seen_table_ready", result)
        return result
    finally:
        conn.close()


def register_seen_entry(bot, feed_alias: str, entry: FeedEntry) -> bool:
    conn = bot.open_db_connection()
    if conn is None:
        return False

    entry_hash = build_entry_hash(entry)
    seen_at = str(int(time.time()))

    try:
        inserted, known = RSSRepository(conn, bot.config.network_key).register_seen_entry(
            feed_alias, entry_hash,
            normalize_text(entry.entry_id),
            normalize_text(entry.entry_link),
            normalize_text(entry.entry_title),
            seen_at,
        )
    finally:
        conn.close()

    if not inserted:
        return False

    return known


def build_entry_hash(entry: FeedEntry) -> str:
    unique_id = normalize_text(entry.entry_id)
    unique_link = normalize_text(entry.entry_link)
    unique_title = normalize_text(entry.entry_title)
    payload = "\n".join((unique_id, unique_link, unique_title)).encode("utf-8", errors="ignore")
    return hashlib.sha256(payload).hexdigest()


def resolve_feed_target(raw_target: str, configured_feeds: dict[str, str]) -> str | None:
    normalized_target = raw_target.strip()
    if not normalized_target:
        return None

    for alias, url in configured_feeds.items():
        if alias.strip().lower() == normalized_target.lower():
            return url.strip()

    lowered_target = normalized_target.lower()
    if lowered_target.startswith(("http://", "https://")):
        return normalized_target
    return None


def fetch_latest_entry(url: str, timeout_seconds: float) -> dict[str, object]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.1",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            content_length = parse_content_length(response.headers.get("Content-Length"))
            if content_length is not None and content_length > MAX_FEED_BYTES:
                return {"status": "too_large"}

            raw_bytes = response.read(MAX_FEED_BYTES + 1)
            if len(raw_bytes) > MAX_FEED_BYTES:
                return {"status": "too_large"}
    except HTTPError as exc:
        return {"status": "http_error", "http_status": exc.code}
    except OSError:
        return {"status": "fetch_failed"}

    try:
        entry = parse_feed(raw_bytes)
    except ET.ParseError:
        return {"status": "invalid_feed"}

    if entry is None:
        return {"status": "no_entries"}
    return {"status": "ok", "entry": entry}


def parse_content_length(raw_value: object) -> int | None:
    if raw_value is None:
        return None
    try:
        parsed = int(str(raw_value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def parse_feed(raw_bytes: bytes) -> FeedEntry | None:
    root = ET.fromstring(raw_bytes)
    root_name = local_name(root.tag)
    if root_name == "feed":
        return parse_atom_feed(root)
    return parse_rss_feed(root)


def parse_rss_feed(root: ET.Element) -> FeedEntry | None:
    channel = find_child(root, "channel") or root
    feed_title = normalize_text(child_text(channel, "title"))
    item = find_child(channel, "item")
    if item is None and local_name(root.tag) == "rdf":
        item = find_child(root, "item")
    if item is None:
        return None

    entry_title = normalize_text(child_text(item, "title"))
    entry_link = normalize_text(child_text(item, "link"))
    entry_id = normalize_text(child_text(item, "guid"))
    if not entry_title and not entry_link:
        return None
    return FeedEntry(feed_title=feed_title, entry_title=entry_title, entry_link=entry_link, entry_id=entry_id)


def parse_atom_feed(root: ET.Element) -> FeedEntry | None:
    feed_title = normalize_text(child_text(root, "title"))
    entry = find_child(root, "entry")
    if entry is None:
        return None

    entry_title = normalize_text(child_text(entry, "title"))
    entry_link = normalize_text(find_atom_link(entry))
    entry_id = normalize_text(child_text(entry, "id"))
    if not entry_title and not entry_link:
        return None
    return FeedEntry(feed_title=feed_title, entry_title=entry_title, entry_link=entry_link, entry_id=entry_id)


def find_child(node: ET.Element, name: str) -> ET.Element | None:
    for child in node:
        if local_name(child.tag) == name:
            return child
    return None


def child_text(node: ET.Element | None, name: str) -> str:
    if node is None:
        return ""
    child = find_child(node, name)
    if child is None:
        return ""
    return "".join(child.itertext())


def find_atom_link(entry: ET.Element) -> str:
    fallback = ""
    for child in entry:
        if local_name(child.tag) != "link":
            continue
        href = str(child.attrib.get("href", "")).strip()
        if not href:
            continue
        rel = str(child.attrib.get("rel", "alternate")).strip().lower()
        if rel == "alternate":
            return href
        if not fallback:
            fallback = href
    return fallback


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1].lower()
    return tag.lower()


def normalize_text(value: str) -> str:
    cleaned = unescape(value or "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def shorten_text(text: str, max_length: int) -> str:
    if max_length < 4:
        return text[:max_length]
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def render_feed_reply(bot, feed_title: str, entry_title: str, entry_link: str) -> str:
    normalized_feed = normalize_text(feed_title) or "RSS"
    normalized_title = normalize_text(entry_title)
    normalized_link = normalize_text(entry_link)

    if normalized_title and normalized_link:
        prefix = f"{normalized_feed}: "
        suffix = f" - {normalized_link}"
        max_title_length = max(24, MAX_REPLY_LENGTH - len(prefix) - len(suffix))
        return bot.tr(
            "rss_latest_entry",
            feed=normalized_feed,
            title=shorten_text(normalized_title, max_title_length),
            link=normalized_link,
        )
    if normalized_title:
        available = max(24, MAX_REPLY_LENGTH - len(normalized_feed) - 2)
        return bot.tr("rss_latest_entry_no_link", feed=normalized_feed, title=shorten_text(normalized_title, available))
    return bot.tr("rss_latest_link_only", feed=normalized_feed, link=shorten_text(normalized_link, MAX_REPLY_LENGTH))


def ensure_rss_tables(db_conn):
    with db_conn.cursor() as cur:
        cur.execute(RSS_ANNOUNCE_CHANNELS_TABLE_SQL)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_rss_seen (
                network VARCHAR(255) NOT NULL,
                feed_alias VARCHAR(128) NOT NULL,
                entry_hash CHAR(64) NOT NULL,
                entry_id VARCHAR(512) NOT NULL DEFAULT '',
                entry_link VARCHAR(2048) NOT NULL DEFAULT '',
                entry_title VARCHAR(512) NOT NULL DEFAULT '',
                seen_at VARCHAR(32) NOT NULL,
                PRIMARY KEY (network, feed_alias, entry_hash),
                KEY idx_bot_rss_seen_lookup (network, feed_alias, seen_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )


def on_config_loaded(bot, raw_config: dict[str, object]) -> None:
    bot._rss_feeds = dict(raw_config.get("rss_feeds", {}) or {})
    bot._rss_announce_channel = str(raw_config.get("rss_announce_channel", "") or "").strip()


PLUGIN = PluginSpec(
    name="rss",
    translations=MESSAGES,
    commands=(
        CommandSpec(
            canonical="rss",
            handler=handle_rss,
            aliases=("feed",),
            help_args={"de": "<feed|url>", "en": "<feed|url>"},
            help_texts={
                "de": "liest den neuesten Eintrag aus einem RSS- oder Atom-Feed",
                "en": "reads the latest entry from an RSS or Atom feed",
            },
            help_sort=115,
        ),
    ),
    tick_handlers=(
        TickHandlerSpec(handler=handle_tick),
    ),
    hooks={
        "ensure_tables": ensure_rss_tables,
        "set_rss_announce_channels": set_rss_announce_channels,
    },
    on_config_loaded=on_config_loaded,
)