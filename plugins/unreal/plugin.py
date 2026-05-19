import re

from plugin_system import MessageHandlerSpec, PluginSpec


def handle_unreal(bot, context) -> None:
    if re.search(r"\bunreal\b", context.message, re.IGNORECASE):
        action_target = context.source_nick if context.target.lower() == bot.current_nick.lower() else context.target
        bot.send_action(action_target, "rocketjumps!")


PLUGIN = PluginSpec(
    name="unreal",
    message_handlers=(MessageHandlerSpec(handler=handle_unreal),),
)