from __future__ import annotations

import hashlib
import hmac
import os
import re
import time

from plugin_system import CommandSpec, MessageHandlerSpec, PluginSpec

try:
    import pymysql
except ImportError:
    pymysql = None

try:
    from plugins.rss.plugin import get_rss_announce_channels, set_rss_announce_channels
except Exception:
    get_rss_announce_channels = None
    set_rss_announce_channels = None


class AdminRepository:
    def __init__(self, db_conn, network_key):
        self.db_conn = db_conn
        self.network_key = network_key

    def has_users(self):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM bot_admin_users WHERE network = %s LIMIT 1",
                    (self.network_key,),
                )
                return cur.fetchone() is not None
        except Exception:
            return False

    def ensure_default_role(self, current_time):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM bot_admin_roles WHERE network = %s AND role_name = %s LIMIT 1",
                    (self.network_key, "admin"),
                )
                if cur.fetchone() is not None:
                    cur.execute(
                        "UPDATE bot_admin_roles SET is_admin = 1, can_raw = 1 WHERE network = %s AND role_name = %s",
                        (self.network_key, "admin"),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO bot_admin_roles (network, role_name, is_admin, can_raw, created_at)
                        VALUES (%s, %s, 1, 1, %s)
                        """,
                        (self.network_key, "admin", current_time),
                    )

                cur.execute(
                    "SELECT 1 FROM bot_admin_roles WHERE network = %s AND role_name = %s LIMIT 1",
                    (self.network_key, "user"),
                )
                if cur.fetchone() is None:
                    cur.execute(
                        """
                        INSERT INTO bot_admin_roles (network, role_name, is_admin, can_raw, created_at)
                        VALUES (%s, %s, 0, 0, %s)
                        """,
                        (self.network_key, "user", current_time),
                    )
        except Exception:
            pass

    def load_user(self, user_mask):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT u.user_mask, u.display_name, u.password_salt, u.password_hash, u.role_name,
                           COALESCE(r.is_admin, 0) AS is_admin,
                           COALESCE(r.can_raw, 0) AS can_raw
                    FROM bot_admin_users u
                    LEFT JOIN bot_admin_roles r
                      ON r.network = u.network AND r.role_name = u.role_name
                    WHERE u.network = %s AND u.user_mask = %s
                    LIMIT 1
                    """,
                    (self.network_key, user_mask),
                )
                return cur.fetchone()
        except Exception:
            return None

    def create_role(self, role_name, is_admin=False, can_raw=False, current_time=""):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM bot_admin_roles WHERE network = %s AND role_name = %s LIMIT 1",
                    (self.network_key, role_name),
                )
                if cur.fetchone() is not None:
                    return False
                cur.execute(
                    """
                    INSERT INTO bot_admin_roles (network, role_name, is_admin, can_raw, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (self.network_key, role_name, 1 if is_admin else 0, 1 if can_raw else 0, current_time),
                )
            return True
        except Exception:
            return False

    def set_role_flag(self, role_name, flag_name, enabled):
        allowed_columns = {"admin": "is_admin", "raw": "can_raw"}
        column = allowed_columns.get(flag_name)
        if not column:
            return False
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(
                    f"UPDATE bot_admin_roles SET {column} = %s WHERE network = %s AND role_name = %s",
                    (1 if enabled else 0, self.network_key, role_name),
                )
                return cur.rowcount > 0
        except Exception:
            return False

    def list_roles(self):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT role_name, is_admin, can_raw
                    FROM bot_admin_roles
                    WHERE network = %s
                    ORDER BY role_name ASC
                    """,
                    (self.network_key,),
                )
                return list(cur.fetchall() or [])
        except Exception:
            return []

    def create_user(self, display_name, user_mask, password_salt, password_hash, role_name, current_time, created_by):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM bot_admin_roles WHERE network = %s AND role_name = %s LIMIT 1",
                    (self.network_key, role_name),
                )
                if cur.fetchone() is None:
                    return False, "role_missing"

                cur.execute(
                    "SELECT 1 FROM bot_admin_users WHERE network = %s AND user_mask = %s LIMIT 1",
                    (self.network_key, user_mask),
                )
                if cur.fetchone() is not None:
                    return False, "user_exists"

                cur.execute(
                    """
                    INSERT INTO bot_admin_users
                        (network, user_mask, display_name, password_salt, password_hash, role_name, created_at, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self.network_key,
                        user_mask,
                        display_name[:64],
                        password_salt,
                        password_hash,
                        role_name,
                        current_time,
                        created_by[:64],
                    ),
                )
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def delete_user(self, user_mask):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM bot_admin_user_modes WHERE network = %s AND user_mask = %s",
                    (self.network_key, user_mask),
                )
                cur.execute(
                    "DELETE FROM bot_admin_users WHERE network = %s AND user_mask = %s",
                    (self.network_key, user_mask),
                )
                return cur.rowcount > 0
        except Exception:
            return False

    def set_user_role(self, user_mask, role_name):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(
                    "UPDATE bot_admin_users SET role_name = %s WHERE network = %s AND user_mask = %s",
                    (role_name, self.network_key, user_mask),
                )
                return cur.rowcount > 0
        except Exception:
            return False

    def list_users(self):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_mask, display_name, role_name
                    FROM bot_admin_users
                    WHERE network = %s
                    ORDER BY user_mask ASC
                    """,
                    (self.network_key,),
                )
                return list(cur.fetchall() or [])
        except Exception:
            return []

    def set_role_channel_mode(self, role_name, channel, mode, current_time, enabled):
        try:
            with self.db_conn.cursor() as cur:
                if enabled:
                    cur.execute(
                        """
                        INSERT IGNORE INTO bot_admin_role_modes (network, role_name, channel, mode, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (self.network_key, role_name, channel, mode, current_time),
                    )
                else:
                    cur.execute(
                        "DELETE FROM bot_admin_role_modes WHERE network = %s AND role_name = %s AND channel = %s AND mode = %s",
                        (self.network_key, role_name, channel, mode),
                    )
            return True
        except Exception:
            return False

    def set_user_channel_mode(self, user_mask, channel, mode, current_time, enabled):
        try:
            with self.db_conn.cursor() as cur:
                if enabled:
                    cur.execute(
                        """
                        INSERT IGNORE INTO bot_admin_user_modes (network, user_mask, channel, mode, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (self.network_key, user_mask, channel, mode, current_time),
                    )
                else:
                    cur.execute(
                        "DELETE FROM bot_admin_user_modes WHERE network = %s AND user_mask = %s AND channel = %s AND mode = %s",
                        (self.network_key, user_mask, channel, mode),
                    )
            return True
        except Exception:
            return False

    def get_configured_user_channel_modes(self, user_mask, channel):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(
                    "SELECT role_name FROM bot_admin_users WHERE network = %s AND user_mask = %s LIMIT 1",
                    (self.network_key, user_mask),
                )
                row = cur.fetchone() or {}
                role_name = str(row.get("role_name", "")).strip()

                modes = set()
                if role_name:
                    cur.execute(
                        "SELECT mode FROM bot_admin_role_modes WHERE network = %s AND role_name = %s AND channel = %s",
                        (self.network_key, role_name, channel),
                    )
                    modes.update(
                        mode
                        for mode in (
                            str(entry.get("mode", "")).strip()
                            for entry in (cur.fetchall() or [])
                        )
                        if mode
                    )

                cur.execute(
                    "SELECT mode FROM bot_admin_user_modes WHERE network = %s AND user_mask = %s AND channel = %s",
                    (self.network_key, user_mask, channel),
                )
                modes.update(
                    mode
                    for mode in (
                        str(entry.get("mode", "")).strip()
                        for entry in (cur.fetchall() or [])
                    )
                    if mode
                )
            return modes
        except Exception:
            return set()

    def get_user_assigned_channels(self, user_mask):
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(
                    "SELECT role_name FROM bot_admin_users WHERE network = %s AND user_mask = %s LIMIT 1",
                    (self.network_key, user_mask),
                )
                row = cur.fetchone() or {}
                role_name = str(row.get("role_name", "")).strip()

                channels = set()
                if role_name:
                    cur.execute(
                        "SELECT channel FROM bot_admin_role_modes WHERE network = %s AND role_name = %s",
                        (self.network_key, role_name),
                    )
                    channels.update(
                        str(entry.get("channel", "")).strip()
                        for entry in (cur.fetchall() or [])
                        if str(entry.get("channel", "")).strip()
                    )

                cur.execute(
                    "SELECT channel FROM bot_admin_user_modes WHERE network = %s AND user_mask = %s",
                    (self.network_key, user_mask),
                )
                channels.update(
                    str(entry.get("channel", "")).strip()
                    for entry in (cur.fetchall() or [])
                    if str(entry.get("channel", "")).strip()
                )
            return channels
        except Exception:
            return set()


MESSAGES = {
    "de": {
        "admin_help_overview": "Admin-PM Hilfe: help [{topics}]",
        "admin_help_auth_1": "login <passwort> authentifiziert deine Hostmask für Admin-Befehle.",
        "admin_help_auth_2": "logout beendet deine aktuelle Admin-Session.",
        "admin_help_auth_3": "whoami zeigt deine aktuelle Rolle und gesetzte Rechte.",
        "admin_help_users_1": "listusers listet alle gespeicherten Admin-Benutzer auf.",
        "admin_help_users_2": "adduser <name> <ident@host> <passwort> [rolle] legt einen Benutzer an.",
        "admin_help_users_3": "deluser <ident@host> entfernt einen Benutzer vollständig.",
        "admin_help_users_4": "setrole <ident@host> <rolle> weist einem Benutzer eine andere Rolle zu.",
        "admin_help_roles_1": "listroles zeigt alle Rollen mit Admin- und RAW-Rechten.",
        "admin_help_roles_2": "roleadd <rolle> [admin=on] [raw=on] legt eine neue Rolle an.",
        "admin_help_roles_3": "roleflag <rolle> <admin|raw> <on|off> schaltet ein Rollen-Flag um.",
        "admin_help_modes_1": "rolemode <rolle> <#channel> <modus> erlaubt einen Channel-Modus für eine Rolle.",
        "admin_help_modes_2": "rolemode-del <rolle> <#channel> <modus> entfernt diesen Rollen-Modus wieder.",
        "admin_help_modes_3": "usermode <ident@host> <#channel> <modus> setzt eine benutzerspezifische Ausnahme.",
        "admin_help_modes_4": "usermode-del <ident@host> <#channel> <modus> entfernt diese Benutzer-Ausnahme.",
        "admin_help_modes_5": "apply <nick> <#channel> <ident@host> wendet die gespeicherten Modi sofort an.",
        "admin_help_rss_1": "rssannounce zeigt den aktuellen RSS-Ankuendigungs-Channel.",
        "admin_help_rss_2": "rssannounce <#channel[,#channel...]> setzt einen oder mehrere RSS-Ankuendigungs-Channels.",
        "admin_help_rss_3": "rssannounce +<#channel[,#channel...]> fuegt Channels zur bestehenden Liste hinzu.",
        "admin_help_rss_4": "rssannounce -<#channel[,#channel...]> entfernt Channels einzeln aus der bestehenden Liste.",
        "admin_help_rss_5": "rssannounce off deaktiviert automatische RSS-Ankuendigungen.",
        "admin_help_mg_1": "mgadd [de|en] <punkt|komma|strich> speichert einen neuen Mondgesicht-Text.",
        "admin_help_mg_2": "mglist [de|en] [punkt|komma|strich] listet gespeicherte Mondgesicht-Texte auf.",
        "admin_help_mg_3": "mgdel <id> löscht einen Mondgesicht-Text per ID.",
        "admin_help_mg_4": "mgseed spielt die Standard-Mondgesicht-Texte erneut ein.",
        "admin_help_mg_5": "mgchannels zeigt alle aktiven Mondgesicht-Channels.",
        "admin_help_mg_6": "mgchannel-add <#channel> aktiviert Mondgesicht für einen Channel.",
        "admin_help_mg_7": "mgchannel-del <#channel> deaktiviert Mondgesicht für einen Channel.",
        "admin_help_mg_8": "mggott-add <#channel> <nick> trägt einen Mondgesicht-Gott channelspezifisch ein.",
        "admin_help_mg_9": "mggott-del <#channel> <nick> entfernt einen Mondgesicht-Gott channelspezifisch.",
        "admin_help_mg_10": "mgignore-add <#channel> <nick> trägt einen Mondgesicht-Ignore-Nick channelspezifisch ein.",
        "admin_help_mg_11": "mgignore-del <#channel> <nick> entfernt einen Mondgesicht-Ignore-Nick channelspezifisch.",
        "admin_help_raw_1": "raw <IRC-RAW-Zeile> sendet eine IRC-Zeile direkt an den Server.",
        "admin_help_raw_2": "Beispiel: raw MODE #chan +o Nick",
        "admin_help_caps": "caps zeigt die aktuell aktivierten IRC-Capabilities.",
        "admin_help_reload": "reloadplugins lädt alle Plugins dynamisch neu.",
        "admin_reload_ok": "Plugins wurden neu geladen ({count}): {plugins}",
        "admin_reload_failed": "Plugins konnten nicht neu geladen werden: {error}",
        "admin_caps_none": "Keine IRC-Capabilities aktiviert.",
        "admin_caps_enabled": "Aktive IRC-Capabilities: {caps}",
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
        "admin_usage_rssannounce": "Nutzung: rssannounce [#channel[,#channel...]|+#channel[,#channel...]|-#channel[,#channel...]|off]",
        "admin_unknown": "Unbekannter Admin-Unterbefehl. help zeigt die Übersicht.",
        "admin_help_unknown": "Unbekanntes Hilfethema. Erlaubt: {topics}.",
        "admin_roles_empty": "Keine Rollen konfiguriert.",
        "admin_users_empty": "Keine Benutzer konfiguriert.",
        "admin_rssannounce_current": "RSS-Ankuendigungs-Channels: {channels}",
        "admin_rssannounce_disabled": "RSS-Ankuendigungen sind deaktiviert.",
        "admin_rssannounce_set": "RSS-Ankuendigungs-Channels gesetzt auf {channels}.",
        "admin_rssannounce_cleared": "RSS-Ankuendigungs-Channel deaktiviert.",
        "admin_rssannounce_feeds": "Konfigurierte RSS-Feeds: {feeds}",
        "admin_rssannounce_feeds_none": "Keine RSS-Feeds konfiguriert.",
        "admin_rssannounce_feeds_channel": "RSS-Feeds fuer diesen Channel: {feeds}",
        "admin_rssannounce_invalid": "Ungueltiger Channel. Erwarte #channel oder #channel,#channel oder +#channel oder -#channel oder off.",
        "admin_rssannounce_save_failed": "RSS-Ankuendigungs-Channel konnte nicht gespeichert werden: {error}",
        "admin_whoami": "Du bist {mask} mit Rolle {role} (admin={admin}, raw={raw}).",
        "admin_raw_usage": "Nutzung: raw <IRC-RAW-Zeile>",
        "admin_raw_sent": "RAW gesendet.",
        "admin_logout_ok": "Logout erfolgreich.",
        "admin_logout_missing": "Keine aktive Session.",
    },
    "en": {
        "admin_help_overview": "Admin PM help: help [{topics}]",
        "admin_help_auth_1": "login <password> authenticates your hostmask for admin commands.",
        "admin_help_auth_2": "logout ends your current admin session.",
        "admin_help_auth_3": "whoami shows your current role and granted rights.",
        "admin_help_users_1": "listusers shows all stored admin users.",
        "admin_help_users_2": "adduser <name> <ident@host> <password> [role] creates a user.",
        "admin_help_users_3": "deluser <ident@host> removes a user completely.",
        "admin_help_users_4": "setrole <ident@host> <role> assigns a different role to a user.",
        "admin_help_roles_1": "listroles shows all roles with admin and RAW rights.",
        "admin_help_roles_2": "roleadd <role> [admin=on] [raw=on] creates a new role.",
        "admin_help_roles_3": "roleflag <role> <admin|raw> <on|off> toggles one role flag.",
        "admin_help_modes_1": "rolemode <role> <#channel> <mode> allows one channel mode for a role.",
        "admin_help_modes_2": "rolemode-del <role> <#channel> <mode> removes that role mode again.",
        "admin_help_modes_3": "usermode <ident@host> <#channel> <mode> creates a user-specific override.",
        "admin_help_modes_4": "usermode-del <ident@host> <#channel> <mode> removes that user override.",
        "admin_help_modes_5": "apply <nick> <#channel> <ident@host> applies the stored modes immediately.",
        "admin_help_rss_1": "rssannounce shows the current RSS announce channel.",
        "admin_help_rss_2": "rssannounce <#channel[,#channel...]> sets one or multiple RSS announce channels.",
        "admin_help_rss_3": "rssannounce +<#channel[,#channel...]> adds channels to the current list.",
        "admin_help_rss_4": "rssannounce -<#channel[,#channel...]> removes channels individually from the current list.",
        "admin_help_rss_5": "rssannounce off disables automatic RSS announcements.",
        "admin_help_mg_1": "mgadd [de|en] <point|comma|stroke> stores a new Moonface text.",
        "admin_help_mg_2": "mglist [de|en] [point|comma|stroke] lists stored Moonface texts.",
        "admin_help_mg_3": "mgdel <id> deletes a Moonface text by ID.",
        "admin_help_mg_4": "mgseed restores the built-in Moonface texts.",
        "admin_help_mg_5": "mgchannels shows all active Moonface channels.",
        "admin_help_mg_6": "mgchannel-add <#channel> enables Moonface for one channel.",
        "admin_help_mg_7": "mgchannel-del <#channel> disables Moonface for one channel.",
        "admin_help_mg_8": "mggod-add <#channel> <nick> stores one channel-specific Moonface god.",
        "admin_help_mg_9": "mggod-del <#channel> <nick> removes one channel-specific Moonface god.",
        "admin_help_mg_10": "mgignore-add <#channel> <nick> stores one channel-specific Moonface ignore nick.",
        "admin_help_mg_11": "mgignore-del <#channel> <nick> removes one channel-specific Moonface ignore nick.",
        "admin_help_raw_1": "raw <IRC raw line> sends one IRC line directly to the server.",
        "admin_help_raw_2": "Example: raw MODE #chan +o Nick",
        "admin_help_caps": "caps shows the currently active IRC capabilities.",
        "admin_help_reload": "reloadplugins dynamically reloads all plugins.",
        "admin_reload_ok": "Plugins reloaded ({count}): {plugins}",
        "admin_reload_failed": "Failed to reload plugins: {error}",
        "admin_caps_none": "No IRC capabilities active.",
        "admin_caps_enabled": "Active IRC capabilities: {caps}",
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
        "admin_usage_rssannounce": "Usage: rssannounce [#channel[,#channel...]|+#channel[,#channel...]|-#channel[,#channel...]|off]",
        "admin_unknown": "Unknown admin subcommand. help shows the overview.",
        "admin_help_unknown": "Unknown help topic. Allowed: {topics}.",
        "admin_roles_empty": "No roles configured.",
        "admin_users_empty": "No users configured.",
        "admin_rssannounce_current": "RSS announce channels: {channels}",
        "admin_rssannounce_disabled": "RSS announcements are disabled.",
        "admin_rssannounce_set": "RSS announce channels set to {channels}.",
        "admin_rssannounce_cleared": "RSS announce channel disabled.",
        "admin_rssannounce_feeds": "Configured RSS feeds: {feeds}",
        "admin_rssannounce_feeds_none": "No RSS feeds configured.",
        "admin_rssannounce_feeds_channel": "RSS feeds for this channel: {feeds}",
        "admin_rssannounce_invalid": "Invalid channel. Expected #channel or #channel,#channel or +#channel or -#channel or off.",
        "admin_rssannounce_save_failed": "Could not save RSS announce channel: {error}",
        "admin_whoami": "You are {mask} with role {role} (admin={admin}, raw={raw}).",
        "admin_raw_usage": "Usage: raw <IRC raw line>",
        "admin_raw_sent": "RAW sent.",
        "admin_logout_ok": "Logout successful.",
        "admin_logout_missing": "No active session.",
    },
}


ADMIN_COMMANDS = frozenset({
    "admin",
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
    "rssannounce",
    "rsschannel",
    "raw",
    "caps",
    "reloadplugins",
})


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


def has_mg_admin_help(bot) -> bool:
    return "moonface" in bot.plugin_manager.loaded_plugins


def admin_help_topics(bot) -> str:
    topics = ["auth", "users", "roles", "modes", "rss"]
    if has_mg_admin_help(bot):
        topics.append("mg")
    topics.append("raw")
    topics.append("cap")
    topics.append("reload")
    return "|".join(topics)


def get_admin_help_entries(bot, context) -> tuple[str, ...]:
    if not context.is_private_message or "admin" not in bot.plugin_manager.loaded_plugins:
        return ()

    admin_row = bot.get_authenticated_admin(context.source_mask, require_admin=True)
    if admin_row is None or not bool(int(admin_row.get("is_admin", 0))):
        return ()

    language = bot.config.language if bot.config.language in {"de", "en"} else "de"
    return ADMIN_HELP_ENTRIES.get(language, ADMIN_HELP_ENTRIES["de"])


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
    normalized_topic = topic.strip().lower()
    admin_row = None
    if context.is_private_message and context.source_mask:
        admin_row = bot.get_authenticated_admin(context.source_mask, require_admin=True)
    if admin_row is None:
        reply(bot, context, bot.tr("admin_help_auth_1"))
        return

    help_sections = {
        "": (
            "admin_help_auth_1",
            "admin_help_auth_2",
            "admin_help_auth_3",
            "admin_help_users_1",
            "admin_help_users_2",
            "admin_help_users_3",
            "admin_help_users_4",
            "admin_help_roles_1",
            "admin_help_roles_2",
            "admin_help_roles_3",
            "admin_help_modes_1",
            "admin_help_modes_2",
            "admin_help_modes_3",
            "admin_help_modes_4",
            "admin_help_modes_5",
            "admin_help_rss_1",
            "admin_help_rss_2",
            "admin_help_rss_3",
            "admin_help_rss_4",
            "admin_help_rss_5",
            "admin_help_raw_1",
            "admin_help_raw_2",
            "admin_help_caps",
            "admin_help_reload",
        ),
        "auth": ("admin_help_auth_1", "admin_help_auth_2", "admin_help_auth_3"),
        "users": ("admin_help_users_1", "admin_help_users_2", "admin_help_users_3", "admin_help_users_4"),
        "roles": ("admin_help_roles_1", "admin_help_roles_2", "admin_help_roles_3"),
        "modes": (
            "admin_help_modes_1",
            "admin_help_modes_2",
            "admin_help_modes_3",
            "admin_help_modes_4",
            "admin_help_modes_5",
        ),
        "rss": (
            "admin_help_rss_1",
            "admin_help_rss_2",
            "admin_help_rss_3",
            "admin_help_rss_4",
            "admin_help_rss_5",
        ),
        "raw": ("admin_help_raw_1", "admin_help_raw_2"),
        "cap": ("admin_help_caps",),
        "reload": ("admin_help_reload",),
    }
    if has_mg_admin_help(bot):
        help_sections[""] = (
            help_sections[""][:-3]
            + (
                "admin_help_mg_1",
                "admin_help_mg_2",
                "admin_help_mg_3",
                "admin_help_mg_4",
                "admin_help_mg_5",
                "admin_help_mg_6",
                "admin_help_mg_7",
                "admin_help_mg_8",
                "admin_help_mg_9",
                "admin_help_mg_10",
                "admin_help_mg_11",
            )
            + help_sections[""][-3:]
        )
        help_sections["mg"] = (
            "admin_help_mg_1",
            "admin_help_mg_2",
            "admin_help_mg_3",
            "admin_help_mg_4",
            "admin_help_mg_5",
            "admin_help_mg_6",
            "admin_help_mg_7",
            "admin_help_mg_8",
            "admin_help_mg_9",
            "admin_help_mg_10",
            "admin_help_mg_11",
        )

    help_topics = admin_help_topics(bot)

    if not normalized_topic:
        reply(bot, context, bot.tr("admin_help_overview", topics=help_topics))
        for key in help_sections[""]:
            reply(bot, context, bot.tr(key))
        return

    if normalized_topic in {"mondgesicht", "moonface"}:
        normalized_topic = "mg"
    if normalized_topic in {"cap", "caps", "capability", "capabilities"}:
        normalized_topic = "cap"
    if normalized_topic in {"reload", "reloadplugins"}:
        normalized_topic = "reload"

    topic_keys = help_sections.get(normalized_topic)
    if topic_keys is None:
        reply(bot, context, bot.tr("admin_help_unknown", topics=help_topics))
        reply(bot, context, bot.tr("admin_help_overview", topics=help_topics))
        return

    for key in topic_keys:
        reply(bot, context, bot.tr(key))


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
    roles = list_admin_roles(bot)
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
    users = list_admin_users(bot)
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
    return token in ADMIN_COMMANDS


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

    if command in ADMIN_COMMANDS:
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

    _, message = create_admin_role(bot, role_name, is_admin=is_admin, can_raw=can_raw)
    reply(bot, context, message)


def handle_admin_roleflag(bot, context, parts: list[str]) -> None:
    if len(parts) != 4:
        reply_admin_usage(bot, context, "admin_usage_roleflag")
        return

    enabled = parse_switch(parts[3])
    if enabled is None:
        reply_admin_usage(bot, context, "admin_usage_roleflag")
        return

    _, message = set_role_flag(bot, parts[1], parts[2], enabled)
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
        _, message = create_admin_user(
            bot,
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
        _, message = delete_admin_user(bot, parts[1])
        reply(bot, context, message)
        return True

    if subcommand == "setrole":
        if len(parts) != 3:
            reply_admin_usage(bot, context, "admin_usage_setrole")
            return True
        _, message = set_admin_user_role(bot, parts[1], parts[2])
        reply(bot, context, message)
        return True

    return False


def handle_admin_mode_command(bot, context, parts: list[str]) -> bool:
    subcommand = parts[0].lower()

    if subcommand in {"rolemode", "rolemode-del"}:
        if len(parts) != 4:
            reply_admin_usage(bot, context, "admin_usage_rolemode")
            return True
        _, message = set_role_channel_mode(bot, parts[1], parts[2], parts[3], enabled=subcommand == "rolemode")
        reply(bot, context, message)
        return True

    if subcommand in {"usermode", "usermode-del"}:
        if len(parts) != 4:
            reply_admin_usage(bot, context, "admin_usage_usermode")
            return True
        _, message = set_user_channel_mode(bot, parts[1], parts[2], parts[3], enabled=subcommand == "usermode")
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


def parse_rssannounce_channels_arg(requested: str) -> tuple[str, list[str] | None, bool]:
    stripped = requested.strip()
    lowered = stripped.lower()
    if lowered in {"off", "none", "-"}:
        return "off", [], True

    mode = "set"
    payload = stripped
    if stripped.startswith("+"):
        mode = "add"
        payload = stripped[1:].strip()
    elif stripped.startswith("-"):
        mode = "remove"
        payload = stripped[1:].strip()

    if not payload:
        return mode, None, False

    channels: list[str] = []
    for token in payload.replace(";", ",").split(","):
        channel = token.strip()
        if not channel:
            continue
        if not channel.startswith("#"):
            return mode, None, False
        normalized = channel.lower()
        if normalized not in channels:
            channels.append(normalized)

    return mode, channels if channels else None, bool(channels)


def current_rssannounce_channels(bot) -> list[str]:
    if get_rss_announce_channels is None:
        return []
    return [str(channel).strip().lower() for channel in (get_rss_announce_channels(bot) or ()) if str(channel).strip()]


def target_rssannounce_channels(bot, mode: str, parsed_channels: list[str]) -> list[str]:
    if mode == "set" or mode == "off":
        return parsed_channels

    current = current_rssannounce_channels(bot)
    if mode == "add":
        for channel in parsed_channels:
            if channel not in current:
                current.append(channel)
        return current

    blocked = set(parsed_channels)
    return [channel for channel in current if channel not in blocked]


def reply_rssannounce_current(bot, context) -> None:
    channels = tuple(current_rssannounce_channels(bot))
    if channels:
        reply(bot, context, bot.tr("admin_rssannounce_current", channels=", ".join(channels)))
        return
    reply(bot, context, bot.tr("admin_rssannounce_disabled"))


def reply_rssannounce_invalid(bot, context) -> None:
    reply(bot, context, bot.tr("admin_rssannounce_invalid"))
    reply_admin_usage(bot, context, "admin_usage_rssannounce")


def reply_rssannounce_feeds(bot, context) -> None:
    configured_feeds = dict(getattr(bot.config, "rss_feeds", {}) or {})
    if not configured_feeds:
        reply(bot, context, bot.tr("admin_rssannounce_feeds_none"))
        return

    rendered = ", ".join(sorted((str(alias).strip() for alias in configured_feeds.keys() if str(alias).strip()), key=str.lower))
    if not rendered:
        reply(bot, context, bot.tr("admin_rssannounce_feeds_none"))
        return
    reply(bot, context, bot.tr("admin_rssannounce_feeds", feeds=rendered))


def announce_rss_feeds_in_channels(bot, channels: list[str]) -> None:
    configured_feeds = dict(getattr(bot.config, "rss_feeds", {}) or {})
    if not configured_feeds:
        return

    rendered = ", ".join(sorted((str(alias).strip() for alias in configured_feeds.keys() if str(alias).strip()), key=str.lower))
    if not rendered:
        return

    message = bot.tr("admin_rssannounce_feeds_channel", feeds=rendered)
    latest_messages = build_latest_feed_messages(bot, configured_feeds)
    for channel in channels:
        normalized = str(channel).strip().lower()
        if not normalized.startswith("#"):
            continue
        bot.send_privmsg(normalized, message)
        for latest_message in latest_messages:
            bot.send_privmsg(normalized, latest_message)


def build_latest_feed_messages(bot, configured_feeds: dict[str, str]) -> list[str]:
    try:
        from plugins.rss.plugin import FeedEntry, fetch_latest_entry, render_feed_reply
    except Exception:
        return []

    timeout_seconds = float(getattr(bot.config, "url_timeout_seconds", 3.0))
    latest_messages: list[str] = []

    for feed_alias, feed_url in sorted(configured_feeds.items(), key=lambda item: str(item[0]).lower()):
        target_url = str(feed_url).strip()
        if not target_url.lower().startswith(("http://", "https://")):
            continue

        result = fetch_latest_entry(target_url, timeout_seconds=timeout_seconds)
        entry = result.get("entry")
        if str(result.get("status", "")) != "ok" or not isinstance(entry, FeedEntry):
            continue

        display_name = entry.feed_title or str(feed_alias)
        latest_messages.append(render_feed_reply(bot, display_name, entry.entry_title, entry.entry_link))

    return latest_messages


def handle_admin_rss_command(bot, context, parts: list[str]) -> bool:
    subcommand = parts[0].lower()
    if subcommand not in {"rssannounce", "rsschannel"}:
        return False

    if len(parts) > 2:
        reply_admin_usage(bot, context, "admin_usage_rssannounce")
        return True

    if len(parts) == 1:
        reply_rssannounce_current(bot, context)
        return True

    mode, parsed_channels, valid = parse_rssannounce_channels_arg(parts[1])
    if not valid or parsed_channels is None:
        reply_rssannounce_invalid(bot, context)
        return True

    target_channels = target_rssannounce_channels(bot, mode, parsed_channels)

    if set_rss_announce_channels is None:
        reply(bot, context, bot.tr("admin_rssannounce_save_failed", error="RSS plugin not available"))
        return True

    ok, error = set_rss_announce_channels(bot, target_channels)
    if not ok:
        reply(bot, context, bot.tr("admin_rssannounce_save_failed", error=error))
        return True

    if target_channels:
        reply(bot, context, bot.tr("admin_rssannounce_set", channels=", ".join(target_channels)))
        announce_rss_feeds_in_channels(bot, target_channels)
    else:
        reply(bot, context, bot.tr("admin_rssannounce_cleared"))
    reply_rssannounce_feeds(bot, context)
    return True


def handle_admin_whoami(bot, context, source_mask: str, admin_row) -> bool:
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


def handle_admin_caps(bot, context) -> bool:
    active_caps = sorted(str(cap).strip() for cap in getattr(bot, "active_capabilities", set()) if str(cap).strip())
    if active_caps:
        reply(bot, context, bot.tr("admin_caps_enabled", caps=", ".join(active_caps)))
    else:
        reply(bot, context, bot.tr("admin_caps_none"))
    return True


def handle_admin_reloadplugins(bot, context) -> bool:
    try:
        bot.plugin_manager.reload_plugins()
        loaded_plugins = bot.plugin_manager.loaded_plugins
        rendered_plugins = ", ".join(loaded_plugins) if loaded_plugins else "-"
        reply(
            bot,
            context,
            bot.tr("admin_reload_ok", count=len(loaded_plugins), plugins=rendered_plugins),
        )
    except Exception as exc:
        reply(bot, context, bot.tr("admin_reload_failed", error=str(exc)))
    return True


def handle_admin_info_command(bot, context, subcommand: str, source_mask: str, admin_row) -> bool:
    if subcommand == "whoami":
        return handle_admin_whoami(bot, context, source_mask, admin_row)

    if subcommand == "listroles":
        reply(bot, context, render_roles(bot))
        return True

    if subcommand == "listusers":
        reply(bot, context, render_users(bot))
        return True

    if subcommand == "caps":
        return handle_admin_caps(bot, context)

    if subcommand == "reloadplugins":
        return handle_admin_reloadplugins(bot, context)

    return False


def handle_admin_authenticated(bot, context, parts: list[str], source_mask: str, admin_row) -> bool:
    subcommand = parts[0].lower()
    if handle_admin_info_command(bot, context, subcommand, source_mask, admin_row):
        return True

    return (
        handle_admin_role_command(bot, context, parts)
        or handle_admin_user_command(bot, context, parts, source_mask)
        or handle_admin_mode_command(bot, context, parts)
        or handle_admin_rss_command(bot, context, parts)
    )


def handle_admin(bot, context, arg: str) -> None:
    if not require_private(bot, context):
        return

    if context.message.startswith(context.command_prefix):
        reply(bot, context, bot.tr("admin_prefix_forbidden"))
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
    admin_row = require_admin(bot, context)
    if admin_row is None:
        return

    if context.message.startswith(context.command_prefix):
        reply(bot, context, bot.tr("admin_prefix_forbidden"))
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


def normalize_user_mask(mask: str) -> str | None:
    raw = mask.strip()
    if raw.count("@") != 1:
        return None
    ident, host = raw.split("@", 1)
    ident = ident.strip().lower()
    host = host.strip().lower()
    if not ident or not host:
        return None
    return f"{ident}@{host}"


def normalize_role_name(role_name: str) -> str | None:
    role = role_name.strip().lower()
    if not role or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", role):
        return None
    return role


def normalize_channel_name(channel: str) -> str:
    return channel.strip().lower()


def normalize_member_mode(bot, mode_or_prefix: str) -> str | None:
    token = mode_or_prefix.strip()
    if len(token) == 2 and token[0] in {"+", "-"}:
        token = token[1:]
    if len(token) != 1:
        return None
    server_prefix_modes = getattr(bot, "server_prefix_modes", {})
    if token in server_prefix_modes:
        return token
    for mode, prefix in server_prefix_modes.items():
        if prefix == token:
            return mode
    return None


def hash_admin_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt = os.urandom(16).hex() if salt_hex is None else salt_hex
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        200000,
    ).hex()
    return salt, derived


def verify_admin_password(password: str, salt_hex: str, expected_hash: str) -> bool:
    _, derived = hash_admin_password(password, salt_hex)
    return hmac.compare_digest(derived, expected_hash)


def ensure_default_admin_role(bot) -> None:
    if pymysql is None:
        return
    conn = bot.open_db_connection()
    if conn is None:
        return
    try:
        AdminRepository(conn, bot.config.network_key).ensure_default_role(bot.current_time_string())
    finally:
        conn.close()


def load_admin_user(bot, user_mask: str) -> dict[str, object] | None:
    normalized_mask = normalize_user_mask(user_mask)
    if normalized_mask is None:
        return None
    if pymysql is None:
        return None
    conn = bot.open_db_connection()
    if conn is None:
        return None
    try:
        return AdminRepository(conn, bot.config.network_key).load_user(normalized_mask)
    finally:
        conn.close()


def create_admin_role(bot, role_name: str, is_admin: bool = False, can_raw: bool = False) -> tuple[bool, str]:
    normalized_role = normalize_role_name(role_name)
    if normalized_role is None:
        return False, "Ungültiger Rollenname. Erlaubt sind a-z, 0-9, _ und - ."
    if pymysql is None:
        return False, "pymysql missing"
    conn = bot.open_db_connection()
    if conn is None:
        return False, "DB connection failed"
    try:
        repo = AdminRepository(conn, bot.config.network_key)
        if not repo.create_role(normalized_role, is_admin, can_raw, bot.current_time_string()):
            return False, f"Rolle {normalized_role} existiert bereits."
        return True, f"Rolle {normalized_role} angelegt."
    except Exception as exc:
        return False, f"Rolle konnte nicht angelegt werden: {exc}"
    finally:
        conn.close()


def set_role_flag(bot, role_name: str, flag_name: str, enabled: bool) -> tuple[bool, str]:
    normalized_role = normalize_role_name(role_name)
    allowed_columns = {"admin": "is_admin", "raw": "can_raw"}
    column = allowed_columns.get(flag_name.strip().lower())
    if normalized_role is None or column is None:
        return False, "Ungültige Rolle oder Flag. Erlaubte Flags: admin, raw."
    if pymysql is None:
        return False, "pymysql missing"
    conn = bot.open_db_connection()
    if conn is None:
        return False, "DB connection failed"
    try:
        repo = AdminRepository(conn, bot.config.network_key)
        if not repo.set_role_flag(normalized_role, flag_name, enabled):
            return False, f"Rolle {normalized_role} existiert nicht."
        return True, f"Flag {flag_name.lower()} fuer Rolle {normalized_role} ist jetzt {'an' if enabled else 'aus'}."
    except Exception as exc:
        return False, f"Rollenflag konnte nicht gesetzt werden: {exc}"
    finally:
        conn.close()


def list_admin_roles(bot) -> list[dict[str, object]]:
    if pymysql is None:
        return []
    conn = bot.open_db_connection()
    if conn is None:
        return []
    try:
        return AdminRepository(conn, bot.config.network_key).list_roles()
    finally:
        conn.close()


def create_admin_user(bot, display_name: str, user_mask: str, password: str, role_name: str, created_by: str) -> tuple[bool, str]:
    normalized_mask = normalize_user_mask(user_mask)
    normalized_role = normalize_role_name(role_name)
    label = display_name.strip()[:64]
    if normalized_mask is None:
        return False, "Ungültige Hostmask. Erwartet wird ident@host."
    if normalized_role is None:
        return False, "Ungültiger Rollenname."
    if not password:
        return False, "Passwort darf nicht leer sein."
    if pymysql is None:
        return False, "pymysql missing"
    conn = bot.open_db_connection()
    if conn is None:
        return False, "DB connection failed"
    try:
        salt_hex, hash_hex = hash_admin_password(password)
        repo = AdminRepository(conn, bot.config.network_key)
        created, message = repo.create_user(
            label, normalized_mask, salt_hex, hash_hex, normalized_role,
            bot.current_time_string(), created_by
        )
        if not created:
            if message == "role_missing":
                return False, f"Rolle {normalized_role} existiert nicht."
            if message == "user_exists":
                return False, f"Benutzer {normalized_mask} existiert bereits."
            return False, f"Benutzer konnte nicht angelegt werden: {message}"
        return True, f"Benutzer {normalized_mask} mit Rolle {normalized_role} angelegt."
    except Exception as exc:
        return False, f"Benutzer konnte nicht angelegt werden: {exc}"
    finally:
        conn.close()


def delete_admin_user(bot, user_mask: str) -> tuple[bool, str]:
    normalized_mask = normalize_user_mask(user_mask)
    if normalized_mask is None:
        return False, "Ungültige Hostmask."
    if pymysql is None:
        return False, "pymysql missing"
    conn = bot.open_db_connection()
    if conn is None:
        return False, "DB connection failed"
    try:
        repo = AdminRepository(conn, bot.config.network_key)
        if not repo.delete_user(normalized_mask):
            return False, f"Benutzer {normalized_mask} existiert nicht."
        bot._admin_sessions.pop(normalized_mask, None)
        return True, f"Benutzer {normalized_mask} geloescht."
    except Exception as exc:
        return False, f"Benutzer konnte nicht geloescht werden: {exc}"
    finally:
        conn.close()


def set_admin_user_role(bot, user_mask: str, role_name: str) -> tuple[bool, str]:
    normalized_mask = normalize_user_mask(user_mask)
    normalized_role = normalize_role_name(role_name)
    if normalized_mask is None or normalized_role is None:
        return False, "Ungültige Hostmask oder Rolle."
    if pymysql is None:
        return False, "pymysql missing"
    conn = bot.open_db_connection()
    if conn is None:
        return False, "DB connection failed"
    try:
        repo = AdminRepository(conn, bot.config.network_key)
        if not repo.set_user_role(normalized_mask, normalized_role):
            return False, "Rolle konnte nicht gesetzt werden."
        return True, f"Benutzer {normalized_mask} hat jetzt Rolle {normalized_role}."
    except Exception as exc:
        return False, f"Rolle konnte nicht gesetzt werden: {exc}"
    finally:
        conn.close()


def list_admin_users(bot) -> list[dict[str, object]]:
    if pymysql is None:
        return []
    conn = bot.open_db_connection()
    if conn is None:
        return []
    try:
        return AdminRepository(conn, bot.config.network_key).list_users()
    finally:
        conn.close()


def set_role_channel_mode(bot, role_name: str, channel: str, mode_or_prefix: str, enabled: bool) -> tuple[bool, str]:
    normalized_role = normalize_role_name(role_name)
    normalized_channel = normalize_channel_name(channel)
    mode = normalize_member_mode(bot, mode_or_prefix)
    if normalized_role is None or not normalized_channel.startswith("#") or mode is None:
        return False, "Ungültige Rolle, Channel oder Modus."
    if pymysql is None:
        return False, "pymysql missing"
    conn = bot.open_db_connection()
    if conn is None:
        return False, "DB connection failed"
    try:
        repo = AdminRepository(conn, bot.config.network_key)
        repo.set_role_channel_mode(normalized_role, normalized_channel, mode, bot.current_time_string(), enabled)
        action = "gesetzt" if enabled else "entfernt"
        return True, f"Rollenrecht {normalized_role} {normalized_channel} +{mode} {action}."
    except Exception as exc:
        return False, f"Rollenrecht konnte nicht gespeichert werden: {exc}"
    finally:
        conn.close()


def set_user_channel_mode(bot, user_mask: str, channel: str, mode_or_prefix: str, enabled: bool) -> tuple[bool, str]:
    normalized_mask = normalize_user_mask(user_mask)
    normalized_channel = normalize_channel_name(channel)
    mode = normalize_member_mode(bot, mode_or_prefix)
    if normalized_mask is None or not normalized_channel.startswith("#") or mode is None:
        return False, "Ungültige Hostmask, Channel oder Modus."
    if pymysql is None:
        return False, "pymysql missing"
    conn = bot.open_db_connection()
    if conn is None:
        return False, "DB connection failed"
    try:
        repo = AdminRepository(conn, bot.config.network_key)
        repo.set_user_channel_mode(normalized_mask, normalized_channel, mode, bot.current_time_string(), enabled)
        action = "gesetzt" if enabled else "entfernt"
        return True, f"Benutzerrecht {normalized_mask} {normalized_channel} +{mode} {action}."
    except Exception as exc:
        return False, f"Benutzerrecht konnte nicht gespeichert werden: {exc}"
    finally:
        conn.close()


def get_configured_user_channel_modes(bot, user_mask: str, channel: str) -> tuple[str, ...]:
    normalized_mask = normalize_user_mask(user_mask)
    normalized_channel = normalize_channel_name(channel)
    if normalized_mask is None or not normalized_channel:
        return ()
    if pymysql is None:
        return ()
    conn = bot.open_db_connection()
    if conn is None:
        return ()
    try:
        return AdminRepository(conn, bot.config.network_key).get_configured_user_channel_modes(normalized_mask, normalized_channel)
    finally:
        conn.close()


def get_user_assigned_channels(bot, user_mask: str) -> set[str]:
    normalized_mask = normalize_user_mask(user_mask)
    if normalized_mask is None:
        return set()
    if pymysql is None:
        return set()
    conn = bot.open_db_connection()
    if conn is None:
        return set()
    try:
        return AdminRepository(conn, bot.config.network_key).get_user_assigned_channels(normalized_mask)
    finally:
        conn.close()


def ensure_admin_tables(db_conn, network_key, current_time):
    with db_conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_admin_roles (
                network VARCHAR(255) NOT NULL,
                role_name VARCHAR(64) NOT NULL,
                is_admin TINYINT(1) NOT NULL DEFAULT 0,
                can_raw TINYINT(1) NOT NULL DEFAULT 0,
                created_at VARCHAR(32) NOT NULL,
                PRIMARY KEY (network, role_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_admin_users (
                network VARCHAR(255) NOT NULL,
                user_mask VARCHAR(255) NOT NULL,
                display_name VARCHAR(64) NOT NULL DEFAULT '',
                password_salt VARCHAR(64) NOT NULL,
                password_hash VARCHAR(128) NOT NULL,
                role_name VARCHAR(64) NOT NULL,
                created_at VARCHAR(32) NOT NULL,
                created_by VARCHAR(64) NOT NULL DEFAULT '',
                PRIMARY KEY (network, user_mask),
                KEY idx_bot_admin_users_role (network, role_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_admin_role_modes (
                network VARCHAR(255) NOT NULL,
                role_name VARCHAR(64) NOT NULL,
                channel VARCHAR(128) NOT NULL,
                mode CHAR(1) NOT NULL,
                created_at VARCHAR(32) NOT NULL,
                PRIMARY KEY (network, role_name, channel, mode)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_admin_user_modes (
                network VARCHAR(255) NOT NULL,
                user_mask VARCHAR(255) NOT NULL,
                channel VARCHAR(128) NOT NULL,
                mode CHAR(1) NOT NULL,
                created_at VARCHAR(32) NOT NULL,
                PRIMARY KEY (network, user_mask, channel, mode)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )


def has_admin_users(bot) -> bool:
    if pymysql is None:
        return False
    conn = bot.open_db_connection()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM bot_admin_users WHERE network = %s LIMIT 1",
                (bot.config.network_key,),
            )
            return cur.fetchone() is not None
    except Exception:
        return False
    finally:
        conn.close()


PLUGIN = PluginSpec(
    name="admin",
    translations=MESSAGES,
    message_handlers=(
        MessageHandlerSpec(handler=handle_admin_message),
    ),
    hooks={
        "ensure_tables": ensure_admin_tables,
        "load_admin_user": load_admin_user,
        "ensure_default_admin_role": ensure_default_admin_role,
        "hash_admin_password": hash_admin_password,
        "create_admin_user": create_admin_user,
        "get_user_assigned_channels": get_user_assigned_channels,
        "get_configured_user_channel_modes": get_configured_user_channel_modes,
        "has_admin_users": has_admin_users,
    },
)
