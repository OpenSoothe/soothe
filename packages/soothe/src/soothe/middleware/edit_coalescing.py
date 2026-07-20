"""Shim (IG-668): alias ``middleware/edit_coalescing`` to ``soothe_nano.middleware.edit_coalescing``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware.edit_coalescing")
sys.modules[__name__] = _nano
