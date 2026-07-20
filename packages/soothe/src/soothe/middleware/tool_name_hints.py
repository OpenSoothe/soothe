"""Shim (IG-668): alias ``middleware/tool_name_hints`` to ``soothe_nano.middleware.tool_name_hints``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware.tool_name_hints")
sys.modules[__name__] = _nano
