"""Lazy-loading plugin proxy.

This module provides the LazyPlugin class that defers plugin instantiation
until first attribute access, improving startup performance.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class LazyPlugin:
    """Lazy-loading plugin proxy.

    Defers plugin instantiation until first attribute access.
    This improves startup performance by not loading plugins that
    may never be used during a session.

    Attributes:
        _name: Plugin name for logging.
        _loader: Callable that creates plugin instance.
        _instance: Cached plugin instance (None until loaded).
    """

    def __init__(self, name: str, loader: Callable[[], Any]) -> None:
        """Initialize lazy plugin.

        Args:
            name: Plugin name for logging.
            loader: Callable that creates plugin instance.
        """
        self._name = name
        self._loader = loader
        self._instance: Any | None = None

    def __getattr__(self, attr: str) -> Any:
        """Load plugin on first attribute access.

        Args:
            attr: Attribute name.

        Returns:
            Attribute from loaded plugin instance.
        """
        if self._instance is None:
            logger.info("Lazy-loading plugin '%s'", self._name)
            self._instance = self._loader()
        return getattr(self._instance, attr)

    def is_loaded(self) -> bool:
        """Check if plugin has been loaded.

        Returns:
            True if plugin instance exists, False otherwise.
        """
        return self._instance is not None

    def get_instance(self) -> Any | None:
        """Get the underlying plugin instance without triggering load.

        Returns:
            Plugin instance if loaded, None otherwise.
        """
        return self._instance


__all__ = ["LazyPlugin"]
