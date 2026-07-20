"""Shim (IG-668): alias ``mcp/events`` to ``soothe_nano.mcp.events``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.mcp.events")
sys.modules[__name__] = _nano
