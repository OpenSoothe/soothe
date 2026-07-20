"""Shim (IG-668): alias ``mcp/loader`` to ``soothe_nano.mcp.loader``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.mcp.loader")
sys.modules[__name__] = _nano
