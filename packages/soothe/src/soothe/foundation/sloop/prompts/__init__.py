"""Compatibility shim — host prompts live in ``soothe.prompts``.

Import from ``soothe.prompts`` (or submodules) in new code.
"""

from __future__ import annotations

from typing import Any

from soothe.prompts import *  # noqa: F403
from soothe.prompts import __all__ as __all__  # noqa: F401


def __getattr__(name: str) -> Any:
    """Lazy-load submodule attributes for ``from soothe.foundation.sloop.prompts.X``."""
    import importlib

    if name.startswith("_"):
        raise AttributeError(name)
    try:
        return importlib.import_module(f"soothe.prompts.{name}")
    except ModuleNotFoundError as exc:
        raise AttributeError(name) from exc
