"""Textual UI application for Soothe - migrated from Soothe per RFC-606."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from soothe_cli.runtime.state.session_stats import (
    SessionStats,
)
from soothe_cli.tui import theme

# Keep module-level imports minimal before first paint.
# All other config imports — settings, create_model, detect_provider, etc. — are
# deferred to local imports at their call sites since they are only accessed
# after user interaction begins.
from soothe_cli.tui._version import CHANGELOG_URL, DOCS_URL
from soothe_cli.tui.widgets.message_store import (
    MessageData,
)

logger = logging.getLogger(__name__)
_monotonic = time.monotonic

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


# iTerm2 Cursor Guide Workaround
# ===============================
# iTerm2's cursor guide (highlight cursor line) causes visual artifacts when
# Textual takes over the terminal in alternate screen mode. We disable it at
# module load and restore on exit. Both atexit and exit() override are used
# for defense-in-depth: atexit catches abnormal termination (SIGTERM, unhandled
# exceptions), while exit() ensures restoration before Textual's cleanup.

# Detection: check env vars AND that stderr is a TTY (avoids false positives
# when env vars are inherited but running in non-TTY context like CI)
_IS_ITERM = (
    (
        os.environ.get("LC_TERMINAL", "") == "iTerm2"
        or os.environ.get("TERM_PROGRAM", "") == "iTerm.app"
    )
    and hasattr(os, "isatty")
    and os.isatty(2)
)

# iTerm2 cursor guide escape sequences (OSC 1337)
# Format: OSC 1337 ; HighlightCursorLine=<yes|no> ST
# Where OSC = ESC ] (0x1b 0x5d) and ST = ESC \ (0x1b 0x5c)
_ITERM_CURSOR_GUIDE_OFF = "\x1b]1337;HighlightCursorLine=no\x1b\\"
_ITERM_CURSOR_GUIDE_ON = "\x1b]1337;HighlightCursorLine=yes\x1b\\"


def _write_iterm_escape(sequence: str) -> None:
    """Write an iTerm2 escape sequence to stderr.

    Silently fails if the terminal is unavailable (redirected, closed, broken
    pipe). This is a cosmetic feature, so failures should never crash the app.
    """
    if not _IS_ITERM:
        return
    try:
        import sys

        if sys.__stderr__ is not None:
            sys.__stderr__.write(sequence)
            sys.__stderr__.flush()
    except OSError:
        # Terminal may be unavailable (redirected, closed, broken pipe)
        pass


# Disable cursor guide at module load (before Textual takes over)
_write_iterm_escape(_ITERM_CURSOR_GUIDE_OFF)

if _IS_ITERM:
    import atexit

    def _restore_cursor_guide() -> None:
        """Restore iTerm2 cursor guide on exit.

        Registered with atexit to ensure the cursor guide is re-enabled
        when the CLI exits, regardless of how the exit occurs.
        """
        _write_iterm_escape(_ITERM_CURSOR_GUIDE_ON)

    atexit.register(_restore_cursor_guide)


def _load_theme_preference() -> str:
    """Load the saved theme name from config, or return the default.

    Returns:
        A Textual theme name (e.g., `'langchain'`, `'langchain-light'`).
    """
    import yaml

    try:
        from soothe_cli.tui.model_config import DEFAULT_CONFIG_PATH

        if not DEFAULT_CONFIG_PATH.exists():
            return theme.DEFAULT_THEME

        with DEFAULT_CONFIG_PATH.open("rb") as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, PermissionError, OSError) as exc:
        logger.warning("Could not read config for theme preference: %s", exc)
        return theme.DEFAULT_THEME

    name = data.get("ui", {}).get("theme")
    if isinstance(name, str) and name in theme.ThemeEntry.REGISTRY:
        return name
    if isinstance(name, str):
        logger.warning(
            "Unknown theme '%s' in config; falling back to default",
            name,
        )
    return theme.DEFAULT_THEME


def save_theme_preference(name: str) -> bool:
    """Persist theme preference to `~/SOOTHE_HOME/config/config.yml`.

    Args:
        name: Textual theme name to save.

    Returns:
        `True` if the preference was saved, `False` if any error occurred.
    """
    if name not in theme.ThemeEntry.REGISTRY:
        logger.warning("Refusing to save unknown theme '%s'", name)
        return False

    import contextlib
    import tempfile

    try:
        import yaml

        from soothe_cli.tui.model_config import DEFAULT_CONFIG_PATH

        DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if DEFAULT_CONFIG_PATH.exists():
            with DEFAULT_CONFIG_PATH.open("r") as f:
                data = yaml.safe_load(f)
        else:
            data = {}

        if "ui" not in data:
            data["ui"] = {}
        data["ui"]["theme"] = name

        fd, tmp_path = tempfile.mkstemp(dir=DEFAULT_CONFIG_PATH.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                yaml.safe_dump(data, f)
            Path(tmp_path).replace(DEFAULT_CONFIG_PATH)
        except BaseException:
            with contextlib.suppress(OSError):
                Path(tmp_path).unlink()
            raise
    except Exception:
        logger.exception("Could not save theme preference")
        return False
    return True


def _extract_model_params_flag(raw_arg: str) -> tuple[str, dict[str, Any] | None]:
    """Extract `--model-params` and its JSON value from a `/model` arg string.

    Handles quoted (`'...'` / `"..."`) and bare `{...}` values with balanced
    braces so that JSON containing spaces works without quoting.

    Note:
        The bare-brace mode counts `{` / `}` characters without awareness of
        JSON string contents. Values that contain literal braces inside strings
        (e.g., `{"stop": "end}here"}`) will mis-parse. Users should quote the
        value in that case.

    Args:
        raw_arg: The argument string after `/model `.

    Returns:
        Tuple of `(remaining_args, parsed_dict | None)`. Returns `None` for the
            dict when the flag is absent.

    Raises:
        ValueError: If the value is missing, has unclosed quotes,
            unbalanced braces, or is not valid JSON.
        TypeError: If the parsed JSON is not a dict.
    """
    flag = "--model-params"
    idx = raw_arg.find(flag)
    if idx == -1:
        return raw_arg, None

    before = raw_arg[:idx].rstrip()
    after = raw_arg[idx + len(flag) :].lstrip()

    if not after:
        msg = "--model-params requires a JSON object value"
        raise ValueError(msg)

    # Determine the JSON string boundaries.
    if after[0] in {"'", '"'}:
        quote = after[0]
        end = -1
        backslash_count = 0
        for i, ch in enumerate(after[1:], start=1):
            if ch == "\\":
                backslash_count += 1
                continue
            if ch == quote and backslash_count % 2 == 0:
                end = i
                break
            backslash_count = 0
        if end == -1:
            msg = f"Unclosed {quote} in --model-params value"
            raise ValueError(msg)
        # Parse the quoted token with shlex so escaped quotes are unescaped.
        json_str = shlex.split(after[: end + 1], posix=True)[0]
        rest = after[end + 1 :].lstrip()
    elif after[0] == "{":
        # Walk forward to find the matching closing brace.
        depth = 0
        end = -1
        for i, ch in enumerate(after):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end == -1:
            msg = "Unbalanced braces in --model-params value"
            raise ValueError(msg)
        json_str = after[: end + 1]
        rest = after[end + 1 :].lstrip()
    else:
        # Non-brace, non-quoted — take the next whitespace-delimited token.
        parts = after.split(None, 1)
        json_str = parts[0]
        rest = parts[1] if len(parts) > 1 else ""

    remaining = f"{before} {rest}".strip()
    try:
        params = json.loads(json_str)
    except json.JSONDecodeError:
        msg = f'Invalid JSON in --model-params: {json_str!r}. Expected format: --model-params \'{{"key": "value"}}\''
        raise ValueError(msg) from None
    if not isinstance(params, dict):
        msg = "--model-params must be a JSON object, got " + type(params).__name__
        raise TypeError(msg)
    return remaining, params


InputMode = Literal["normal", "shell", "command"]


@dataclass(frozen=True, slots=True)
class QueuedMessage:
    """Represents a queued user message awaiting processing."""

    text: str
    """The message text content."""

    mode: InputMode
    """The input mode that determines message routing."""


DeferredActionKind = Literal["model_switch", "loop_switch", "chat_output"]
"""Valid `DeferredAction.kind` values for type-checked deduplication."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DeferredAction:
    """An action deferred until the current busy state resolves."""

    kind: DeferredActionKind
    """Identity key for deduplication — one of `DeferredActionKind`."""

    execute: Callable[[], Awaitable[None]]
    """Async callable that performs the actual work."""


