"""Sloop package — StrangeLoop single-goal orchestration."""

from __future__ import annotations

from typing import Any

__all__ = [
    "Sloop",
    "StrangeLoop",
]


def __getattr__(name: str) -> Any:
    """Lazy import root public symbols."""
    if name in ("StrangeLoop", "Sloop"):
        from soothe.sloop.strange_loop import StrangeLoop

        return StrangeLoop

    error_msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(error_msg)
