"""Lazy global Rich Console singleton."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe_cli.settings.bootstrap import _singleton_lock

if TYPE_CHECKING:
    from rich.console import Console

logger = logging.getLogger(__name__)


def _get_console() -> Console:
    """Return the lazily-initialized global `Console` instance.

    Defers the `rich.console` import until console output is actually
    needed. The result is cached in `globals()["console"]`.

    Returns:
        The global Rich `Console` singleton.
    """
    cached = globals().get("console")
    if cached is not None:
        return cached
    with _singleton_lock:
        cached = globals().get("console")
        if cached is not None:
            return cached
        from rich.console import Console

        inst = Console(highlight=False)
        globals()["console"] = inst
        return inst
