import threading

from plugin_system import CommandSpec, PluginSpec


MESSAGES = {
    "de": {
        "help_label": "Befehle",
        "help_admin_label": "Admin-Befehle:",
        "help_mg_admin_label": "Mondgesicht-Verwaltung:",
        "help_admin_login_label": "Admin-Login:",
        "help_moonface_empty": "Keine Mondgesicht-Befehle für diesen Channel verfügbar.",
    },
    "en": {
        "help_label": "Commands",
        "help_admin_label": "Admin commands:",
        "help_mg_admin_label": "Moonface management:",
        "help_admin_login_label": "Admin login:",
        "help_moonface_empty": "No Moonface commands are available for this channel.",
    },
}


def help_language(bot) -> str:
    return bot.config.language if bot.config.language in {"de", "en"} else "de"


def authenticated_admin_row(bot, context):
    if not context.is_private_message or not context.source_mask or "admin" not in bot.plugin_manager.loaded_plugins:
        return None
    return bot.get_authenticated_admin(context.source_mask, require_admin=True)


def admin_help_entries(bot, context) -> tuple[str, ...]:
    if "admin" not in bot.plugin_manager.loaded_plugins:
        return ()
    try:
        from plugins.admin.plugin import get_admin_help_entries
    except Exception:
        return ()
    return tuple(get_admin_help_entries(bot, context))


def admin_mg_help_entries(bot, context) -> tuple[str, ...]:
    if "moonface" not in bot.plugin_manager.loaded_plugins:
        return ()
    try:
        from plugins.moonface.plugin import get_admin_mg_help_entries
    except Exception:
        return ()
    return tuple(get_admin_mg_help_entries(bot, context))


def admin_login_help_entries(bot, context) -> tuple[str, ...]:
    login_entries: tuple[str, ...] = ()
    if context.is_private_message and "admin" in bot.plugin_manager.loaded_plugins:
        is_admin = authenticated_admin_row(bot, context) is not None
        if not is_admin:
            login_entries = (bot.tr("admin_help_auth_1"),)
    return login_entries


def moonface_command_canonicals() -> tuple[str, ...]:
    try:
        from plugins.moonface.plugin import MOONFACE_COMMANDS
    except Exception:
        return ()
    return MOONFACE_COMMANDS


def moonface_help_visible(bot, context) -> bool:
    if context.is_private_message:
        return False
    if "moonface" not in bot.plugin_manager.loaded_plugins:
        return False
    try:
        from plugins.moonface.plugin import mondgesicht_channels as _mondgesicht_channels
    except Exception:
        return False
    active_channels = {channel.strip().lower() for channel in _mondgesicht_channels(bot) if channel.strip()}
    return bool(active_channels) and context.target.lower() in active_channels


def moonface_help_entries(bot, context) -> tuple[str, ...]:
    if not moonface_help_visible(bot, context):
        return ()

    all_entries = tuple(bot.build_help_entries(context.command_prefix, context))
    canonicals = moonface_command_canonicals()
    prefixes = tuple(
        f"{context.command_prefix}{bot.primary_command_name(canonical)}"
        for canonical in canonicals
    )
    return tuple(entry for entry in all_entries if entry.startswith(prefixes))


def send_help_notices(
    bot,
    target: str,
    entries: tuple[str, ...],
    admin_entries: tuple[str, ...],
    mg_admin_entries: tuple[str, ...],
    login_entries: tuple[str, ...],
) -> None:
    if entries:
        bot.send_notice(target, f"{bot.tr('help_label')}:")
        for entry in entries:
            bot.send_notice(target, entry)

    if admin_entries:
        bot.send_notice(target, bot.tr("help_admin_label"))
        for entry in admin_entries:
            bot.send_notice(target, entry)

    if mg_admin_entries:
        bot.send_notice(target, bot.tr("help_mg_admin_label"))
        for entry in mg_admin_entries:
            bot.send_notice(target, entry)

    if login_entries:
        bot.send_notice(target, bot.tr("help_admin_login_label"))
        for entry in login_entries:
            bot.send_notice(target, entry)


def handle_help(bot, context, arg: str) -> None:
    entries = tuple(bot.build_help_entries(context.command_prefix, context))
    if context.is_private_message and "admin" in bot.plugin_manager.loaded_plugins:
        entries = tuple(entry for entry in entries if not entry.startswith(context.command_prefix + "help "))
    admin_entries = tuple(admin_help_entries(bot, context))
    mg_admin_entries = tuple(admin_mg_help_entries(bot, context))
    login_entries = tuple(admin_login_help_entries(bot, context))
    if context.is_private_message and login_entries and not admin_entries:
        version_prefixes = tuple(
            f"{context.command_prefix}{alias}"
            for alias in bot.command_aliases().get("version", [])
        )
        entries = tuple(entry for entry in entries if entry.startswith(version_prefixes))
        mg_admin_entries = ()
    worker = threading.Thread(
        target=send_help_notices,
        args=(bot, context.source_nick, entries, admin_entries, mg_admin_entries, login_entries),
        name=f"help-notice-{context.source_nick}",
        daemon=True,
    )
    worker.start()


def handle_moonface_help(bot, context, arg: str) -> None:
    entries = moonface_help_entries(bot, context)
    if not entries:
        bot.send_notice(context.source_nick, bot.tr("help_moonface_empty"))
        return

    send_help_notices(bot, context.source_nick, entries, (), (), ())


PLUGIN = PluginSpec(
    name="help",
    translations=MESSAGES,
    commands=(
        CommandSpec(
            canonical="help",
            handler=handle_help,
            aliases=("hilfe",),
            primary_names={"de": "hilfe", "en": "help"},
            help_texts={
                "de": "zeigt die verfuegbaren Befehle",
                "en": "shows the available commands",
            },
            help_sort=10,
        ),
        CommandSpec(
            canonical="moonfacehelp",
            handler=handle_moonface_help,
            aliases=("mondgesichthilfe",),
            primary_names={"de": "mondgesichthilfe", "en": "moonfacehelp"},
            help_texts={
                "de": "zeigt die Mondgesicht-Befehle für den aktuellen Channel",
                "en": "shows the Moonface commands for the current channel",
            },
            help_visible=moonface_help_visible,
            help_sort=85,
        ),
    ),
)
