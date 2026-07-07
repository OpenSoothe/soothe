"""Configuration, constants, and model creation for the CLI."""

from __future__ import annotations

import importlib
import json
import logging
import os
import re
import sys
import threading
from dataclasses import dataclass
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

from soothe_sdk.client.config import SOOTHE_HOME

from soothe_cli.tui._version import __version__

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
    from langchain_core.language_models import BaseChatModel
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
    """Always use Unicode glyphs (e.g. `⏺`, `✓`, `…`)."""

    ASCII = "ascii"
    """Always use ASCII-safe fallbacks (e.g. `(*)`, `[OK]`, `...`)."""

    AUTO = "auto"
    """Detect charset support at runtime and pick Unicode or ASCII."""


@dataclass(frozen=True)
class Glyphs:
    """Character glyphs for TUI display."""

    tool_prefix: str  # ⏺ vs (*)
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
    tool_prefix="⏺",
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
    user="👤",  # User/human icon
    assistant="🤖",  # AI/assistant icon
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
    tool_prefix="(*)",
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

_editable_cache: tuple[bool, str | None] | None = None
"""Module-level cache for editable install info: (is_editable, source_path)."""


def _resolve_editable_info() -> tuple[bool, str | None]:
    """Parse PEP 610 `direct_url.json` once and cache both results.

    Returns:
        Tuple of (is_editable, contracted_source_path). The path is
        `~`-contracted when it falls under the user's home directory, or
        `None` when the install is non-editable or the path is unavailable.
    """
    global _editable_cache  # noqa: PLW0603  # Module-level cache requires global statement
    if _editable_cache is not None:
        return _editable_cache

    editable = False
    path: str | None = None

    try:
        dist = distribution("Soothe")
        raw = dist.read_text("direct_url.json")
        if raw:
            data = json.loads(raw)
            editable = data.get("dir_info", {}).get("editable", False)
            if editable:
                url = data.get("url", "")
                if url.startswith("file://"):
                    path = unquote(urlparse(url).path)
                    home = str(Path.home())
                    if path.startswith(home):
                        path = "~" + path[len(home) :]
    except (PackageNotFoundError, FileNotFoundError, json.JSONDecodeError, TypeError):
        logger.debug(
            "Failed to read editable install info from PEP 610 metadata",
            exc_info=True,
        )

    _editable_cache = (editable, path)
    return _editable_cache


def _is_editable_install() -> bool:
    """Check if Soothe is installed in editable mode.

    Uses PEP 610 `direct_url.json` metadata to detect editable installs.

    Returns:
        `True` if installed in editable mode, `False` otherwise.
    """
    return _resolve_editable_info()[0]


def _get_editable_install_path() -> str | None:
    """Return the `~`-contracted source directory for an editable install.

    Returns `None` for non-editable installs or when the path cannot be
    determined.
    """
    return _resolve_editable_info()[1]


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


