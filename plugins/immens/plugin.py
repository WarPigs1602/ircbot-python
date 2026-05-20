from plugin_system import MessageHandlerSpec, PluginSpec


def handle_immens(bot, context) -> None:
    if context.message.strip().lower() != "das denkste nur.":
        return
    bot.send_privmsg(context.reply_target, "Immer doch.")


PLUGIN = PluginSpec(
    name="immens",
    message_handlers=(MessageHandlerSpec(handler=handle_immens),),
)