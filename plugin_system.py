from __future__ import annotations

import sys
from dataclasses import dataclass, field
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from bot import IRCBot


@dataclass(frozen=True)
class MessageContext:
    source_nick: str
    source_ident: str
    source_host: str
    source_mask: str
    target: str
    message: str
    reply_target: str
    command_prefix: str
    is_private_message: bool


CommandHandler = Callable[["IRCBot", MessageContext, str], None]
MessageHandler = Callable[["IRCBot", MessageContext], None]
TickHandler = Callable[["IRCBot"], None]
HelpVisibilityHandler = Callable[["IRCBot", MessageContext], bool]


@dataclass(frozen=True)
class CommandSpec:
    canonical: str
    handler: CommandHandler
    aliases: tuple[str, ...] = ()
    primary_names: dict[str, str] = field(default_factory=dict)
    help_args: dict[str, str] = field(default_factory=dict)
    help_texts: dict[str, str] = field(default_factory=dict)
    help_visible: HelpVisibilityHandler | None = None
    help_sort: int = 100

    def all_aliases(self) -> tuple[str, ...]:
        values = [self.canonical, *self.aliases]
        seen: set[str] = set()
        normalized: list[str] = []
        for value in values:
            alias = value.strip().lower()
            if not alias or alias in seen:
                continue
            seen.add(alias)
            normalized.append(alias)
        return tuple(normalized)

    def primary_name(self, language: str) -> str:
        return self.primary_names.get(language, self.primary_names.get("en", self.canonical))

    def help_arg(self, language: str) -> str:
        return self.help_args.get(language, self.help_args.get("en", "")).strip()

    def help_text(self, language: str) -> str:
        return self.help_texts.get(language, self.help_texts.get("en", "")).strip()


@dataclass(frozen=True)
class MessageHandlerSpec:
    handler: MessageHandler


@dataclass(frozen=True)
class TickHandlerSpec:
    handler: TickHandler


@dataclass(frozen=True)
class PluginSpec:
    name: str
    aliases: tuple[str, ...] = ()
    commands: tuple[CommandSpec, ...] = ()
    message_handlers: tuple[MessageHandlerSpec, ...] = ()
    tick_handlers: tuple[TickHandlerSpec, ...] = ()
    translations: dict[str, dict[str, str]] = field(default_factory=dict)
    enabled_by_default: bool = True


