"""Shim (IG-668): alias ``utils/tool_error_handler`` to ``soothe_nano.utils.tool_error_handler``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.tool_error_handler")
sys.modules[__name__] = _nano
