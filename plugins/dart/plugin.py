from plugin_system import CommandSpec, PluginSpec


MESSAGES = {
    "de": {
        "usage_dart": "Nutzung: {prefix}{command} <nick>",
        "self_target": "sich selbst",
        "dart_db_missing_pkg": "Fehler: Python-Paket 'pymysql' fehlt. Bitte 'pip install -r requirements.txt' ausfuehren.",
        "dart_db_unreachable": "Dart-DB nicht erreichbar: {error}",
        "dart_top_failed": "Dart-Top10 fehlgeschlagen: {error}",
        "dart_no_data": "Keine Dart-Daten vorhanden.",
        "dart_top": "Dart Top10: {items}",
        "dart_top_entry": "{index}. {nick} {points}P/{throws}W",
        "dart_hit": "{bot} benutzt {target} als Dartpfeil und trifft {hit} ({points} Punkte) (Requested by {requested_by})",
        "dart_destroy": "{bot} benutzt {target} als Dartpfeil und zerstoert die Dartscheibe! ({points} Punkte) ({hit}) (Requested by {requested_by})",
    },
    "en": {
        "usage_dart": "Usage: {prefix}{command} <nick>",
        "self_target": "themselves",
        "dart_db_missing_pkg": "Error: Python package 'pymysql' is missing. Run 'pip install -r requirements.txt'.",
        "dart_db_unreachable": "Dart DB not reachable: {error}",
        "dart_top_failed": "Dart Top10 failed: {error}",
        "dart_no_data": "No dart data available.",
        "dart_top": "Dart Top 10: {items}",
        "dart_top_entry": "{index}. {nick} {points}pts/{throws}th",
        "dart_hit": "{bot} uses {target} as a dart and hits {hit} ({points} points) (Requested by {requested_by})",
        "dart_destroy": "{bot} uses {target} as a dart and destroys the dartboard! ({points} points) ({hit}) (Requested by {requested_by})",
    },
}


def handle_dart(bot, context, arg: str) -> None:
    if arg.strip().lower() == "top10":
        bot.send_privmsg(context.reply_target, bot.get_dart_top10_text())
        return

    target_nick = arg.strip() if arg.strip() else context.source_nick
    if not target_nick:
        bot.send_privmsg(
            context.reply_target,
            bot.tr("usage_dart", prefix=context.command_prefix, command=bot.primary_command_name("dart")),
        )
        return

    bot.send_privmsg(context.reply_target, bot.get_dart_stats_text(target_nick, context.source_nick))


PLUGIN = PluginSpec(
    name="dart",
    translations=MESSAGES,
    commands=(
        CommandSpec(
            canonical="dart",
            handler=handle_dart,
            help_args={"de": "<nick>", "en": "<nick>"},
            help_texts={
                "de": "zeigt Dart-Stats fuer einen Nick; mit top10 die Rangliste",
                "en": "shows dart stats for a nick; use top10 for the ranking",
            },
            help_sort=70,
        ),
    ),
)