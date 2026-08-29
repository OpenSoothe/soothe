"""Theme preference persistence: load and save the Textual theme name."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from soothe_cli.display import theme

logger = logging.getLogger(__name__)


def _load_theme_preference() -> str:
    """Load the saved theme name from config, or return the default.

    Returns:
    A Textual theme name (e.g., `'langchain'`, `'langchain-light'`).
    """
    import yaml

    try:
        from soothe_cli.model_config import resolve_cli_config_path

        config_path = resolve_cli_config_path()
        if not config_path.exists():
            return theme.DEFAULT_THEME

        with config_path.open("rb") as f:
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
    """Persist theme preference to `~/SOOTHE_HOME/config/cli.yml`.

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

        from soothe_cli.model_config import resolve_cli_config_path

        config_path = resolve_cli_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if config_path.exists():
            with config_path.open("r") as f:
                data = yaml.safe_load(f)
        else:
            data = {}

        if "ui" not in data:
            data["ui"] = {}
        data["ui"]["theme"] = name

        fd, tmp_path = tempfile.mkstemp(dir=config_path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                yaml.safe_dump(data, f)
            Path(tmp_path).replace(config_path)
        except BaseException:
            with contextlib.suppress(OSError):
                Path(tmp_path).unlink()
            raise
    except Exception:
        logger.exception("Could not save theme preference")
        return False
    return True
