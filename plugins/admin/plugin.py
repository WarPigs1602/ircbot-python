from __future__ import annotations

from plugin_system import CommandSpec, MessageHandlerSpec, PluginSpec


MESSAGES = {
    "de": {
        "admin_help_overview": (
            "Admin-PM Übersicht: "
            "help [auth|users|roles|modes|raw]"
        ),
        "admin_help_auth": (
            "Auth: login <passwort> | logout | whoami"
        ),
        "admin_help_users": (
            "User: listusers | adduser <name> <ident@host> <passwort> [rolle] | "
            "deluser <ident@host> | setrole <ident@host> <rolle>"
        ),
        "admin_help_roles": (
            "Rollen: listroles | roleadd <rolle> [admin=on] [raw=on] | "
            "roleflag <rolle> <admin|raw> <on|off>"
        ),
        "admin_help_modes": (
            "Rechte: rolemode <rolle> <#channel> <modus> | rolemode-del <rolle> <#channel> <modus> | "
            "usermode <ident@host> <#channel> <modus> | usermode-del <ident@host> <#channel> <modus> | "
            "apply <nick> <#channel> <ident@host>"
        ),
        "admin_help_raw": (
            "RAW: raw <IRC-RAW-Zeile> sendet die Zeile direkt an den Server, z.B. "
            "raw MODE #chan +o Nick"
        ),
        "admin_pm_only": "Administrative Befehle nur per privater Nachricht an den Bot.",
        "admin_prefix_forbidden": "Administrative Befehle im PM bitte ohne Prefix senden.",
        "admin_hostmask_missing": "Deine Hostmask ist unvollständig. Bitte mit ident@host verbinden.",
        "admin_auth_required": "Bitte zuerst mit login <passwort> authentifizieren.",
        "admin_not_allowed": "Deine Rolle darf diesen Befehl nicht ausführen.",
        "admin_usage_login": "Nutzung: login <passwort>",
        "admin_usage_adduser": "Nutzung: adduser <name> <ident@host> <passwort> [rolle]",
        "admin_usage_deluser": "Nutzung: deluser <ident@host>",
        "admin_usage_setrole": "Nutzung: setrole <ident@host> <rolle>",
        "admin_usage_roleadd": "Nutzung: roleadd <rolle> [admin=on] [raw=on]",
        "admin_usage_roleflag": "Nutzung: roleflag <rolle> <admin|raw> <on|off>",
        "admin_usage_rolemode": "Nutzung: rolemode <rolle> <#channel> <modus>",
        "admin_usage_usermode": "Nutzung: usermode <ident@host> <#channel> <modus>",
        "admin_usage_apply": "Nutzung: apply <nick> <#channel> <ident@host>",
        "admin_unknown": "Unbekannter Admin-Unterbefehl. help zeigt die Übersicht.",
        "admin_help_unknown": "Unbekanntes Hilfethema. Erlaubt: auth, users, roles, modes, raw.",
        "admin_roles_empty": "Keine Rollen konfiguriert.",
        "admin_users_empty": "Keine Benutzer konfiguriert.",
        "admin_whoami": "Du bist {mask} mit Rolle {role} (admin={admin}, raw={raw}).",
        "admin_raw_usage": "Nutzung: raw <IRC-RAW-Zeile>",
        "admin_raw_sent": "RAW gesendet.",
        "admin_logout_ok": "Logout erfolgreich.",
        "admin_logout_missing": "Keine aktive Session.",
    },
    "en": {
        "admin_help_overview": (
            "Admin PM overview: "
            "help [auth|users|roles|modes|raw]"
        ),
        "admin_help_auth": (
            "Auth: login <password> | logout | whoami"
        ),
        "admin_help_users": (
            "Users: listusers | adduser <name> <ident@host> <password> [role] | "
            "deluser <ident@host> | setrole <ident@host> <role>"
        ),
        "admin_help_roles": (
            "Roles: listroles | roleadd <role> [admin=on] [raw=on] | "
            "roleflag <role> <admin|raw> <on|off>"
        ),
        "admin_help_modes": (
            "Modes: rolemode <role> <#channel> <mode> | rolemode-del <role> <#channel> <mode> | "
            "usermode <ident@host> <#channel> <mode> | usermode-del <ident@host> <#channel> <mode> | "
            "apply <nick> <#channel> <ident@host>"
        ),
        "admin_help_raw": (
            "RAW: raw <IRC raw line> sends the line directly to the server, e.g. "
            "raw MODE #chan +o Nick"
        ),
        "admin_pm_only": "Administrative commands only work in private messages to the bot.",
        "admin_prefix_forbidden": "Send administrative PM commands without the prefix.",
        "admin_hostmask_missing": "Your hostmask is incomplete. Please connect with ident@host.",
        "admin_auth_required": "Authenticate first with login <password>.",
        "admin_not_allowed": "Your role is not allowed to run this command.",
        "admin_usage_login": "Usage: login <password>",
        "admin_usage_adduser": "Usage: adduser <name> <ident@host> <password> [role]",
        "admin_usage_deluser": "Usage: deluser <ident@host>",
        "admin_usage_setrole": "Usage: setrole <ident@host> <role>",
        "admin_usage_roleadd": "Usage: roleadd <role> [admin=on] [raw=on]",
        "admin_usage_roleflag": "Usage: roleflag <role> <admin|raw> <on|off>",
        "admin_usage_rolemode": "Usage: rolemode <role> <#channel> <mode>",
        "admin_usage_usermode": "Usage: usermode <ident@host> <#channel> <mode>",
        "admin_usage_apply": "Usage: apply <nick> <#channel> <ident@host>",
        "admin_unknown": "Unknown admin subcommand. help shows the overview.",
        "admin_help_unknown": "Unknown help topic. Allowed: auth, users, roles, modes, raw.",
        "admin_roles_empty": "No roles configured.",
        "admin_users_empty": "No users configured.",
        "admin_whoami": "You are {mask} with role {role} (admin={admin}, raw={raw}).",
        "admin_raw_usage": "Usage: raw <IRC raw line>",
        "admin_raw_sent": "RAW sent.",
        "admin_logout_ok": "Logout successful.",
        "admin_logout_missing": "No active session.",
    },
}


