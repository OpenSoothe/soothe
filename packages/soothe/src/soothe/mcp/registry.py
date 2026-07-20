"""Shim (IG-668): alias ``mcp/registry`` to ``soothe_nano.mcp.registry``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.mcp.registry")
sys.modules[__name__] = _nano
