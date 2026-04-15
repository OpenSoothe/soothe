"""Configuration templates for Soothe package distribution."""

from importlib.resources import files
from pathlib import Path


def get_config_template_path() -> Path | None:
    """Get path to the default config.yml template.

    Uses importlib.resources to find the template whether installed
    from wheel or running from source.

    Returns:
        Path to config.yml template, or None if not found.
    """
    try:
        config_package = files("soothe.config")

        # Handle MultiplexedPath (e.g., when in editable install)
        if hasattr(config_package, "_paths"):
            template_path = Path(str(config_package._paths[0])) / "config.yml"
        else:
            template_path = Path(str(config_package)) / "config.yml"

        if template_path.exists():
            return template_path

    except (TypeError, AttributeError, FileNotFoundError):
        pass

    return None


__all__ = ["get_config_template_path"]
