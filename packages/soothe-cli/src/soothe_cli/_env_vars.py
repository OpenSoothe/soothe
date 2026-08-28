"""Canonical registry of `SOOTHE_CLI_*` environment variables."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Constants — import these instead of bare string literals.
# Keep alphabetically sorted by constant name.
# ---------------------------------------------------------------------------

AUTO_UPDATE = "SOOTHE_CLI_AUTO_UPDATE"
"""Override automatic CLI updates: '1'/'true'/'yes' on, '0'/'false'/'no' off. On by default when unset."""

DEBUG = "SOOTHE_CLI_DEBUG"
"""Enable verbose debug logging to a file."""

DEBUG_FILE = "SOOTHE_CLI_DEBUG_FILE"
"""Path for the debug log file (default: `/tmp/soothe_debug.log`)."""

EXTRA_SKILLS_DIRS = "SOOTHE_CLI_EXTRA_SKILLS_DIRS"
"""Colon-separated paths added to the skill containment allowlist."""

NO_UPDATE_CHECK = "SOOTHE_CLI_NO_UPDATE_CHECK"
"""Disable automatic update checking when set."""

UPDATE_CHECK = "SOOTHE_CLI_UPDATE_CHECK"
"""Force-enable startup PyPI update checks ('1', 'true', or 'yes'). On by default."""

SERVER_ENV_PREFIX = "SOOTHE_CLI_SERVER_"
"""Environment variable prefix used to pass CLI config to the server subprocess."""

SHELL_ALLOW_LIST = "SOOTHE_CLI_SHELL_ALLOW_LIST"
"""Comma-separated shell commands to allow (or 'recommended'/'all')."""

USER_ID = "SOOTHE_CLI_USER_ID"
"""Attach a user identifier to stream metadata (when set)."""

TUI_REFRESH_INTERVAL_MS = "SOOTHE_CLI_TUI_REFRESH_INTERVAL_MS"
"""Minimum interval between TUI widget refreshes in milliseconds (default: 800).

Set to throttle frequent refreshes during streaming, reducing UI lag.
Lower values = more responsive but more CPU load; higher values = smoother.
"""

WORKSPACE = "SOOTHE_CLI_WORKSPACE"
"""Explicit project directory sent to the daemon on ``loop_new`` (defaults to cwd)."""

OMIT_WORKSPACE = "SOOTHE_CLI_OMIT_WORKSPACE"
"""Optional: when ``1``/``true``/``yes``, omit ``workspace`` on ``loop_new`` (default: send cwd)."""


def resolve_cli_loop_workspace() -> str | None:
    """Return the workspace path to send on `loop_new`, or `None` to omit it.

    By default sends `cwd`. The daemon ignores host paths that are not present
    on the daemon filesystem (falls back to persisted layout) unless
    `workspace_mount` is configured. `SOOTHE_CLI_OMIT_WORKSPACE` is
    optional — use it only to skip sending `workspace` on the wire.
    """
    import os

    omit = os.environ.get(OMIT_WORKSPACE, "").strip().lower()
    if omit in ("1", "true", "yes", "on"):
        return None

    explicit = os.environ.get(WORKSPACE, "").strip()
    if explicit.lower() in ("none", "-", "omit"):
        return None
    if explicit:
        return explicit
    return os.getcwd()
