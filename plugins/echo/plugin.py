from plugin_system import CommandSpec, PluginSpec


MESSAGES = {
    "de": {
        "usage_echo": "Nutzung: {prefix}{command} <text>",
    },
    "en": {
        "usage_echo": "Usage: {prefix}{command} <text>",
    },
}


def handle_echo(bot, context, arg: str) -> None:
    if arg:
        bot.send_notice(context.source_nick, arg)
    else:
        bot.send_notice(
            context.source_nick,
            bot.tr("usage_echo", prefix=context.command_prefix, command=bot.primary_command_name("echo")),
        )


PLUGIN = PluginSpec(
    name="echo",
    translations=MESSAGES,
    commands=(
        CommandSpec(
            canonical="echo",
            handler=handle_echo,
            help_args={"de": "<text>", "en": "<text>"},
            help_texts={
                "de": "sendet den Text per Notice zurueck",
                "en": "sends the text back as a notice",
            },
            help_sort=50,
        ),
    ),
)