@dataclass(frozen=True, slots=True)
class _LoopHistoryPayload:
    """Data returned by `_fetch_loop_history_data`."""

    messages: list[MessageData]
    """Converted message data ready for bulk loading."""

    context_tokens: int
    """Persisted `_context_tokens` from the checkpoint (0 if absent)."""

    goals: tuple[dict[str, Any], ...] = ()
    """Goal display snapshots from ``loop_history_fetch`` (RFC-631)."""


def _new_loop_id() -> str:
    """Deferred-import wrapper around `sessions.generate_loop_id`.

    Returns:
        UUID7 string.
    """
    from soothe_cli.tui.sessions import generate_loop_id

    return generate_loop_id()


class TextualSessionState:
    """Session state for the Textual app."""

    def __init__(
        self,
        *,
        loop_id: str | None = None,
    ) -> None:
        """Initialize session state.

        Args:
            loop_id: Optional loop ID (generates UUID7 if not provided)
        """
        self.loop_id = loop_id or _new_loop_id()

    def reset_loop(self) -> str:
        """Reset to a new loop.

        Returns:
            The new loop_id.
        """
        self.loop_id = _new_loop_id()
        return self.loop_id


_COMMAND_URLS: dict[str, str] = {
    "/changelog": CHANGELOG_URL,
    "/docs": DOCS_URL,
    "/feedback": "https://github.com/mirasoth/soothe/issues/new/choose",
}
"""Slash-command to URL mapping for commands that just open a browser."""


