import subprocess
from pathlib import Path


REPOSITORY_URL = "https://github.com/WarPigs1602/ircbot-python"


def detect_version() -> str:
    repo_root = Path(__file__).resolve().parent
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


def version_line() -> str:
    return f"Python IRC Bot {detect_version()} | GitHub: {REPOSITORY_URL}"
