from plugin_system import CommandSpec, PluginSpec


MESSAGES = {
    "de": {
        "help_label": "Befehle",
    },
    "en": {
        "help_label": "Commands",
    },
}


def handle_help(bot, context, arg: str) -> None:
    entries = bot.build_help_entries(context.command_prefix)
    bot.send_notice(context.source_nick, f"{bot.tr('help_label')}: " + ", ".join(entries))


PLUGIN = PluginSpec(
    name="help",
    translations=MESSAGES,
    commands=(
        CommandSpec(
            canonical="help",
            handler=handle_help,
            aliases=("hilfe",),
            primary_names={"de": "hilfe", "en": "help"},
            help_sort=10,
        ),
    ),
)