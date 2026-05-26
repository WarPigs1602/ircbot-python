from plugin_system import CommandSpec, PluginSpec


def render_target(bot, target_nick: str) -> str:
    if target_nick.lower() == bot.current_nick.lower():
        return "themselves"
    return target_nick


def slap_action(target: str, item: str) -> str:
    return f"slaps {target} around a bit with a large {item}"


def handle_ping(bot, context, arg: str) -> None:
    target_nick = arg.strip() if arg.strip() else context.source_nick
    pong_name = bot.primary_command_name("pong")
    bot.send_action(
        context.reply_target,
        slap_action(render_target(bot, target_nick), f"{context.command_prefix}{pong_name}"),
    )


PLUGIN = PluginSpec(
    name="ping",
    commands=(
        CommandSpec(
            canonical="ping",
            handler=handle_ping,
            help_texts={
                "de": "schickt einen Ping-Slap; optional mit Zielnick",
                "en": "sends a ping slap; optionally with target nick",
            },
            help_sort=20,
        ),
    ),
)