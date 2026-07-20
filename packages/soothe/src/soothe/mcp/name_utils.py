"""Shim (IG-668): alias ``mcp/name_utils`` to ``soothe_nano.mcp.name_utils``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.mcp.name_utils")
sys.modules[__name__] = _nano
