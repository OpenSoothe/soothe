"""Shim (IG-668): alias ``mcp/tools`` to ``soothe_nano.mcp.tools``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.mcp.tools")
sys.modules[__name__] = _nano
