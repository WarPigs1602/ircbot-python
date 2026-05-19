from plugin_system import CommandSpec, PluginSpec


def render_target(bot, target_nick: str) -> str:
    if target_nick.lower() == bot.current_nick.lower():
        return "themselves"
    return target_nick


def slap_action(target: str, item: str) -> str:
    return f"slaps {target} around a bit with a large {item}"


def handle_pong(bot, context, arg: str) -> None:
    target_nick = arg.strip() if arg.strip() else context.source_nick
    ping_name = bot.primary_command_name("ping")
    bot.send_action(
        context.reply_target,
        slap_action(render_target(bot, target_nick), f"{context.command_prefix}{ping_name}"),
    )


PLUGIN = PluginSpec(
    name="pong",
    commands=(
        CommandSpec(canonical="pong", handler=handle_pong, help_sort=30),
    ),
)