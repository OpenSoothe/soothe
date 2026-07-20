"""Shim (IG-668): alias ``middleware/tool_enforcement`` to ``soothe_nano.middleware.tool_enforcement``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware.tool_enforcement")
sys.modules[__name__] = _nano
