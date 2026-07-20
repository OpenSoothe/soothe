"""Shim (IG-668): alias ``middleware/progressive_tools`` to ``soothe_nano.middleware.progressive_tools``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware.progressive_tools")
sys.modules[__name__] = _nano
