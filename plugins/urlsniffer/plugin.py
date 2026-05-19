from plugin_system import MessageHandlerSpec, PluginSpec


def handle_urlsniffer(bot, context) -> None:
    bot.schedule_url_sniff(context.message, context.target, context.source_nick)


PLUGIN = PluginSpec(
    name="urlsniffer",
    message_handlers=(MessageHandlerSpec(handler=handle_urlsniffer),),
)