"""Public API for the app sub-package."""

from soothe_cli.tui.app._app import SootheApp
from soothe_cli.tui.app._entrypoints import run_textual_app, run_textual_tui
from soothe_cli.tui.app._theme_prefs import save_theme_preference
from soothe_cli.tui.app._types import AppResult, TextualSessionState

__all__ = [
    "SootheApp",
    "AppResult",
    "TextualSessionState",
    "run_textual_app",
    "run_textual_tui",
    "save_theme_preference",
]
