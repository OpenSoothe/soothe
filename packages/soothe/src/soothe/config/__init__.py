"""Shim (IG-668): re-export ``soothe_nano.config`` under ``soothe.config``."""

from soothe_nano.config import *  # noqa: F403
from soothe_nano.config import __all__ as __all__