def parse_switch(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"on", "true", "yes", "1"}:
        return True
    if normalized in {"off", "false", "no", "0"}:
        return False
    return None


def reply(bot, context, message: str) -> None:
    bot.send_privmsg(context.reply_target, message)


def reply_admin_help(bot, context, topic: str = "") -> None:
    values: dict[str, str] = {}
    normalized_topic = topic.strip().lower()

    if not normalized_topic:
        for key in (
            "admin_help_overview",
            "admin_help_auth",
            "admin_help_users",
            "admin_help_roles",
            "admin_help_modes",
            "admin_help_raw",
        ):
            reply(bot, context, bot.tr(key, **values))
        return

    topic_key = {
        "auth": "admin_help_auth",
        "users": "admin_help_users",
        "roles": "admin_help_roles",
        "modes": "admin_help_modes",
        "raw": "admin_help_raw",
    }.get(normalized_topic)
    if topic_key is None:
        reply(bot, context, bot.tr("admin_help_unknown"))
        reply(bot, context, bot.tr("admin_help_overview", **values))
        return

    reply(bot, context, bot.tr(topic_key, **values))


def require_private(bot, context) -> bool:
    if context.is_private_message:
        return True
    bot.send_notice(context.source_nick, bot.tr("admin_pm_only"))
    return False


def require_hostmask(bot, context) -> str | None:
    if context.source_mask:
        return context.source_mask
    reply(bot, context, bot.tr("admin_hostmask_missing"))
    return None


def require_admin(bot, context, require_raw: bool = False):
    if not require_private(bot, context):
        return None

    source_mask = require_hostmask(bot, context)
    if source_mask is None:
        return None

    admin_row = bot.get_authenticated_admin(source_mask, require_admin=True, require_raw=require_raw)
    if admin_row is None:
        reply(bot, context, bot.tr("admin_auth_required"))
        return None

    if require_raw and not bool(int(admin_row.get("can_raw", 0))):
        reply(bot, context, bot.tr("admin_not_allowed"))
        return None

    return admin_row


def render_roles(bot) -> str:
    roles = bot.list_admin_roles()
    if not roles:
        return bot.tr("admin_roles_empty")

    rendered = []
    for role in roles:
        rendered.append(
            f"{role.get('role_name')}"
            f"(admin={'on' if int(role.get('is_admin', 0)) else 'off'},raw={'on' if int(role.get('can_raw', 0)) else 'off'})"
        )
    return "; ".join(rendered)


def render_users(bot) -> str:
    users = bot.list_admin_users()
    if not users:
        return bot.tr("admin_users_empty")

    rendered = []
    for user in users:
        label = str(user.get("display_name", "")).strip()
        suffix = f"/{label}" if label else ""
        rendered.append(f"{user.get('user_mask')} -> {user.get('role_name')}{suffix}")
    return "; ".join(rendered)


def reply_admin_usage(bot, context, key: str) -> None:
    reply(bot, context, bot.tr(key))


