import json
import re
import time
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


URL_PATTERN = re.compile(r'https?://[^\s<>"]+', re.IGNORECASE)
USER_AGENT = "Mozilla/5.0 IRCBot"


class _TopicParser(HTMLParser):
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

    def close(self) -> None:
        if self._capture_title and not self.title:
            self.title = "".join(self._title_parts).strip()
            self._capture_title = False
        if self._capture_topic and not self.topic:
            self.topic = "".join(self._topic_parts).strip()
            self._capture_topic = False
        super().close()


class URLService:
    def sniff_urls_in_message(self, bot, message: str, channel: str, source_nick: str) -> None:
        seen_in_message: set[str] = set()
        for raw_url in URL_PATTERN.findall(message):
            normalized_url = self.normalize_url(raw_url)
            if not normalized_url or normalized_url in seen_in_message:
                continue

            seen_in_message.add(normalized_url)
            self._process_single_url(bot, channel, source_nick, normalized_url)

    def _process_single_url(self, bot, channel: str, source_nick: str, normalized_url: str) -> None:
        record = self.fetch_url_by_value(bot, normalized_url)
        if record and self.is_flagged(record):
            return
        if record:
            cached_result = self.build_cached_url_result(bot, record)
            if cached_result:
                self.handle_url_result(bot, cached_result, channel, requested_by=source_nick, show_max_id=True)
                return

        if self.is_spammy(bot, normalized_url):
            bot.block_url(normalized_url)
            return

        topic_result = self.describe_url(bot, normalized_url)
        if topic_result.get("status") == "ok":
            topic_result["posted_by"] = source_nick
            stored_url_id = self.store_url_if_missing(
                bot,
                normalized_url,
                source_nick,
                topic=str(topic_result.get("topic", "")) or None,
                title_missing=bool(topic_result.get("title_missing", False)),
            )
            if stored_url_id is not None:
                topic_result["id"] = stored_url_id
        self.handle_url_result(bot, topic_result, channel, requested_by=source_nick, show_max_id=True)

    def handle_url_result(
        self,
        bot,
        result: dict[str, str | int | bool | None] | None,
        reply_target: str,
        requested_by: str,
        show_max_id: bool = False,
    ) -> None:
        max_id_suffix = self._max_id_suffix(bot, result, show_max_id)
        if self._handle_non_ok_status(bot, result, reply_target, max_id_suffix):
            return

        assert result is not None
        url_id = bot.safe_int(result.get("id"))
        id_prefix = f"[#{url_id}] " if url_id is not None else ""
        actor_context = self.build_url_actor_context(bot, requested_by, str(result.get("posted_by", "")))

        if str(result.get("kind", "")) == "youtube":
            self._send_youtube_result(bot, result, reply_target, id_prefix, actor_context, max_id_suffix)
            return

        url = str(result.get("url", ""))
        topic = str(result.get("topic", ""))
        title_missing = bool(result.get("title_missing", False))
        if not url:
            bot.send_privmsg(reply_target, bot.tr("url_not_found"))
            return

        if not topic:
            if title_missing:
                bot.send_privmsg(reply_target, f"{id_prefix}{bot.tr('url_without_title_no_topic', url=url)} ({actor_context}){max_id_suffix}")
                return
            bot.send_privmsg(reply_target, f"{id_prefix}{bot.tr('url_no_html_topic', url=url)}{max_id_suffix}")
            return
        if title_missing:
            bot.send_privmsg(reply_target, f"{id_prefix}{bot.tr('url_without_title', url=url, topic=topic)} ({actor_context}){max_id_suffix}")
            return

        is_dangerous = bool(result.get("is_dangerous", False)) or topic in getattr(bot, "dangerous_content_types", set())
        if is_dangerous:
            warn_label = self._danger_label(bot, reply_target)
            bot.send_privmsg(reply_target, f"{id_prefix}{url} :: {warn_label}: {topic} ({actor_context}){max_id_suffix}")
            return

        bot.send_privmsg(reply_target, f"{id_prefix}{url} :: {topic} ({actor_context}){max_id_suffix}")

    def _max_id_suffix(self, bot, result: dict[str, str | int | bool | None] | None, show_max_id: bool) -> str:
        max_id = bot.safe_int(result.get("max_id")) if (result and show_max_id) else None
        if show_max_id and max_id is None:
            max_id = self.get_max_url_id(bot)
        return f" | {bot.tr('url_max_id', max_id=max_id)}" if max_id is not None else ""

    def _handle_non_ok_status(self, bot, result, reply_target: str, max_id_suffix: str) -> bool:
        if not result:
            bot.send_privmsg(reply_target, f"{bot.tr('url_not_found')}{max_id_suffix}")
            return True

        status = str(result.get("status", ""))
        if status == "discarded":
            return True
        if status == "blocked":
            bot.send_privmsg(reply_target, f"{bot.tr('url_blocked')}{max_id_suffix}")
            return True
        if status == "deadlink":
            http_status = bot.safe_int(result.get("http_status"))
            status_suffix = f" (HTTP {http_status})" if http_status is not None else ""
            bot.send_privmsg(reply_target, f"{bot.tr('url_dead')}{status_suffix}{max_id_suffix}")
            return True
        if status == "too_large":
            bot.send_privmsg(reply_target, f"{bot.tr('url_too_large')}{max_id_suffix}")
            return True
        if status == "error":
            bot.send_privmsg(reply_target, f"{bot.tr('url_error', message=result.get('message', bot.tr('unknown')))}{max_id_suffix}")
            return True
        return False

    def _send_youtube_result(
        self,
        bot,
        result: dict[str, str | int | bool | None],
        reply_target: str,
        id_prefix: str,
        actor_context: str,
        max_id_suffix: str,
    ) -> None:
        title = str(result.get("topic", ""))
        channel_title = str(result.get("channel_title", ""))
        duration_text = str(result.get("duration_text", ""))
        published_text = str(result.get("published_text", ""))
        view_count = result.get("view_count")
        like_count = result.get("like_count")
        comment_count = result.get("comment_count")

        if bot.allows_control_codes(reply_target):
            bot.send_privmsg(
                reply_target,
                f"{id_prefix}"
                + self.format_youtube_with_control_codes(
                    bot,
                    title=title,
                    channel_title=channel_title,
                    duration_text=duration_text,
                    published_text=published_text,
                    view_count=view_count,
                    like_count=like_count,
                    comment_count=comment_count,
                    actor_context=actor_context,
                )
                + max_id_suffix,
            )
            return

        parts = []
        if channel_title:
            parts.append(bot.tr("yt_channel", channel=channel_title))
        if duration_text:
            parts.append(bot.tr("yt_duration", duration=duration_text))
        if published_text:
            parts.append(bot.tr("yt_published", published=published_text))
        if view_count is not None:
            parts.append(bot.tr("yt_views", count=view_count))
        if like_count is not None:
            parts.append(bot.tr("yt_likes", count=like_count))
        if comment_count is not None:
            parts.append(bot.tr("yt_comments", count=comment_count))

        suffix = f" ({' | '.join(parts)})" if parts else ""
        bot.send_privmsg(reply_target, f"{id_prefix}{bot.tr('yt_prefix')} :: {title}{suffix} ({actor_context}){max_id_suffix}")

    def _danger_label(self, bot, reply_target: str) -> str:
        if not bot.allows_control_codes(reply_target):
            return bot.tr("url_dangerous_file")
        bold = "\x02"
        red = "\x0304"
        reset_code = "\x0f"
        return f"{bold}{red}{bot.tr('url_dangerous_file')}{reset_code}"

    def fetch_url_by_id(self, bot, url_id: int) -> dict[str, str | int | bool | None] | None:
        conn = bot.open_db_connection()
        if conn is None:
            return {"status": "error", "message": "Database unavailable." if bot.config.language == "en" else "Datenbank nicht erreichbar."}

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

        flagged = self._build_flagged_status(row)
        if flagged is not None:
            return flagged

        cached_result = self.build_cached_url_result(bot, row)
        if cached_result:
            cached_result["max_id"] = self.get_max_url_id(bot)
            return cached_result

        topic_result = self.describe_url(bot, str(row.get("url", "")))
        if topic_result and topic_result.get("status") == "ok":
            topic_result["id"] = int(row.get("id", url_id))
            topic_result["posted_by"] = str(row.get("posted_by", "")).strip()
            topic_result["max_id"] = self.get_max_url_id(bot)
            self.store_url_if_missing(
                bot,
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
        return {"status": "error", "message": "URL could not be read." if bot.config.language == "en" else "URL konnte nicht gelesen werden."}

    def _build_flagged_status(self, row: dict[str, str | int | bool | None]) -> dict[str, str] | None:
        if int(row.get("is_blocked", 0)):
            return {"status": "blocked", "url": str(row.get("url", ""))}
        if int(row.get("is_deadlink", 0)):
            return {"status": "deadlink", "url": str(row.get("url", ""))}
        return None

    def fetch_random_url(self, bot) -> dict[str, str | int | bool | None] | None:
        conn = bot.open_db_connection()
        if conn is None:
            return {"status": "error", "message": "Database unavailable." if bot.config.language == "en" else "Datenbank nicht erreichbar."}

        try:
            with conn.cursor() as cur:
                for _ in range(10):
                    cur.execute(
                        "SELECT id, url, posted_by, time, is_blocked, is_deadlink, topic, title_missing FROM bot_url WHERE is_blocked = 0 AND is_deadlink = 0 ORDER BY RAND() LIMIT 1"
                    )
                    row = cur.fetchone()
                    if not row:
                        return None

                    cached_result = self.build_cached_url_result(bot, row)
                    if cached_result:
                        cached_result["max_id"] = self.get_max_url_id(bot)
                        return cached_result

                    topic_result = self.describe_url(bot, str(row.get("url", "")))
                    if topic_result.get("status") == "ok":
                        topic_result["id"] = int(row.get("id", 0))
                        topic_result["posted_by"] = str(row.get("posted_by", "")).strip()
                        topic_result["max_id"] = self.get_max_url_id(bot)
                        self.store_url_if_missing(
                            bot,
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

    def fetch_url_by_value(self, bot, url: str) -> dict[str, str | int | bool | None] | None:
        conn = bot.open_db_connection()
        if conn is None:
            return None

        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, url, posted_by, time, is_blocked, is_deadlink, topic, title_missing FROM bot_url WHERE url = %s ORDER BY id ASC LIMIT 1",
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

    def build_cached_url_result(self, bot, row: dict[str, str | int | bool | None]) -> dict[str, str | int | bool | None] | None:
        url = str(row.get("url", ""))
        if self.is_youtube_url(url):
            return None

        topic_value = row.get("topic")
        topic = str(topic_value).strip() if topic_value is not None else ""
        if not topic:
            return None

        return {
            "status": "ok",
            "id": bot.safe_int(row.get("id")),
            "url": url,
            "posted_by": str(row.get("posted_by", "")).strip(),
            "topic": topic,
            "title_missing": bool(int(row.get("title_missing", 0) or 0)),
        }

    def fetch_url_topic(self, bot, url: str) -> dict[str, str | int | bool | None]:
        if self.is_spammy(bot, url):
            bot.block_url(url)
            return {"status": "blocked", "url": url}

        try:
            head_request = Request(
                url,
                headers={"User-Agent": USER_AGENT},
                method="HEAD",
            )
            head_content_type: str | None = None
            try:
                with urlopen(head_request, timeout=bot.config.url_timeout_seconds) as response:
                    head_status = getattr(response, "status", None)
                    head_content_type = response.headers.get_content_type()
            except HTTPError as exc:
                head_status = exc.code

            if head_status is not None and head_status not in {405, 501} and not 200 <= head_status < 300:
                bot.mark_deadlink(url)
                return {"status": "deadlink", "url": url, "http_status": head_status}

            if head_status not in {405, 501} and head_content_type is not None and head_content_type not in {"text/html", "application/xhtml+xml"}:
                is_dangerous = head_content_type in getattr(bot, "dangerous_content_types", set())
                return {
                    "status": "ok",
                    "url": url,
                    "topic": head_content_type,
                    "title_missing": False,
                    "content_type": head_content_type,
                    "is_dangerous": is_dangerous,
                    "http_status": head_status,
                }

            max_sniff_bytes = bot.config.url_sniff_max_bytes
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Range": f"bytes=0-{max_sniff_bytes - 1}",
                },
            )
            with urlopen(request, timeout=bot.config.url_timeout_seconds) as response:
                response_headers = response.headers
                content_length = bot.safe_int(response_headers.get("Content-Length"))
                if content_length is not None and content_length > bot.config.url_max_content_length_bytes:
                    return {"status": "too_large", "url": url, "http_status": getattr(response, "status", None)}

                raw_bytes = response.read(max_sniff_bytes + 1)
                if len(raw_bytes) > max_sniff_bytes:
                    raw_bytes = raw_bytes[:max_sniff_bytes]

                encoding = response_headers.get_content_charset() or "utf-8"
                html_text = raw_bytes.decode(encoding, errors="replace")
        except OSError as exc:
            if self._is_timeout_error(exc):
                return {"status": "discarded", "url": url}
            bot.mark_deadlink(url)
            return {"status": "deadlink", "url": url}

        topic, title_missing = self.extract_html_topic(html_text)
        if not topic:
            return {"status": "ok", "url": url, "topic": "", "title_missing": title_missing}

        if self.is_spammy(bot, topic):
            bot.block_url(url)
            return {"status": "blocked", "url": url}

        return {"status": "ok", "url": url, "topic": topic, "title_missing": title_missing}

    def store_url_if_missing(self, bot, url: str, posted_by: str, topic: str | None = None, title_missing: bool = False) -> int | None:
        conn = bot.open_db_connection()
        if conn is None:
            return None

        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM bot_url WHERE url = %s ORDER BY id ASC LIMIT 1", (url,))
                existing_row = cur.fetchone()
                if existing_row:
                    if topic:
                        cur.execute(
                            "UPDATE bot_url SET topic = %s, title_missing = %s WHERE url = %s",
                            (topic[:180], 1 if title_missing else 0, url),
                        )
                    return bot.safe_int(existing_row.get("id"))

                cur.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM bot_url")
                next_row = cur.fetchone() or {}
                next_id = int(next_row.get("next_id", 1))

                cur.execute(
                    "INSERT INTO bot_url (id, url, posted_by, time, is_blocked, is_deadlink, topic, title_missing) VALUES (%s, %s, %s, %s, 0, 0, %s, %s)",
                    (next_id, url, posted_by, bot.current_time_string(), (topic[:180] if topic else None), 1 if title_missing else 0),
                )
                return next_id
        except Exception:
            return None
        finally:
            conn.close()

        return None

    def get_max_url_id(self, bot) -> int | None:
        conn = bot.open_db_connection()
        if conn is None:
            return None

        try:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(id) AS max_id FROM bot_url")
                row = cur.fetchone() or {}
                return bot.safe_int(row.get("max_id"))
        except Exception:
            return None
        finally:
            conn.close()

    def extract_html_topic(self, html_text: str) -> tuple[str, bool]:
        parser = _TopicParser()
        parser.feed(html_text)
        parser.close()
        topic = parser.topic or parser.title
        fallback_tag = ""
        if not topic:
            fallback_match = re.search(r"<(?P<tag>h1|h2|title)\b[^>]*>(.*?)(?:</(?:h1|h2|title)>|$)", html_text, re.IGNORECASE | re.DOTALL)
            if fallback_match:
                fallback_tag = str(fallback_match.group("tag")).lower()
                topic = re.sub(r"<[^>]+>", " ", fallback_match.group(2))
        topic = unescape(topic).strip()
        topic = re.sub(r"\s+", " ", topic)
        title_missing = not (bool(parser.title) or fallback_tag == "title")
        return topic[:180], title_missing

    def is_spammy(self, bot, text: str) -> bool:
        lowered = text.lower()
        if any(host in lowered for host in getattr(bot, "spam_hosts", ())):
            return True
        return any(word in lowered for word in getattr(bot, "spam_words", ()))

    def is_flagged(self, row: dict[str, str | int | bool | None]) -> bool:
        return bool(int(row.get("is_blocked", 0))) or bool(int(row.get("is_deadlink", 0)))

    def normalize_url(self, url: str) -> str:
        return url.rstrip(".,;:!?)\"]}")

    @staticmethod
    def _is_timeout_error(exc: Exception) -> bool:
        if isinstance(exc, TimeoutError):
            return True
        if isinstance(exc, URLError):
            reason = str(getattr(exc, "reason", "")).lower()
            return "timed out" in reason or "timeout" in reason
        return "timed out" in str(exc).lower()

    def describe_url(self, bot, url: str) -> dict[str, str | int | bool | None]:
        if self.is_youtube_url(url):
            youtube_result = self.fetch_youtube_metadata(bot, url)
            if youtube_result:
                return youtube_result

            return {"status": "error", "message": bot.tr("yt_api_no_metadata")}

        return self.fetch_url_topic(bot, url)

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

        query = self._parse_query(parsed.query)

        if "v" in query:
            return query["v"] or None

        for prefix in ("embed/", "shorts/", "live/"):
            if path.startswith(prefix):
                return path.split("/", 1)[1] or None

        return None

    def _parse_query(self, query_text: str) -> dict[str, str]:
        query: dict[str, str] = {}
        if not query_text:
            return query
        for part in query_text.split("&"):
            if "=" in part:
                key, value = part.split("=", 1)
                query[key] = value
        return query

    def fetch_youtube_metadata(self, bot, url: str) -> dict[str, str | int | bool | None] | None:
        video_id = self.extract_youtube_video_id(url)
        if not video_id:
            return {"status": "error", "message": bot.tr("yt_invalid_id")}

        if not bot.config.youtube_api_key:
            return {"status": "error", "message": bot.tr("yt_missing_key")}

        api_url = (
            "https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails,statistics&id="
            f"{quote(video_id)}&key={quote(bot.config.youtube_api_key)}"
        )
        data = self.fetch_json_with_timeout(api_url, bot.config.url_timeout_seconds)
        if not data:
            return {"status": "error", "message": bot.tr("yt_api_unreachable")}

        api_error = data.get("error")
        if api_error:
            if isinstance(api_error, dict):
                message = str(api_error.get("message", bot.tr("unknown_error")))
            else:
                message = bot.tr("unknown_error")
            return {"status": "error", "message": f"YouTube-API: {message}"}

        items = data.get("items") or []
        if not items:
            return {"status": "error", "message": bot.tr("yt_no_data")}

        item = items[0]
        snippet = item.get("snippet") or {}
        content_details = item.get("contentDetails") or {}
        statistics = item.get("statistics") or {}

        title = str(snippet.get("title", ""))
        channel_title = str(snippet.get("channelTitle", ""))
        duration = bot.format_iso8601_duration(str(content_details.get("duration", "")))
        view_count = statistics.get("viewCount")
        try:
            view_count = int(view_count) if view_count is not None else None
        except (TypeError, ValueError):
            view_count = None

        like_count = bot.safe_int(statistics.get("likeCount"))
        comment_count = bot.safe_int(statistics.get("commentCount"))

        if not title:
            return {"status": "error", "message": bot.tr("yt_no_title")}

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
            "published_text": bot.format_youtube_date(str(snippet.get("publishedAt", ""))),
            "description_text": bot.extract_youtube_description(str(snippet.get("description", ""))),
            "title_missing": False,
        }

    def fetch_json_with_timeout(self, url: str, timeout_seconds: float) -> dict[str, object] | None:
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = response.read()
            decoded = payload.decode("utf-8", errors="replace")
            parsed = json.loads(decoded)
            return parsed
        except (OSError, ValueError):
            return None

    def format_youtube_with_control_codes(
        self,
        bot,
        title: str,
        channel_title: str,
        duration_text: str,
        published_text: str,
        view_count: object,
        like_count: object,
        comment_count: object,
        actor_context: str,
    ) -> str:
        bold = "\x02"
        reset = "\x0f"
        red = "\x0304"
        green = "\x0303"

        header = f"{bold}{red}{bot.tr('yt_prefix')}{reset} :: {bold}{title}{reset}"
        details = []
        if channel_title:
            details.append(f"{green}{bot.tr('yt_detail_channel_label')}:{reset} {channel_title}")
        if published_text:
            details.append(f"{green}{bot.tr('yt_detail_published_label')}:{reset} {published_text}")
        if duration_text:
            details.append(f"{green}{bot.tr('yt_detail_duration_label')}:{reset} {duration_text}")
        if view_count is not None:
            details.append(f"{green}{bot.tr('yt_detail_views_label')}:{reset} {bot.format_compact_number(view_count)}")
        if like_count is not None:
            details.append(f"{green}{bot.tr('yt_detail_likes_label')}:{reset} {bot.format_compact_number(like_count)}")
        if comment_count is not None:
            details.append(f"{green}{bot.tr('yt_detail_comments_label')}:{reset} {bot.format_compact_number(comment_count)}")

        details_text = f" ({' | '.join(details)})" if details else ""
        return f"{header}{details_text} ({actor_context})"

    def build_url_actor_context(self, bot, requested_by: str, posted_by: str = "") -> str:
        normalized_requested_by = requested_by.strip() or bot.tr("unknown")
        normalized_posted_by = posted_by.strip()
        if not normalized_posted_by:
            return bot.tr("url_requested_by_only", requested_by=normalized_requested_by)
        if normalized_posted_by.lower() == normalized_requested_by.lower():
            return bot.tr("url_first_posted_by_only", posted_by=normalized_posted_by)
        return bot.tr(
            "url_first_posted_and_requested_by",
            posted_by=normalized_posted_by,
            requested_by=normalized_requested_by,
        )
