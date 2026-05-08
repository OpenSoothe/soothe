"""Public API for the app sub-package."""

from soothe_cli.tui.app._app import SootheApp
from soothe_cli.tui.app._module_init import (
    AppResult,
    TextualSessionState,
    run_textual_app,
    run_textual_tui,
    save_theme_preference,
)

__all__ = [
    "SootheApp",
    "AppResult",
    "TextualSessionState",
    "run_textual_app",
    "run_textual_tui",
    "save_theme_preference",
]
