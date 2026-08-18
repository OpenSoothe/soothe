"""Configuration and constants for the CLI."""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe_sdk.paths import SOOTHE_HOME

from soothe_cli.tui._version import (
    __version__,
)
from soothe_cli.tui._version import (
    is_editable_install as _is_editable_install,
)

__all__ = ["_is_editable_install"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy bootstrap: dotenv loading and start-path detection are deferred until
# first access of `settings` (via module `__getattr__`).  This avoids disk I/O
# and path traversal during import for callers that never touch `settings`
# (e.g. `Soothe --help`).
# ---------------------------------------------------------------------------

_bootstrap_done = False
"""Whether `_ensure_bootstrap()` has executed."""

_bootstrap_lock = threading.Lock()
"""Guards `_ensure_bootstrap()` against concurrent access from the main thread
and the prewarm worker thread."""

_singleton_lock = threading.Lock()
"""Guards lazy singleton construction in `_get_console` / `_get_settings`."""

_bootstrap_start_path: Path | None = None
"""Working directory captured at bootstrap time for dotenv and project discovery."""


def _find_dotenv_from_start_path(start_path: Path) -> Path | None:
    """Find the nearest `.env` file from an explicit start path upward.

    Args:
        start_path: Directory to start searching from.

    Returns:
        Path to the nearest `.env` file, or `None` if not found.
    """
    current = start_path.expanduser().resolve()
    for parent in [current, *list(current.parents)]:
        candidate = parent / ".env"
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            logger.warning("Could not inspect .env candidate %s", candidate)
            continue
    return None


# Global user-level .env (SOOTHE_HOME/.env); sentinel when Path.home() fails.
try:
    _GLOBAL_DOTENV_PATH = Path(SOOTHE_HOME) / ".env"
except RuntimeError:
    _GLOBAL_DOTENV_PATH = Path("/nonexistent/.soothe/.env")


def _load_dotenv(*, start_path: Path | None = None) -> bool:
    """Load environment variables from project and global `.env` files.

    Loads in order (first write wins, `override=False`):

    1. Project/CWD `.env` — project-specific values
    2. `SOOTHE_HOME/.env` — global user defaults

    Both layers use `override=False` (the python-dotenv default) so that
    shell-exported variables always take precedence over dotenv files.
    Because project loads first, the effective precedence is:

    ```text
    shell env (incl. inline `VAR=x`)  >  project `.env`  >  global `.env`
    ```

    !!! note

        To scope credentials to the CLI without colliding with
        identically-named shell exports, use the `SOOTHE_` env-var
        prefix (see `resolve_env_var` in `soothe.model_config`).

    Args:
        start_path: Directory to use for project `.env` discovery.

    Returns:
        `True` when at least one dotenv file was loaded, `False` otherwise.
    """
    import dotenv

    loaded = False

    # 1. Project/CWD .env — loads first so project values are set before the
    # global file, which can only fill in vars not already present.
    dotenv_path: Path | str | None = None
    try:
        if start_path is None:
            loaded = dotenv.load_dotenv(override=False) or loaded
        else:
            dotenv_path = _find_dotenv_from_start_path(start_path)
            if dotenv_path is not None:
                loaded = dotenv.load_dotenv(dotenv_path=dotenv_path, override=False) or loaded
    except (OSError, ValueError):
        logger.warning(
            "Could not read project dotenv at %s; project env vars will not be loaded",
            dotenv_path or start_path or "cwd",
            exc_info=True,
        )

    # 2. Global (SOOTHE_HOME/.env) — fills in any vars not already set by
    # the shell or the project dotenv.
    # try/except wraps both is_file() and load_dotenv() to cover the TOCTOU
    # window where the file can vanish between stat and open.
    try:
        if _GLOBAL_DOTENV_PATH.is_file() and dotenv.load_dotenv(
            dotenv_path=_GLOBAL_DOTENV_PATH, override=False
        ):
            loaded = True
            logger.debug("Loaded global dotenv: %s", _GLOBAL_DOTENV_PATH)
    except (OSError, ValueError):
        logger.warning(
            "Could not read global dotenv at %s; global defaults will not be applied",
            _GLOBAL_DOTENV_PATH,
            exc_info=True,
        )

    return loaded


def _ensure_bootstrap() -> None:
    """Run one-time bootstrap: dotenv loading from project and global paths.

    Idempotent and thread-safe — subsequent calls are no-ops. Called
    automatically by `_get_settings()` when `settings` is first accessed.

    The flag is set in `finally` so that partial failures (e.g. a
    malformed `.env`) still mark bootstrap as done — preventing infinite retry
    loops. Exceptions are caught and logged at ERROR level; the CLI proceeds
    with the environment as-is.
    """
    global _bootstrap_done, _bootstrap_start_path  # noqa: PLW0603

    if _bootstrap_done:
        return

    with _bootstrap_lock:
        if _bootstrap_done:  # double-check after acquiring lock
            return

        try:
            from soothe_cli.tui.project_utils import (
                get_server_project_context as _get_server_project_context,
            )

            ctx = _get_server_project_context()
            _bootstrap_start_path = ctx.user_cwd if ctx else None
            _load_dotenv(start_path=_bootstrap_start_path)
        except Exception:
            logger.exception(
                "Bootstrap failed; project .env may not be loaded. "
                "The CLI will proceed with environment as-is.",
            )
        finally:
            _bootstrap_done = True


if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from rich.console import Console

    # Static type stubs for lazy module attributes resolved by __getattr__.
    # At runtime these are created on first access by _get_settings() /
    # _get_console() and cached in globals().
    settings: Settings
    console: Console

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


config: RunnableConfig = {
    "recursion_limit": 1000,
}
"""Default LangGraph runnable config.

Sets `recursion_limit` to 1000 to accommodate deeply nested agent graphs without
hitting the default LangGraph ceiling.
"""

_git_branch_cache: dict[str, str | None] = {}
"""Per-cwd cache of resolved git branch names.

Avoids repeated `git rev-parse` subprocess calls within the same session. Keyed
by `str(Path.cwd())`; `None` values indicate the directory is not inside a git
repository.
"""


def _get_git_branch() -> str | None:
    """Return the current git branch name, or `None` if not in a repo."""
    import subprocess  # noqa: S404

    try:
        cwd = str(Path.cwd())
    except OSError:
        logger.debug("Could not determine cwd for git branch lookup", exc_info=True)
        return None
    if cwd in _git_branch_cache:
        return _git_branch_cache[cwd]

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            branch = result.stdout.strip() or None
            _git_branch_cache[cwd] = branch
            return branch
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        logger.debug("Could not determine git branch", exc_info=True)
    _git_branch_cache[cwd] = None
    return None


def build_stream_config(
    loop_id: str,
    assistant_id: str | None,
    *,
    sandbox_type: str | None = None,
    workspace: str | None = None,
) -> RunnableConfig:
    """Build the LangGraph stream config dict.

    Injects the resolved Soothe version into ``metadata["versions"]`` so runs
    can be correlated with specific releases. The runtime config replaces the
    graph config's ``versions`` key at stream time, so this must carry the
    canonical release string.

    Args:
        loop_id: Active StrangeLoop id (stored under LangGraph ``configurable.thread_id``).
        assistant_id: The agent/assistant identifier, if any.
        sandbox_type: Sandbox provider name for trace metadata, or `None` if no
            sandbox is active.
        workspace: Workspace directory for in-process TUI runs. When
            omitted, uses `Path.cwd()` (resolved). Mirrored to
            `configurable["workspace"]` for middleware and task-tool propagation
            (RFC-103).

    Returns:
        Config dict with `configurable` and `metadata` keys.
    """
    from datetime import UTC, datetime

    try:
        cwd = str(Path.cwd())
    except OSError:
        logger.warning("Could not determine working directory", exc_info=True)
        cwd = ""

    metadata: dict[str, Any] = {
        "versions": {"Soothe": __version__},
    }
    from soothe_cli.tui._env_vars import USER_ID

    user_id = os.environ.get(USER_ID)
    if user_id:
        metadata["user_id"] = user_id
    if cwd:
        metadata["cwd"] = cwd
    if assistant_id:
        metadata.update(
            {
                "assistant_id": assistant_id,
                "agent_name": assistant_id,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
    branch = _get_git_branch()
    if branch:
        metadata["git_branch"] = branch
    if sandbox_type and sandbox_type != "none":
        metadata["sandbox_type"] = sandbox_type

    configurable: dict[str, Any] = {"thread_id": loop_id}
    resolved_workspace: str | None = None
    if workspace and str(workspace).strip():
        try:
            resolved_workspace = str(Path(workspace).expanduser().resolve())
        except OSError:
            logger.warning(
                "Could not resolve workspace path %r; omitting configurable.workspace",
                workspace,
                exc_info=True,
            )
    else:
        try:
            resolved_workspace = str(Path.cwd().resolve())
        except OSError:
            logger.warning("Could not resolve cwd for configurable.workspace", exc_info=True)
    if resolved_workspace:
        configurable["workspace"] = resolved_workspace

    return {
        "configurable": configurable,
        "metadata": metadata,
    }


class _ShellAllowAll(list):  # noqa: FURB189  # sentinel type, not a general-purpose list subclass
    """Sentinel subclass for unrestricted shell access.

    Using a dedicated type instead of a plain list lets consumers use
    `isinstance` checks, which survive serialization/copy unlike identity
    checks (`is`).
    """


SHELL_ALLOW_ALL: list[str] = _ShellAllowAll(["__ALL__"])
"""Sentinel value returned by `parse_shell_allow_list` for `--shell-allow-list=all`."""


def parse_shell_allow_list(allow_list_str: str | None) -> list[str] | None:
    """Parse shell allow-list from string.

    Args:
        allow_list_str: Comma-separated list of commands, `'recommended'` for
            safe defaults, or `'all'` to allow any command.

            `'all'` must be the sole value — it is not recognized inside a
            comma-separated list (unlike `'recommended'`).

            Can also include `'recommended'` in the list to merge with custom
            commands.

    Returns:
        List of allowed commands, `SHELL_ALLOW_ALL` if `'all'` was specified,
            or `None` if no allow-list configured.

    Raises:
        ValueError: If `'all'` is combined with other commands.
    """
    if not allow_list_str:
        return None

    # Special value 'all' allows any shell command
    if allow_list_str.strip().lower() == "all":
        return SHELL_ALLOW_ALL

    # Special value 'recommended' uses our curated safe list
    if allow_list_str.strip().lower() == "recommended":
        return list(RECOMMENDED_SAFE_SHELL_COMMANDS)

    # Split by comma and strip whitespace
    commands = [cmd.strip() for cmd in allow_list_str.split(",") if cmd.strip()]

    # Reject ambiguous input: 'all' mixed with other commands
    if any(cmd.lower() == "all" for cmd in commands):
        msg = (
            "Cannot combine 'all' with other commands in --shell-allow-list. "
            "Use '--shell-allow-list all' alone to allow any command."
        )
        raise ValueError(msg)

    # If "recommended" is in the list, merge with recommended commands
    result = []
    for cmd in commands:
        if cmd.lower() == "recommended":
            result.extend(RECOMMENDED_SAFE_SHELL_COMMANDS)
        else:
            result.append(cmd)

    # Remove duplicates while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for cmd in result:
        if cmd not in seen:
            seen.add(cmd)
            unique.append(cmd)
    return unique


def _read_config_yaml_skills_dirs() -> list[str] | None:
    """Read `[skills].extra_allowed_dirs` from `SOOTHE_HOME/config/cli.yml`.

    Returns:
        List of path strings, or `None` if the key is absent or the file
            cannot be read.
    """
    import yaml

    from soothe_cli.tui.model_config import resolve_cli_config_path

    try:
        config_path = resolve_cli_config_path()
        with config_path.open("r") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        return None
    except (PermissionError, OSError, yaml.YAMLError):
        logger.warning(
            "Could not read skills config from %s",
            resolve_cli_config_path(),
            exc_info=True,
        )
        return None

    skills_section = data.get("skills", {}) if data else {}
    dirs = skills_section.get("extra_allowed_dirs")
    if isinstance(dirs, list):
        return dirs
    return None


def _parse_extra_skills_dirs(
    env_raw: str | None,
    config_yaml_dirs: list[str] | None = None,
) -> list[Path] | None:
    """Merge extra skill directories from env var and cli.yml.

    Extra skills directories extend the containment allowlist used by
    `load_skill_content` to validate that a resolved skill path lives inside a
    trusted root. They do **not** add new skill discovery locations — skills are
    still discovered only from the standard directories. This exists so that
    symlinks inside standard skill directories can legitimately point to targets
    in user-specified locations without being rejected by the path
    containment check.

    The env var (`SOOTHE_EXTRA_SKILLS_DIRS`, colon-separated) takes
    precedence: when set, `cli.yml` values are ignored.

    Args:
        env_raw: Value of `SOOTHE_EXTRA_SKILLS_DIRS` (colon-separated), or
            `None` if unset.
        config_yaml_dirs: List of path strings from
            `[skills].extra_allowed_dirs` in `SOOTHE_HOME/config/cli.yml`.

    Returns:
        List of resolved `Path` objects, or `None` if not configured.
    """
    # Env var takes precedence when set
    if env_raw:
        dirs = [Path(p.strip()).expanduser().resolve() for p in env_raw.split(":") if p.strip()]
        return dirs or None

    if config_yaml_dirs:
        dirs = [
            Path(p).expanduser().resolve()
            for p in config_yaml_dirs
            if isinstance(p, str) and p.strip()
        ]
        return dirs or None

    return None


@dataclass
class Settings:
    """Global settings and environment detection for Soothe.

    This class is initialized once at startup and provides access to:
    - Available models and API keys
    - Current project information
    - Tool availability (e.g., Tavily)
    - File system paths
    """

    openai_api_key: str | None
    """OpenAI API key if available."""

    anthropic_api_key: str | None
    """Anthropic API key if available."""

    google_api_key: str | None
    """Google API key if available."""

    nvidia_api_key: str | None
    """NVIDIA API key if available."""

    tavily_api_key: str | None
    """Tavily API key if available."""

    google_cloud_project: str | None
    """Google Cloud project ID for VertexAI authentication."""

    model_name: str | None = None
    """Currently active model name, set after model creation."""

    model_provider: str | None = None
    """Provider identifier (e.g., `openai`, `anthropic`, `google_genai`)."""

    model_context_limit: int | None = None
    """Maximum input token count from the model profile."""

    project_root: Path | None = None
    """Current project root directory, or `None` if not in a git project."""

    shell_allow_list: list[str] | None = None
    """Shell commands that don't require user approval."""

    extra_skills_dirs: list[Path] | None = None
    """Extra directories added to the skill path containment allowlist.

    These do NOT add new skill discovery locations — skills are still only
    discovered from the standard directories. They exist so that symlinks inside
    standard skill directories can point to targets in these additional
    locations without being rejected by the containment check
    in `load_skill_content`.

    Set via `SOOTHE_EXTRA_SKILLS_DIRS` env var (colon-separated) or
    `[skills].extra_allowed_dirs` in `SOOTHE_HOME/config/cli.yml`.
    """

    @classmethod
    def from_environment(cls, *, start_path: Path | None = None) -> Settings:
        """Create settings by detecting the current environment.

        Args:
            start_path: Directory to start project detection from (defaults to cwd)

        Returns:
            Settings instance with detected configuration
        """
        # Detect API keys (normalize empty strings to None).
        from soothe_cli.tui.model_config import resolve_env_var

        openai_key = resolve_env_var("OPENAI_API_KEY")
        anthropic_key = resolve_env_var("ANTHROPIC_API_KEY")
        google_key = resolve_env_var("GOOGLE_API_KEY")
        nvidia_key = resolve_env_var("NVIDIA_API_KEY")
        tavily_key = resolve_env_var("TAVILY_API_KEY")
        google_cloud_project = resolve_env_var("GOOGLE_CLOUD_PROJECT")

        from soothe_cli.tui._env_vars import (
            EXTRA_SKILLS_DIRS,
            SHELL_ALLOW_LIST,
        )

        # Detect project
        from soothe_cli.tui.project_utils import find_project_root

        project_root = find_project_root(start_path)

        # Parse shell command allow-list from environment
        # Format: comma-separated list of commands (e.g., "ls,cat,grep,pwd")

        shell_allow_list_str = os.environ.get(SHELL_ALLOW_LIST)
        shell_allow_list = parse_shell_allow_list(shell_allow_list_str)

        # Parse extra skill containment roots from env var or cli.yml.
        # These extend the path allowlist for load_skill_content but do not
        # add new skill discovery locations.
        extra_skills_dirs = _parse_extra_skills_dirs(
            os.environ.get(EXTRA_SKILLS_DIRS),
            _read_config_yaml_skills_dirs(),
        )

        return cls(
            openai_api_key=openai_key,
            anthropic_api_key=anthropic_key,
            google_api_key=google_key,
            nvidia_api_key=nvidia_key,
            tavily_api_key=tavily_key,
            google_cloud_project=google_cloud_project,
            project_root=project_root,
            shell_allow_list=shell_allow_list,
            extra_skills_dirs=extra_skills_dirs,
        )

    def reload_from_environment(self, *, start_path: Path | None = None) -> list[str]:
        """Reload selected settings from environment variables and project files.

        This refreshes only fields that are expected to change at runtime
        (API keys, Google Cloud project, project root, and shell allow-list).

        Runtime model state (`model_name`, `model_provider`,
        `model_context_limit`) is intentionally preserved — it is not in
        `reloadable_fields` and is never touched by this method.

        !!! note

            `.env` files are loaded with `override=False`, so shell-exported
            variables always take precedence.  To override a shell-exported key
            from `.env`, use the `SOOTHE_` prefix (e.g.
            `SOOTHE_OPENAI_API_KEY`).

        Args:
            start_path: Directory to start project detection from (defaults to cwd).

        Returns:
            A list of human-readable change descriptions.
        """
        _load_dotenv(start_path=start_path)

        api_key_fields = {
            "openai_api_key",
            "anthropic_api_key",
            "google_api_key",
            "nvidia_api_key",
            "tavily_api_key",
        }
        """Fields that hold API keys — used to mask values in change reports
        so secrets are not logged as plaintext."""

        reloadable_fields = (
            "openai_api_key",
            "anthropic_api_key",
            "google_api_key",
            "nvidia_api_key",
            "tavily_api_key",
            "google_cloud_project",
            "project_root",
            "shell_allow_list",
            "extra_skills_dirs",
        )
        """Fields refreshed on `/reload`.

        Runtime model state (`model_name`, `model_provider`, `model_context_limit`)
        is intentionally excluded — it is set once and should not change across
        reloads.
        """

        previous = {field: getattr(self, field) for field in reloadable_fields}

        from soothe_cli.tui._env_vars import (
            EXTRA_SKILLS_DIRS,
            SHELL_ALLOW_LIST,
        )

        try:
            shell_allow_list = parse_shell_allow_list(os.environ.get(SHELL_ALLOW_LIST))
        except ValueError:
            logger.warning(
                "Invalid %s during reload; keeping previous value",
                SHELL_ALLOW_LIST,
            )
            shell_allow_list = previous["shell_allow_list"]

        try:
            from soothe_cli.tui.project_utils import find_project_root

            project_root = find_project_root(start_path)
        except OSError:
            logger.warning("Could not detect project root during reload; keeping previous value")
            project_root = previous["project_root"]

        from soothe_cli.tui.model_config import resolve_env_var

        refreshed = {
            "openai_api_key": resolve_env_var("OPENAI_API_KEY"),
            "anthropic_api_key": resolve_env_var("ANTHROPIC_API_KEY"),
            "google_api_key": resolve_env_var("GOOGLE_API_KEY"),
            "nvidia_api_key": resolve_env_var("NVIDIA_API_KEY"),
            "tavily_api_key": resolve_env_var("TAVILY_API_KEY"),
            "google_cloud_project": resolve_env_var("GOOGLE_CLOUD_PROJECT"),
            "project_root": project_root,
            "shell_allow_list": shell_allow_list,
            "extra_skills_dirs": _parse_extra_skills_dirs(
                os.environ.get(EXTRA_SKILLS_DIRS),
                _read_config_yaml_skills_dirs(),
            ),
        }

        for field, value in refreshed.items():
            setattr(self, field, value)

        def _display(field: str, value: object) -> str:
            if field in api_key_fields:
                return "set" if value else "unset"
            return str(value)

        changes: list[str] = []
        for field in reloadable_fields:
            old_value = previous[field]
            new_value = refreshed[field]
            if old_value != new_value:
                changes.append(
                    f"{field}: {_display(field, old_value)} -> {_display(field, new_value)}"
                )
        return changes

    @property
    def has_openai(self) -> bool:
        """Check if OpenAI API key is configured."""
        return self.openai_api_key is not None

    @property
    def has_anthropic(self) -> bool:
        """Check if Anthropic API key is configured."""
        return self.anthropic_api_key is not None

    @property
    def has_google(self) -> bool:
        """Check if Google API key is configured."""
        return self.google_api_key is not None

    @property
    def has_nvidia(self) -> bool:
        """Check if NVIDIA API key is configured."""
        return self.nvidia_api_key is not None

    @property
    def has_vertex_ai(self) -> bool:
        """Check if VertexAI is available (Google Cloud project set, no API key).

        VertexAI uses Application Default Credentials (ADC) for authentication,
        so if GOOGLE_CLOUD_PROJECT is set and GOOGLE_API_KEY is not, we assume
        VertexAI.
        """
        return self.google_cloud_project is not None and self.google_api_key is None

    @staticmethod
    def _is_valid_agent_name(agent_name: str) -> bool:
        """Validate to prevent invalid filesystem paths and security issues.

        Returns:
            True if the agent name is valid, False otherwise.
        """
        if not agent_name or not agent_name.strip():
            return False
        # Allow only alphanumeric, hyphens, underscores, and whitespace
        return bool(re.match(r"^[a-zA-Z0-9_\-\s]+$", agent_name))

    def get_agent_dir(self, agent_name: str) -> Path:
        """Get the global agent directory path.

        Args:
            agent_name: Name of the agent

        Returns:
            Path to ~/SOOTHE_HOME/{agent_name}

        Raises:
            ValueError: If the agent name contains invalid characters.
        """
        if not self._is_valid_agent_name(agent_name):
            msg = (
                f"Invalid agent name: {agent_name!r}. Agent names can only "
                "contain letters, numbers, hyphens, underscores, and spaces."
            )
            raise ValueError(msg)
        return Path(SOOTHE_HOME) / agent_name


RECOMMENDED_SAFE_SHELL_COMMANDS = (
    # Directory listing
    "ls",
    "dir",
    # File content viewing (read-only)
    "cat",
    "head",
    "tail",
    # Text searching (read-only)
    "grep",
    "wc",
    "strings",
    # Text processing (read-only, no shell execution)
    "cut",
    "tr",
    "diff",
    "md5sum",
    "sha256sum",
    # Path utilities
    "pwd",
    "which",
    # System info (read-only)
    "uname",
    "hostname",
    "whoami",
    "id",
    "groups",
    "uptime",
    "nproc",
    "lscpu",
    "lsmem",
    # Process viewing (read-only)
    "ps",
)
"""Read-only commands auto-approved in non-interactive mode.

Only includes readers and formatters — shells, editors, interpreters, package
managers, network tools, archivers, and anything on GTFOBins/LOOBins is
intentionally excluded.
"""


def detect_provider(model_name: str) -> str | None:
    """Auto-detect provider from model name.

    Intentionally duplicates a subset of LangChain's
    `_attempt_infer_model_provider` because we need to resolve the provider
    **before** calling `init_chat_model` in order to:

    1. Build provider-specific kwargs (API base URLs, headers, etc.) that are
       passed *into* `init_chat_model`.
    2. Validate credentials early to surface user-friendly errors.

    Args:
        model_name: Model name to detect provider from.

    Returns:
        Provider name (openai, anthropic, google_genai, google_vertexai,
            nvidia) or `None` if the provider cannot be determined from the
            name alone.
    """
    model_lower = model_name.lower()

    if model_lower.startswith(("gpt-", "o1", "o3", "o4", "chatgpt")):
        return "openai"

    if model_lower.startswith("claude"):
        s = _get_settings()
        if not s.has_anthropic and s.has_vertex_ai:
            return "google_vertexai"
        return "anthropic"

    if model_lower.startswith("gemini"):
        s = _get_settings()
        if s.has_vertex_ai and not s.has_google:
            return "google_vertexai"
        return "google_genai"

    if model_lower.startswith(("nemotron", "nvidia/")):
        return "nvidia"

    return None


def _get_console() -> Console:
    """Return the lazily-initialized global `Console` instance.

    Defers the `rich.console` import until console output is actually
    needed. The result is cached in `globals()["console"]`.

    Returns:
        The global Rich `Console` singleton.
    """
    cached = globals().get("console")
    if cached is not None:
        return cached
    with _singleton_lock:
        cached = globals().get("console")
        if cached is not None:
            return cached
        from rich.console import Console

        inst = Console(highlight=False)
        globals()["console"] = inst
        return inst


def _get_settings() -> Settings:
    """Return the lazily-initialized global `Settings` instance.

    Ensures bootstrap has run before constructing settings. The result is cached
    in `globals()["settings"]` so subsequent access — including
    `from config import settings` in other modules — resolves instantly.

    Returns:
        The global `Settings` singleton.
    """
    cached = globals().get("settings")
    if cached is not None:
        return cached
    with _singleton_lock:
        cached = globals().get("settings")
        if cached is not None:
            return cached
        _ensure_bootstrap()
        try:
            inst = Settings.from_environment(start_path=_bootstrap_start_path)
        except Exception:
            logger.exception(
                "Failed to initialize settings from environment (start_path=%s)",
                _bootstrap_start_path,
            )
            raise
        globals()["settings"] = inst
        return inst


def __getattr__(name: str) -> Settings | Console:
    """Lazy module attributes for `settings` and `console`.

    Defers heavy initialization until first access. Subsequent accesses hit
    the module-level attribute directly (no `__getattr__` overhead).

    Returns:
        The requested lazy singleton.

    Raises:
        AttributeError: If *name* is not a lazily-provided attribute.
    """
    if name == "settings":
        return _get_settings()
    if name == "console":
        return _get_console()
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
