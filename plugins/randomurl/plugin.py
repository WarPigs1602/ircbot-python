from plugin_system import CommandSpec, PluginSpec


MESSAGES = {
    "de": {
        "url_not_found": "URL nicht gefunden.",
        "url_blocked": "URL geblockt (Spamverdacht).",
        "url_dead": "URL ist tot oder keine HTML-Seite.",
        "url_dangerous_file": "⚠ Sicherheitswarnung",
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
        "url_not_found": "URL not found.",
        "url_blocked": "URL blocked (suspected spam).",
        "url_dead": "URL is dead or not an HTML page.",
        "url_dangerous_file": "⚠ Security warning",
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


def handle_randomurl(bot, context, arg: str) -> None:
    result = bot.fetch_random_url()
    bot.handle_url_result(result, context.reply_target, requested_by=context.source_nick, show_max_id=True)


PLUGIN = PluginSpec(
    name="randomurl",
    translations=MESSAGES,
    commands=(
        CommandSpec(
            canonical="randomurl",
            handler=handle_randomurl,
            aliases=("zufallsurl",),
            primary_names={"de": "zufallsurl", "en": "randomurl"},
            help_sort=120,
        ),
    ),
)