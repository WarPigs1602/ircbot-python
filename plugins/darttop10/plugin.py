from plugin_system import CommandSpec, PluginSpec


MESSAGES = {
    "de": {
        "dart_db_missing_pkg": "Fehler: Python-Paket 'pymysql' fehlt. Bitte 'pip install -r requirements.txt' ausfuehren.",
        "dart_db_unreachable": "Dart-DB nicht erreichbar: {error}",
        "dart_top_failed": "Dart-Top10 fehlgeschlagen: {error}",
        "dart_no_data": "Keine Dart-Daten vorhanden.",
        "dart_top": "Dart Top10: {items}",
        "dart_top_entry": "{index}. {nick} {points}P/{throws}W",
    },
    "en": {
        "dart_db_missing_pkg": "Error: Python package 'pymysql' is missing. Run 'pip install -r requirements.txt'.",
        "dart_db_unreachable": "Dart DB not reachable: {error}",
        "dart_top_failed": "Dart Top10 failed: {error}",
        "dart_no_data": "No dart data available.",
        "dart_top": "Dart Top 10: {items}",
        "dart_top_entry": "{index}. {nick} {points}pts/{throws}th",
    },
}


def handle_darttop10(bot, context, arg: str) -> None:
    bot.send_privmsg(context.reply_target, bot.get_dart_top10_text())


PLUGIN = PluginSpec(
    name="darttop10",
    translations=MESSAGES,
    commands=(
        CommandSpec(
            canonical="darttop10",
            handler=handle_darttop10,
            help_texts={
                "de": "zeigt die Top-10 der Dartpunkte",
                "en": "shows the top 10 dart scores",
            },
            help_sort=80,
        ),
    ),
)