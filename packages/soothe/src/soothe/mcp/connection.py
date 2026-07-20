"""Shim (IG-668): alias ``mcp/connection`` to ``soothe_nano.mcp.connection``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.mcp.connection")
sys.modules[__name__] = _nano