@dataclass(frozen=True)
class AppResult:
    """Result from running the Textual application."""

    return_code: int
    """Exit code (0 for success, non-zero for error)."""

    loop_id: str | None
    """The final StrangeLoop id at shutdown (may change if the user switched loops)."""

    session_stats: SessionStats = field(default_factory=SessionStats)
    """Cumulative usage stats across all turns in the session."""

    update_available: tuple[bool, str | None] = (False, None)
    """`(is_available, latest_version)` for post-exit update warning."""


async def run_textual_app(
    *,
    daemon_config: Any,  # noqa: ANN401
    assistant_id: str | None = None,
    cwd: str | Path | None = None,
    resume_loop_id: str | None = None,
    initial_prompt: str | None = None,
    initial_skill: str | None = None,
    mcp_server_info: list[dict[str, Any]] | None = None,
    profile_override: dict[str, Any] | None = None,
) -> AppResult:
    """Run the Textual TUI (daemon execution only).

    Args:
        daemon_config: Loaded Soothe configuration used for WebSocket bootstrap.
        assistant_id: Agent identifier for memory storage.
        cwd: Current working directory to display.
        resume_loop_id: Initial loop id when attaching to an existing conversation.
        initial_prompt: Optional prompt to auto-submit when session starts.
        initial_skill: Optional skill name to invoke when session starts.
        mcp_server_info: MCP server metadata for the `/mcp` viewer.
        profile_override: Extra profile fields from ``--profile-override``.

    Returns:
        An `AppResult` with the return code and final loop id.
    """
    from soothe_cli.tui.app._app import SootheApp  # deferred to avoid circular import

    app = SootheApp(
        daemon_config=daemon_config,
        assistant_id=assistant_id,
        cwd=cwd,
        resume_loop_id=resume_loop_id,
        initial_prompt=initial_prompt,
        initial_skill=initial_skill,
        mcp_server_info=mcp_server_info,
        profile_override=profile_override,
    )
    try:
        await app.run_async()
    finally:
        if app._daemon_session is not None:
            from soothe_cli.runtime.transport.session import TUI_EXIT_HANDSHAKE_TIMEOUT_S

            await app._daemon_session.close(handshake_timeout=TUI_EXIT_HANDSHAKE_TIMEOUT_S)

    return AppResult(
        return_code=app.return_code or 0,
        loop_id=app._lc_loop_id,
        session_stats=app._session_stats,
        update_available=app._update_available,
    )


def run_textual_tui(
    config: Any,  # noqa: ANN401
    resume_loop_id: str | None = None,
    initial_prompt: str | None = None,
) -> AppResult:
    """Launch the Textual TUI with optional loop attachment and initial prompt.

    Args:
        config: Soothe configuration used for daemon-backed startup.
        resume_loop_id: Loop id to attach to when starting the TUI
        initial_prompt: Auto-submit prompt on launch
    """

    # Caller cwd is forwarded as the loop workspace hint (IG-344).
    # Daemon workspace is ephemeral TEMP unless SOOTHE_WORKSPACE env set.
    cwd = os.getcwd()

    return asyncio.run(
        run_textual_app(
            resume_loop_id=resume_loop_id,
            initial_prompt=initial_prompt,
            daemon_config=config,
            cwd=cwd,
        )
    )
