from plugin_system import CommandSpec, PluginSpec


def usage_text(bot, prefix: str, command: str) -> str:
    if bot.config.language == "en":
        return f"Usage: {prefix}{command} <nick>"
    return f"Nutzung: {prefix}{command} <nick>"


def slap_action(target: str, item: str) -> str:
    return f"slaps {target} around a bit with a large {item}"


def handle_slap(bot, context, arg: str) -> None:
    target_nick = arg.strip() if arg.strip() else context.source_nick
    if not target_nick:
        bot.send_privmsg(
            context.reply_target,
            usage_text(bot, context.command_prefix, bot.primary_command_name("slap")),
        )
        return

    bot.send_action(
        context.reply_target,
        slap_action(target_nick, bot.current_nick),
    )


PLUGIN = PluginSpec(
    name="slap",
    commands=(
        CommandSpec(
            canonical="slap",
            handler=handle_slap,
            help_args={"de": "<nick>", "en": "<nick>"},
            help_texts={
                "de": "verpasst einem Nick einen Action-Slap",
                "en": "gives a nick an action slap",
            },
            help_sort=60,
        ),
    ),
)