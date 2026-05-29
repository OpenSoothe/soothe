"""Channel discovery registry (RFC-620 §7).

Provides plugin discovery for channels via:
1. pkgutil scan of built-in channels in soothe_daemon.channels package
2. Python entry_points for external plugins ("soothe.channels" group)

Only enabled channels are imported, reducing startup overhead.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe_daemon.channels.base import Channel

logger = logging.getLogger(__name__)


def discover_channel_names() -> list[str]:
    """Scan channels/ directory via pkgutil for available module names.

    This is a cheap operation (no imports) that lists candidate channel
    modules. Used to identify config sections that might be channel configs.

    Returns:
        List of channel module names (excluding base, message, events, registry).
    """
    try:
        from soothe_daemon.channels import __path__
    except ImportError:
        return []

    names = []
    for info in pkgutil.iter_modules(__path__):
        # Skip infrastructure modules
        if info.name in ("base", "message", "events", "registry", "__init__"):
            continue
        names.append(info.name)

    return sorted(names)


def load_channel_class(name: str) -> type[Channel] | None:
    """Import and return Channel class by module name.

    Args:
        name: Channel module name (e.g., "websocket", "telegram").

    Returns:
        Channel subclass, or None if not found or not a valid Channel.
    """
    try:
        module = importlib.import_module(f"soothe_daemon.channels.{name}")
    except ImportError as e:
        logger.debug("Could not import channel module %s: %s", name, e)
        return None

    # Find Channel subclass in module
    for attr_name in dir(module):
        if attr_name.startswith("_"):
            continue
        attr = getattr(module, attr_name)
        if isinstance(attr, type):
            # Import Channel base here to avoid circular import
            from soothe_daemon.channels.base import Channel
            if issubclass(attr, Channel) and attr is not Channel:
                return attr

    logger.warning("No Channel subclass found in module %s", name)
    return None


def discover_plugins(enabled_names: set[str]) -> dict[str, type[Channel]]:
    """Load external channels via Python entry_points.

    Entry points are registered in pyproject.toml:
    ```toml
    [project.entry-points."soothe.channels"]
    telegram = "soothe_telegram:TelegramChannel"
    ```

    Args:
        enabled_names: Set of channel names to load.

    Returns:
        Dict mapping channel name to Channel class.
    """
    channels: dict[str, type[Channel]] = {}

    try:
        # Python 3.10+ uses importlib.metadata
        from importlib.metadata import entry_points

        eps = entry_points(group="soothe.channels")
    except Exception as e:
        logger.debug("Could not load entry_points: %s", e)
        return channels

    from soothe_daemon.channels.base import Channel

    for ep in eps:
        if ep.name not in enabled_names:
            continue
        try:
            cls = ep.load()
        except Exception as e:
            logger.warning("Could not load entry_point %s: %s", ep.name, e)
            continue

        if isinstance(cls, type) and issubclass(cls, Channel):
            channels[ep.name] = cls
            logger.info("Loaded plugin channel: %s", ep.name)
        else:
            logger.warning(
                "Entry point %s loaded %s, not a Channel subclass",
                ep.name,
                cls,
            )

    return channels


def discover_enabled(enabled_names: set[str]) -> dict[str, type[Channel]]:
    """Return {name: ChannelClass} for all enabled channels.

    Combines built-in channels (pkgutil scan) with external plugins
    (entry_points). Only imports enabled channels.

    Args:
        enabled_names: Set of channel names that are enabled in config.

    Returns:
        Dict mapping channel name to Channel class.
    """
    channels: dict[str, type[Channel]] = {}

    # Load built-in channels
    for name in enabled_names:
        cls = load_channel_class(name)
        if cls:
            channels[name] = cls

    # Load plugin channels (may override built-in if same name)
    plugins = discover_plugins(enabled_names)
    channels.update(plugins)

    return channels


def discover_all() -> dict[str, type[Channel]]:
    """Return all available channels (built-in + plugins).

    Imports ALL discovered channels, which may be slow. Prefer
    discover_enabled() when you have a specific set to load.

    Returns:
        Dict mapping channel name to Channel class.
    """
    # Get all candidate names
    built_in_names = set(discover_channel_names())

    # Get plugin names from entry_points
    plugin_names: set[str] = set()
    try:
        from importlib.metadata import entry_points
        eps = entry_points(group="soothe.channels")
        plugin_names = {ep.name for ep in eps}
    except Exception:
        pass

    all_names = built_in_names | plugin_names
    return discover_enabled(all_names)


__all__ = [
    "discover_all",
    "discover_channel_names",
    "discover_enabled",
    "discover_plugins",
    "load_channel_class",
]