def reset_glyphs_cache() -> None:
    """Reset the glyphs cache (for testing)."""
    global _glyphs_cache  # noqa: PLW0603  # Module-level cache requires global statement
    _glyphs_cache = None


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

    Injects CLI and SDK versions into `metadata["versions"]` so runs can be
    correlated with specific releases.

    Why the CLI sets *both* versions:

    * `create_deep_agent` bakes `versions: {"Soothe": "X.Y.Z"}` into the
        compiled graph via `with_config`. At stream time, LangGraph merges
        the graph config with the runtime config passed here. Because the
        metadata merge is shallow (effectively `{**graph_meta, **runtime_meta}`
        for top-level keys), both configs containing a `versions` key means
        the runtime dict **replaces** the graph dict entirely — the SDK
        version would be lost.
    * Including the SDK version here ensures it survives the merge.

    Args:
        loop_id: Active StrangeLoop id (stored under LangGraph ``configurable.thread_id``).
        assistant_id: The agent/assistant identifier, if any.
        sandbox_type: Sandbox provider name for trace metadata, or `None` if no
            sandbox is active.
        workspace: Workspace directory for in-process TUI runs. When
            omitted, uses `Path.cwd()` (resolved). Mirrored to
            `configurable["workspace"]` for middleware and task-tool propagation
            (IG-341, RFC-103).

    Returns:
        Config dict with `configurable` and `metadata` keys.
    """
    import contextlib
    import importlib.metadata as importlib_metadata
    from datetime import UTC, datetime

    try:
        cwd = str(Path.cwd())
    except OSError:
        logger.warning("Could not determine working directory", exc_info=True)
        cwd = ""

    # Include SDK version alongside CLI version — see docstring for why.
    versions: dict[str, str] = {"Soothe": __version__}
    with contextlib.suppress(importlib_metadata.PackageNotFoundError):
        versions["Soothe"] = importlib_metadata.version("Soothe")

    metadata: dict[str, Any] = {
        "versions": versions,
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
    """Read `[skills].extra_allowed_dirs` from `SOOTHE_HOME/config/config.yml`.

    Returns:
        List of path strings, or `None` if the key is absent or the file
            cannot be read.
    """
    import yaml

    from soothe_cli.tui.model_config import DEFAULT_CONFIG_PATH

    try:
        with DEFAULT_CONFIG_PATH.open("r") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        return None
    except (PermissionError, OSError, yaml.YAMLError):
        logger.warning(
            "Could not read skills config from %s",
            DEFAULT_CONFIG_PATH,
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
    """Merge extra skill directories from env var and config.yml.

    Extra skills directories extend the containment allowlist used by
    `load_skill_content` to validate that a resolved skill path lives inside a
    trusted root. They do **not** add new skill discovery locations — skills are
    still discovered only from the standard directories. This exists so that
    symlinks inside standard skill directories can legitimately point to targets
    in user-specified locations without being rejected by the path
    containment check.

    The env var (`SOOTHE_EXTRA_SKILLS_DIRS`, colon-separated) takes
    precedence: when set, `config.yml` values are ignored.

    Args:
        env_raw: Value of `SOOTHE_EXTRA_SKILLS_DIRS` (colon-separated), or
            `None` if unset.
        config_yaml_dirs: List of path strings from
            `[skills].extra_allowed_dirs` in `SOOTHE_HOME/config/config.yml`.

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

    model_unsupported_modalities: frozenset[str] = frozenset()
    """Input modalities not indicated as supported by the model profile."""

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
    `[skills].extra_allowed_dirs` in `SOOTHE_HOME/config/config.yml`.
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

        # Parse extra skill containment roots from env var or config.yml.
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

    @property
    def has_tavily(self) -> bool:
        """Check if Tavily API key is configured."""
        return self.tavily_api_key is not None

    @property
    def user_soothe_dir(self) -> Path:
        """Get the base user-level Soothe directory (SOOTHE_HOME).

        Returns:
            Path to SOOTHE_HOME
        """
        return Path(SOOTHE_HOME)

    @staticmethod
    def get_user_agent_md_path(agent_name: str) -> Path:
        """Get user-level AGENTS.md path for a specific agent.

        Returns path regardless of whether the file exists.

        Args:
            agent_name: Name of the agent

        Returns:
            Path to ~/SOOTHE_HOME/{agent_name}/AGENTS.md
        """
        return Path(SOOTHE_HOME) / agent_name / "AGENTS.md"

    def get_project_agent_md_path(self) -> list[Path]:
        """Get project-level AGENTS.md paths.

        Checks both `{project_root}/.soothe/AGENTS.md` and
        `{project_root}/AGENTS.md`, returning all that exist. If both are
        present, both are loaded and their instructions are combined, with
        `.soothe/AGENTS.md` first.

        Returns:
            Existing AGENTS.md paths.

                Empty if neither file exists or not in a project, one entry if
                only one is present, or two entries if both locations have the
                file.
        """
        if not self.project_root:
            return []
        from soothe_cli.tui.project_utils import find_project_agent_md

        return find_project_agent_md(self.project_root)

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

    def ensure_agent_dir(self, agent_name: str) -> Path:
        """Ensure the global agent directory exists and return its path.

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
        agent_dir = self.get_agent_dir(agent_name)
        agent_dir.mkdir(parents=True, exist_ok=True)
        return agent_dir

    def get_user_skills_dir(self, agent_name: str) -> Path:
        """Get user-level skills directory path for a specific agent.

        Args:
            agent_name: Name of the agent

        Returns:
            Path to ~/SOOTHE_HOME/{agent_name}/skills/
        """
        return self.get_agent_dir(agent_name) / "skills"

    def ensure_user_skills_dir(self, agent_name: str) -> Path:
        """Ensure user-level skills directory exists and return its path.

        Args:
            agent_name: Name of the agent

        Returns:
            Path to ~/SOOTHE_HOME/{agent_name}/skills/
        """
        skills_dir = self.get_user_skills_dir(agent_name)
        skills_dir.mkdir(parents=True, exist_ok=True)
        return skills_dir

    def get_project_skills_dir(self) -> Path | None:
        """Get project-level skills directory path.

        Returns:
            Path to {project_root}/.soothe/skills/, or None if not in a project
        """
        if not self.project_root:
            return None
        return self.project_root / ".soothe" / "skills"

    def ensure_project_skills_dir(self) -> Path | None:
        """Ensure project-level skills directory exists and return its path.

        Returns:
            Path to {project_root}/.soothe/skills/, or None if not in a project
        """
        if not self.project_root:
            return None
        skills_dir = self.get_project_skills_dir()
        if skills_dir is None:
            return None
        skills_dir.mkdir(parents=True, exist_ok=True)
        return skills_dir

    def get_user_agents_dir(self, agent_name: str) -> Path:
        """Get user-level agents directory path for custom subagent definitions.

        Args:
            agent_name: Name of the CLI agent (e.g., "Soothe")

        Returns:
            Path to ~/SOOTHE_HOME/{agent_name}/agents/
        """
        return self.get_agent_dir(agent_name) / "agents"

    def get_project_agents_dir(self) -> Path | None:
        """Get project-level agents directory path for custom subagent definitions.

        Returns:
            Path to {project_root}/.soothe/agents/, or None if not in a project
        """
        if not self.project_root:
            return None
        return self.project_root / ".soothe" / "agents"

    @property
    def user_agents_dir(self) -> Path:
        """Get the base user-level `.agents` directory (`~/.agents`).

        Returns:
            Path to `~/.agents`
        """
        return Path.home() / ".agents"

    def get_user_agent_skills_dir(self) -> Path:
        """Get user-level `~/.agents/skills/` directory.

        This is a generic alias path for skills that is tool-agnostic.

        Returns:
            Path to `~/.agents/skills/`
        """
        return self.user_agents_dir / "skills"

    def get_project_agent_skills_dir(self) -> Path | None:
        """Get project-level `.agents/skills/` directory.

        This is a generic alias path for skills that is tool-agnostic.

        Returns:
            Path to `{project_root}/.agents/skills/`, or `None` if not in a project
        """
        if not self.project_root:
            return None
        return self.project_root / ".agents" / "skills"


class SessionState:
    """Mutable session state shared across the app, adapter, and agent."""

    def __init__(self, no_splash: bool = False) -> None:
        """Initialize session state with optional flags.

        Args:
            no_splash: Whether to skip displaying the splash screen on startup.
        """
        self.no_splash = no_splash
        self.exit_hint_until: float | None = None
        self.exit_hint_handle = None
        from soothe_cli.tui.sessions import generate_loop_id

        self.loop_id = generate_loop_id()


DANGEROUS_SHELL_PATTERNS = (
    "$(",  # Command substitution
    "`",  # Backtick command substitution
    "$'",  # ANSI-C quoting (can encode dangerous chars via escape sequences)
    "\n",  # Newline (command injection)
    "\r",  # Carriage return (command injection)
    "\t",  # Tab (can be used for injection in some shells)
    "<(",  # Process substitution (input)
    ">(",  # Process substitution (output)
    "<<<",  # Here-string
    "<<",  # Here-doc (can embed commands)
    ">>",  # Append redirect
    ">",  # Output redirect
    "<",  # Input redirect
    "${",  # Variable expansion with braces (can run commands via ${var:-$(cmd)})
)
"""Literal substrings that indicate shell injection risk.

