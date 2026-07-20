"""Shim (IG-668): alias ``mcp/reconnect`` to ``soothe_nano.mcp.reconnect``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.mcp.reconnect")
sys.modules[__name__] = _nano
