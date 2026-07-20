"""Shim (IG-668): alias ``mcp/budget`` to ``soothe_nano.mcp.budget``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.mcp.budget")
sys.modules[__name__] = _nano
