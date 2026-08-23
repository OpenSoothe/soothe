"""Configuration and constants for the CLI.

This subpackage was split out from the former ``tui/config.py`` god module.
Each concern lives in its own module:

- :mod:`soothe_cli.settings.settings` — ``Settings`` class + lazy singleton
- :mod:`soothe_cli.settings.bootstrap` — dotenv loading and start-path detection
- :mod:`soothe_cli.settings.glyphs` — charset detection and display glyphs
- :mod:`soothe_cli.settings.provider` — LLM provider auto-detection
- :mod:`soothe_cli.settings.shell_allow` — shell command allow-list parsing
- :mod:`soothe_cli.settings.skills_dirs` — extra skill directory parsing
- :mod:`soothe_cli.settings.stream_config` — LangGraph stream config construction
- :mod:`soothe_cli.settings.console` — lazy global Rich Console singleton

The lazy ``settings`` and ``console`` singletons are resolved via
``__getattr__`` to preserve the deferred-initialization semantics of the
original module — heavy I/O (dotenv loading, project detection) is deferred
until first access so that e.g. ``Soothe --help`` does not touch the disk.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe_cli._version import (
    is_editable_install as _is_editable_install,
)
from soothe_cli.settings.glyphs import (
    ASCII_GLYPHS,
    MODE_DISPLAY_GLYPHS,
    MODE_PREFIXES,
    PREFIX_TO_MODE,
    UNICODE_GLYPHS,
    Glyphs,
    get_banner,
    get_glyphs,
    is_ascii_mode,
    newline_shortcut,
)
from soothe_cli.settings.shell_allow import parse_shell_allow_list
from soothe_cli.settings.stream_config import build_stream_config

if TYPE_CHECKING:
    from rich.console import Console

    # Static type stubs for lazy module attributes resolved by __getattr__.
    # At runtime these are created on first access by _get_settings() /
    # _get_console() and cached in globals().
    from soothe_cli.settings.core import Settings

    settings: Settings
    console: Console

logger = logging.getLogger(__name__)

__all__ = [
    "ASCII_GLYPHS",
    "MODE_DISPLAY_GLYPHS",
    "MODE_PREFIXES",
    "PREFIX_TO_MODE",
    "Glyphs",
    "UNICODE_GLYPHS",
    "_is_editable_install",
    "build_stream_config",
    "get_banner",
    "get_glyphs",
    "is_ascii_mode",
    "newline_shortcut",
    "parse_shell_allow_list",
]


def __getattr__(name: str):
    """Lazy module attributes for ``settings`` and ``console``.

    Defers heavy initialization until first access. Subsequent accesses hit
    the module-level attribute directly (no ``__getattr__`` overhead).

    Also lazily resolves ``detect_provider`` to avoid importing the settings
    singleton module at import time (it would pull in dotenv/bootstrap).

    Raises:
        AttributeError: If *name* is not a lazily-provided attribute.
    """
    if name == "settings":
        from soothe_cli.settings.core import _get_settings

        return _get_settings()
    if name == "console":
        from soothe_cli.settings._console_impl import _get_console

        return _get_console()
    if name == "detect_provider":
        from soothe_cli.settings.provider import detect_provider

        return detect_provider
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