Used by `contains_dangerous_patterns` to reject commands that embed arbitrary
execution via redirects, substitution operators, or control characters — even
when the base command is on the allow-list.
"""

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
intentionally excluded. File-write and injection vectors are blocked separately
by `DANGEROUS_SHELL_PATTERNS`.
"""


def contains_dangerous_patterns(command: str) -> bool:
    """Check if a command contains dangerous shell patterns.

    These patterns can be used to bypass allow-list validation by embedding
    arbitrary commands within seemingly safe commands. The check includes
    both literal substring patterns (redirects, substitution operators, etc.)
    and regex patterns for bare variable expansion (`$VAR`) and the background
    operator (`&`).

    Args:
        command: The shell command to check.

    Returns:
        True if dangerous patterns are found, False otherwise.
    """
    if any(pattern in command for pattern in DANGEROUS_SHELL_PATTERNS):
        return True

    # Bare variable expansion ($VAR without braces) can leak sensitive paths.
    # We already block ${ and $( above; this catches plain $HOME, $IFS, etc.
    if re.search(r"\$[A-Za-z_]", command):
        return True

    # Standalone & (background execution) changes the execution model and
    # should not be allowed.  We check for & that is NOT part of &&.
    return bool(re.search(r"(?<![&])&(?![&])", command))


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


