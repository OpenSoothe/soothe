"""Lazy bootstrap: dotenv loading and start-path detection."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from soothe_sdk.paths import SOOTHE_HOME

logger = logging.getLogger(__name__)

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
    shell env (incl. inline `VAR=x`) > project `.env` > global `.env`
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
            from soothe_cli.project_utils import (
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