def is_prefixed_admin_message(context) -> bool:
    if not context.is_private_message:
        return False
    if not context.message.startswith(context.command_prefix):
        return False

    without_prefix = context.message[len(context.command_prefix):].strip().lower()
    if not without_prefix:
        return False

    token = without_prefix.split(maxsplit=1)[0]
    return token in {
        "login",
        "logout",
        "whoami",
        "listroles",
        "listusers",
        "roleadd",
        "roleflag",
        "adduser",
        "deluser",
        "setrole",
        "rolemode",
        "rolemode-del",
        "usermode",
        "usermode-del",
        "apply",
    }


def parse_pm_admin_message(message: str) -> tuple[str, str] | None:
    stripped = message.strip()
    if not stripped:
        return None

    parts = stripped.split(maxsplit=1)
    command = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    if command == "admin":
        nested = rest.strip()
        if not nested:
            return "help", ""
        nested_parts = nested.split(maxsplit=1)
        return nested_parts[0].lower(), nested_parts[1] if len(nested_parts) > 1 else ""

    if command in {
        "help",
        "login",
        "logout",
        "whoami",
        "listroles",
        "listusers",
        "roleadd",
        "roleflag",
        "adduser",
        "deluser",
        "setrole",
        "rolemode",
        "rolemode-del",
        "usermode",
        "usermode-del",
        "apply",
        "raw",
    }:
        return command, rest

    return None


def handle_admin_message(bot, context) -> None:
    if not context.is_private_message:
        return

    if is_prefixed_admin_message(context):
        reply(bot, context, bot.tr("admin_prefix_forbidden"))
        return

    parsed = parse_pm_admin_message(context.message)
    if parsed is None:
        return

    command, rest = parsed
    if command == "raw":
        handle_raw(bot, context, rest)
        return

    handle_admin(bot, context, f"{command} {rest}".strip())


def handle_admin_roleadd(bot, context, parts: list[str]) -> None:
    if len(parts) < 2:
        reply_admin_usage(bot, context, "admin_usage_roleadd")
        return

    role_name = parts[1]
    is_admin = False
    can_raw = False
    for token in parts[2:]:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        parsed = parse_switch(value)
        if parsed is None:
            continue
        if key.lower() == "admin":
            is_admin = parsed
        if key.lower() == "raw":
            can_raw = parsed

    _, message = bot.create_admin_role(role_name, is_admin=is_admin, can_raw=can_raw)
    reply(bot, context, message)


def handle_admin_roleflag(bot, context, parts: list[str]) -> None:
    if len(parts) != 4:
        reply_admin_usage(bot, context, "admin_usage_roleflag")
        return

    enabled = parse_switch(parts[3])
    if enabled is None:
        reply_admin_usage(bot, context, "admin_usage_roleflag")
        return

    _, message = bot.set_role_flag(parts[1], parts[2], enabled)
    reply(bot, context, message)


def handle_admin_public(bot, context, source_mask: str, subcommand: str, rest: str) -> bool:
    if subcommand == "help":
        reply_admin_help(bot, context, rest)
        return True

    if subcommand == "login":
        if not rest:
            reply_admin_usage(bot, context, "admin_usage_login")
            return True
        _, message = bot.login_admin_user(source_mask, rest, context.source_nick)
        reply(bot, context, message)
        return True

    if subcommand == "logout":
        if bot.logout_admin_user(source_mask):
            reply(bot, context, bot.tr("admin_logout_ok"))
        else:
            reply(bot, context, bot.tr("admin_logout_missing"))
        return True

    return False


def handle_admin_role_command(bot, context, parts: list[str]) -> bool:
    subcommand = parts[0].lower()

    if subcommand == "roleadd":
        handle_admin_roleadd(bot, context, parts)
        return True

    if subcommand == "roleflag":
        handle_admin_roleflag(bot, context, parts)
        return True

    return False


def handle_admin_user_command(bot, context, parts: list[str], source_mask: str) -> bool:
    subcommand = parts[0].lower()

    if subcommand == "adduser":
        if len(parts) < 4:
            reply_admin_usage(bot, context, "admin_usage_adduser")
            return True
        role_name = parts[4] if len(parts) >= 5 else "user"
        _, message = bot.create_admin_user(
            display_name=parts[1],
            user_mask=parts[2],
            password=parts[3],
            role_name=role_name,
            created_by=source_mask,
        )
        reply(bot, context, message)
        return True

    if subcommand == "deluser":
        if len(parts) != 2:
            reply_admin_usage(bot, context, "admin_usage_deluser")
            return True
        _, message = bot.delete_admin_user(parts[1])
        reply(bot, context, message)
        return True

    if subcommand == "setrole":
        if len(parts) != 3:
            reply_admin_usage(bot, context, "admin_usage_setrole")
            return True
        _, message = bot.set_admin_user_role(parts[1], parts[2])
        reply(bot, context, message)
        return True

    return False