def _get_default_model_spec() -> str:
    """Get default model specification based on available credentials.

    Checks in order:

    1. `[models].default` in config file (user's intentional preference).
    2. `[models].recent` in config file (last `/model` switch).
    3. Auto-detection based on available API credentials.

    Returns:
        Model specification in provider:model format.

    Raises:
        ModelConfigError: If no credentials are configured.
    """
    from soothe_cli.tui.model_config import ModelConfig, ModelConfigError

    config = ModelConfig.load()
    if config.default_model:
        return config.default_model

    if config.recent_model:
        return config.recent_model

    s = _get_settings()
    if s.has_openai:
        return "openai:gpt-5.2"
    if s.has_anthropic:
        return "anthropic:claude-sonnet-4-6"
    if s.has_google:
        return "google_genai:gemini-3.1-pro-preview"
    if s.has_vertex_ai:
        return "google_vertexai:gemini-3.1-pro-preview"
    if s.has_nvidia:
        return "nvidia:nvidia/nemotron-3-super-120b-a12b"

    msg = (
        "No credentials configured. Please set one of: "
        "ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, "
        "GOOGLE_CLOUD_PROJECT, or NVIDIA_API_KEY"
    )
    raise ModelConfigError(msg)


_OPENROUTER_APP_URL = "https://pypi.org/project/Soothe/"
"""Default `app_url` (maps to `HTTP-Referer`) for OpenRouter attribution.

See https://openrouter.ai/docs/app-attribution for details.
"""

_OPENROUTER_APP_TITLE = "Deep Agents CLI"
"""Default `app_title` (maps to `X-Title`) for OpenRouter attribution."""

_OPENROUTER_APP_CATEGORIES: list[str] = ["cli-agent"]
"""Default `app_categories` (maps to `X-OpenRouter-Categories`) for OpenRouter."""


def _apply_openrouter_defaults(kwargs: dict[str, Any]) -> None:
    """Inject default OpenRouter attribution kwargs.

    Sets `app_url`, `app_title`, and `app_categories` via `setdefault` so
    that user-supplied values in config take precedence. These map to the
    `HTTP-Referer`, `X-Title`, and `X-OpenRouter-Categories` headers that
    `ChatOpenRouter` sends for app attribution
    (see https://openrouter.ai/docs/app-attribution).

    Users can override either value provider-wide or per-model in
    `SOOTHE_HOME/config/config.yml`:

    ```yaml
    # Provider-wide
    [models.providers.openrouter.params]
    app_url = "https://myapp.com"
    app_title = "My App"

    # Per-model (shallow-merges on top of provider-wide)
    [models.providers.openrouter.params."openai/gpt-oss-120b"]
    app_title = "My App (GPT)"
    ```

    Args:
        kwargs: Mutable kwargs dict to update in place.
    """
    kwargs.setdefault("app_url", _OPENROUTER_APP_URL)
    kwargs.setdefault("app_title", _OPENROUTER_APP_TITLE)
    kwargs.setdefault("app_categories", _OPENROUTER_APP_CATEGORIES)