class PluginManager:
    def __init__(self, bot: "IRCBot", plugins_dir: Path) -> None:
        self.bot = bot
        self.plugins_dir = plugins_dir
        self._commands_by_canonical: dict[str, CommandSpec] = {}
        self._commands_by_alias: dict[str, CommandSpec] = {}
        self._message_handlers: list[MessageHandler] = []
        self._tick_handlers: list[TickHandler] = []
        self._loaded_plugins: list[str] = []
        self._translations: dict[str, dict[str, str]] = {}
        self.load_plugins()

    @property
    def loaded_plugins(self) -> tuple[str, ...]:
        return tuple(self._loaded_plugins)

    def command_aliases(self) -> dict[str, list[str]]:
        return {name: list(spec.all_aliases()) for name, spec in self._commands_by_canonical.items()}

    def primary_command_name(self, canonical: str, language: str) -> str:
        spec = self._commands_by_canonical.get(canonical)
        if spec is None:
            return canonical
        return spec.primary_name(language)

    def translation(self, key: str, language: str) -> str | None:
        return self._translations.get(language, {}).get(key)

    def resolve_command(self, token: str) -> CommandSpec | None:
        return self._commands_by_alias.get(token.strip().lower())

    def build_help_entries(self, prefix: str, language: str, context: MessageContext | None = None) -> tuple[str, ...]:
        rendered: list[str] = []
        ordered = sorted(self._commands_by_canonical.values(), key=lambda spec: (spec.help_sort, spec.canonical))
        for spec in ordered:
            if context is not None and spec.help_visible is not None and not spec.help_visible(self.bot, context):
                continue
            command_name = spec.primary_name(language)
            help_arg = spec.help_arg(language)
            help_text = spec.help_text(language)
            line = f"{prefix}{command_name} {help_arg}".rstrip()
            if help_text:
                line = f"{line} - {help_text}"
            rendered.append(line)
        return tuple(rendered)

    def handle_privmsg(self, context: MessageContext) -> None:
        if not self.bot.public_triggers_enabled():
            return

        for handler in self._message_handlers:
            handler(self.bot, context)

        if not context.message.startswith(context.command_prefix):
            return

        cmdline = context.message[len(context.command_prefix) :].strip()
        if not cmdline:
            return

        parts = cmdline.split(maxsplit=1)
        token = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        command = self.resolve_command(token)
        if command is None:
            return

        command.handler(self.bot, context, arg)

    def handle_tick(self) -> None:
        for handler in self._tick_handlers:
            handler(self.bot)

    def _reset_plugin_runtime_state(self) -> None:
        # Clear plugin-specific in-memory state so reload starts clean.
        for attr_name in (
            "_mondgesicht_channels",
            "_moonface_round_states",
            "_moonface_start_locks",
            "_moonface_auto_start_deadlines",
        ):
            if hasattr(self.bot, attr_name):
                delattr(self.bot, attr_name)

    def reload_plugins(self) -> None:
        """Entlädt alle Plugin-Module aus sys.modules und lädt sie erneut."""
        self._reset_plugin_runtime_state()
        for key in [k for k in sys.modules if k.startswith("ircbot_plugin_")]:
            del sys.modules[key]
        self.load_plugins()

    def load_plugins(self) -> None:
        self._commands_by_canonical.clear()
        self._commands_by_alias.clear()
        self._message_handlers.clear()
        self._tick_handlers.clear()
        self._loaded_plugins.clear()
        self._translations.clear()

        if not self.plugins_dir.exists():
            return

        enabled_plugins = {name.strip().lower() for name in (self.bot.config.enabled_plugins or []) if name.strip()}
        disabled_plugins = {name.strip().lower() for name in (self.bot.config.disabled_plugins or []) if name.strip()}

        for plugin_path in sorted(self.plugins_dir.glob("*/plugin.py")):
            module_name = f"ircbot_plugin_{plugin_path.parent.name.lower()}"
            spec = spec_from_file_location(module_name, plugin_path)
            if spec is None or spec.loader is None:
                continue

            module = module_from_spec(spec)
            spec.loader.exec_module(module)
            plugin = getattr(module, "PLUGIN", None)
            if not isinstance(plugin, PluginSpec):
                raise TypeError(f"Plugin {plugin_path.parent.name} exportiert kein PluginSpec in PLUGIN.")

            plugin_name = plugin.name.strip().lower()
            plugin_aliases = {
                alias.strip().lower()
                for alias in (plugin_path.parent.name, *plugin.aliases)
                if alias.strip()
            }
            plugin_aliases.add(plugin_name)
            if enabled_plugins:
                is_enabled = bool(plugin_aliases & enabled_plugins)
            else:
                is_enabled = plugin.enabled_by_default and not (plugin_aliases & disabled_plugins)

            if not is_enabled:
                continue

            self._register_plugin(plugin)
            self._loaded_plugins.append(plugin_name)

    def _register_plugin(self, plugin: PluginSpec) -> None:
        self._register_translations(plugin)
        self._register_commands(plugin)

        for message_handler in plugin.message_handlers:
            self._message_handlers.append(message_handler.handler)

        for tick_handler in plugin.tick_handlers:
            self._tick_handlers.append(tick_handler.handler)

    def _register_translations(self, plugin: PluginSpec) -> None:
        for language, translations in plugin.translations.items():
            catalog = self._translations.setdefault(language, {})
            for key, value in translations.items():
                existing = catalog.get(key)
                if existing is not None and existing != value:
                    raise ValueError(f"Übersetzungsschlüssel {key} kollidiert in Sprache {language}.")
                catalog[key] = value

    def _register_commands(self, plugin: PluginSpec) -> None:
        for command in plugin.commands:
            if command.canonical in self._commands_by_canonical:
                raise ValueError(f"Befehl {command.canonical} wurde mehrfach registriert.")

            self._commands_by_canonical[command.canonical] = command
            for alias in command.all_aliases():
                existing = self._commands_by_alias.get(alias)
                if existing is not None:
                    raise ValueError(f"Alias {alias} kollidiert mit {existing.canonical}.")
                self._commands_by_alias[alias] = command