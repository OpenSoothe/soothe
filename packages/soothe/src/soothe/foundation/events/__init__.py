"""Shim (IG-668): re-export ``soothe_nano.events``."""

from __future__ import annotations

import soothe_nano.events as _nano_events
from soothe_nano.events import *  # noqa: F403

try:
    from soothe_nano.events import __all__ as __all__  # type: ignore[attr-defined]
except ImportError:
    pass


def __getattr__(name: str):
    return getattr(_nano_events, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_nano_events)))
