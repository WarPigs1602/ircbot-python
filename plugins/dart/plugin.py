from plugin_system import CommandSpec, PluginSpec

try:
    import pymysql
except ImportError:
    pymysql = None


class DartRepository:
    def __init__(self, db_conn, network_key):
        self.db_conn = db_conn
        self.network_key = network_key

    def record_throw(self, nick, points):
        try:
            with self.db_conn.cursor() as cur:
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

    def get_stats(self, nick):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute("SELECT points, `throws` FROM bot_dart WHERE nick = %s LIMIT 1", (nick,))
                row = cur.fetchone()
                if not row:
                    return None
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

                return {"points": points, "throws": throws, "rank": rank, "total_players": total_players}
        except Exception:
            return None

    def get_top10(self):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(
                    "SELECT nick, points, `throws` FROM bot_dart ORDER BY points DESC, `throws` DESC, nick ASC LIMIT 10"
                )
                return cur.fetchall() or []
        except Exception:
            return []


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
        "dart_hit": "{bot} benutzt {target} als Dartpfeil und trifft {hit} ({points} Punkte). (Requested by {requested_by})",
        "dart_destroy": "{bot} benutzt {target} als Dartpfeil und zerstoert die Dartscheibe! (31337 Punkte) (Requested by {requested_by})",
        "dart_single": "einfach {points}",
        "dart_double": "doppelt {points}",
        "dart_triple": "dreifach {points}",
        "dart_bull": "Bull (25)",
        "dart_double_bull": "Double Bull (50)",
        "dart_miss": "daneben",
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
        "dart_hit": "{bot} uses {target} as a dart and hits {hit} ({points} points). (Requested by {requested_by})",
        "dart_destroy": "{bot} uses {target} as a dart and destroys the dartboard! (31337 points) (Requested by {requested_by})",
        "dart_single": "single {points}",
        "dart_double": "double {points}",
        "dart_triple": "triple {points}",
        "dart_bull": "bull (25)",
        "dart_double_bull": "double bull (50)",
        "dart_miss": "missed",
    },
}


import random


def roll_dart_turn() -> tuple[int, int, str]:
    roll = random.randint(1, 100)
    if roll <= 25:
        return 0, 0, "dart_miss"
    if roll <= 30:
        return 25, 1, "dart_bull"
    if roll <= 35:
        return 50, 1, "dart_double_bull"
    if roll <= 36:
        return 31337, 1, "dart_destroy"
    number = random.randint(1, 20)
    segment_roll = random.randint(1, 100)
    if segment_roll <= 55:
        return number, number, "dart_single"
    if segment_roll <= 85:
        return number * 2, number, "dart_double"
    return number * 3, number, "dart_triple"


def record_dart_throw(bot, nick: str, points: int) -> None:
    if pymysql is None:
        return
    conn = bot.open_db_connection()
    if conn is None:
        return
    try:
        DartRepository(conn, bot.config.network_key).record_throw(nick, points)
    except Exception:
        pass
    finally:
        conn.close()


def get_my_dart_stats_text(bot, nick: str) -> str:
    if pymysql is None:
        return bot.tr("dart_db_missing_pkg")
    conn = bot.open_db_connection()
    if conn is None:
        return bot.tr("dart_db_unreachable", error="connection failed")
    try:
        stats = DartRepository(conn, bot.config.network_key).get_stats(nick)
        if not stats:
            return bot.tr("dart_no_data")
    except Exception as exc:
        return bot.tr("dart_db_unreachable", error=exc)
    finally:
        conn.close()
    average = stats["points"] / stats["throws"] if stats["throws"] else 0.0
    return bot.tr(
        "dart_stats",
        points=bot.format_points(stats["points"]),
        throws=bot.format_points(stats["throws"]),
        average=bot.format_average(average),
        rank=stats["rank"],
        total=stats["total_players"],
    )


def get_dart_top10_text(bot) -> str:
    if pymysql is None:
        return bot.tr("dart_db_missing_pkg")
    conn = bot.open_db_connection()
    if conn is None:
        return bot.tr("dart_db_unreachable", error="connection failed")
    try:
        rows = DartRepository(conn, bot.config.network_key).get_top10()
    except Exception as exc:
        return bot.tr("dart_top_failed", error=exc)
    finally:
        conn.close()
    if not rows:
        return bot.tr("dart_no_data")
    leaderboard = []
    for index, row in enumerate(rows, start=1):
        nick = str(row.get("nick", "?"))
        points = int(row.get("points", 0))
        throw_count = int(row.get("throws", 0))
        leaderboard.append(
            bot.tr(
                "dart_top_entry",
                index=index,
                nick=nick,
                points=bot.format_points(points),
                throws=bot.format_points(throw_count),
            )
        )
    return bot.tr("dart_top", items=" | ".join(leaderboard))


def get_dart_stats_text(bot, target_nick: str, requested_by: str) -> str:
    points, base_number, hit_key = roll_dart_turn()
    record_dart_throw(bot, requested_by, points)
    rendered_target = bot.format_target_nick(target_nick)
    if hit_key == "dart_destroy":
        return bot.tr(
            "dart_destroy",
            bot=bot.current_nick,
            target=rendered_target,
            requested_by=requested_by,
        )
    return bot.tr(
        "dart_hit",
        bot=bot.current_nick,
        target=rendered_target,
        points=bot.format_points(points),
        hit=bot.tr(hit_key, points=bot.format_points(base_number)),
        requested_by=requested_by,
    )


def handle_dart(bot, context, arg: str) -> None:
    if arg.strip().lower() == "top10":
        bot.send_privmsg(context.reply_target, get_dart_top10_text(bot))
        return

    target_nick = arg.strip() if arg.strip() else context.source_nick
    if not target_nick:
        bot.send_privmsg(
            context.reply_target,
            bot.tr("usage_dart", prefix=context.command_prefix, command=bot.primary_command_name("dart")),
        )
        return

    bot.send_action(context.reply_target, get_dart_stats_text(bot, target_nick, context.source_nick))


def ensure_dart_tables(db_conn):
    with db_conn.cursor() as cur:
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
    hooks={
        "ensure_tables": ensure_dart_tables,
    },
)