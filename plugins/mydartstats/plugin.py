from plugin_system import CommandSpec, PluginSpec


MESSAGES = {
    "de": {
        "dart_stats_missing_pkg": "Dart-Stats nicht verfuegbar: Python-Paket 'pymysql' fehlt.",
        "dart_stats_unavailable": "Dart-Stats momentan nicht verfuegbar.",
        "dart_stats_empty": "Du hast noch keine Dart-Statistiken.",
        "dart_stats": "Deine Dart-Stats: {points} Punkte aus {throws} Würfen (Ø {average}) | Rang #{rank}/{total}",
    },
    "en": {
        "dart_stats_missing_pkg": "Dart stats unavailable: Python package 'pymysql' is missing.",
        "dart_stats_unavailable": "Dart stats are currently unavailable.",
        "dart_stats_empty": "You do not have any dart stats yet.",
        "dart_stats": "Your dart stats: {points} points from {throws} throws (avg {average}) | Rank #{rank}/{total}",
    },
}


def handle_mydartstats(bot, context, arg: str) -> None:
    bot.send_notice(context.source_nick, bot.get_my_dart_stats_text(context.source_nick))


PLUGIN = PluginSpec(
    name="mydartstats",
    translations=MESSAGES,
    commands=(
        CommandSpec(
            canonical="mydartstats",
            handler=handle_mydartstats,
            aliases=("meinedartstats",),
            primary_names={"de": "meinedartstats", "en": "mydartstats"},
            help_sort=90,
        ),
    ),
)