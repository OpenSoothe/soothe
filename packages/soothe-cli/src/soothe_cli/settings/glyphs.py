"""Character set detection and display glyphs for TUI display."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import StrEnum


class CharsetMode(StrEnum):
    """Character set mode for TUI display."""

    UNICODE = "unicode"
    """Always use Unicode glyphs (e.g. `●`, `✓`, `…`)."""

    ASCII = "ascii"
    """Always use ASCII-safe fallbacks (e.g. `[*]`, `[OK]`, `...`)."""

    AUTO = "auto"
    """Detect charset support at runtime and pick Unicode or ASCII."""


@dataclass(frozen=True)
class Glyphs:
    """Character glyphs for TUI display."""

    tool_prefix: str  # ● vs [*]
    file_edit_prefix: str  # ■ vs [#]
    subagent_prefix: str  # ◆ vs [S]
    ellipsis: str  # … vs ...
    checkmark: str  # ✓ vs [OK]
    error: str  # ✗ vs [X]
    circle_empty: str  # ○ vs [ ]
    circle_filled: str  # ● vs [*]
    output_prefix: str  # ⎿ vs L
    spinner_frames: tuple[str, ...]  # Braille vs ASCII spinner
    pause: str  # ⏸ vs ||
    newline: str  # ⏎ vs \\n
    warning: str  # ⚠ vs [!]
    question: str  # ? vs [?]
    arrow_up: str  # up arrow vs ^
    arrow_down: str  # down arrow vs v
    bullet: str  # bullet vs -
    cursor: str  # cursor vs >
    user: str  # User/human icon
    assistant: str  # AI/assistant icon

    # Expand/collapse icons
    expand: str  # ▶ vs [+] - shown when collapsed (click to expand)
    collapse: str  # ▼ vs [v] - shown when expanded (click to collapse)

    # Box-drawing characters
    box_vertical: str  # │ vs |
    box_horizontal: str  # ─ vs -
    box_double_horizontal: str  # ═ vs =

    # Diff-specific
    gutter_bar: str  # ▌ vs |

    # Status bar
    git_branch: str  # "↗" vs "git:"


UNICODE_GLYPHS = Glyphs(
    tool_prefix="●",
    file_edit_prefix="■",
    subagent_prefix="◆",
    ellipsis="…",
    checkmark="✓",
    error="✗",
    circle_empty="○",
    circle_filled="●",
    output_prefix="⎿",
    spinner_frames=("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"),
    pause="⏸",
    newline="⏎",
    warning="⚠",
    question="?",
    arrow_up="↑",
    arrow_down="↓",
    bullet="•",
    cursor="›",  # noqa: RUF001  # Intentional Unicode glyph
    user="»",  # User/human icon
    assistant="«",  # AI/assistant icon
    # Expand/collapse icons
    expand="▶",
    collapse="▼",
    # Box-drawing characters
    box_vertical="│",
    box_horizontal="─",
    box_double_horizontal="═",
    gutter_bar="▌",
    git_branch="↗",
)
"""Glyph set for terminals with full Unicode support."""

ASCII_GLYPHS = Glyphs(
    tool_prefix="[*]",
    file_edit_prefix="[#]",
    subagent_prefix="[S]",
    ellipsis="...",
    checkmark="[OK]",
    error="[X]",
    circle_empty="[ ]",
    circle_filled="[*]",
    output_prefix="L",
    spinner_frames=("(-)", "(\\)", "(|)", "(/)"),
    pause="||",
    newline="\\n",
    warning="[!]",
    question="[?]",
    arrow_up="^",
    arrow_down="v",
    bullet="-",
    cursor=">",
    user="[U]",  # User/human icon (ASCII)
    assistant="[A]",  # AI/assistant icon (ASCII)
    # Expand/collapse icons
    expand="[+]",
    collapse="[v]",
    # Box-drawing characters
    box_vertical="|",
    box_horizontal="-",
    box_double_horizontal="=",
    gutter_bar="|",
    git_branch="git:",
)
"""Glyph set for terminals limited to 7-bit ASCII."""

_glyphs_cache: Glyphs | None = None
"""Module-level cache for detected glyphs."""


def _detect_charset_mode() -> CharsetMode:
    """Auto-detect terminal charset capabilities.

    Returns:
    The detected CharsetMode based on environment and terminal encoding.
    """
    env_mode = os.environ.get("UI_CHARSET_MODE", "auto").lower()
    if env_mode == "unicode":
        return CharsetMode.UNICODE
    if env_mode == "ascii":
        return CharsetMode.ASCII

    # Auto: check stdout encoding and LANG
    encoding = getattr(sys.stdout, "encoding", "") or ""
    if "utf" in encoding.lower():
        return CharsetMode.UNICODE
    lang = os.environ.get("LANG", "") or os.environ.get("LC_ALL", "")
    if "utf" in lang.lower():
        return CharsetMode.UNICODE
    return CharsetMode.ASCII


def get_glyphs() -> Glyphs:
    """Get the glyph set for the current charset mode.

    Returns:
    The appropriate Glyphs instance based on charset mode detection.
    """
    global _glyphs_cache  # noqa: PLW0603  # Module-level cache requires global statement
    if _glyphs_cache is not None:
        return _glyphs_cache

    mode = _detect_charset_mode()
    _glyphs_cache = ASCII_GLYPHS if mode == CharsetMode.ASCII else UNICODE_GLYPHS
    return _glyphs_cache


def is_ascii_mode() -> bool:
    """Check whether the terminal is in ASCII charset mode.

    Convenience wrapper so widgets can branch on charset without importing
    both `_detect_charset_mode` and `CharsetMode`.

    Returns:
    `True` when the detected charset mode is ASCII.
    """
    return _detect_charset_mode() == CharsetMode.ASCII


def newline_shortcut() -> str:
    """Return the platform-native label for the newline keyboard shortcut.

    macOS labels the modifier "Option" while other platforms use Ctrl+J
    as the most reliable cross-terminal shortcut.

    Returns:
    A human-readable shortcut string, e.g. `'Option+Enter'` or `'Ctrl+J'`.
    """
    return "Option+Enter" if sys.platform == "darwin" else "Ctrl+J"


_UNICODE_BANNER = """
███████╗ ██████╗  ██████╗ ████████╗██╗  ██╗███████╗
██╔════╝██╔═══██╗██╔═══██╗╚══██╔══╝██║  ██║██╔════╝
███████╗██║   ██║██║   ██║   ██║   ███████║█████╗
╚════██║██║   ██║██║   ██║   ██║   ██╔══██║██╔══╝
███████║╚██████╔╝╚██████╔╝   ██║   ██║  ██║███████╗
╚══════╝ ╚═════╝  ╚═════╝    ╚═╝   ╚═╝  ╚═╝╚══════╝
"""
_ASCII_BANNER = """
 _______  _______  _______  _______  _______
