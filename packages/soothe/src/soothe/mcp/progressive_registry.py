"""Shim (IG-668): alias ``mcp/progressive_registry`` to ``soothe_nano.mcp.progressive_registry``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.mcp.progressive_registry")
sys.modules[__name__] = _nano
