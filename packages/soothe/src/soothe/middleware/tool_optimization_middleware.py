"""Shim (IG-668): alias ``middleware/tool_optimization_middleware`` to ``soothe_nano.middleware.tool_optimization_middleware``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware.tool_optimization_middleware")
sys.modules[__name__] = _nano
