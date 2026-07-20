"""Shim (IG-668): alias ``mcp/builtin_servers`` to ``soothe_nano.mcp.builtin_servers``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.mcp.builtin_servers")
sys.modules[__name__] = _nano
