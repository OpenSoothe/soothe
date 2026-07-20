"""Shim (IG-668): alias ``mcp/transports`` to ``soothe_nano.mcp.transports``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.mcp.transports")
sys.modules[__name__] = _nano
