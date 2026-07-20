"""Shim (IG-668): alias ``middleware/filesystem`` to ``soothe_nano.middleware.filesystem``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware.filesystem")
sys.modules[__name__] = _nano
