"""Shim (IG-668): alias ``middleware/progressive_listing`` to ``soothe_nano.middleware.progressive_listing``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware.progressive_listing")
sys.modules[__name__] = _nano
