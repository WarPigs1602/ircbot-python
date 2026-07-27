import threading

from plugin_system import CommandSpec, PluginSpec


MESSAGES = {
    "de": {
        "help_label": "Befehle",
        "help_admin_label": "Admin-Befehle:",
        "help_admin_login_label": "Admin-Login:",
    },
    "en": {
        "help_label": "Commands",
        "help_admin_label": "Admin commands:",
        "help_admin_login_label": "Admin login:",
    },
}

ADMIN_HELP_ENTRIES = {
    "de": (
        "logout - beendet deine aktuelle Admin-Session.",
        "whoami - zeigt deine aktuelle Rolle und gesetzte Rechte.",
        "listusers - listet alle gespeicherten Admin-Benutzer auf.",
        "adduser <name> <ident@host> <passwort> [rolle] - legt einen Benutzer an.",
        "deluser <ident@host> - entfernt einen Benutzer vollständig.",
        "setrole <ident@host> <rolle> - weist einem Benutzer eine andere Rolle zu.",
        "listroles - zeigt alle Rollen mit Admin- und RAW-Rechten.",
        "roleadd <rolle> [admin=on] [raw=on] - legt eine neue Rolle an.",
        "roleflag <rolle> <admin|raw> <on|off> - schaltet ein Rollen-Flag um.",
        "rolemode <rolle> <#channel> <modus> - erlaubt einen Channel-Modus für eine Rolle.",
        "rolemode-del <rolle> <#channel> <modus> - entfernt diesen Rollen-Modus wieder.",
        "usermode <ident@host> <#channel> <modus> - setzt eine benutzerspezifische Ausnahme.",
        "usermode-del <ident@host> <#channel> <modus> - entfernt diese Benutzer-Ausnahme.",
        "apply <nick> <#channel> <ident@host> - wendet die gespeicherten Modi sofort an.",
        "raw <IRC-RAW-Zeile> - sendet eine IRC-Zeile direkt an den Server.",
    ),
    "en": (
        "logout - ends your current admin session.",
        "whoami - shows your current role and granted rights.",
        "listusers - shows all stored admin users.",
        "adduser <name> <ident@host> <password> [role] - creates a user.",
        "deluser <ident@host> - removes a user completely.",
        "setrole <ident@host> <role> - assigns a different role to a user.",
        "listroles - shows all roles with admin and RAW rights.",
        "roleadd <role> [admin=on] [raw=on] - creates a new role.",
        "roleflag <role> <admin|raw> <on|off> - toggles one role flag.",
        "rolemode <role> <#channel> <mode> - allows one channel mode for a role.",
        "rolemode-del <role> <#channel> <mode> - removes that role mode again.",
        "usermode <ident@host> <#channel> <mode> - creates a user-specific override.",
        "usermode-del <ident@host> <#channel> <mode> - removes that user override.",
        "apply <nick> <#channel> <ident@host> - applies the stored modes immediately.",
        "raw <IRC raw line> - sends one IRC line directly to the server.",
    ),
}


def help_language(bot) -> str:
    return bot.config.language if bot.config.language in {"de", "en"} else "de"


def authenticated_admin_row(bot, context):
    if not context.is_private_message or not context.source_mask or "admin" not in bot.plugin_manager.loaded_plugins:
        return None
    return bot.get_authenticated_admin(context.source_mask, require_admin=True)


def admin_help_entries(bot, context) -> tuple[str, ...]:
    admin_row = authenticated_admin_row(bot, context)
    if admin_row is None or not bool(int(admin_row.get("is_admin", 0))):
        return ()

    return ADMIN_HELP_ENTRIES[help_language(bot)]


def admin_login_help_entries(bot, context) -> tuple[str, ...]:
    login_entries: tuple[str, ...] = ()
    if context.is_private_message and "admin" in bot.plugin_manager.loaded_plugins:
        is_admin = authenticated_admin_row(bot, context) is not None
        if not is_admin:
            login_entries = (bot.tr("admin_help_auth_1"),)
    return login_entries


def send_help_notices(
    bot,
    target: str,
    entries: tuple[str, ...],
    admin_entries: tuple[str, ...],
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

    if login_entries:
        bot.send_notice(target, bot.tr("help_admin_login_label"))
        for entry in login_entries:
            bot.send_notice(target, entry)


def handle_help(bot, context, arg: str) -> None:
    entries = tuple(bot.build_help_entries(context.command_prefix, context))
    if context.is_private_message and "admin" in bot.plugin_manager.loaded_plugins:
        entries = tuple(entry for entry in entries if not entry.startswith(context.command_prefix + "help "))
    admin_entries = tuple(admin_help_entries(bot, context))
    login_entries = tuple(admin_login_help_entries(bot, context))
    if context.is_private_message and login_entries and not admin_entries:
        version_prefixes = tuple(
            f"{context.command_prefix}{alias}"
            for alias in bot.command_aliases().get("version", [])
        )
        entries = tuple(entry for entry in entries if entry.startswith(version_prefixes))
    worker = threading.Thread(
        target=send_help_notices,
        args=(bot, context.source_nick, entries, admin_entries, login_entries),
        name=f"help-notice-{context.source_nick}",
        daemon=True,
    )
    worker.start()


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
    ),
)