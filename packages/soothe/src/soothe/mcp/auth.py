"""Shim (IG-668): alias ``mcp/auth`` to ``soothe_nano.mcp.auth``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.mcp.auth")
sys.modules[__name__] = _nano