def _get_provider_kwargs(provider: str, *, model_name: str | None = None) -> dict[str, Any]:
    """Get provider-specific kwargs from the config file.

    Reads `base_url`, `api_key_env`, and the `params` table from the user's
    `config.yml` for the given provider.

    When `model_name` is provided, per-model overrides from the `params`
    sub-table are shallow-merged on top.

    Args:
        provider: Provider name (e.g., openai, anthropic, fireworks, ollama).
        model_name: Optional model name for per-model overrides.

    Returns:
        Dictionary of provider-specific kwargs.
    """
    from soothe_cli.tui.model_config import ModelConfig

    config = ModelConfig.load()
    result: dict[str, Any] = config.get_kwargs(provider, model_name=model_name)
    base_url = config.get_base_url(provider)
    if base_url:
        result["base_url"] = base_url
    from soothe_cli.tui.model_config import PROVIDER_API_KEY_ENV, resolve_env_var

    api_key_env = config.get_api_key_env(provider)
    if not api_key_env:
        api_key_env = PROVIDER_API_KEY_ENV.get(provider)
        if api_key_env:
            logger.debug(
                "No api_key_env in config.yml for '%s'; using hardcoded provider env var",
                provider,
            )
    if api_key_env:
        api_key = resolve_env_var(api_key_env)
        if api_key:
            result["api_key"] = api_key

    if provider == "openrouter":
        _apply_openrouter_defaults(result)

    return result


def _create_model_from_class(
    class_path: str,
    model_name: str,
    provider: str,
    kwargs: dict[str, Any],
) -> BaseChatModel:
    """Import and instantiate a custom `BaseChatModel` class.

    Args:
        class_path: Fully-qualified class in `module.path:ClassName` format.
        model_name: Model identifier to pass as `model` kwarg.
        provider: Provider name (for error messages).
        kwargs: Additional keyword arguments for the constructor.

    Returns:
        Instantiated `BaseChatModel`.

    Raises:
        ModelConfigError: If the class cannot be imported, is not a
            `BaseChatModel` subclass, or fails to instantiate.
    """
    from langchain_core.language_models import (
        BaseChatModel as _BaseChatModel,  # Runtime import; module level is typing only
    )

    from soothe_cli.tui.model_config import ModelConfigError

    if ":" not in class_path:
        msg = f"Invalid class_path '{class_path}' for provider '{provider}': must be in module.path:ClassName format"
        raise ModelConfigError(msg)

    module_path, class_name = class_path.rsplit(":", 1)

    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        msg = f"Could not import module '{module_path}' for provider '{provider}': {e}"
        raise ModelConfigError(msg) from e

    cls = getattr(module, class_name, None)
    if cls is None:
        msg = f"Class '{class_name}' not found in module '{module_path}' for provider '{provider}'"
        raise ModelConfigError(msg)

    if not (isinstance(cls, type) and issubclass(cls, _BaseChatModel)):
        msg = f"'{class_path}' is not a BaseChatModel subclass (got {type(cls).__name__})"
        raise ModelConfigError(msg)

    try:
        return cls(model=model_name, **kwargs)
    except Exception as e:
        msg = f"Failed to instantiate '{class_path}' for '{provider}:{model_name}': {e}"
        raise ModelConfigError(msg) from e


def _create_model_via_init(
    model_name: str,
    provider: str,
    kwargs: dict[str, Any],
) -> BaseChatModel:
    """Create a model using langchain's `init_chat_model`.

    Args:
        model_name: Model identifier.
        provider: Provider name (may be empty for auto-detection).
        kwargs: Additional keyword arguments.

    Returns:
        Instantiated `BaseChatModel`.

    Raises:
        ModelConfigError: On import, value, or runtime errors.
    """
    from langchain.chat_models import init_chat_model

    from soothe_cli.tui.model_config import ModelConfigError

    try:
        if provider:
            return init_chat_model(model_name, model_provider=provider, **kwargs)
        return init_chat_model(model_name, **kwargs)
    except ImportError as e:
        import importlib.util

        package_map = {
            "anthropic": "langchain-anthropic",
            "openai": "langchain-openai",
            "google_genai": "langchain-google-genai",
            "google_vertexai": "langchain-google-vertexai",
            "nvidia": "langchain-nvidia-ai-endpoints",
        }
        package = package_map.get(provider, f"langchain-{provider}")
        # Convert pip package name to Python module name for import check.
        module_name = package.replace("-", "_")
        try:
            spec_found = importlib.util.find_spec(module_name) is not None
        except (ImportError, ValueError):
            spec_found = False
        if spec_found:
            # Package is installed but an internal import failed — surface
            # the real error instead of the misleading "missing package" hint.
            msg = f"Provider package '{package}' is installed but failed to import for provider '{provider}': {e}"
        else:
            msg = f"Missing package for provider '{provider}'. Install: pip install {package}"
        raise ModelConfigError(msg) from e
    except (ValueError, TypeError) as e:
        spec = f"{provider}:{model_name}" if provider else model_name
        msg = f"Invalid model configuration for '{spec}': {e}"
        raise ModelConfigError(msg) from e
    except Exception as e:  # provider SDK auth/network errors
        spec = f"{provider}:{model_name}" if provider else model_name
        msg = f"Failed to initialize model '{spec}': {e}"
        raise ModelConfigError(msg) from e


