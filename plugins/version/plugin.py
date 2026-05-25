import subprocess
from pathlib import Path

from plugin_system import CommandSpec, MessageHandlerSpec, PluginSpec


REPOSITORY_URL = "https://github.com/WarPigs1602/ircbot-python"


def detect_version() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    try:
        branch = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        commit = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unbekannt"

    if branch and commit:
        return f"{branch}@{commit}"
    if commit:
        return commit
    return "unbekannt"


BOT_VERSION = detect_version()


def send_version(bot, target: str) -> None:
    bot.send_notice(target, f"Python IRC Bot {BOT_VERSION} | GitHub: {REPOSITORY_URL}")


def handle_version(bot, context, arg: str) -> None:
    send_version(bot, context.reply_target)


def handle_version_query(bot, context) -> None:
    if not context.is_private_message:
        return

    token = context.message.strip().lower()
    if token not in {"version", "ver"}:
        return

    send_version(bot, context.reply_target)


PLUGIN = PluginSpec(
    name="version",
    message_handlers=(
        MessageHandlerSpec(handler=handle_version_query),
    ),
    commands=(
        CommandSpec(
            canonical="version",
            handler=handle_version,
            aliases=("ver",),
            help_texts={
                "de": "Zeigt Bot-Version und GitHub-Repository an",
                "en": "Shows the bot version and GitHub repository",
            },
            help_sort=15,
        ),
    ),
)