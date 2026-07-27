import re

from plugin_system import MessageHandlerSpec, PluginSpec

WAHNSINN_PATTERN = re.compile(r"\bwahnsinn\b", re.IGNORECASE)


def handle_wahnsinn(bot, context) -> None:
    if context.source_nick.lower() == bot.current_nick.lower():
        return

    if WAHNSINN_PATTERN.search(context.message):
        bot.send_privmsg(context.reply_target, "Hölle! Hölle! Hölle!")


PLUGIN = PluginSpec(
    name="wahnsinn",
    message_handlers=(MessageHandlerSpec(handler=handle_wahnsinn),),
)
