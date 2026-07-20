"""Shim (IG-668): alias ``mcp/cleanup`` to ``soothe_nano.mcp.cleanup``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.mcp.cleanup")
sys.modules[__name__] = _nano
