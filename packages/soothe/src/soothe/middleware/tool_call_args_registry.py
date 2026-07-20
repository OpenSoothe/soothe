"""Shim (IG-668): alias ``middleware/tool_call_args_registry`` to ``soothe_nano.middleware.tool_call_args_registry``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware.tool_call_args_registry")
sys.modules[__name__] = _nano
