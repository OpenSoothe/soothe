"""Plugin instance caching for improved performance.

Provides caching of loaded plugin instances to avoid redundant loading
and improve agent creation time.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

_plugin_cache: dict[str, Any] = {}


def get_cached_plugin(name: str) -> Any | None:
    """Get cached plugin instance.

    Args:
        name: Plugin name.

    Returns:
        Cached plugin instance or None if not cached.
    """
    return _plugin_cache.get(name)


def cache_plugin(name: str, instance: Any) -> None:
    """Cache a plugin instance.

    Args:
        name: Plugin name.
        instance: Plugin instance to cache.
    """
    _plugin_cache[name] = instance
    logger.debug("Cached plugin '%s'", name)


def clear_plugin_cache() -> None:
    """Clear all cached plugins."""
    global _plugin_cache
    _plugin_cache = {}
    logger.debug("Cleared plugin cache")