@dataclass(frozen=True)
class ModelResult:
    """Result of creating a chat model, bundling the model with its metadata.

    This separates model creation from settings mutation so callers can decide
    when to commit the metadata to global settings.

    Attributes:
        model: The instantiated chat model.
        model_name: Resolved model name.
        provider: Resolved provider name.
        context_limit: Max input tokens from the model profile, or `None`.
        unsupported_modalities: Input modalities not indicated as supported by
            the model profile (e.g. `{"audio", "video"}`).
    """

    model: BaseChatModel
    model_name: str
    provider: str
    context_limit: int | None = None
    unsupported_modalities: frozenset[str] = frozenset()

    def apply_to_settings(self) -> None:
        """Commit this result's metadata to global `settings`."""
        s = _get_settings()
        s.model_name = self.model_name
        s.model_provider = self.provider
        s.model_context_limit = self.context_limit
        s.model_unsupported_modalities = self.unsupported_modalities


def _apply_profile_overrides(
    model: BaseChatModel,
    overrides: dict[str, Any],
    model_name: str,
    *,
    label: str,
    raise_on_failure: bool = False,
) -> None:
    """Merge `overrides` into `model.profile`.

    If the model already has a dict profile, overrides are layered on top
    so existing keys (e.g., `tool_calling`) are preserved unchanged.

    Args:
        model: The chat model whose profile will be updated.
        overrides: Key/value pairs to merge into the profile.
        model_name: Model name used in log/error messages.
        label: Human-readable source label for messages
            (e.g., `"config.yml"`, `"CLI --profile-override"`).
        raise_on_failure: When `True`, raise `ModelConfigError` instead
            of logging a warning if assignment fails.

    Raises:
        ModelConfigError: If `raise_on_failure` is `True` and the model
            rejects profile assignment.
    """
    from soothe_cli.tui.model_config import ModelConfigError

    logger.debug("Applying %s profile overrides: %s", label, overrides)
    profile = getattr(model, "profile", None)
    merged = {**profile, **overrides} if isinstance(profile, dict) else overrides
    try:
        model.profile = merged  # type: ignore[union-attr]
    except (AttributeError, TypeError, ValueError) as exc:
        if raise_on_failure:
            msg = f"Could not apply {label} to model '{model_name}': {exc}. The model may not support profile assignment."
            raise ModelConfigError(msg) from exc
        logger.warning(
            "Could not apply %s profile overrides to model '%s': %s. Overrides will be ignored.",
            label,
            model_name,
            exc,
        )