def handle_admin_mode_command(bot, context, parts: list[str]) -> bool:
    subcommand = parts[0].lower()

    if subcommand in {"rolemode", "rolemode-del"}:
        if len(parts) != 4:
            reply_admin_usage(bot, context, "admin_usage_rolemode")
            return True
        _, message = bot.set_role_channel_mode(parts[1], parts[2], parts[3], enabled=subcommand == "rolemode")
        reply(bot, context, message)
        return True

    if subcommand in {"usermode", "usermode-del"}:
        if len(parts) != 4:
            reply_admin_usage(bot, context, "admin_usage_usermode")
            return True
        _, message = bot.set_user_channel_mode(parts[1], parts[2], parts[3], enabled=subcommand == "usermode")
        reply(bot, context, message)
        return True

    if subcommand == "apply":
        if len(parts) != 4:
            reply_admin_usage(bot, context, "admin_usage_apply")
            return True
        _, message = bot.apply_channel_modes_for_mask(parts[2], parts[1], parts[3])
        reply(bot, context, message)
        return True

    return False


def handle_admin_authenticated(bot, context, parts: list[str], source_mask: str, admin_row) -> bool:
    subcommand = parts[0].lower()

    if subcommand == "whoami":
        reply(
            bot,
            context,
            bot.tr(
                "admin_whoami",
                mask=source_mask,
                role=str(admin_row.get("role_name", "?")),
                admin="on" if int(admin_row.get("is_admin", 0)) else "off",
                raw="on" if int(admin_row.get("can_raw", 0)) else "off",
            ),
        )
        return True

    if subcommand == "listroles":
        reply(bot, context, render_roles(bot))
        return True

    if subcommand == "listusers":
        reply(bot, context, render_users(bot))
        return True

    return (
        handle_admin_role_command(bot, context, parts)
        or handle_admin_user_command(bot, context, parts, source_mask)
        or handle_admin_mode_command(bot, context, parts)
    )


def handle_admin(bot, context, arg: str) -> None:
    if context.message.startswith(context.command_prefix):
        reply(bot, context, bot.tr("admin_prefix_forbidden"))
        return

    if not require_private(bot, context):
        return

    source_mask = require_hostmask(bot, context)
    if source_mask is None:
        return

    parts = arg.strip().split()
    if not parts:
        reply_admin_help(bot, context)
        return

    subcommand = parts[0].lower()
    rest = arg.strip()[len(parts[0]):].strip() if arg.strip() else ""

    if handle_admin_public(bot, context, source_mask, subcommand, rest):
        return

    admin_row = require_admin(bot, context)
    if admin_row is None:
        return

    if handle_admin_authenticated(bot, context, parts, source_mask, admin_row):
        return

    reply(
        bot,
        context,
        bot.tr(
            "admin_unknown",
            prefix=context.command_prefix,
            admin=bot.primary_command_name("admin"),
        ),
    )


def handle_raw(bot, context, arg: str) -> None:
    if context.message.startswith(context.command_prefix):
        reply(bot, context, bot.tr("admin_prefix_forbidden"))
        return

    admin_row = require_admin(bot, context)
    if admin_row is None:
        return

    if not bool(int(admin_row.get("can_raw", 0))):
        reply(bot, context, bot.tr("admin_not_allowed"))
        return

    line = arg.lstrip()
    if not line:
        reply(
            bot,
            context,
            bot.tr(
                "admin_raw_usage",
                prefix=context.command_prefix,
                raw=bot.primary_command_name("raw"),
            ),
        )
        return

    bot.send_raw(line)
    reply(bot, context, bot.tr("admin_raw_sent"))


PLUGIN = PluginSpec(
    name="admin",
    translations=MESSAGES,
    message_handlers=(
        MessageHandlerSpec(handler=handle_admin_message),
    ),
    commands=(
        CommandSpec(
            canonical="admin",
            handler=handle_admin,
            aliases=("adm",),
            help_args={"de": "help", "en": "help"},
            help_sort=5,
        ),
        CommandSpec(
            canonical="raw",
            handler=handle_raw,
            help_args={"de": "<irc-raw>", "en": "<irc-raw>"},
            help_sort=6,
        ),
    ),
)
