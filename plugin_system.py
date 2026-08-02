from __future__ import annotations

import importlib
import sys
import threading
from dataclasses import dataclass, field
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

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
    hooks: dict[str, Callable[..., Any]] | None = None
    on_config_loaded: Callable[..., Any] | None = None


class PluginManager:
    def __init__(self, bot: "IRCBot", plugins_dir: Path) -> None:
        self.bot = bot
        self.plugins_dir = plugins_dir.resolve()
        self._commands_by_canonical: dict[str, CommandSpec] = {}
        self._commands_by_alias: dict[str, CommandSpec] = {}
        self._message_handlers: list[MessageHandler] = []
        self._tick_handlers: list[TickHandler] = []
        self._loaded_plugins: list[str] = []
        self._translations: dict[str, dict[str, str]] = {}
        self._plugins_by_name: dict[str, PluginSpec] = {}
        self._state_lock = threading.RLock()
        self.load_plugins()

    @property
    def loaded_plugins(self) -> tuple[str, ...]:
        with self._state_lock:
            return tuple(self._loaded_plugins)

    def command_aliases(self) -> dict[str, list[str]]:
        with self._state_lock:
            return {name: list(spec.all_aliases()) for name, spec in self._commands_by_canonical.items()}

    def primary_command_name(self, canonical: str, language: str) -> str:
        with self._state_lock:
            spec = self._commands_by_canonical.get(canonical)
        if spec is None:
            return canonical
        return spec.primary_name(language)

    def translation(self, key: str, language: str) -> str | None:
        with self._state_lock:
            return self._translations.get(language, {}).get(key)

    def resolve_command(self, token: str) -> CommandSpec | None:
        with self._state_lock:
            return self._commands_by_alias.get(token.strip().lower())

    def build_help_entries(self, prefix: str, language: str, context: MessageContext | None = None) -> tuple[str, ...]:
        rendered: list[str] = []
        with self._state_lock:
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

    def get_hooks(self, name: str) -> tuple[Callable[..., Any], ...]:
        with self._state_lock:
            hooks = []
            for plugin in self._plugins_by_name.values():
                plugin_hooks = plugin.hooks
                if plugin_hooks:
                    hook = plugin_hooks.get(name)
                    if hook is not None:
                        hooks.append(hook)
            return tuple(hooks)

    def get_hook(self, name: str) -> Callable[..., Any] | None:
        with self._state_lock:
            for plugin in self._plugins_by_name.values():
                plugin_hooks = plugin.hooks
                if plugin_hooks:
                    hook = plugin_hooks.get(name)
                    if hook is not None:
                        return hook
        return None

    def call_config_hooks(self, bot) -> None:
        raw_config = getattr(bot, "raw_config", {})
        with self._state_lock:
            for plugin in self._plugins_by_name.values():
                hook = plugin.on_config_loaded
                if hook is not None:
                    try:
                        hook(bot, raw_config)
                    except Exception:
                        pass

    def call_hooks(self, name: str, *args, **kwargs) -> None:
        with self._state_lock:
            for plugin in self._plugins_by_name.values():
                plugin_hooks = plugin.hooks
                if plugin_hooks:
                    hook = plugin_hooks.get(name)
                    if hook is not None:
                        try:
                            hook(*args, **kwargs)
                        except Exception:
                            pass

    def handle_privmsg(self, context: MessageContext) -> None:
        if not self.bot.public_triggers_enabled():
            return

        with self._state_lock:
            message_handlers = tuple(self._message_handlers)
        for handler in message_handlers:
            handler(self.bot, context)

        if not context.message.startswith(context.command_prefix):
            return

        cmdline = context.message[len(context.command_prefix) :].strip()
        if not cmdline:
            return

        parts = cmdline.split(maxsplit=1)
        token = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        with self._state_lock:
            command = self._commands_by_alias.get(token)
        if command is None:
            return

        command.handler(self.bot, context, arg)

    def handle_tick(self) -> None:
        with self._state_lock:
            tick_handlers = tuple(self._tick_handlers)
        for handler in tick_handlers:
            handler(self.bot)

    def _reset_plugin_runtime_state(self) -> None:
        # Clear plugin-specific in-memory state so reload starts clean.
        explicit_attrs = {
            "_url_service",
        }
        with self._state_lock:
            loaded_plugins_snapshot = tuple(self._loaded_plugins)
        plugin_prefixes = {f"_{name.strip().lower().replace('-', '_')}_" for name in loaded_plugins_snapshot if name.strip()}
        prefixed_attrs = tuple(
            name
            for name in vars(self.bot)
            if any(name.startswith(prefix) for prefix in plugin_prefixes)
        )
        for attr_name in (*explicit_attrs, *prefixed_attrs):
            if hasattr(self.bot, attr_name):
                delattr(self.bot, attr_name)

    def reload_plugins(self) -> None:
        """Entlädt alle Plugin-Module aus sys.modules und lädt sie erneut."""
        self._reset_plugin_runtime_state()
        self._unload_plugin_modules()
        self.load_plugins()

    def _is_inside_plugins_dir(self, module_file: str | None) -> bool:
        if not module_file:
            return False
        try:
            module_path = Path(module_file).resolve()
        except OSError:
            return False
        try:
            module_path.relative_to(self.plugins_dir)
            return True
        except ValueError:
            return False

    def _unload_plugin_modules(self) -> None:
        # Ensure file system changes are seen before next import.
        importlib.invalidate_caches()
        module_names_to_unload: set[str] = set()
        for module_name, module in sys.modules.items():
            if module_name.startswith("ircbot_plugin_"):
                module_names_to_unload.add(module_name)
                continue
            if module_name == "plugins" or module_name.startswith("plugins."):
                module_file = getattr(module, "__file__", None)
                if self._is_inside_plugins_dir(module_file):
                    module_names_to_unload.add(module_name)

        for module_name in module_names_to_unload:
            sys.modules.pop(module_name, None)

    def _load_plugin_spec(self, plugin_path: Path) -> PluginSpec:
        if plugin_path.parent.name == "plugins":
            module_name = f"ircbot_plugin_{plugin_path.stem.lower()}"
        else:
            module_name = f"ircbot_plugin_{plugin_path.parent.name.lower()}"
        spec = spec_from_file_location(module_name, plugin_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Plugin {plugin_path.parent.name} konnte nicht geladen werden.")

        module = module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise

        plugin = getattr(module, "PLUGIN", None)
        if not isinstance(plugin, PluginSpec):
            raise TypeError(f"Plugin {plugin_path.parent.name} exportiert kein PluginSpec in PLUGIN.")
        return plugin

    @staticmethod
    def _plugin_is_enabled(
        plugin_path: Path,
        plugin: PluginSpec,
        enabled_plugins: set[str],
        disabled_plugins: set[str],
    ) -> bool:
        plugin_name = plugin.name.strip().lower()
        if plugin_path.parent.name == "plugins":
            plugin_aliases = {plugin_path.stem.lower()}
        else:
            plugin_aliases = {
                alias.strip().lower()
                for alias in (plugin_path.parent.name, *plugin.aliases)
                if alias.strip()
            }
        plugin_aliases.add(plugin_name)
        if enabled_plugins:
            return bool(plugin_aliases & enabled_plugins)
        return plugin.enabled_by_default and not (plugin_aliases & disabled_plugins)

    def load_plugins(self) -> None:
        if not self.plugins_dir.exists():
            with self._state_lock:
                self._commands_by_canonical.clear()
                self._commands_by_alias.clear()
                self._message_handlers.clear()
                self._tick_handlers.clear()
                self._loaded_plugins.clear()
                self._translations.clear()
                self._plugins_by_name.clear()
            return

        enabled_plugins = {name.strip().lower() for name in (self.bot.config.enabled_plugins or []) if name.strip()}
        disabled_plugins = {name.strip().lower() for name in (self.bot.config.disabled_plugins or []) if name.strip()}

        next_commands_by_canonical: dict[str, CommandSpec] = {}
        next_commands_by_alias: dict[str, CommandSpec] = {}
        next_message_handlers: list[MessageHandler] = []
        next_tick_handlers: list[TickHandler] = []
        next_loaded_plugins: list[str] = []
        next_translations: dict[str, dict[str, str]] = {}
        next_plugins_by_name: dict[str, PluginSpec] = {}

        def _register_loaded_plugin(plugin_path: Path, plugin: PluginSpec) -> None:
            plugin_name = plugin.name.strip().lower()
            self._register_plugin(
                plugin,
                commands_by_canonical=next_commands_by_canonical,
                commands_by_alias=next_commands_by_alias,
                message_handlers=next_message_handlers,
                tick_handlers=next_tick_handlers,
                translation_catalogs=next_translations,
            )
            next_loaded_plugins.append(plugin_name)
            next_plugins_by_name[plugin_name] = plugin

        for plugin_path in sorted(self.plugins_dir.glob("*/plugin.py")):
            try:
                plugin = self._load_plugin_spec(plugin_path)
            except Exception:
                continue
            if not self._plugin_is_enabled(plugin_path, plugin, enabled_plugins, disabled_plugins):
                continue
            _register_loaded_plugin(plugin_path, plugin)

        for plugin_path in sorted(self.plugins_dir.glob("*.py")):
            if plugin_path.name.startswith("_"):
                continue
            try:
                plugin = self._load_plugin_spec(plugin_path)
            except Exception:
                continue
            if not self._plugin_is_enabled(plugin_path, plugin, enabled_plugins, disabled_plugins):
                continue
            _register_loaded_plugin(plugin_path, plugin)

        with self._state_lock:
            self._commands_by_canonical = next_commands_by_canonical
            self._commands_by_alias = next_commands_by_alias
            self._message_handlers = next_message_handlers
            self._tick_handlers = next_tick_handlers
            self._loaded_plugins = next_loaded_plugins
            self._translations = next_translations
            self._plugins_by_name = next_plugins_by_name

    def _register_plugin(
        self,
        plugin: PluginSpec,
        commands_by_canonical: dict[str, CommandSpec],
        commands_by_alias: dict[str, CommandSpec],
        message_handlers: list[MessageHandler],
        tick_handlers: list[TickHandler],
        translation_catalogs: dict[str, dict[str, str]],
    ) -> None:
        self._register_translations(plugin, translation_catalogs)
        self._register_commands(plugin, commands_by_canonical, commands_by_alias)

        for message_handler in plugin.message_handlers:
            message_handlers.append(message_handler.handler)

        for tick_handler in plugin.tick_handlers:
            tick_handlers.append(tick_handler.handler)

    def _register_translations(self, plugin: PluginSpec, translation_catalogs: dict[str, dict[str, str]]) -> None:
        for language, plugin_catalog in plugin.translations.items():
            catalog = translation_catalogs.setdefault(language, {})
            for key, value in plugin_catalog.items():
                existing = catalog.get(key)
                if existing is not None and existing != value:
                    raise ValueError(f"Übersetzungsschlüssel {key} kollidiert in Sprache {language}.")
                catalog[key] = value

    def _register_commands(
        self,
        plugin: PluginSpec,
        commands_by_canonical: dict[str, CommandSpec],
        commands_by_alias: dict[str, CommandSpec],
    ) -> None:
        for command in plugin.commands:
            if command.canonical in commands_by_canonical:
                raise ValueError(f"Befehl {command.canonical} wurde mehrfach registriert.")

            commands_by_canonical[command.canonical] = command
            for alias in command.all_aliases():
                existing = commands_by_alias.get(alias)
                if existing is not None:
                    raise ValueError(f"Alias {alias} kollidiert mit {existing.canonical}.")
                commands_by_alias[alias] = command