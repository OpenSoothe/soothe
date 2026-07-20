"""Shim (IG-668): alias ``mcp/discovery_tools`` to ``soothe_nano.mcp.discovery_tools``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.mcp.discovery_tools")
sys.modules[__name__] = _nano
