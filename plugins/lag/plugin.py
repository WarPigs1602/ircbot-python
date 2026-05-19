from plugin_system import CommandSpec, PluginSpec


MESSAGES = {
    "de": {
        "lag_now": "Aktueller Lag: {ms} ms ({ns} ns)",
    },
    "en": {
        "lag_now": "Current lag: {ms} ms ({ns} ns)",
    },
}


def handle_lag(bot, context, arg: str) -> None:
    bot.send_lag_probe(context.reply_target)


PLUGIN = PluginSpec(
    name="lag",
    translations=MESSAGES,
    commands=(
        CommandSpec(canonical="lag", handler=handle_lag, help_sort=40),
    ),
)