def create_model(
    model_spec: str | None = None,
    *,
    extra_kwargs: dict[str, Any] | None = None,
    profile_overrides: dict[str, Any] | None = None,
) -> ModelResult:
    """Create a chat model.

    Uses `init_chat_model` for standard providers, or imports a custom
    `BaseChatModel` subclass when the provider has a `class_path` in config.

    Supports `provider:model` format (e.g., `'anthropic:claude-sonnet-4-5'`)
    for explicit provider selection, or bare model names for auto-detection.

    Args:
        model_spec: Model specification in `provider:model` format (e.g.,
            `'anthropic:claude-sonnet-4-5'`, `'openai:gpt-4o'`) or just the model
            name for auto-detection (e.g., `'claude-sonnet-4-5'`).

                If not provided, uses environment-based defaults.
        extra_kwargs: Additional kwargs to pass to the model constructor.

            These take highest priority, overriding values from the config file.
        profile_overrides: Extra profile fields from `--profile-override`.

            Merged on top of config file profile overrides (CLI wins).

    Returns:
        A `ModelResult` containing the model and its metadata.

    Raises:
        ModelConfigError: If provider cannot be determined from the model name,
            required provider package is not installed, or no credentials are
            configured.

    Examples:
        >>> model = create_model("anthropic:claude-sonnet-4-5")
        >>> model = create_model("openai:gpt-4o")
        >>> model = create_model("gpt-4o")  # Auto-detects openai
        >>> model = create_model()  # Uses environment defaults
    """
    from soothe_cli.tui.model_config import (
        IMPLICIT_AUTH_PROVIDERS,
        ModelConfig,
        ModelConfigError,
        ModelSpec,
        get_credential_env_var,
        has_provider_credentials,
    )

    if not model_spec:
        model_spec = _get_default_model_spec()

    # Parse provider:model syntax
    provider: str
    model_name: str
    parsed = ModelSpec.try_parse(model_spec)
    if parsed:
        # Explicit provider:model (e.g., "anthropic:claude-sonnet-4-5")
        provider, model_name = parsed.provider, parsed.model
    elif ":" in model_spec:
        # Contains colon but ModelSpec rejected it (empty provider or model)
        _, _, after = model_spec.partition(":")
        if after:
            # Leading colon (e.g., ":claude-opus-4-6") — treat as bare model name
            model_name = after
            provider = detect_provider(model_name) or ""
        else:
            msg = (
                f"Invalid model spec '{model_spec}': model name is required "
                "(e.g., 'anthropic:claude-sonnet-4-5' or 'claude-sonnet-4-5')"
            )
            raise ModelConfigError(msg)
    else:
        # Bare model name — auto-detect provider or let init_chat_model infer
        model_name = model_spec
        provider = detect_provider(model_spec) or ""

    # Early credential check — fail fast with an actionable message instead of
    # letting the provider SDK raise an opaque auth error on first invocation.
    # Providers that support implicit auth (e.g., Vertex AI ADC) are excluded
    # because their env-var mapping is not a reliable indicator.
    if provider and provider not in IMPLICIT_AUTH_PROVIDERS:
        cred_status = has_provider_credentials(provider)
        if cred_status is False:
            env_var = get_credential_env_var(provider) or f"<{provider} API key>"
            msg = f"No credentials found for provider '{provider}'. Please set the {env_var} environment variable."
            raise ModelConfigError(msg)

    # Provider-specific kwargs (with per-model overrides)
    kwargs = _get_provider_kwargs(provider, model_name=model_name)

    # CLI --model-params take highest priority
    if extra_kwargs:
        kwargs.update(extra_kwargs)

    # Check if this provider uses a custom BaseChatModel class
    config = ModelConfig.load()
    class_path = config.get_class_path(provider) if provider else None

    if class_path:
        model = _create_model_from_class(class_path, model_name, provider, kwargs)
    else:
        model = _create_model_via_init(model_name, provider, kwargs)

    resolved_provider = provider or getattr(model, "_model_provider", provider)

    # Apply profile overrides from config.yml (e.g., max_input_tokens)
    if provider:
        config_profile_overrides = config.get_profile_overrides(provider, model_name=model_name)
        if config_profile_overrides:
            _apply_profile_overrides(
                model,
                config_profile_overrides,
                model_name,
                label=f"config.yml (provider '{provider}')",
            )

    # CLI --profile-override takes highest priority (on top of config.yml)
    if profile_overrides:
        _apply_profile_overrides(
            model,
            profile_overrides,
            model_name,
            label="CLI --profile-override",
            raise_on_failure=True,
        )

    # Extract context limit and modality support from model profile
    context_limit: int | None = None
    unsupported_modalities: frozenset[str] = frozenset()
    profile = getattr(model, "profile", None)
    if isinstance(profile, dict):
        if isinstance(profile.get("max_input_tokens"), int):
            context_limit = profile["max_input_tokens"]

        modality_keys = {
            "image_inputs": "image",
            "audio_inputs": "audio",
            "video_inputs": "video",
            "pdf_inputs": "pdf",
        }
        unsupported_modalities = frozenset(
            label for key, label in modality_keys.items() if profile.get(key) is False
        )

    return ModelResult(
        model=model,
        model_name=model_name,
        provider=resolved_provider,
        context_limit=context_limit,
        unsupported_modalities=unsupported_modalities,
    )


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