/  ___  \\/  ___  \\/  ___  \\/  ___  \\/  ___  \
| |   | || |   | || |   | || |   | || |   | |
| |___| || |___| || |___| || |___| || |___| |
\\_______/\\_______/\\_______/\\_______/\\_______/
"""


def get_banner() -> str:
    """Get the appropriate banner for the current charset mode.

    Returns:
    The text art banner string (Unicode or ASCII based on charset mode).
    """
    if _detect_charset_mode() == CharsetMode.ASCII:
        return _ASCII_BANNER
    return _UNICODE_BANNER


# Non-normal mode trigger prefixes and display glyphs.
MODE_PREFIXES: dict[str, str] = {
    "shell": "!",
    "command": "/",
}
"""Maps each non-normal mode to its trigger character."""

MODE_DISPLAY_GLYPHS: dict[str, str] = {
    "shell": "$",
    "command": "/",
}
"""Maps each non-normal mode to its display glyph shown in the prompt/UI."""

if MODE_PREFIXES.keys() != MODE_DISPLAY_GLYPHS.keys():
    _only_prefixes = MODE_PREFIXES.keys() - MODE_DISPLAY_GLYPHS.keys()
    _only_glyphs = MODE_DISPLAY_GLYPHS.keys() - MODE_PREFIXES.keys()
    msg = (
        "MODE_PREFIXES and MODE_DISPLAY_GLYPHS have mismatched keys: "
        f"only in PREFIXES={_only_prefixes}, only in GLYPHS={_only_glyphs}"
    )
    raise ValueError(msg)

PREFIX_TO_MODE: dict[str, str] = {v: k for k, v in MODE_PREFIXES.items()}
"""Reverse lookup: trigger character -> mode name."""
