"""Shim (IG-668): package re-export for ``soothe_nano.backends.memory.memu.config.profile``."""

from __future__ import annotations

import soothe_nano.backends.memory.memu.config.profile as _mod
from soothe_nano.backends.memory.memu.config.profile import *  # noqa: F403

try:
    from soothe_nano.backends.memory.memu.config.profile import (
        __all__ as __all__,  # type: ignore[attr-defined]
    )
except ImportError:
    __all__ = [n for n in dir(_mod) if not n.startswith("_")]


def __getattr__(name: str):
    return getattr(_mod, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_mod)))
